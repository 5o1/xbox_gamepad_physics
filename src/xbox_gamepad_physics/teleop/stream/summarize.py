"""Summarize already-captured server timing by displayed frame/step range."""
import argparse
import json
import math
from pathlib import Path
from ..record import iter_records,find_record


def summary(values,scale=1):
    values=sorted(v*scale for v in values)
    if not values:return None
    return {'count':len(values),'mean':sum(values)/len(values),'p95':values[max(0,math.ceil(len(values)*.95)-1)]}


def run(args):
    browser=json.loads(args.browser.read_text())
    presented=[r for r in browser['presented'] if browser['start_ms']<=r['time']<browser['start_ms']+60000]
    first,last=min(r['id'] for r in presented),max(r['id'] for r in presented)
    first_step,last_step=min(r['step'] for r in presented),max(r['step'] for r in presented)
    physics=list(iter_records(find_record(args.run,'physics_timing')))
    render=list(iter_records(find_record(args.run,'render_timing')))
    encoded=list(iter_records(find_record(args.run,'stream_timing')))
    pr=[r for r in physics if first_step<=r['step']<=last_step]
    rr=[r for r in render if first<=r['frame_id']<=last]
    er=[r for r in encoded if first<=r['frame_id']<=last]
    decode={round(r['timestamp']/16667):r['time'] for r in browser['decoded']}
    received={r['id']:r['time'] for r in browser.get('received',[])}
    result={'frame_range':[first,last],'step_range':[first_step,last_step],
            'physics_realtime_factor_same_server_clock':len(pr)*.004/((pr[-1]['end_ns']-pr[0]['boundary_ns'])/1e9),
            'physics_lateness_ms':summary([r['lateness_s'] for r in pr],1000),
            'physics_ms':summary([r['physics_seconds'] for r in pr],1000),
            'physics_owner_total_ms':summary([r['end_ns']-r['boundary_ns'] for r in pr],1e-6),
            'render_submit_ms':summary([r['render_ns'] for r in rr],1e-6),
            'readback_including_gpu_wait_ms':summary([r['readback_ns'] for r in rr],1e-6),
            'conversion_ms':summary([r['conversion_ns'] for r in rr],1e-6),
            'encode_pipeline_ms':summary([r['encode_ns'] for r in er],1e-6),
            'send_ms':summary([r['send_ns'] for r in er],1e-6),
            'decode_output_to_canvas_draw_ms':summary([r['time']-decode[r['id']] for r in presented if r['id'] in decode]),
            'websocket_rtt_ms':summary(browser['networkRtt']),
            'pure_gpu_render_ms':None,'pure_nvenc_ms':None,'network_one_way_ms':None,'decode_input_to_output_ms':None,
            'websocket_receive_to_decode_output_ms':summary([decode[i]-received[i] for i in received if i in decode and first<=i<=last]),
            'canvas_draw_call_ms':summary(browser.get('drawDurations',[])),
            'panel_update_call_ms':summary(browser.get('panelDurations',[])),
            'observed_stop_events':sum(e['kind'] in ('stop','disconnect') for r in physics for e in r['input_events']),
            'stop_boundary_hold_flags_all_true':all(r.get('hold',False) for r in physics if any(e['kind'] in ('stop','disconnect') for e in r['input_events']))}
    result['low_fps_windows']=[]
    for second in range(60):
        shown=[r for r in presented if browser['start_ms']+second*1000<=r['time']<browser['start_ms']+(second+1)*1000]
        if len(shown)>=30:continue
        if not shown:continue
        low,high=min(r['id'] for r in shown),max(r['id'] for r in shown)
        matched=[r for r in rr if low<=r['frame_id']<=high]
        result['low_fps_windows'].append({'second':second+1,'presented':len(shown),
            'received':sum(browser['start_ms']+second*1000<=r['time']<browser['start_ms']+(second+1)*1000 for r in browser.get('received',[])),
            'decoded':sum(browser['start_ms']+second*1000<=r['time']<browser['start_ms']+(second+1)*1000 for r in browser['decoded']),
            'matched_render_total_ms':summary([r['total_ns'] for r in matched],1e-6)})
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--browser',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args())
