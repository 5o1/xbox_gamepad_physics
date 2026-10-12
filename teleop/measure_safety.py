"""K10 event delivery and N9 silent-loss movement, outside FPS measurements."""
from .site import require, browser_url
import argparse
import asyncio
import json
from pathlib import Path
import subprocess


async def run(args):
    from playwright.async_api import async_playwright
    args.output.mkdir(parents=True,exist_ok=True)
    output={'chrome_version':subprocess.check_output([require('TELEOP_BROWSER'),'--version'],text=True).strip(),
            'events':[],'losses':[],'initial_clock':None,'final_clock':None,
            'closed_preload':args.closed_preload}
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=require('TELEOP_BROWSER'),headless=True,
                                      args=['--no-sandbox','--disable-dev-shm-usage'])
        page=await browser.new_page(viewport={'width':1560,'height':1060})
        await page.goto(args.url)
        await page.wait_for_function('teleopStats.presented.length>10')
        await page.evaluate('''() => {
            const Native=window.WebSocket;
            window.safetyClock=[];window.safetyCalibration=[];
            window.safetyConnect=async () => {
                const ws=new Native(`ws://${location.host}/control`);
                await new Promise(resolve => ws.addEventListener('message',e=>{
                    if(JSON.parse(e.data).kind==='welcome')resolve();},{once:true}));
                window.safetyClockSocket=ws;
                ws.addEventListener('message',e=>{
                    const end=performance.now(),m=JSON.parse(e.data);
                    if(m.kind==='probe-clock')safetyClock.push({...m,t3_ms:end});});
            };
            window.safetyProbe=async count => {
                safetyClock=[];safetyCalibration=[];
                for(let i=0;i<count;i++) {
                    const id=performance.now();safetyCalibration.push({id,t0_ms:id});
                    safetyClockSocket.send(JSON.stringify({kind:'probe-clock',id}));
                    await new Promise(resolve=>setTimeout(resolve,15));
                }
                await new Promise(resolve=>setTimeout(resolve,60));
                return safetyClock.map(x=>({...x,t0_ms:safetyCalibration.find(y=>y.id===x.id).t0_ms}));
            };
            // The probe socket is unsequenced and never updates the lease. Keep it
            // open throughout: closing any control socket invokes disconnect.
        }''')
        await page.evaluate('safetyConnect()')
        output['initial_clock']=await page.evaluate('safetyProbe(40)')
        # Capture real DOM action times in capture phase, before app listeners.
        await page.evaluate('''() => {
            window.safetyActions=[];
            document.querySelector('#video').addEventListener('blur',()=>safetyActions.push({kind:'blur',time:performance.now()}),true);
            window.addEventListener('keydown',e=>{if(e.code==='Escape')safetyActions.push({kind:'escape',time:performance.now()});},true);
        }''')
        async def calibrate():return await page.evaluate('safetyProbe(8)')
        async def focus():
            await page.locator('#video').click()
            await page.wait_for_timeout(30)
        if args.closed_preload:
            await focus()
            # Cursor controls latch closure with the left button; wheel opening
            # was removed by ruling 6.
            await page.locator('#video').click()
            await page.wait_for_timeout(300)
            output['preload_frame']=await page.evaluate('teleopStats.lastFrame')
            print(json.dumps({'preload_drive_targets':output['preload_frame']['main']['drive_targets']}),flush=True)
        for kind in ('escape','blur','disconnect'):

            for i in range(args.event_repeats):
                if kind=='disconnect' and i>0:
                    await page.reload()
                    await page.wait_for_function('teleopStats.presented.length>5')
                    # A fresh performance epoch needs its own clock probes.
                    await install_clock(page)
                pre=await calibrate()
                await focus()
                await page.keyboard.down('w')
                await page.wait_for_timeout(45+i%13*2)
                if kind=='escape':
                    await page.keyboard.press('Escape')
                    action=await page.evaluate("safetyActions.filter(x=>x.kind==='escape').at(-1).time")
                elif kind=='blur':
                    await page.locator('[data-view="overall"]').focus()
                    action=await page.evaluate("safetyActions.filter(x=>x.kind==='blur').at(-1).time")
                else:
                    action=await page.evaluate('() => {const t=performance.now();teleopDisconnect();return t;}')
                await page.wait_for_timeout(70)
                sent=await page.evaluate('teleopStats.sent.at(-1)')
                seq=sent['seq']+1 if kind=='disconnect' else sent['seq']
                post=await calibrate()
                output['events'].append({'kind':kind,'repeat':i,'seq':seq,'action_ms':action,
                                          'clock_before':pre,'clock_after':post})
                await page.keyboard.up('w')
                if (i+1)%10==0:print(json.dumps({'completed_event':kind,'count':i+1}),flush=True)
                (args.output/'browser_safety_raw.json').write_text(json.dumps(output,indent=2))
        # Fresh page reconnects both input and heartbeat after clean-close tests.
        await page.reload();await page.wait_for_function('teleopStats.presented.length>5')
        await install_clock(page)
        # Block every control send, not only heartbeat, without a close event.
        # Already transmitted data remains in flight, as with a real outbound loss.
        await page.evaluate('''() => {
            const proto=WebSocket.prototype,original=proto.send;
            window.safetyBlocked=false;window.safetyDropped=[];
            proto.send=function(data){if(safetyBlocked&&this.url.endsWith('/control')){
                safetyDropped.push({time:performance.now(),data});return;}return original.call(this,data);};
        }''')
        for fine in (False,True):
            for diagonal in (False,True):
                for i in range(args.phases):
                    pre=await calibrate()
                    await focus()
                    if fine:await page.keyboard.down('Shift')
                    # Alternate opposite directions to retain an unobstructed workspace.
                    keys=(['w','a','q'] if i%2==0 else ['s','d','e']) if diagonal else ['w' if i%2==0 else 's']
                    for key in keys:await page.keyboard.down(key)
                    await page.wait_for_timeout(600+2*i) # scan a complete 52 ms repeat period
                    action=await page.evaluate('() => {safetyBlocked=true;teleopPauseHeartbeat();return {time:performance.now(),seq:teleopStats.sent.at(-1).seq};}')
                    # During loss, no control events or clock probes are sent.
                    await page.wait_for_function("teleopStats.lastFrame?.hold_reason==='lease-expired'",timeout=5000)
                    observed=await page.evaluate('performance.now()')
                    await page.wait_for_timeout(500) # include finite-PD settling after target hold
                    await page.evaluate('safetyBlocked=false')
                    post=await calibrate()
                    output['losses'].append({'fine':fine,'diagonal':diagonal,'phase_index':i,'keys':keys,
                        'seq':action['seq'],'cut_ms':action['time'],'hold_visible_ms':observed,
                        'clock_before':pre,'clock_after':post,'settling_observation_ms':500})
                    for key in keys:await page.keyboard.up(key)
                    if fine:await page.keyboard.up('Shift')
                    # Reload restores heartbeats and requires explicit focus next trial.
                    await page.reload();await page.wait_for_function('teleopStats.presented.length>5')
                    await install_clock(page)
                    await page.evaluate('''() => {
                        const proto=WebSocket.prototype,original=proto.send;
                        window.safetyBlocked=false;
                        proto.send=function(data){if(safetyBlocked&&this.url.endsWith('/control'))return;return original.call(this,data);};
                    }''')
                    if (i+1)%13==0:print(json.dumps({'fine':fine,'diagonal':diagonal,'completed_phases':i+1}),flush=True)
                    (args.output/'browser_safety_raw.json').write_text(json.dumps(output,indent=2))
        output['final_clock']=await calibrate()
        (args.output/'browser_safety_raw.json').write_text(json.dumps(output,indent=2))
        print(json.dumps({'event_trials':len(output['events']),'silent_loss_trials':len(output['losses']),
                          'chrome_version':output['chrome_version']}))
        await browser.close()


async def install_clock(page):
    await page.evaluate('''async () => {
        window.safetyClock=[];window.safetyCalibration=[];window.safetyActions=[];
        const ws=new WebSocket(`ws://${location.host}/control`);
        await new Promise(resolve=>ws.addEventListener('message',e=>{if(JSON.parse(e.data).kind==='welcome')resolve();},{once:true}));
        window.safetyClockSocket=ws;
        ws.addEventListener('message',e=>{const t=performance.now(),m=JSON.parse(e.data);if(m.kind==='probe-clock')safetyClock.push({...m,t3_ms:t});});
        window.safetyProbe=async count => {
            safetyClock=[];safetyCalibration=[];
            for(let i=0;i<count;i++){const id=performance.now();safetyCalibration.push({id,t0_ms:id});ws.send(JSON.stringify({kind:'probe-clock',id}));await new Promise(r=>setTimeout(r,15));}
            await new Promise(r=>setTimeout(r,60));
            return safetyClock.map(x=>({...x,t0_ms:safetyCalibration.find(y=>y.id===x.id).t0_ms}));
        };
        document.querySelector('#video').addEventListener('blur',()=>safetyActions.push({kind:'blur',time:performance.now()}),true);
        window.addEventListener('keydown',e=>{if(e.code==='Escape')safetyActions.push({kind:'escape',time:performance.now()});},true);
    }''')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--url',default=browser_url())
    p.add_argument('--event-repeats',type=int,default=30);p.add_argument('--phases',type=int,default=26)
    p.add_argument('--closed-preload',action='store_true')
    asyncio.run(run(p.parse_args()))
