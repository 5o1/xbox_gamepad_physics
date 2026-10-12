"""Headless browser presentation/input latency and review screenshots."""
from .site import require, browser_url
import argparse
import asyncio
import json
import math
import subprocess
from pathlib import Path
import time


async def measure(args):
    from playwright.async_api import async_playwright
    args.output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=args.executable,headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width":1560,"height":1060})
        errors = []
        page.on("pageerror",lambda error:errors.append(str(error)))
        await page.goto(args.url)
        await page.wait_for_function("window.teleopStats?.presented.length > 30",timeout=90000)
        await page.wait_for_timeout(args.warmup*1000) # Warm decoding before arming; retain all 60 measurement windows.
        await page.locator("#video").click()
        if args.mouse:
            await page.wait_for_function("document.pointerLockElement === document.querySelector('#video') && teleopCursor.armed")
        await page.wait_for_timeout(1000)
        chrome_version = subprocess.check_output([args.executable,"--version"],text=True).strip()
        start = await page.evaluate("performance.now()")
        initial_bytes = await page.evaluate("teleopStats.receivedBytes")
        if args.idle:
            await page.wait_for_timeout(args.seconds*1000)
        elif args.mouse:
            box=await page.locator('#video').bounding_box()
            x,y=box['x']+box['width']/2,box['y']+box['height']/2
            # Alternating relative mouse movement, no buttons: +/-10 pixels in
            # both image axes, fine and ordinary profiles each used for 30 s.
            i=0;fine_started=False
            while (await page.evaluate('performance.now()')) < start+args.seconds*1000:
                elapsed=await page.evaluate('performance.now()')-start
                if elapsed>=args.seconds*500 and not fine_started:
                    await page.keyboard.down('Shift');fine_started=True
                sign=1 if i%2==0 else -1
                await page.mouse.move(x+sign*5,y+sign*5)
                await page.wait_for_timeout(50)
                i+=1
            await page.keyboard.up('Shift')
            await page.wait_for_timeout(300)
        else:
            for i in range(round(args.seconds/.5)):
                await page.keyboard.down("Shift")
                await page.keyboard.down("w" if i%2==0 else "s")
                await page.wait_for_timeout(60)
                await page.keyboard.up("w" if i%2==0 else "s")
                await page.keyboard.up("Shift")
                # Burst two mouse increments; both must actually execute before acknowledgement.
                await page.evaluate("() => {teleopSend('delta',{rotation:[0,0,0.02],fine:true});teleopSend('delta',{rotation:[0,0,-0.02],fine:true});}")
                await page.wait_for_timeout(440)
        end = await page.evaluate("performance.now()")
        pointer_locked_at_window_end=await page.evaluate("document.pointerLockElement===document.querySelector('#video') && teleopCursor.armed") if args.mouse else None
        raw = await page.evaluate("({presented:teleopStats.presented,drawDurations:teleopStats.drawDurations,panelDurations:teleopStats.panelDurations,rafTimes:teleopStats.rafTimes,decoded:teleopStats.decoded,received:teleopStats.received,latencies:teleopStats.latencies,sent:teleopStats.sent,errors:teleopStats.errors,networkRtt:teleopStats.networkRtt,bytes:teleopStats.receivedBytes,lastFrame:teleopStats.lastFrame})")
        times = [r["time"] for r in raw["presented"] if start <= r["time"] < start+args.seconds*1000]
        buckets = [sum(start+i*1000 <= t < start+(i+1)*1000 for t in times) for i in range(int(args.seconds))]
        mouse_seq={s['seq'] for s in raw['sent'] if s.get('screen_pixels') and any(s['screen_pixels'])}
        delays = sorted(r["ms"] for r in raw["latencies"] if (not args.mouse or r['seq'] in mouse_seq) and any(s["seq"]==r["seq"] and start <= s["time"] < start+args.seconds*1000
                                                                     for s in raw["sent"]))
        percentile = lambda values,f:values[min(len(values)-1,max(0,math.ceil(len(values)*f)-1))] if values else None
        result = {"input_mode":"pointer-lock mouse" if args.mouse else "keyboard/scripted deltas", "chrome_executable":args.executable,"chrome_version":chrome_version,
                  "sequence_definition":"post-physics execution sequence from rendered snapshot", "seconds":args.seconds,"fps_per_second":buckets,"mean_presented_fps":len(times)/args.seconds,
                  "minimum_one_second_fps":min(buckets),"input_samples":len(delays),"input_p95_ms":percentile(delays,.95),
                  "input_p50_ms":percentile(delays,.5),"network_rtt_p95_ms":percentile(sorted(raw["networkRtt"]),.95),
                  "bandwidth_mbps":(raw["bytes"]-initial_bytes)*8/(end-start)/1000,"page_errors":errors,
                  "K6":min(buckets)>=30 if len(buckets)>=60 else None,"K7":len(delays)>0 and percentile(delays,.95)<=200}
        if args.mouse:
            by_seq={s['seq']:s for s in raw['sent']}
            event_delays=sorted(r['ms']+by_seq[r['seq']]['time']-by_seq[r['seq']]['event_time_ms'] for r in raw['latencies']
                                if r['seq'] in mouse_seq and start<=by_seq[r['seq']]['time']<start+args.seconds*1000)
            result['mouse_event_to_display_p95_ms']=percentile(event_delays,.95)
            result['mouse_inputs']=len(mouse_seq)
            result['pointer_locked_at_window_end']=pointer_locked_at_window_end
            result['pointer_locked_after_collection']=await page.evaluate("document.pointerLockElement===document.querySelector('#video') && teleopCursor.armed")
        (args.output/"browser_raw.json").write_text(json.dumps({"start_ms":start,"end_ms":end,**raw},indent=2))
        (args.output/"browser_metrics.json").write_text(json.dumps(result,indent=2))
        if args.performance_only:
            print(json.dumps(result))
            await browser.close()
            return
        # Safety events and four views are retained separately from the fps interval.
        if await page.evaluate('document.pointerLockElement!==null'):
            await page.keyboard.press('Escape')
        for view in ("overall","buttons","triggers"):
            await page.locator(f'[data-view="{view}"]').click()
            await page.wait_for_function(f"teleopStats.lastFrame?.view === '{view}'")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(args.output/(view+".png")))
        await page.locator("#video").click()
        await page.keyboard.press("Tab")
        await page.wait_for_function("teleopStats.lastFrame?.ghost === true")
        await page.keyboard.down("d")
        await page.wait_for_timeout(100)
        await page.keyboard.up("d")
        await page.screenshot(path=str(args.output/"ghost.png"))
        safety = []
        for event in ("escape","blur","disconnect"):
            await page.locator("#video").click()
            await page.keyboard.down("w")
            await page.wait_for_timeout(50)
            before = await page.evaluate("teleopStats.sent.length")
            if event == "escape":
                await page.keyboard.press("Escape")
            elif event == "blur":
                await page.locator('[data-view="overall"]').focus()
            else:
                await page.evaluate("window.teleopDisconnect()")
            await page.wait_for_timeout(100)
            safety.append({"event":event,"sent":await page.evaluate(f"teleopStats.sent.slice({before})")})
            await page.keyboard.up("w")
        await page.reload()
        await page.wait_for_function("teleopStats.presented.length > 10")
        await page.locator("#video").click()
        await page.keyboard.down("w")
        await page.wait_for_timeout(50)
        await page.evaluate("teleopPauseHeartbeat()")
        loss_start=await page.evaluate("performance.now()")
        await page.wait_for_function("teleopStats.lastFrame?.hold_reason === 'lease-expired'",timeout=3000)
        safety.append({"event":"silent-control-loss", "visible_hold_delay_ms":await page.evaluate("performance.now()")-loss_start})
        (args.output/"safety_browser.json").write_text(json.dumps(safety,indent=2))
        (args.output/"browser_metrics.json").write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
        await browser.close()


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default=browser_url())
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--seconds",type=float,default=60)
    parser.add_argument("--warmup",type=float,default=10)
    parser.add_argument("--idle",action="store_true",help="warmed control with no mouse/key inputs")
    parser.add_argument("--executable",default=require("TELEOP_BROWSER"))
    parser.add_argument("--performance-only",action="store_true")
    parser.add_argument("--mouse",action="store_true")
    asyncio.run(measure(parser.parse_args()))
