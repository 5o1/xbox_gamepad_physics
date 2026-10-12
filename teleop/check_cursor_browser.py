"""Live browser checks for pointer-lock cursor input and hold events."""
from .site import require, browser_url
import argparse
import asyncio
import json
from pathlib import Path


async def run(args):
    from playwright.async_api import async_playwright
    args.output.mkdir(parents=True,exist_ok=True)
    result={"cases":[],"errors":[]}
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=require('TELEOP_BROWSER'),headless=True,
                                       args=['--no-sandbox','--disable-dev-shm-usage'])
        result['chrome_version']=browser.version
        page=await browser.new_page(viewport={'width':1560,'height':1060})
        page.on('pageerror',lambda error:result['errors'].append(str(error)))
        await page.goto(args.url);await page.wait_for_function('teleopStats.presented.length>20')
        async def lock():
            await page.locator('#video').click()
            await page.wait_for_function("document.pointerLockElement===document.querySelector('#video') && teleopCursor.armed")
        async def snapshot():return await page.evaluate('teleopStats.lastFrame')
        async def unarmed_mouse():
            before=await page.evaluate('teleopStats.sent.length')
            await page.locator('#video').dispatch_event('mousemove',{'movementX':100,'movementY':100})
            await page.wait_for_timeout(100)
            sent=await page.evaluate(f'teleopStats.sent.slice({before})')
            assert not any('screen_pixels' in s for s in sent),sent
            return sent
        result['unarmed_mouse']=await unarmed_mouse()
        await lock()
        await page.mouse.down(button='left');await page.mouse.up(button='left')
        await page.wait_for_function("Object.values(teleopStats.lastFrame.main.drive_targets).every(x=>Math.abs(x+.002)<1e-8)")
        await page.wait_for_timeout(200)
        result['close']=await snapshot()
        await page.mouse.down(button='right');await page.mouse.up(button='right')
        await page.wait_for_function("Object.values(teleopStats.lastFrame.main.drive_targets).every(x=>Math.abs(x-.04765)<1e-8)")
        await page.wait_for_timeout(200)
        result['open']=await snapshot()
        # Wheel is inert; right-button movement remains translation, not rotation.
        before=await page.evaluate('teleopStats.sent.length')
        await page.mouse.wheel(0,200)
        await page.wait_for_timeout(100)
        result['wheel_sent']=await page.evaluate(f'teleopStats.sent.slice({before})')
        assert not result['wheel_sent'],result['wheel_sent']
        await page.screenshot(path=str(args.output/'cursor_locked.png'))
        for event in ('escape','blur','disconnect'):
            if not await page.evaluate('teleopCursor.armed'):
                await page.wait_for_timeout(1200);await lock()
            # Keep closed preload across each safety event and rotate while held.
            await page.mouse.down();await page.mouse.up()
            await page.wait_for_function("Object.values(teleopStats.lastFrame.main.drive_targets).every(x=>Math.abs(x+.002)<1e-8)")
            await page.keyboard.down('w');await page.wait_for_timeout(80)
            before=await page.evaluate('teleopStats.sent.length')
            at=await page.evaluate('performance.now()')
            if event=='escape':await page.keyboard.press('Escape')
            elif event=='blur':await page.evaluate("window.dispatchEvent(new Event('blur'))")
            else:await page.evaluate('teleopDisconnect()')
            await page.wait_for_function('document.pointerLockElement===null && !teleopCursor.armed')
            await page.wait_for_timeout(350)
            data={'event':event,'action_ms':at,'sent':await page.evaluate(f'teleopStats.sent.slice({before})'),
                  'frame':await snapshot(),'unarmed_mouse_sent':await unarmed_mouse()}
            assert all(abs(x+.002)<1e-8 for x in data['frame']['main']['drive_targets'].values()),data
            assert data['frame']['hold_reason'],data
            result['cases'].append(data)
            await page.keyboard.up('w')
        # Fresh page checks ghost toggle and reconnection with the new controls.
        await page.reload();await page.wait_for_function('teleopStats.presented.length>20');await lock()
        await page.keyboard.press('Tab');await page.wait_for_function("teleopStats.lastFrame.state!=='main'")
        result['secondary']=await snapshot()
        await page.keyboard.press('Tab');await page.wait_for_function("teleopStats.lastFrame.state==='main'")
        result['restored']=await snapshot()
        await page.keyboard.press('Escape')
        result['teleop_errors']=await page.evaluate('teleopStats.errors')
        result['passed']=not result['errors'] and not result['teleop_errors']
        (args.output/'browser_checks.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({'passed':result['passed'],'events':[x['event'] for x in result['cases']]}))
        await browser.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default=browser_url())
    p.add_argument('--output',type=Path,required=True);asyncio.run(run(p.parse_args()))
