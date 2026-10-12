"""Browser evidence for the teleop-to-overlay boundary, without simulator inputs."""
from .site import require, browser_url
import argparse
import asyncio
import json
import mimetypes
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


async def local_page(browser, url="http://127.0.0.1:18986/", revision=None):
    """Serve repository bytes via browser routing; no camera/gamepad hardware IO."""
    page = await browser.new_page(viewport={"width": 1560, "height": 1060})
    async def static(route):
        path = urlparse(route.request.url).path
        file = ROOT/"teleop/web/index.html" if path == "/" else ROOT/"teleop"/path[1:] if path.startswith("/web/") else ROOT/path[1:]
        if not file.is_file():
            await route.fulfill(status=404, body="missing")
            return
        body = (subprocess.check_output(['git','show',f'{revision}:{file.relative_to(ROOT)}'],cwd=ROOT)
                if revision and path.startswith('/viewer/gamepad_overlay/') else file.read_bytes())
        if path == "/web/app.js":
            body += b"\nwindow.__teleopTestPanel = panel;\n"
        await route.fulfill(body=body, content_type=mimetypes.guess_type(file)[0] or "application/octet-stream")
    await page.route("http://127.0.0.1:18986/**", static)
    await page.goto(url)
    await page.wait_for_function("document.body.dataset.ready === 'true'" if "/viewer/" in url else
                                 "document.querySelector('#overlay').contentDocument?.body.dataset.ready === 'true'")
    return page


def sample(signals):
    hand = {"pose": [.3, 0, .12, 0, 0, 0, 1], "joints": {"fl_joint7": .02, "fl_joint8": .02}}
    return {"state": "main", "main": hand, "secondary": hand, "ghost": False,
            "ghost_blocked": False, "geometry_blockers": [], "step": 0,
            "last_input_seq": 0, "view": "front", "signals": signals}


async def diagnose(args):
    from playwright.async_api import async_playwright
    args.output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=require("TELEOP_BROWSER"), headless=True,
                                           args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await local_page(browser)
        frame = page.frames[1]
        before = await frame.locator("#overlayRoot").inner_html()
        result = await page.evaluate("""m => {
          const w=document.querySelector('#overlay').contentWindow, original=w.__gamepadOverlayAdapter;
          let calls=0;
          w.__gamepadOverlayAdapter={get ready(){return original.ready},applyFrame(f){calls++;return original.applyFrame(f)}};
          __teleopTestPanel(m);
          return {adapterReady:original.ready,calls,errors:teleopStats.errors,table:document.querySelector('#channel-dpad_down').outerHTML};
        }""", sample({"dpad_down": 1}))
        await page.wait_for_timeout(100)
        result["svg_changed"] = before != await frame.locator("#overlayRoot").inner_html()
        result["errors"] = await page.evaluate("teleopStats.errors")
        result["dpad_down_dom"] = await frame.evaluate("""() => [...document.querySelectorAll('#overlayRoot [data-side="left"][data-role="down"]')].map(e=>{
          const clip=e.getAttribute('clip-path');
          return {tag:e.tagName,classes:e.getAttribute('class'),fill:getComputedStyle(e).fill,
            href:e.getAttribute('href'),clip,clipRect:clip?document.getElementById(clip.slice(5,-1))?.innerHTML:null};
        })""")
        result["guide_elements"] = await frame.locator('#overlayRoot [data-role="guide"]').count()
        direct = await frame.evaluate("""async () => {
          const {CHANNEL_NAMES,LAYOUT_ID}=await import('./canonical_adapter.mjs');
          const values=CHANNEL_NAMES.map(n=>n==='dpad_down'?1:0),mask=CHANNEL_NAMES.map((_,i)=>i<21);
          const f={layout_id:LAYOUT_ID,values,available_mask:mask,task_mask:mask,device_id:0};
          const state=await __gamepadOverlayAdapter.applyFrame(f);
          return {frame:f,state,pressedFill:[...document.querySelectorAll('[data-side="left"][data-role="down"].gamepad-button-pressed-fill')].map(e=>getComputedStyle(e).fill)};
        }""")
        result["direct_iframe_apply"] = direct
        await page.screenshot(path=str(args.output/"before_fix.png"))
        # Read-only contrasts: distinguish a hidden SVG update from a visible one.
        # These are diagnosis images, not a claim that the blocked K11 passed.
        import io
        from PIL import Image, ImageChops
        core = direct["frame"]["available_mask"]
        names = await frame.evaluate("import('./canonical_adapter.mjs').then(m=>m.CHANNEL_NAMES)")
        neutral = {name: 0 for name, available in zip(names, core) if available}
        cases = []
        for name in ("dpad_down", "south", "left_x", "right_trigger", "guide"):
            page = await local_page(browser)
            frame = page.frames[1]
            await page.evaluate("m=>__teleopTestPanel(m)", sample(neutral))
            await page.wait_for_timeout(100)
            before_pixels = await frame.locator("#overlayRoot").screenshot()
            before_dom = await frame.locator("#overlayRoot").inner_html()
            await page.evaluate("m=>__teleopTestPanel(m)", sample({**neutral, name: 1}))
            await page.wait_for_timeout(100)
            after_pixels = await frame.locator("#overlayRoot").screenshot()
            difference = ImageChops.difference(Image.open(io.BytesIO(before_pixels)).convert("RGB"),
                                             Image.open(io.BytesIO(after_pixels)).convert("RGB"))
            cases.append({"channel": name, "value": 1, "svg_changed": before_dom != await frame.locator("#overlayRoot").inner_html(),
                          "visible_pixel_difference_bbox": difference.getbbox()})
            await page.screenshot(path=str(args.output/(name+".png")))
            await page.close()
        result["contrasts"] = cases
        result["contrast_isolation"] = "independent page per channel"
        result["chrome_version"] = browser.version
        (args.output/"diagnosis.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(diagnose(parser.parse_args()))
