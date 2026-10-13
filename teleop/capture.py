"""Review views and a separated ghost; run outside FPS measurements."""
from .site import require, browser_url
import argparse
import base64
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def run(args):
    output=args.output
    output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=require('TELEOP_BROWSER'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        page=await browser.new_page(viewport={'width':1560,'height':1060})
        await page.goto(browser_url())
        await page.wait_for_function('teleopStats.presented.length>30')
        for view in ('overall','front','buttons_close','triggers','reference_front','reference_head'):
            await page.evaluate("view => teleopSend('view',{view})", view)
            await page.wait_for_function(f"teleopStats.lastFrame?.view === '{view}'")
            await page.wait_for_timeout(250)
            await page.screenshot(path=str(output/(view+'.png')))
            (output/(view+'_video.png')).write_bytes(base64.b64decode((await page.evaluate("document.querySelector('#video').toDataURL('image/png')")).split(',',1)[1]))
            (output/(view+'_metadata.json')).write_text(json.dumps(await page.evaluate('teleopStats.lastFrame'),indent=2))
        await page.locator('[data-view="front"]').click()
        await page.wait_for_function("teleopStats.lastFrame?.view === 'front'")
        await page.locator('#video').click()
        if args.blocked_ghost:
            await page.wait_for_function("document.pointerLockElement===document.querySelector('#video')")
            # Move the downward-pointing cursor over the right half of the pad.
            await page.locator('#video').dispatch_event('mousemove',{'movementX':-300,'movementY':0})
            await page.wait_for_function('teleopStats.lastFrame.main.pose[0] < .085',timeout=5000)
            # Use a real external-object overlap so the .5 s minimum can elapse without
            # switching to normal while a screenshot is being captured.
            await page.keyboard.down('e')
            await page.wait_for_function('teleopStats.lastFrame.main.pose[2] < .175',timeout=5000)
            await page.keyboard.up('e')
            await page.wait_for_timeout(150)
        await page.keyboard.press('Tab')
        await page.wait_for_function('teleopStats.lastFrame?.ghost===true')
        await page.evaluate("keys => teleopSend('keys',{keys})",['KeyE'] if args.blocked_ghost else ['KeyQ'])
        await page.wait_for_timeout(100 if args.blocked_ghost else 280)
        await page.evaluate("teleopSend('keys',{keys:[]})")
        if args.blocked_ghost:
            await page.wait_for_function('teleopStats.lastFrame.ghost && teleopStats.lastFrame.ghost_blocked',timeout=3000)
            await page.wait_for_function("document.querySelector('#blocked').textContent.startsWith('Still overlapping')",timeout=3000)
        await page.screenshot(path=str(output/'ghost.png'))
        (output/'ghost_video.png').write_bytes(base64.b64decode((await page.evaluate("document.querySelector('#video').toDataURL('image/png')")).split(',',1)[1]))
        state=await page.evaluate('teleopStats.lastFrame')
        if not state['ghost']:raise RuntimeError('ghost expired during capture; do not label normal frame as ghost')
        (output/'ghost_metadata.json').write_text(json.dumps(state,indent=2))
        print(json.dumps({'ghost':state['ghost'],'step':state['step'],'secondary_pose':state['secondary']['pose'],'frozen_pose':state['frozen']['pose']}))
        await browser.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--blocked-ghost',action='store_true')
    asyncio.run(run(parser.parse_args()))
