import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {artifactOutput} from './artifact_output.mjs';
import {
 buildVerifiedSourceBinding,
 makeCacheBustedNavigationUrl,
 prepareUncachedNetwork,
 recordSourceResponse,
} from './browser_source_binding.mjs';
import {closeCdpTarget,connectCdp,evaluateCdp} from './cdp_client.mjs';
const args=process.argv.slice(2),publishIndex=args.indexOf('--publish'),publish=publishIndex!==-1;
if(publish)args.splice(publishIndex,1);
if(args.length)throw Error(`Unknown arguments: ${args.join(' ')}`);
const base=process.env.CHROME_CDP??'http://127.0.0.1:9230';
const url=process.env.REFERENCE_URL??'http://127.0.0.1:9877/sketchfab_reference.html';
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
let client=null,primaryError=null,output=null,runtime=null;
try{
 client=await connectCdp(page.webSocketDebuggerUrl);
 const {call}=client,events=[],sourceResponses=new Map();
 client.onEvent(message=>{
  recordSourceResponse(sourceResponses,message,new URL(navigation.url).origin,sourceSpecifications);
  if(['Network.loadingFailed','Runtime.consoleAPICalled','Runtime.exceptionThrown'].includes(message.method))events.push(message);
 });
 output=await artifactOutput({publish,publishUrl:new URL('../build/experiments/xbox_sketchfab_viewer_reference/',import.meta.url),temporaryPrefix:'xbox-sketchfab-reference-'});
 const cache=await prepareUncachedNetwork(call);
 await call('Runtime.enable');await call('Page.enable');
 await call('Emulation.setDeviceMetricsOverride',{width:1600,height:900,deviceScaleFactor:1,mobile:false});
 const navigationResult=await call('Page.navigate',{url:navigation.url});
 if(navigationResult.errorText)throw Error(`Reference navigation failed: ${navigationResult.errorText}`);
 const reference=await evaluateCdp(client,`new Promise((resolve,reject)=>{const end=Date.now()+90000;function poll(){if(document.body.dataset.error)return reject(Error(document.body.dataset.error));if(window.reference?.ready)return requestAnimationFrame(()=>requestAnimationFrame(()=>resolve({...window.reference,api:undefined})));if(Date.now()>end)return reject(Error('Sketchfab viewer timeout '+JSON.stringify(window.reference)));setTimeout(poll,250)}poll()})`,{callTimeout:100000}).catch(error=>{console.error(JSON.stringify(events,null,2));throw error;});
 if(reference.error||reference.environmentError||reference.cameraError)throw Error(`Reference reported an API error: ${JSON.stringify(reference)}`);
 if(reference.uid!==expectedUid)throw Error(`Unexpected Sketchfab model UID: ${reference.uid}`);
 const actualNavigationUrl=await evaluateCdp(client,'location.href');
 const sourceBinding=await buildVerifiedSourceBinding({
  call,
  responses:sourceResponses,
  specifications:sourceSpecifications,
  navigation,
  actualNavigationUrl,
  cache,
  externalAssetScope:'Only the locally maintained Sketchfab entry HTML is worktree-bound. Viewer API scripts, iframe documents, model streams and environment bytes remain external and are not represented as local source hashes.',
 });
 runtime={...reference,capture:{model_uid:reference.uid,requested_navigation_url:navigation.url,navigation_url:actualNavigationUrl,source_binding:sourceBinding}};
 await writeFile(join(output.directory,'runtime.json'),JSON.stringify(runtime,null,2));
 // Use Sketchfab's documented renderer screenshot API for the acceptance
 // reference.  A DevTools screenshot includes the embed UI and is retained
 // separately only as browser-context evidence.
 const dataUrl=await evaluateCdp(client,`new Promise((resolve,reject)=>window.reference.api.getScreenShot(1600,900,'image/png',(error,result)=>error?reject(Error(String(error))):resolve(result)))`);
 if(typeof dataUrl!=='string'||!dataUrl.startsWith('data:image/png;base64,'))throw Error('Unexpected Viewer API screenshot result');
 await writeFile(join(output.directory,'front.png'),Buffer.from(dataUrl.slice(dataUrl.indexOf(',')+1),'base64'));
 const browserShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 await writeFile(join(output.directory,'browser_context.png'),Buffer.from(browserShot.data,'base64'));
}catch(error){primaryError=error;throw error;}
finally{
 client?.close();
 try{await closeCdpTarget(base,page.id);}
 catch(error){if(!primaryError)throw error;console.error(JSON.stringify({cleanup_warning:String(error),target_id:page.id}));}
}
// Publishing happens only after CDP target cleanup succeeds. A command that
// exits nonzero must not have already replaced canonical capture evidence.
await output.finalize();
console.log(JSON.stringify({...runtime,published:output.published,output_directory:output.directory}));
