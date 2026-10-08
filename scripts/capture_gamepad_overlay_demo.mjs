/** Capture deterministic canonical gamepad frames through one Chrome instance. */

import assert from 'node:assert/strict';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

import {
  closeCdpTarget,
  connectCdp,
  describeRuntimeException,
  evaluateCdp,
} from '../tests/cdp_client.mjs';


const viewerUrl = process.argv[2] ?? 'http://127.0.0.1:8770/viewer/gamepad_overlay/index.html';
const cdpUrl = process.argv[3] ?? 'http://127.0.0.1:9321';
const tracePath = process.argv[4] ?? 'results/gamepad_overlay_left_stick_circle/trace.json';
const outputDirectory = process.argv[5] ?? '/tmp/gamepad-overlay-circle-frames';
const trace = JSON.parse(await readFile(tracePath, 'utf8'));
await mkdir(outputDirectory, {recursive: true});

let page = null;
let client = null;
const runtimeFailures = [];
try {
  const response = await fetch(new URL('/json/new?about:blank', cdpUrl), {
    method: 'PUT',
    signal: AbortSignal.timeout(20_000),
  });
  assert.ok(response.ok, `create CDP target: HTTP ${response.status}`);
  page = await response.json();
  client = await connectCdp(page.webSocketDebuggerUrl);
  client.onEvent(message => {
    if (message.method === 'Runtime.exceptionThrown') {
      runtimeFailures.push(describeRuntimeException(message.params.exceptionDetails));
    }
  });
  await client.call('Runtime.enable');
  await client.call('Page.enable');
  await client.call('Emulation.setDeviceMetricsOverride', {
    width: 1280,
    height: 720,
    deviceScaleFactor: 1,
    mobile: false,
  });
  const url = new URL(viewerUrl);
  url.searchParams.set('source', 'canonical');
  url.searchParams.set('theme', 'research');
  const navigation = await client.call('Page.navigate', {url: url.href});
  assert.equal(navigation.errorText, undefined);

  const evaluate = expression => evaluateCdp(client, expression);
  let ready = false;
  for (let attempt = 0; attempt < 200; attempt += 1) {
    ready = await evaluate('document.body?.dataset.ready === "true" && window.__gamepadOverlayAdapter?.ready === true');
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  assert.ok(ready, 'canonical overlay adapter did not become ready');

  for (let index = 0; index < trace.frames.length; index += 1) {
    const frame = JSON.stringify(trace.frames[index]);
    await evaluate(`window.__gamepadOverlayAdapter.applyFrame(${frame})`);
    const screenshot = await client.call('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
      fromSurface: true,
    });
    await writeFile(
      join(outputDirectory, `frame_${String(index).padStart(4, '0')}.png`),
      Buffer.from(screenshot.data, 'base64'),
    );
  }

  assert.deepEqual(runtimeFailures, []);
  process.stdout.write(`${JSON.stringify({
    frames: trace.frames.length,
    fps: trace.fps,
    output: outputDirectory,
    runtime_failures: runtimeFailures,
  })}\n`);
} finally {
  client?.close();
  if (page?.id) {
    try { await closeCdpTarget(cdpUrl, page.id); } catch {}
  }
}
