import {mkdir, writeFile} from 'node:fs/promises';

const base = process.env.CHROME_CDP ?? 'http://127.0.0.1:9232';
const url = process.env.REFERENCE_URL ?? 'http://127.0.0.1:9877/sketchfab_reference.html';
const page = await (await fetch(`${base}/json/new?about:blank`, {method: 'PUT'})).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, {once: true});
  ws.addEventListener('error', reject, {once: true});
});

let sequence = 0;
const pending = new Map();
ws.addEventListener('message', event => {
  const data = JSON.parse(event.data);
  if (!data.id) return;
  const promise = pending.get(data.id);
  pending.delete(data.id);
  data.error ? promise.reject(data.error) : promise.resolve(data.result);
});
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  pending.set(id, {resolve, reject});
  ws.send(JSON.stringify({id, method, params}));
});

const output = new URL('../results/xbox_sketchfab_viewer_reference/camera_axes/', import.meta.url);
await mkdir(output, {recursive: true});

try {
  await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride', {
    width: 1200,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await call('Page.navigate', {url});
  await call('Runtime.evaluate', {
    expression: `new Promise((resolve, reject) => {
      const deadline = Date.now() + 90000;
      function poll() {
        if (document.body.dataset.error) reject(Error(document.body.dataset.error));
        else if (window.reference?.ready) resolve(true);
        else if (Date.now() > deadline) reject(Error('viewer timeout'));
        else setTimeout(poll, 250);
      }
      poll();
    })`,
    awaitPromise: true,
  });

  const views = [
    ['plus_x', [4.5, 0, 0]],
    ['minus_x', [-4.5, 0, 0]],
    ['plus_y', [0, 4.5, 0]],
    ['minus_y', [0, -4.5, 0]],
    ['plus_z', [0, 0, 4.5]],
    ['minus_z', [0, 0, -4.5]],
    ['top_front_near', [0, -0.8, 4.5]],
    ['top_front_oblique', [0, -2.0, 4.0]],
    ['top_back_oblique', [0, 2.0, 4.0]],
  ];
  const manifest = [];
  for (const [name, offset] of views) {
    const expression = `new Promise((resolve, reject) => {
      const target = [-0.03751669638838028, 0.24024943525070927, -0.2933788650683066];
      const offset = ${JSON.stringify(offset)};
      const position = target.map((value, index) => value + offset[index]);
      window.reference.api.setCameraLookAt(position, target, 0, error => {
        if (error) return reject(Error(String(error)));
        window.reference.api.getCameraLookAt((cameraError, camera) => {
          if (cameraError) return reject(Error(String(cameraError)));
          setTimeout(() => resolve({requested: {position, target}, returned: camera}), 1200);
        });
      });
    })`;
    const result = await call('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
    }
    const shot = await call('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
    });
    const file = `${name}.png`;
    await writeFile(new URL(file, output), Buffer.from(shot.data, 'base64'));
    manifest.push({name, file, ...result.result.value});
  }
  await writeFile(new URL('manifest.json', output), JSON.stringify({views: manifest}, null, 2));
  console.log(JSON.stringify({views: manifest}, null, 2));
} finally {
  ws.close();
}
