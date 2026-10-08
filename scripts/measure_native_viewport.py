"""X11 input/capture measurement for the isolated native viewport pilot.

Run on the GPU node: python this.py run_directory [--capture-only]
DISPLAY must identify the pilot's private X server, never another user's desktop.
"""
import ctypes as C
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

import numpy as np
from PIL import Image

assert os.environ.get('DISPLAY') == ':99', 'This probe is restricted to isolated display :99'
parser=argparse.ArgumentParser()
parser.add_argument('input_directory',type=Path)
parser.add_argument('--output',type=Path)
parser.add_argument('--capture-only',action='store_true')
args=parser.parse_args()
input_root=args.input_directory
root=args.output or input_root
root.mkdir(parents=True,exist_ok=True)
ready=json.loads((input_root/'ready.json').read_text())
lib=C.CDLL('libX11.so.6');xtst=C.CDLL('libXtst.so.6')
lib.XInitThreads()
lib.XOpenDisplay.argtypes=[C.c_char_p];lib.XOpenDisplay.restype=C.c_void_p
lib.XDefaultRootWindow.argtypes=[C.c_void_p];lib.XDefaultRootWindow.restype=C.c_ulong
lib.XGetImage.argtypes=[C.c_void_p,C.c_ulong,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_ulong,C.c_int]
lib.XGetImage.restype=C.c_void_p
lib.XDestroyImage.argtypes=[C.c_void_p]
lib.XSync.argtypes=[C.c_void_p,C.c_int]
lib.XCloseDisplay.argtypes=[C.c_void_p]
xtst.XTestFakeMotionEvent.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_ulong]
xtst.XTestFakeButtonEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]


class XImage(C.Structure):
    _fields_=[('width',C.c_int),('height',C.c_int),('xoffset',C.c_int),('format',C.c_int),
              ('data',C.c_void_p),('byte_order',C.c_int),('bitmap_unit',C.c_int),('bitmap_bit_order',C.c_int),
              ('bitmap_pad',C.c_int),('depth',C.c_int),('bytes_per_line',C.c_int),('bits_per_pixel',C.c_int)]


display=lib.XOpenDisplay(b':99')
window=lib.XDefaultRootWindow(display)
def capture(x=0,y=0,width=1600,height=900):
    ptr=lib.XGetImage(display,window,x,y,width,height,0xffffffff,2)
    if not ptr:raise RuntimeError('XGetImage failed')
    image=C.cast(ptr,C.POINTER(XImage)).contents
    assert image.bits_per_pixel==32 and image.byte_order==0
    raw=C.string_at(image.data,image.bytes_per_line*height)
    data=np.frombuffer(raw,dtype=np.uint8).reshape(height,image.bytes_per_line)[:,:width*4].reshape(height,width,4)
    rgb=data[:,:,2::-1].copy()
    lib.XDestroyImage(ptr)
    return rgb


Image.fromarray(capture()).save(root/'before.png')
if args.capture_only:
    lib.XCloseDisplay(display)
    raise SystemExit(0)

region=ready['region'];positions=ready['positions']
def xy(radius):
    point=positions[str(radius)]
    return round(region[0]+point[0]),round(900-region[1]-point[1])
cx,cy=xy(0)
roi=(max(0,cx-90),max(0,cy-90),180,180)
frames=[];timestamps=[];stop=threading.Event()
def sample():
    while not stop.is_set():
        start=time.monotonic()
        frames.append(capture(*roi));timestamps.append(start)
        stop.wait(max(0,1/30-(time.monotonic()-start)))

thread=threading.Thread(target=sample);thread.start()
inputs=[]
def move(point,label):
    stamp=time.monotonic()
    xtst.XTestFakeMotionEvent(display,-1,*point,0);lib.XSync(display,0)
    inputs.append({'kind':'move','t':stamp,'label':label,'xy':point})
def button(pressed):
    stamp=time.monotonic();xtst.XTestFakeButtonEvent(display,1,int(pressed),0);lib.XSync(display,0)
    inputs.append({'kind':'press' if pressed else 'release','t':stamp})

time.sleep(2)
move(xy(0),'neutral');time.sleep(.2);button(True);time.sleep(2)
move(xy(.6),'step');time.sleep(5)
start_continuous=time.monotonic()
previous=xy(.6)
for radius in [.8,1,2,3,2,1,.9,.8,.6,.4,.2,0]:
    target=xy(radius)
    for i in range(1,9):
        point=tuple(round(a+(b-a)*i/8) for a,b in zip(previous,target))
        move(point,f'radius_{radius}');time.sleep(1/30)
    previous=target
end_continuous=time.monotonic();time.sleep(1);button(False)
time.sleep(8)
stop.set();thread.join()
Image.fromarray(capture()).save(root/'after.png')
pixels=np.stack(frames);ts=np.array(timestamps)
np.savez_compressed(root/'roi_frames.npz',frames=pixels,t=ts)
(root/'input_events.json').write_text(json.dumps(inputs,indent=2))
step=next(e['t'] for e in inputs if e.get('label')=='step')
baseline=pixels[np.where(ts<step)[0][-1]].astype(np.float32)
delta=np.abs(pixels.astype(np.float32)-baseline).mean(axis=(1,2,3))
changed=np.where((ts>=step)&(delta>=2))[0]
last_release=next(e['t'] for e in reversed(inputs) if e['kind']=='release')
end_image=pixels[-1].astype(np.float32)
distance_to_final=np.abs(pixels.astype(np.float32)-end_image).mean(axis=(1,2,3))
unsettled=np.where((ts>=last_release)&(distance_to_final>=1))[0]
consecutive=np.abs(np.diff(pixels.astype(np.float32),axis=0)).mean(axis=(1,2,3))
mask=(ts[1:]>=start_continuous)&(ts[1:]<=end_continuous)
report={
 'display':ready,'capture_hz':30,'roi_xywh':roi,
 'first_visible_change_ms':float((ts[changed[0]]-step)*1000) if len(changed) else None,
 'first_change_definition':'ROI mean absolute RGB difference >= 2/255 from converged pre-step image',
 'continuous_changed_frames_per_second':float(np.sum(consecutive[mask]>=.1)/(end_continuous-start_continuous)),
 'image_update_definition':'ROI frame-to-frame mean absolute RGB difference >= 0.1/255; includes progressive refinements, not distinct pose FPS',
 'settle_after_release_ms':float((ts[unsettled[-1]]-last_release)*1000) if len(unsettled) else 0,
 'settle_definition':'last ROI differing by >= 1/255 from final frame',
 'capture_count':len(ts),'input_count':len(inputs),
}
events=[e for e in json.loads((input_root/'events.json').read_text()) if e['t']>=inputs[0]['t']]
poses=[e for e in events if e['kind']=='pose']
assert poses, 'No native stick pose events were received'
report['pose_event_count']=len(poses)
first_step=next((e for e in poses if e['t']>=step),None)
report['first_pose_event_ms']=(first_step['t']-step)*1000 if first_step else None
report['max_stick_radius']=max(float(np.hypot(*e['q'])) for e in poses) if poses else None
report['last_pose']=poses[-1]['q'] if poses else None
(root/'metrics.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
lib.XCloseDisplay(display)
