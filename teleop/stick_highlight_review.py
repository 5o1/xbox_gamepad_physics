"""Read-only historical/current full-panel stick color comparison."""
import argparse,asyncio,json,subprocess
from pathlib import Path
from .site import require
from .overlay_check import local_page
from .overlay_validate import canonical,TARGETS
from .overlay_colors import YELLOW_SNAPSHOT,color_verdict


async def review(output):
    from playwright.async_api import async_playwright
    output.mkdir(parents=True,exist_ok=True);rows=[]
    cases=[(side+'_'+axis,v) for side in ('left','right') for axis in ('x','y') for v in (1,-1)]
    cases += [('left_stick',1),('right_stick',1)]
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=require('TELEOP_BROWSER'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for revision in ('4c85f11','be4f188',None):
            label=revision or 'current';folder=output/label;folder.mkdir(exist_ok=True)
            page=await local_page(browser,'http://127.0.0.1:18986/viewer/gamepad_overlay/index.html?source=canonical',revision)
            await page.wait_for_function('__gamepadOverlayAdapter?.ready')
            for name,value in cases:
                await page.evaluate('f=>__gamepadOverlayAdapter.applyFrame(f)',canonical())
                before=await page.evaluate(YELLOW_SNAPSHOT)
                await page.evaluate('f=>__gamepadOverlayAdapter.applyFrame(f)',canonical(name,value))
                styles=await page.evaluate(YELLOW_SNAPSHOT)
                verdict=color_verdict(styles,TARGETS[name]);slug=name+('_pos' if value==1 else '_neg')
                await page.screenshot(path=str(folder/(slug+'_page.png')))
                await page.locator('#overlayRoot').screenshot(path=str(folder/(slug+'.png')))
                rows.append({'revision':label,'url':page.url,'channel':name,'value':value,
                             'before':before,'styles':styles,'verdict':verdict,'input':canonical(name,value)})
            await page.close()
        result={'chrome_version':browser.version,'purpose':'controlled read-only styling/history comparison, not K13 physical evidence','cases':rows}
        await browser.close()
    (output/'results.json').write_text(json.dumps(result,indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=asyncio.run(review(a.output));print(json.dumps([{'revision':r['revision'],'channel':r['channel'],'value':r['value'],**r['verdict']} for r in result['cases']],indent=2))
