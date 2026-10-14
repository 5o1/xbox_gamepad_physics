import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {artifactOutput} from './artifact_output.mjs';
import {
 buildVerifiedSourceBinding,
 MATERIAL_MODULE_SOURCE_RESOURCES,
 makeCacheBustedNavigationUrl,
 prepareUncachedNetwork,
 recordSourceResponse,
} from './browser_source_binding.mjs';
import {closeCdpTarget,connectCdp,evaluateCdp} from './cdp_client.mjs';
const args=process.argv.slice(2),publishIndex=args.indexOf('--publish'),publish=publishIndex!==-1;
if(publish)args.splice(publishIndex,1);
if(args.length)throw Error(`Unknown arguments: ${args.join(' ')}`);
const endpoint=process.env.MATERIAL_REVIEW_URL??'http://127.0.0.1:9877/material_check.html';
const base=process.env.CHROME_CDP??'http://127.0.0.1:9227';
const navigation=makeCacheBustedNavigationUrl(endpoint);
const sourceSpecifications=[
 {request_path:new URL(navigation.url).pathname,binding_kind:'workspace',binding_path:'viewer/material_check.html'},
 ...MATERIAL_MODULE_SOURCE_RESOURCES,
];
const modelUid='a62cf7475b7d4ead9fbf1a86e5a2b6a4';
const targetResponse=await fetch(`${base}/json/new?about:blank`,{method:'PUT',signal:AbortSignal.timeout(20000)});
if(!targetResponse.ok)throw Error(`CDP page creation failed: HTTP ${targetResponse.status}`);
const target=await targetResponse.json();
let client=null,primaryError=null,output=null,audit=null;
let actualNavigationUrl=null,sourceBinding=null;
try{
client=await connectCdp(target.webSocketDebuggerUrl);
const {call}=client;
const sourceResponses=new Map();
client.onEvent(message=>recordSourceResponse(
 sourceResponses,
 message,
 new URL(navigation.url).origin,
 sourceSpecifications,
));
output=await artifactOutput({publish,publishUrl:new URL('../build/experiments/xbox_native_gltf_materials/',import.meta.url),temporaryPrefix:'xbox-material-browser-'});
const cache=await prepareUncachedNetwork(call);
await call('Runtime.enable');await call('Page.enable');
await call('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
const navigationResult=await call('Page.navigate',{url:navigation.url});
if(navigationResult.errorText)throw Error(`Material review navigation failed: ${navigationResult.errorText}`);
audit=await evaluateCdp(client,`new Promise((resolve,reject)=>{const end=Date.now()+30000;function tick(){if(document.body.dataset.error)return reject(Error(document.body.dataset.error));if(document.body.dataset.ready)return requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(window.materialAudit)));if(Date.now()>end)return reject(Error('load timeout'));setTimeout(tick,100);}tick();})`,{callTimeout:40000});
if(audit.checks.meshCount!==16||!audit.checks.allPBRMapsPresent)throw Error('material assertions failed');
if(audit.threeRevision!=='180')throw Error(`Unexpected Three.js revision: ${audit.threeRevision}`);
actualNavigationUrl=await evaluateCdp(client,'location.href');
sourceBinding=await buildVerifiedSourceBinding({
 call,
 responses:sourceResponses,
 specifications:sourceSpecifications,
 navigation,
 actualNavigationUrl,
 cache,
 externalAssetScope:'The local material entry/module and its complete Three.js execution graph are hash-bound. The external GLB is independently identified by audit.checks.sourceHash; its bytes are not claimed as Git-tracked viewer source.',
});
const runtimeAudit={...audit,capture:{model_uid:modelUid,model_source_sha256:audit.checks.sourceHash,requested_navigation_url:navigation.url,navigation_url:actualNavigationUrl,source_binding:sourceBinding}};
await writeFile(join(output.directory,'runtime_audit.json'),JSON.stringify(runtimeAudit,null,2));
for(const [button,file] of [['front','front.png'],['angle','angle.png']]){
 await evaluateCdp(client,`document.querySelector('#${button}').click();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
 const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(join(output.directory,file),Buffer.from(shot.data,'base64'));
}
await evaluateCdp(client,"document.querySelector('#front').click();window.setDepthDiagnostic(true);document.querySelector('#status').textContent='Diagnostic only: transparent material depth writes enabled; not yet accepted';new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))");
const diagnostic=await call('Page.captureScreenshot',{format:'png'});
await writeFile(join(output.directory,'depth_write_diagnostic.png'),Buffer.from(diagnostic.data,'base64'));
}catch(error){primaryError=error;throw error;}
finally{
client?.close();
try{await closeCdpTarget(base,target.id);}
catch(error){if(!primaryError)throw error;console.error(JSON.stringify({cleanup_warning:String(error),target_id:target.id}));}
}
// Canonical evidence changes only after the temporary CDP target is closed.
await output.finalize();
console.log(JSON.stringify({...audit.checks,model_uid:modelUid,requested_navigation_url:navigation.url,navigation_url:actualNavigationUrl,source_binding:sourceBinding,published:output.published,output_directory:output.directory}));
