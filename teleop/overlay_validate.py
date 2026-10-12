"""K11: all core-channel SVG responses through the canonical and teleop boundaries."""
from .site import require, browser_url
import argparse
import asyncio
import io
import json
from pathlib import Path
from PIL import Image, ImageChops
from .overlay_check import local_page, sample

NAMES = ("left_x","left_y","right_x","right_y","left_trigger","right_trigger",
         "south","east","west","north","back","guide","start","left_stick","right_stick",
         "left_shoulder","right_shoulder","dpad_up","dpad_down","dpad_left","dpad_right")
TARGETS = {
    "south": {"right:down"}, "east": {"right:right"}, "west": {"right:left"}, "north": {"right:up"},
    "back": {"left:select"}, "start": {"right:start"}, "guide": {"center:guide"},
    "left_shoulder": {"left:left-bumper"}, "right_shoulder": {"right:right-bumper"},
    "left_trigger": {"left:left-trigger"}, "right_trigger": {"right:right-trigger"},
    "dpad_up": {"left:up"}, "dpad_down": {"left:down"}, "dpad_left": {"left:left"}, "dpad_right": {"left:right"},
}
for prefix in ("left","right"):
    for suffix in ("x","y","stick"):
        TARGETS[f"{prefix}_{suffix}"]={f"{prefix}:analog-stick",f"{prefix}:analog-stick-ring"}

SNAPSHOT = """() => {
 const groups={};
 for(const e of document.querySelectorAll('#overlayRoot [data-side][data-role]')){
  const key=e.dataset.side+':'+e.dataset.role;
  const attrs=n=>n?[...n.attributes].map(a=>[a.name,a.value]).sort():null;
  const clip=e.getAttribute('clip-path');
  const clipNode=clip?document.getElementById(clip.slice(5,-1)):null;
  const rect=clipNode?.firstElementChild;
  const shape=e.getAttribute('href')?document.querySelector(e.getAttribute('href')):null;
  (groups[key]??=[]).push({attrs:attrs(e),shape:attrs(shape),fill:getComputedStyle(e).fill,
   // Zero-width and zero-height clips both mean no visible pressed fill.
   clip:rect?(Number(rect.getAttribute('width'))*Number(rect.getAttribute('height'))===0?'empty':clipNode.innerHTML):null});
 }
 return groups;
}"""


def canonical(name=None, value=0):
    return {"layout_id":"sdl3-gamepad-core-v1","values":[value if n==name else 0 for n in NAMES]+[0]*11,
            "available_mask":[True]*21+[False]*11,"task_mask":[True]*21+[False]*11,"device_id":0}


async def validate(output, modes=("dashboard","teleop")):
    from playwright.async_api import async_playwright
    output.mkdir(parents=True,exist_ok=True)
    results=[];boundaries=[]
    cases=[(name,value) for name in NAMES for value in ((-1,1) if name.endswith(('_x','_y')) else (1,))]
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=require('TELEOP_BROWSER'),headless=True,
                                       args=['--no-sandbox','--disable-dev-shm-usage'])
        for mode in modes:
            page=await local_page(browser,'http://127.0.0.1:18986/viewer/gamepad_overlay/index.html?source=canonical' if mode=='dashboard' else 'http://127.0.0.1:18986/')
            target=page if mode=='dashboard' else page.frames[1]
            await target.evaluate("""()=>{
              window.__k11Frames=[];
              const original=__gamepadOverlayAdapter;
              window.__gamepadOverlayAdapter={get ready(){return original.ready},async applyFrame(f){
                __k11Frames.push(structuredClone(f));return original.applyFrame(f);
              }};
            }""")
            async def apply(frame):
                if mode=='dashboard':await target.evaluate('f=>__gamepadOverlayAdapter.applyFrame(f)',frame)
                else:
                    signals=dict(zip(NAMES,frame['values'][:21]))
                    await page.evaluate('m=>__teleopTestPanel(m)',sample(signals))
                    await target.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                await page.wait_for_timeout(50)
            await apply(canonical())
            baseline=await target.evaluate(SNAPSHOT)
            baseline_pixels=await target.locator('#overlayRoot').screenshot()
            for name,value in cases:
                await apply(canonical(name,value))
                current=await target.evaluate(SNAPSHOT)
                changed={key for key in baseline if current[key]!=baseline[key]}
                expected=TARGETS[name]
                pixels=await target.locator('#overlayRoot').screenshot()
                diff=ImageChops.difference(Image.open(io.BytesIO(baseline_pixels)).convert('RGB'),
                                         Image.open(io.BytesIO(pixels)).convert('RGB'))
                bbox=diff.getbbox()
                case={'mode':mode,'channel':name,'value':value,'changed_components':sorted(changed),
                      'unexpected_components':sorted(changed-expected),'visible_difference_bbox':bbox,
                      'passed':bool(changed&expected) and not changed-expected and bbox is not None}
                results.append(case)
                if (name,value) in (('dpad_down',1),('south',1),('left_x',1),('right_trigger',1),('guide',1)):
                    await page.screenshot(path=str(output/f'{mode}_{name}.png'))
                    await target.locator('#overlayRoot').screenshot(path=str(output/f'{mode}_{name}_svg.png'))
                await apply(canonical())
                assert await target.evaluate(SNAPSHOT)==baseline, f'{mode}/{name}: neutral state did not restore'
            # Preserve a4aa9b4's continuous amplitude and exact-change behavior.
            continuous=[]
            for name in ('south','guide'):
                for value in (.37,5.4e-7,4.4e-6):
                    await apply(canonical(name,value))
                    side,role=next(iter(TARGETS[name])).split(':')
                    height=await target.evaluate("""({side,role})=>{
                      const e=document.querySelector(`.gamepad-button-pressed-fill[data-side="${side}"][data-role="${role}"]`);
                      return Number(document.getElementById(e.getAttribute('clip-path').slice(5,-1)).firstElementChild.getAttribute('height'));
                    }""",{'side':side,'role':role})
                    continuous.append({'channel':name,'value':value,'clip_height':height,'passed':abs(height-value)<1e-12})
            frames=await target.evaluate('__k11Frames')
            boundaries.append({'mode':mode,'requested_url':page.url,'iframe_url':target.url,
                               'frame_count':len(frames),'all_inputs_canonical_32':all(len(f['values'])==32 and f['layout_id']=='sdl3-gamepad-core-v1' for f in frames),
                               'frames':frames,'continuous':continuous})
            await page.close()
        result={'chrome_version':browser.version,'cases':results,'boundaries':boundaries,
                'passed':all(r['passed'] for r in results) and all(b['all_inputs_canonical_32'] and all(c['passed'] for c in b['continuous']) for b in boundaries)}
        await browser.close()
    (output/'K11.json').write_text(json.dumps(result,indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=asyncio.run(validate(args.output))
    print(json.dumps({'passed':r['passed'],'cases':len(r['cases']),'failures':[c for c in r['cases'] if not c['passed']]}))
    raise SystemExit(0 if r['passed'] else 1)
