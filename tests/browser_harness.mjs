// Synthetic browser integration test, NOT a physical-controller acceptance test.
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {artifactOutput} from './artifact_output.mjs';
import {
  buildVerifiedSourceBinding,
  CACHE_BUSTER_PARAMETER,
  CRITICAL_SOURCE_RESOURCES,
  makeCacheBustedNavigationUrl,
  prepareUncachedNetwork,
  recordCriticalResponse,
} from './browser_source_binding.mjs';
import {connectCdp, describeRuntimeException, evaluateCdp} from './cdp_client.mjs';

const argv=process.argv.slice(2);
const publishIndex=argv.indexOf('--publish');
const publish=publishIndex!==-1;
if(publish)argv.splice(publishIndex,1);
function option(name,fallback){
  const equals=argv.findIndex(value=>value.startsWith(`${name}=`));
  if(equals!==-1)return argv.splice(equals,1)[0].slice(name.length+1);
  const index=argv.indexOf(name);
  if(index===-1)return fallback;
  if(index===argv.length-1)throw Error(`${name} requires a value`);
  return argv.splice(index,2)[1];
}
const variantId=option('--variant-id',process.env.XBOX_VIEWER_VARIANT_ID??'legacy_casper_1914_width_scaled_proxy');
assert.deepEqual(argv,[],`Unknown arguments: ${argv.join(' ')}`);
const expectedVariants={
  legacy_casper_1914_width_scaled_proxy:{
    source_candidate_id:'xbox_series_1914_casperh2o_visual',
    status:'width_matched_visual_proxy_not_1708_mechanical_asset',
    inventory_sha256:'c565dd92a5ca6f7a241258b693b9d5120af78cbf5717c89202a51e99d86b50df',
    source_inventory_sha256:'1430fc227cac9c27c1b480e38b603650fa794b3fac21f04a18ebe1123378678a',
    dimensions_evidence_sha256:'25f272d5cbe866d36dc83a2a30bc70a4884cccc4d1d1b3d5dad206c6aac5914c',
    mesh_count:42,
    excluded_objects:['ShareButton','ShareButtonSymbol'],
  },
};
const expectedVariant=expectedVariants[variantId];
assert.ok(expectedVariant,`Unsupported browser fixture variant_id: ${variantId}`);
const cdpUrl=process.env.XBOX_VIEWER_CDP_URL ?? 'http://127.0.0.1:9227';
const viewerUrl=process.env.XBOX_VIEWER_URL ?? 'http://127.0.0.1:9876/';
const navigation=makeCacheBustedNavigationUrl(viewerUrl);
const requestedNavigationUrl=navigation.url;
const output=await artifactOutput({publish,publishUrl:new URL('../results/',import.meta.url),temporaryPrefix:'xbox-viewer-harness-'});
const normalizedViewerPage=raw=>{
  try{
    const url=new URL(raw);
    url.searchParams.delete(CACHE_BUSTER_PARAMETER);
    url.hash='';
    return url.href;
  }catch{return null;}
};
const expectedViewerPage=normalizedViewerPage(viewerUrl);
const requests=new Map(),resourceFailures=[],runtimeFailures=[],criticalResponses=new Map();
const viewerOrigin=new URL(viewerUrl).origin;
const isCritical=url=>{
  try{
    const parsed=new URL(url);
    if(parsed.origin!==viewerOrigin)return false;
    return parsed.pathname!=='/favicon.ico';
  }catch{return false;}
};
const startedAt=new Date().toISOString();
let stage='cdp_page_list';
let actualNavigationUrl=null;
let cacheState={network_cache_disabled:false,browser_cache_cleared_before_navigation:false};
let client=null,call=null,evaluate=null,inspect=null;
try{
  const pagesResponse=await fetch(`${cdpUrl}/json/list`,{signal:AbortSignal.timeout(20000)});
  assert.equal(pagesResponse.status,200,'CDP page list unavailable');
  const pages=await pagesResponse.json();
  stage='cdp_target_selection';
  const page=pages.find(p=>p.type==='page'&&p.url===viewerUrl)
    ?? pages.find(p=>p.type==='page'&&normalizedViewerPage(p.url)===expectedViewerPage);
  assert.ok(page,'Dedicated test browser page missing');
  stage='cdp_connect';
  client=await connectCdp(page.webSocketDebuggerUrl);
  call=client.call;
  evaluate=expression=>evaluateCdp(client,expression);
  inspect=()=>evaluate("import('/app.mjs').then(m=>m.inspect())");
  client.onEvent(message=>{
    if(message.method==='Network.requestWillBeSent')requests.set(message.params.requestId,message.params.request.url);
    recordCriticalResponse(criticalResponses,message,viewerOrigin);
    if(message.method==='Network.responseReceived'&&message.params.response.status>=400&&isCritical(message.params.response.url)){
      resourceFailures.push({kind:'http',url:message.params.response.url,status:message.params.response.status});
    }
    if(message.method==='Network.loadingFailed'){
      const url=requests.get(message.params.requestId);
      if(url&&isCritical(url))resourceFailures.push({kind:'loadingFailed',url,error:message.params.errorText});
    }
    if(message.method==='Runtime.exceptionThrown')runtimeFailures.push(describeRuntimeException(message.params.exceptionDetails));
  });
  stage='http_health';
  cacheState=await prepareUncachedNetwork(call);
  await call('Runtime.enable');
  await call('Page.enable');
  const health=await fetch(viewerUrl,{signal:AbortSignal.timeout(20000)});
  assert.equal(health.status,200,'Viewer HTTP service unavailable');
  stage='candidate_identity';
  const registryResponse=await fetch(new URL('/registry/asset_index.json',viewerUrl),{signal:AbortSignal.timeout(20000)});
  assert.equal(registryResponse.status,200,'Canonical asset registry unavailable');
  const registry=await registryResponse.json();
  const registeredVariants=new Set([
    registry.interactive_viewer.active_variant_id,
    ...(registry.interactive_viewer.allowed_variant_ids??[]),
  ]);
  assert.equal(registeredVariants.has(variantId),true,'Requested legacy fixture is absent from the viewer allowlist');
  const registryVariant=registry.derived_variants?.[variantId];
  assert.ok(registryVariant,`Variant absent from canonical asset registry: ${variantId}`);
  assert.equal(registryVariant.source_candidate_id,expectedVariant.source_candidate_id,'Variant source candidate does not match expected identity');
  assert.equal(registryVariant.inventory,'../results/legacy_casper_1914_width_scaled_1708_proxy/inventory.json','Variant registry points at an unexpected inventory');
  assert.equal(registryVariant.inventory_sha256,expectedVariant.inventory_sha256,'Registry inventory hash does not match the reviewed fixture');
  assert.equal(registry.primary_appearance_candidate_id==='xbox_one_s_batonyrobson_a62cf747',true,'Unexpected primary appearance candidate');
  assert.notEqual(registry.primary_appearance_candidate_id,registryVariant.source_candidate_id,'Legacy viewer fixture must not be presented as the primary candidate');
  const inventoryResponse=await fetch(new URL('/assets/inventory.json',viewerUrl),{signal:AbortSignal.timeout(20000)});
  assert.equal(inventoryResponse.status,200,'Fixture inventory unavailable');
  const inventoryBytes=await inventoryResponse.arrayBuffer();
  const inventoryDigest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',inventoryBytes))].map(value=>value.toString(16).padStart(2,'0')).join('');
  assert.equal(inventoryDigest,registryVariant.inventory_sha256,'Served fixture inventory bytes do not match the canonical registry');
  const inventory=JSON.parse(new TextDecoder().decode(inventoryBytes));
  assert.equal(inventory.status,expectedVariant.status,'Fixture status does not match variant_id');
  assert.equal(inventory.source_inventory_sha256,expectedVariant.source_inventory_sha256,'Fixture source inventory does not match variant_id');
  assert.equal(inventory.dimensions_evidence_sha256,expectedVariant.dimensions_evidence_sha256,'Fixture dimensions evidence does not match variant_id');
  assert.equal(inventory.objects.length,expectedVariant.mesh_count,'Fixture mesh count does not match variant_id');
  assert.deepEqual(inventory.excluded_objects,expectedVariant.excluded_objects,'Fixture exclusions do not match variant_id');
  stage='page_navigation';
  const navigationResult=await call('Page.navigate',{url:requestedNavigationUrl});
  assert.equal(navigationResult.errorText,undefined,`Viewer navigation failed: ${navigationResult.errorText}`);
  stage='document_readiness';
  await call('Page.bringToFront');
  for(let i=0;i<60;i++){
    if(await evaluate("document.readyState==='complete' && !!document.getElementById('rig')"))break;
    await new Promise(r=>setTimeout(r,500));
  }
  assert.ok(await evaluate("!!document.getElementById('rig')"),'Viewer document did not load');
  actualNavigationUrl=await evaluate('location.href');
  const actualNavigation=new URL(actualNavigationUrl);
  const requestedNavigation=new URL(requestedNavigationUrl);
  assert.equal(actualNavigation.origin,requestedNavigation.origin,'Viewer navigation changed origin');
  assert.equal(actualNavigation.pathname,requestedNavigation.pathname,'Viewer navigation changed path');
  assert.equal(actualNavigation.searchParams.get(CACHE_BUSTER_PARAMETER),navigation.nonce,'Viewer navigation lost its cache-buster');
  stage='asset_readiness';
  let state;
  for(let i=0;i<60;i++){state=await inspect();if(state.ready)break;await new Promise(r=>setTimeout(r,500));}
  assert.equal(state.ready,true);assert.equal(state.parts.length,42);
  assert.equal(state.activeVariantId,variantId,'Viewer runtime did not bind the requested variant identity');
  await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  const images=await evaluate("[...document.images].map(image=>({src:image.currentSrc||image.src,complete:image.complete,naturalWidth:image.naturalWidth,naturalHeight:image.naturalHeight}))");
  assert.ok(images.length>0,'Expected at least one critical viewer image');
  assert.deepEqual(images.filter(image=>!image.complete||image.naturalWidth===0||image.naturalHeight===0),[],'Critical viewer image failed to load');
  assert.deepEqual(resourceFailures,[],'Critical viewer resource failed to load');
  assert.deepEqual(runtimeFailures,[],'Viewer raised an uncaught runtime exception');
  stage='source_binding';
  const sourceBinding=await buildVerifiedSourceBinding({
    call,
    responses:criticalResponses,
    specifications:CRITICAL_SOURCE_RESOURCES,
    navigation,
    actualNavigationUrl,
    cache:cacheState,
    externalAssetScope:'OBJ meshes are external to Git and are intentionally not claimed as workspace source bindings; fixture_inventory remains their reviewed identity boundary',
  });
  stage='mouse_fixture';
  // Deliberately synthetic dimensions and axis. Never saved as target calibration.
  const rig={schema:1,joints:[{channel:4,type:'prismatic',axis:[0,1,0],pivot:[0,0,0],q0:0,q1:.003,meshes:['A','A-Button','A-Interior','A-Interior2'],evidence:'Synthetic UI harness only; NOT a measured or estimated Xbox mechanism'}]};
  await evaluate(`(async()=>{const d=new DataTransfer();d.items.add(new File([${JSON.stringify(JSON.stringify(rig))}],'synthetic-harness.json',{type:'application/json'}));const input=document.getElementById('rig');input.files=d.files;input.dispatchEvent(new Event('change'));})()`);
  for(let i=0;i<30;i++){state=await inspect();if(state.joints===1)break;await new Promise(r=>setTimeout(r,100));}
  assert.equal(state.joints,1);
  const [x,y]=state.parts.find(p=>p.name==='A-Button').screen;
  await call('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',buttons:1,clickCount:1});
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x,y:y-40,button:'left',buttons:1});
  state=await inspect();assert.ok(state.values[4]>.1,'Mouse drag failed to produce A state');
  const moved=state.parts.find(p=>p.name==='A-Button').matrix;
  assert.ok(moved[13]>0,'Mesh did not move along test axis');
  await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const mouseShot=await call('Page.captureScreenshot',{format:'png'});
  await writeFile(join(output.directory,`${variantId}_browser_mouse_synthetic.png`),Buffer.from(mouseShot.data,'base64'));
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',x,y:y-40,button:'left',buttons:0,clickCount:1});
  state=await inspect();assert.equal(state.values[4],0);
  const lifecycleResults=[];
  stage='input_lifecycle';
  for(const [name,expression,reason] of [
    ['blur_handler',"window.dispatchEvent(new Event('blur'))",'focus_loss'],
    ['pointer_cancel_handler',"document.querySelector('canvas').dispatchEvent(new PointerEvent('pointercancel',{pointerId:POINTER,bubbles:true}))",'pointer_cancel'],
    ['capture_loss',"document.querySelector('canvas').releasePointerCapture(POINTER)",'capture_lost'],
    ['mode_switch',"document.getElementById('mode').value='device';document.getElementById('mode').dispatchEvent(new Event('change'))",'mode_change'],
    ['device_selection_handler',"document.getElementById('device').dispatchEvent(new Event('change'))",'device_change']
  ]){
    await evaluate("document.getElementById('mode').value='mouse';document.getElementById('mode').dispatchEvent(new Event('change'));document.getElementById('hold').checked=true");
    state=await inspect();const [ax,ay]=state.parts.find(p=>p.name==='A-Button').screen;
    await call('Input.dispatchMouseEvent',{type:'mousePressed',x:ax,y:ay,button:'left',buttons:1,clickCount:1});
    await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:ax,y:ay-20,button:'left',buttons:1});
    state=await inspect();assert.ok(state.values[4]>.1&&state.dragging,`${name}: input not armed`);
    const pointer=state.pointerId;
    await evaluate(expression.replace('POINTER',String(pointer)));
    // Processes pending native lostpointercapture after releasePointerCapture.
    await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:ax+1,y:ay-20,button:'left',buttons:1});
    state=await inspect();assert.ok(state.values.every(v=>v===0),`${name}: stale input`);
    assert.equal(state.dragging,false);assert.equal(state.orbitEnabled,true);
    // Device polling can replace mode_change with a disconnected frame.
    if(name!=='mode_switch')assert.equal(state.reason,reason);
    assert.equal(await evaluate(`document.querySelector('canvas').hasPointerCapture(${pointer})`),false);
    await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:ax+1,y:ay-20,button:'left',buttons:0,clickCount:1});
    lifecycleResults.push(name);
  }
  await evaluate("document.getElementById('hold').checked=false");
  stage='synthetic_device';
  // Synthetic API injection exercises browser polling, not USB/hardware validation.
  await evaluate(`window.testPad={connected:true,mapping:'standard',index:0,id:'SYNTHETIC TEST PAD',timestamp:1,axes:[0,0,0,0],buttons:Array.from({length:17},(_,i)=>({value:i===0?.75:0,pressed:i===0}))};Object.defineProperty(navigator,'getGamepads',{configurable:true,value:()=>[window.testPad]});document.getElementById('mode').value='device';document.getElementById('mode').dispatchEvent(new Event('change'));`);
  for(let i=0;i<30;i++){state=await inspect();if(state.values[4]===.75)break;await new Promise(r=>setTimeout(r,100));}
  assert.equal(state.values[4],.75);assert.ok(Math.abs(state.parts.find(p=>p.name==='A-Button').matrix[13]-.00225)<1e-10);
  await evaluate('window.testPad=null');
  for(let i=0;i<30;i++){state=await inspect();if(state.values[4]===0)break;await new Promise(r=>setTimeout(r,100));}
  assert.equal(state.values[4],0);
  // Two noncommuting rotations on actual mesh; dimensions deliberately synthetic.
  stage='compound_and_two_axis_drag';
  const stickRig={schema:1,joints:[
    {channel:0,type:'revolute',axis:[0,0,1],pivot:[-.04,0,.02],q0:-.2,q1:.2,meshes:['LeftThumb','Joystick-Left-Ring'],evidence:'Synthetic compound-frame regression, not Xbox pivot'},
    {channel:1,type:'revolute',axis:[1,0,0],pivot:[-.04,0,.02],q0:-.2,q1:.2,meshes:['LeftThumb','Joystick-Left-Ring'],evidence:'Synthetic compound-frame regression, not Xbox pivot'}
  ]};
  await evaluate(`(async()=>{const d=new DataTransfer();d.items.add(new File([${JSON.stringify(JSON.stringify(stickRig))}],'synthetic-two-axis.json',{type:'application/json'}));const input=document.getElementById('rig');input.files=d.files;input.dispatchEvent(new Event('change'));document.getElementById('mode').value='mouse';document.getElementById('mode').dispatchEvent(new Event('change'));document.getElementById('hold').checked=true;})()`);
  for(let i=0;i<30;i++){state=await inspect();if(state.joints===2)break;await new Promise(r=>setTimeout(r,100));}
  assert.equal(state.joints,2);
  await evaluate("document.getElementById('drag2d').checked=false");
  async function dragStick(channel,dx,dy){
    await evaluate(`document.getElementById('channel').value='${channel}'`);
    const before=await inspect(), [sx,sy]=before.parts.find(p=>p.name==='LeftThumb').screen;
    await call('Input.dispatchMouseEvent',{type:'mousePressed',x:sx,y:sy,button:'left',buttons:1,clickCount:1});
    await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:sx+dx,y:sy+dy,button:'left',buttons:1});
    await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:sx+dx,y:sy+dy,button:'left',buttons:0,clickCount:1});
    await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
    const after=await inspect();
    assert.ok(stickRig.joints[0].meshes.includes(after.selected),'Pointer did not hit synthetic stick group');
    assert.ok(Math.abs(after.values[channel]-before.values[channel])>.01,`No motion on axis ${channel}`);
    return after;
  }
  state=await dragStick(1,0,-20);
  const heldY=state.values[1];
  state=await dragStick(0,20,0);
  assert.equal(state.values[1],heldY,'Editing X changed held Y');
  // Independent closed-form Rx(y)Rz(x), column-major, about a synthetic pivot.
  const xAngle=.2*state.values[0],yAngle=.2*state.values[1];
  const cx=Math.cos(xAngle),sx=Math.sin(xAngle),cy=Math.cos(yAngle),sy=Math.sin(yAngle);
  const expected=[cx,cy*sx,sy*sx,0,-sx,cy*cx,sy*cx,0,0,-sy,cy,0,0,0,0,1];
  const pivot=stickRig.joints[0].pivot;
  for(let row=0;row<3;row++)expected[12+row]=pivot[row]-pivot.reduce((sum,p,col)=>sum+expected[col*4+row]*p,0);
  const actual=state.parts.find(p=>p.name==='LeftThumb').matrix;
  actual.forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<1e-10,`Compound matrix mismatch ${i}`));
  await evaluate(`document.getElementById('reset').click();document.getElementById('hold').checked=false`);
  state=await inspect();assert.equal(state.values[0],0);assert.equal(state.values[1],0);
  await evaluate("document.getElementById('drag2d').checked=true");
  const [dx,dy]=state.parts.find(p=>p.name==='LeftThumb').screen;
  await call('Input.dispatchMouseEvent',{type:'mousePressed',x:dx,y:dy,button:'left',buttons:1,clickCount:1});
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:dx+3,y:dy-3,button:'left',buttons:1});
  state=await inspect();
  assert.ok(Math.abs(state.values[0])>.001&&Math.abs(state.values[1])>.001,'One pointer motion must update both stick axes');
  assert.ok(state.values.every(Number.isFinite));
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:dx+3,y:dy-3,button:'left',buttons:0,clickCount:1});
  state=await inspect();assert.equal(state.values[0],0);assert.equal(state.values[1],0);
  // Restore the A fixture before the existing device-polling regression.
  await evaluate(`(async()=>{const d=new DataTransfer();d.items.add(new File([${JSON.stringify(JSON.stringify(rig))}],'synthetic-harness.json',{type:'application/json'}));const input=document.getElementById('rig');input.files=d.files;input.dispatchEvent(new Event('change'));})()`);
  for(let i=0;i<30;i++){state=await inspect();if(state.joints===1)break;await new Promise(r=>setTimeout(r,100));}
  assert.equal(state.joints,1);
  const screenshot=await call('Page.captureScreenshot',{format:'png'});
  await writeFile(join(output.directory,`${variantId}_browser_tested.png`),Buffer.from(screenshot.data,'base64'));
  assert.deepEqual(resourceFailures,[],'Critical viewer resource failed during the harness');
  assert.deepEqual(runtimeFailures,[],'Viewer raised an uncaught runtime exception during the harness');
  const browserVersion=await call('Browser.getVersion');
  const threeRevision=await evaluate("import('three').then(module=>module.REVISION)");
  assert.equal(threeRevision,'180','Viewer loaded an unreviewed Three.js revision');
  const result={schema_version:2,passed:true,variant_id:variantId,source_candidate_id:registryVariant.source_candidate_id,primary_appearance_candidate_id:registry.primary_appearance_candidate_id,candidate_role:'legacy_visual_proxy_browser_fixture',primary_appearance_candidate_tested:false,fixture_inventory:{inventory_sha256:inventoryDigest,status:inventory.status,source_inventory_sha256:inventory.source_inventory_sha256,dimensions_evidence_sha256:inventory.dimensions_evidence_sha256,mesh_count:inventory.objects.length,excluded_objects:inventory.excluded_objects},runtime:{browser:browserVersion,three_revision:threeRevision,viewer_url:viewerUrl,requested_navigation_url:requestedNavigationUrl,navigation_url:actualNavigationUrl,cdp_url:cdpUrl},source_binding:sourceBinding,critical_resource_validation:true,critical_resource_failures:resourceFailures,mesh_count:42,synthetic_mouse_to_signal:true,synthetic_signal_to_mesh:true,synthetic_compound_axis_drag:true,simultaneous_two_axis_pointer_drag:true,two_axis_release_reset:true,compound_pose_matches_independent_formula:true,release_reset:true,disconnect_reset:true,lifecycle_browser_checks:lifecycleResults,lifecycle_scope:'Actual CDP mouse drag and native pointer capture; blur/cancel/device-selection handlers dispatched as DOM test events, not OS event generation',real_controller_tested:false,target_rig_calibrated:false};
  await writeFile(join(output.directory,'browser_harness.json'),JSON.stringify(result,null,2)+'\n');
  await writeFile(join(output.directory,'browser_last_attempt.json'),JSON.stringify({startedAt,finishedAt:new Date().toISOString(),passed:true,stage:'complete',variant_id:variantId,source_candidate_id:registryVariant.source_candidate_id,primaryAppearanceCandidateTested:false,requested_navigation_url:requestedNavigationUrl,navigation_url:actualNavigationUrl,source_binding_verified:true,physicalAcceptance:false},null,2)+'\n');
  await output.finalize();
  console.log(JSON.stringify({...result,published:output.published,output_directory:output.directory}));
}catch(error){
  const attempt={startedAt,finishedAt:new Date().toISOString(),passed:false,stage,variant_id:variantId,source_candidate_id:expectedVariant.source_candidate_id,primaryAppearanceCandidateTested:false,requested_navigation_url:requestedNavigationUrl,navigation_url:actualNavigationUrl,cache:{...cacheState,nonce_parameter:navigation.parameter,nonce:navigation.nonce},error:String(error),physicalAcceptance:false,previousHarnessResult:'Historical result only; does not verify current code',publish_requested:publish,published:publish,output_directory:output.directory};
  await writeFile(join(output.directory,'browser_last_attempt.json'),JSON.stringify(attempt,null,2)+'\n');
  // A failed publish updates only the attempt marker. The previous successful
  // harness report and screenshots remain intact and must not be replaced by
  // a partial staging set.
  if(publish){
    try{await output.finalize({files:['browser_last_attempt.json']});}
    catch(publishError){throw new AggregateError([error,publishError],'Browser harness failed and its last-attempt marker could not be published');}
  }
  console.error(JSON.stringify(attempt));
  throw error;
}finally{
  if(evaluate)await evaluate("delete navigator.getGamepads;delete window.testPad;location.reload()").catch(()=>{});
  client?.close();
}
