import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {artifactOutput} from './artifact_output.mjs';
import {
  buildVerifiedSourceBinding,
  makeCacheBustedNavigationUrl,
  prepareUncachedNetwork,
  recordSourceResponse,
} from './browser_source_binding.mjs';
import {closeCdpTarget, connectCdp, evaluateCdp} from './cdp_client.mjs';

const args=process.argv.slice(2),publishIndex=args.indexOf('--publish'),publish=publishIndex!==-1;
if(publish)args.splice(publishIndex,1);
if(args.length)throw Error(`Unknown arguments: ${args.join(' ')}`);

const base = process.env.CHROME_CDP ?? 'http://127.0.0.1:9232';
const url = process.env.REFERENCE_URL ?? 'http://127.0.0.1:9877/sketchfab_reference.html';
const navigation=makeCacheBustedNavigationUrl(url);
const sourceSpecifications=[{
  request_path:new URL(navigation.url).pathname,
  binding_kind:'workspace',
  binding_path:'viewer/sketchfab_reference.html',
}];
const expectedUid='a62cf7475b7d4ead9fbf1a86e5a2b6a4';
const pageResponse=await fetch(`${base}/json/new?about:blank`,{method:'PUT',signal:AbortSignal.timeout(20000)});
if(!pageResponse.ok)throw Error(`CDP page creation failed: HTTP ${pageResponse.status}`);
const page=await pageResponse.json();
let client=null,primaryError=null,output=null,reference=null,manifest=null;
let actualNavigationUrl=null,sourceBinding=null;

try {
  client=await connectCdp(page.webSocketDebuggerUrl);
  const {call}=client;
  const sourceResponses=new Map();
  client.onEvent(message=>recordSourceResponse(
    sourceResponses,
    message,
    new URL(navigation.url).origin,
    sourceSpecifications,
  ));
  output=await artifactOutput({publish,publishUrl:new URL('../results/xbox_sketchfab_viewer_reference/camera_axes/',import.meta.url),temporaryPrefix:'xbox-sketchfab-camera-axes-'});
  const cache=await prepareUncachedNetwork(call);
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride', {
    width: 1200,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false,
  });
  const navigationResult=await call('Page.navigate', {url:navigation.url});
  if(navigationResult.errorText)throw Error(`Reference navigation failed: ${navigationResult.errorText}`);
  reference=await evaluateCdp(client,`new Promise((resolve, reject) => {
      const deadline = Date.now() + 90000;
      function poll() {
        if (document.body.dataset.error) reject(Error(document.body.dataset.error));
        else if (window.reference?.ready) resolve({...window.reference, api: undefined});
        else if (Date.now() > deadline) reject(Error('viewer timeout'));
        else setTimeout(poll, 250);
      }
      poll();
    })`,{callTimeout:100000});
  if(reference.error||reference.environmentError||reference.cameraError)throw Error(`Reference reported an API error: ${JSON.stringify(reference)}`);
  if(reference.uid!==expectedUid)throw Error(`Unexpected Sketchfab model UID: ${reference.uid}`);
  actualNavigationUrl=await evaluateCdp(client,'location.href');
  sourceBinding=await buildVerifiedSourceBinding({
    call,
    responses:sourceResponses,
    specifications:sourceSpecifications,
    navigation,
    actualNavigationUrl,
    cache,
    externalAssetScope:'Only the locally maintained Sketchfab entry HTML is worktree-bound. Viewer API scripts, iframe documents, model streams and environment bytes remain external and are not represented as local source hashes.',
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
  manifest = [];
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
    const result=await evaluateCdp(client,expression);
    const shot = await call('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
    });
    const file = `${name}.png`;
    await writeFile(join(output.directory,file), Buffer.from(shot.data, 'base64'));
    manifest.push({name, file, artifact_availability:'rebuildable_ignored', ...result});
  }
  await writeFile(join(output.directory,'manifest.json'), JSON.stringify({
    artifact_distribution:{batch_renders_default:'rebuildable_ignored',meaning:'Camera-axis screenshots are diagnostic generation outputs and are not distributed in a clean Git clone; recapture requires the public Sketchfab model, Viewer API, Chrome CDP and network access.'},
    capture:{model_uid:reference.uid,requested_navigation_url:navigation.url,navigation_url:actualNavigationUrl,source_binding:sourceBinding},
    views:manifest,
  }, null, 2));
} catch(error) {
  primaryError=error;
  throw error;
} finally {
  client?.close();
  try { await closeCdpTarget(base,page.id); }
  catch(error) {
    if(!primaryError)throw error;
    console.error(JSON.stringify({cleanup_warning:String(error),target_id:page.id}));
  }
}
// Do not replace canonical evidence until the temporary browser target is
// confirmed closed; cleanup failure makes the command fail without publishing.
await output.finalize();
console.log(JSON.stringify({model_uid:reference.uid,requested_navigation_url:navigation.url,navigation_url:actualNavigationUrl,source_binding:sourceBinding,views:manifest,published:output.published,output_directory:output.directory},null,2));
