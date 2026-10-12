"""Observe actual streamed frames and SVG; never inject a canonical state."""
import argparse
import asyncio
import io
import json
from pathlib import Path
from PIL import Image,ImageChops
from .ball_probe import case_spec
from .overlay_validate import SNAPSHOT,TARGETS
from .site import require
from .overlay_colors import YELLOW_SNAPSHOT,color_verdict


async def check(url, name, output):
    from playwright.async_api import async_playwright
    output.mkdir(parents=True,exist_ok=True);spec=case_spec(name)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=require('TELEOP_BROWSER'),headless=True,
                                      args=['--no-sandbox','--disable-dev-shm-usage'])
        page=await browser.new_page(viewport={'width':1560,'height':1100})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(url)
        await page.wait_for_function("teleopStats.lastFrame?.probe?.phase==='idle'",timeout=60000)
        iframe=page.frame_locator('#overlay');target=page.frames[1]
        await target.wait_for_function('__gamepadOverlayAdapter?.ready')
        # Observe frames delivered by the real teleop panel. Do not call applyFrame.
        await target.evaluate("""()=>{
          window.__k13=[];window.__k13last=null;
          const adapter=__gamepadOverlayAdapter, original=adapter.applyFrame.bind(adapter);
          window.__gamepadOverlayAdapter={get ready(){return adapter.ready},async applyFrame(frame){
            const meta=structuredClone(parent.teleopStats.lastFrame);
            await original(frame);
            window.__k13last={meta,frame:structuredClone(frame)};
            __k13.push(__k13last);
          }};
        }""")
        await target.wait_for_function("__k13last?.meta.probe.phase==='idle'")
        baseline=await target.evaluate(SNAPSHOT)
        baseline_pixels=await target.locator('#overlayRoot').screenshot()
        await page.screenshot(path=str(output/'neutral_page.png'))
        response=await page.request.post(url+'probe',data={'action':'start'});assert response.ok
        # Capture during the fixed 0.5 s hold; the browser no longer extends it.
        await target.wait_for_function("__k13last?.meta.probe.phase==='hold' && __k13last.meta.probe.phase_age_s>=.08",timeout=15000)
        current=await target.evaluate(SNAPSHOT)
        colors=await target.evaluate(YELLOW_SNAPSHOT)
        applied=await target.evaluate('__k13last')
        metadata=await page.evaluate('teleopStats.lastFrame')
        video_box=await page.locator('#video').bounding_box()
        overlay_box=await target.locator('#overlayRoot').bounding_box()
        # One page capture gives matching simulation and overlay images.
        screenshot=await page.screenshot(path=str(output/'hold_page.png'))
        picture=Image.open(io.BytesIO(screenshot))
        def crop(box,path):
            result=picture.crop(tuple(round(v) for v in (box['x'],box['y'],box['x']+box['width'],box['y']+box['height'])))
            result.save(path);return result
        crop(video_box,output/'simulation.png')
        overlay_image=crop(overlay_box,output/'overlay.png')
        pixels=io.BytesIO();overlay_image.save(pixels,format='PNG');pixels=pixels.getvalue()
        changed={key for key in baseline if current[key]!=baseline[key]}
        expected=TARGETS[spec['channel']] if spec['channel'] else set()
        diff=ImageChops.difference(Image.open(io.BytesIO(baseline_pixels)).convert('RGB'),Image.open(io.BytesIO(pixels)).convert('RGB'))
        bbox=diff.getbbox()
        color=color_verdict(colors,expected)
        overlay_ok=color["passed"]
        # Pair is intentionally absent from the 32-dimensional game tensor.
        frames=await target.evaluate('__k13')
        canonical_ok=all(f['frame']==f['meta']['canonical_state'] and f['frame']['layout_id']=='sdl3-gamepad-core-v1' and len(f['frame']['values'])==32 and
            f['frame']['values'][:21]==[f['meta']['signals'][n] for n in
              ('left_x','left_y','right_x','right_y','left_trigger','right_trigger','south','east','west','north','back','guide','start','left_stick','right_stick','left_shoulder','right_shoulder','dpad_up','dpad_down','dpad_left','dpad_right')]
            for f in frames)
        result={'case':name,'chrome_version':browser.version,'errors':errors,'source':'real H264 stream and loader signals; observation only',
                'changed_components':sorted(changed),'unexpected_components':color['unexpected_yellow_components'],
                'unexpected_attribute_components':sorted(changed-expected),
                'visible_difference_bbox':bbox,'overlay_color':color,'svg_colors':colors,'overlay_passed':overlay_ok,'all_inputs_canonical_32_from_rendered_signals':canonical_ok,
                'overlay_applied':applied,'displayed_frame_at_capture':metadata,'baseline':baseline,'current':current}
        await page.wait_for_function("teleopStats.lastFrame?.probe?.phase==='done'",timeout=10000)
        result['after_withdraw']=await page.evaluate('teleopStats.lastFrame')
        result['frames_observed']=len(await target.evaluate('__k13'))
        await page.screenshot(path=str(output/'withdrawn_page.png'))
        (output/'browser.json').write_text(json.dumps(result,indent=2));await browser.close()
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True);p.add_argument('--case',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=asyncio.run(check(a.url,a.case,a.output));print(json.dumps({'case':a.case,'overlay_passed':r['overlay_passed'],'changed':r['changed_components'],'canonical_32':r['all_inputs_canonical_32_from_rendered_signals']}))
