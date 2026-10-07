import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {closeCdpTarget,connectCdp,describeRuntimeException,evaluateCdp} from './cdp_client.mjs';
import {buildVerifiedSourceBinding,makeCacheBustedNavigationUrl,prepareUncachedNetwork,recordSourceResponse,V0_SOURCE_RESOURCES} from './browser_source_binding.mjs';

const viewerUrl=process.argv[2]??'http://127.0.0.1:9898/v0.html';
const cdpUrl=process.argv[3]??'http://127.0.0.1:9310';
const output=process.argv[4]??'/tmp/xbox-v0-browser';
await mkdir(output,{recursive:true});
const navigation=makeCacheBustedNavigationUrl(viewerUrl),viewerParsed=new URL(viewerUrl),viewerOrigin=viewerParsed.origin;
let page=null,client=null,call=null,evaluate=null,harnessFailed=false;const runtimeFailures=[],resourceFailures=[],requests=new Map(),criticalResponses=new Map();try{
  const pageResponse=await fetch(new URL('/json/new?about:blank',cdpUrl),{method:'PUT',signal:AbortSignal.timeout(20_000)});assert.ok(pageResponse.ok,`create CDP target: HTTP ${pageResponse.status}`);page=await pageResponse.json();assert.ok(page.id&&page.webSocketDebuggerUrl,'created CDP target is incomplete');
  client=await connectCdp(page.webSocketDebuggerUrl);call=client.call;evaluate=expression=>evaluateCdp(client,expression);client.onEvent(message=>{
    if(message.method==='Runtime.exceptionThrown')runtimeFailures.push(describeRuntimeException(message.params.exceptionDetails));
    if(message.method==='Network.requestWillBeSent')requests.set(message.params.requestId,message.params.request.url);
    recordSourceResponse(criticalResponses,message,viewerOrigin,V0_SOURCE_RESOURCES);
    if(message.method==='Network.responseReceived'&&message.params.response.status>=400)resourceFailures.push({url:message.params.response.url,status:message.params.response.status});
    if(message.method==='Network.loadingFailed')resourceFailures.push({url:requests.get(message.params.requestId),error:message.params.errorText});
  });
  const cache=await prepareUncachedNetwork(call);await call('Runtime.enable');await call('Page.enable');
  const navigationResult=await call('Page.navigate',{url:navigation.url});assert.equal(navigationResult.errorText,undefined,`viewer navigation failed: ${navigationResult.errorText}`);await call('Page.bringToFront');
  const inspect=()=>evaluate("import('/v0_app.mjs').then(module=>module.inspect())");
  const waitForInspect=async(predicate,label,{attempts=180,intervalMs=20}={})=>{
    let observed=null;
    for(let attempt=0;attempt<attempts;attempt++){
      observed=await inspect();if(predicate(observed))return observed;
      await new Promise(resolve=>setTimeout(resolve,intervalMs));
    }
    throw new Error(`${label}; last state=${JSON.stringify(observed)}`);
  };
  let state;
  for(let attempt=0;attempt<120;attempt++){
    state=await inspect().catch(()=>null);
    if(state?.ready||await evaluate('document.body.dataset.error||null'))break;
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  const pageError=await evaluate('document.body.dataset.error||null');
  assert.equal(pageError,null,`viewer error: ${pageError}`);assert.equal(state?.ready,true,'viewer did not become ready');
  assert.equal(state.parts.length,16);assert.equal(state.profileId,'xbox_one_s_batonyrobson_appearance_matched_estimated_v0');
  assert.equal(state.activeVariantId,state.profileId);assert.deepEqual(runtimeFailures,[]);assert.deepEqual(resourceFailures,[]);
  const actualNavigationUrl=await evaluate('location.href');
  const sourceBinding=await buildVerifiedSourceBinding({call,responses:criticalResponses,specifications:V0_SOURCE_RESOURCES,navigation,actualNavigationUrl,cache,externalAssetScope:'The GPU-resident inventory and GLB are hashed in-page and matched to the Git-tracked registry/profile; they are not claimed as Git workspace bytes.'});
  assert.ok(Object.values(state.verifiedBindings).every(binding=>binding.actual_sha256===binding.expected_sha256),'runtime asset binding mismatch');
  assert.equal(state.materialStats.mesh_count,16);assert.ok(state.materialStats.material_slot_count>=16);assert.ok(state.materialStats.unique_texture_count>0,'embedded material textures were not instantiated');
  const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  for(const part of state.parts){part.restMatrix.forEach((value,index)=>assert.ok(Math.abs(value-identity[index])<1e-10,`${part.name}: static GLB rest transform is not identity`));part.matrix.forEach((value,index)=>assert.ok(Math.abs(value-part.restMatrix[index])<1e-10,`${part.name}: neutral runtime pose differs from rest`));}
  const baselineCenters=Object.fromEntries(state.parts.map(part=>[part.name,part.worldCenter]));
  const baseline=await call('Page.captureScreenshot',{format:'png'});await writeFile(join(output,'estimated_v0_baseline.png'),Buffer.from(baseline.data,'base64'));

  const inject=async({axes=[0,0,0,0],buttons={}}={})=>evaluate(`(()=>{window.testPad={connected:true,mapping:'standard',index:0,id:'SYNTHETIC STANDARD PAD',timestamp:1,axes:${JSON.stringify(axes)},buttons:Array.from({length:17},(_,index)=>{const value=(${JSON.stringify(buttons)})[index]??0;return {value,pressed:value>.5,touched:value>0};})};Object.defineProperty(navigator,'getGamepads',{configurable:true,value:()=>[window.testPad]});const mode=document.getElementById('mode');mode.value='device';mode.dispatchEvent(new Event('change'));})()`);
  const profileDocument=JSON.parse(await readFile(new URL('../assets/appearance_matched_estimated_v0/viewer_profile.json',import.meta.url),'utf8'));

  // Independently construct the expected matrix for every standard tensor
  // channel from the profile. This catches no-op, sign, node, and channel-swap
  // defects that a concurrent "some nodes moved" smoke test cannot detect.
  const matMul=(left,right)=>{const out=new Array(16).fill(0);for(let column=0;column<4;column++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)out[column*4+row]+=left[k*4+row]*right[column*4+k];return out;};
  const translation=([x,y,z])=>[1,0,0,0,0,1,0,0,0,0,1,0,x,y,z,1];
  const rotation=(axis,angle)=>{const [x,y,z]=axis,c=Math.cos(angle),s=Math.sin(angle),t=1-c;return [t*x*x+c,t*x*y+s*z,t*x*z-s*y,0,t*x*y-s*z,t*y*y+c,t*y*z+s*x,0,t*x*z+s*y,t*y*z-s*x,t*z*z+c,0,0,0,0,1];};
  const sourceToGltf=([x,y,z])=>[x,z,-y];
  function expectedSingleChannelMatrix(joint,value,restMatrix){
    const driver=joint.driver,[lower,upper]=joint.limits;let q;
    if(driver.kind==='linear_channel'){const [s0,s1]=driver.signal_range;q=lower+Math.max(0,Math.min(1,(value-s0)/(s1-s0)))*(upper-lower);}
    else if(driver.kind==='difference_channels')q=(driver.negative_channel===value.channel?value.signal*lower:value.signal*upper);
    else throw new Error(`${joint.id}: physical event is not a tensor channel`);
    const axis=sourceToGltf(joint.axis_source),pivot=sourceToGltf(joint.pivot_source_m.map(component=>component/profileDocument.visual.meters_per_native_unit)),motion=joint.type==='prismatic'?translation(axis.map(component=>component*q/profileDocument.visual.meters_per_native_unit)):matMul(matMul(translation(pivot),rotation(axis,q)),translation(pivot.map(component=>-component)));
    return {q,matrix:matMul(motion,restMatrix)};
  }
  const channelMatrixChecks=[];
  for(let channel=0;channel<21;channel++){
    const signal=channel<4?.35:.65,axes=[0,0,0,0],buttons={};if(channel<4)axes[channel]=signal;else buttons[channel-4]=signal;
    await inject({axes,buttons});const observed=await waitForInspect(candidate=>Math.abs(candidate.values[channel]-signal)<1e-6,`standard channel ${channel} did not reach its requested value`),joints=profileDocument.joints.filter(joint=>joint.driver.kind==='linear_channel'?joint.driver.channel===channel:[joint.driver.negative_channel,joint.driver.positive_channel].includes(channel));
    assert.equal(joints.length,1,`standard channel ${channel} must drive exactly one joint`);const joint=joints[0],node=observed.parts.find(part=>part.name===joint.node),value=joint.driver.kind==='linear_channel'?observed.values[channel]:{channel,signal:observed.values[channel]},expected=expectedSingleChannelMatrix(joint,value,node.restMatrix),errors=node.matrix.map((entry,index)=>Math.abs(entry-expected.matrix[index])),maxError=Math.max(...errors),scale=Math.max(1,...expected.matrix.map(Math.abs)),tolerance=512*Number.EPSILON*scale,matrixDisplacement=Math.hypot(...node.matrix.map((entry,index)=>entry-node.restMatrix[index]));
    assert.ok(maxError<=tolerance,`standard channel ${channel} matrix differs from independent profile construction (${maxError} > ${tolerance})`);assert.ok(matrixDisplacement>tolerance,`standard channel ${channel} produced an identity/no-op node matrix`);channelMatrixChecks.push({channel,name:profileDocument.channels[channel].name,signal:observed.values[channel],joint:joint.id,node:joint.node,coordinate:expected.q,max_abs_matrix_error:maxError,tolerance,matrix_displacement_from_rest:matrixDisplacement,expected_matrix:expected.matrix,actual_matrix:[...node.matrix],rest_matrix:[...node.restMatrix]});
  }

  const findVisiblePick=nodeName=>evaluate(`import('/v0_app.mjs').then(module=>module.findVisiblePick(${JSON.stringify(nodeName)}))`);
  const projectInteractionPoint=(nodeName,localPoint,targetState)=>evaluate(`import('/v0_app.mjs').then(module=>module.projectInteractionPoint(${JSON.stringify(nodeName)},${JSON.stringify(localPoint)},${JSON.stringify(targetState)}))`);
  const setInspectionCamera=settings=>evaluate(`import('/v0_app.mjs').then(module=>module.setInspectionCamera(${JSON.stringify(settings)}))`);
  const resetInspectionCamera=()=>evaluate("import('/v0_app.mjs').then(module=>module.resetInspectionCamera())");
  const mouseInteractionChecks=[];
  const neutral=()=>new Array(21).fill(0);
  async function configureMouse(channel,drag2d){
    await evaluate(`(()=>{window.testPad=null;const mode=document.getElementById('mode');mode.value='mouse';mode.dispatchEvent(new Event('change'));document.getElementById('channel').value=${JSON.stringify(String(channel))};document.getElementById('drag2d').checked=${drag2d?'true':'false'};})()`);
    return waitForInspect(observed=>observed.mode==='mouse'&&observed.deviceKey==='',`mouse mode/device-list did not stabilize for channel ${channel}`);
  }
  async function exerciseMouse({label,node,motionType,channel,targetState,activeChannels,drag2d=false,cameraView=null,assertMoved}){
    await configureMouse(channel,drag2d);const appliedCamera=cameraView?await setInspectionCamera(cameraView):null,pick=await findVisiblePick(node),neutralProjection=await projectInteractionPoint(node,pick.local_point,neutral()),targetScreen=await projectInteractionPoint(node,pick.local_point,targetState),neutralError=Math.hypot(neutralProjection[0]-pick.screen[0],neutralProjection[1]-pick.screen[1]),screenDisplacement=Math.hypot(targetScreen[0]-pick.screen[0],targetScreen[1]-pick.screen[1]);
    assert.ok(neutralError<1e-5,`${label}: visible pick does not reproject to the same neutral pixel (${neutralError})`);assert.ok(screenDisplacement>1e-3,`${label}: requested motion has no measurable screen displacement`);
    await call('Input.dispatchMouseEvent',{type:'mousePressed',x:pick.screen[0],y:pick.screen[1],button:'left',buttons:1,clickCount:1});let down=await inspect();
    assert.equal(down.selected,node,`${label}: pointerdown selected a different node`);assert.equal(down.pointerDiagnostics.down.selected_node,node,`${label}: pointerdown diagnostic selected a different node`);assert.equal(down.dragging,true,`${label}: pointerdown did not start a drag`);assert.equal(down.pointerDiagnostics.down.projection.degenerate,false,`${label}: screen projection is degenerate`);
    await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:targetScreen[0],y:targetScreen[1],button:'left',buttons:1});const moved=await waitForInspect(assertMoved,`${label}: CDP mouse move did not reach the expected signal`);assert.ok(moved.values.every(Number.isFinite),`${label}: produced non-finite channel values`);
    const screenshot=await call('Page.captureScreenshot',{format:'png'});await writeFile(join(output,`estimated_v0_mouse_${label}.png`),Buffer.from(screenshot.data,'base64'));
    const record={label,node,motion_type:motionType,channel,active_channels:activeChannels,camera_view:appliedCamera,pick,target_screen:targetScreen,requested_screen_displacement_px:[targetScreen[0]-pick.screen[0],targetScreen[1]-pick.screen[1]],requested_screen_span_px:screenDisplacement,pointer_down:moved.pointerDiagnostics.down,pointer_move:moved.pointerDiagnostics.last_move,observed_values:activeChannels.map(index=>({channel:index,value:moved.values[index]}))};mouseInteractionChecks.push(record);
    await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:targetScreen[0],y:targetScreen[1],button:'left',buttons:0,clickCount:1});const released=await waitForInspect(observed=>!observed.dragging&&activeChannels.every(index=>observed.values[index]===0),`${label}: release did not reset the exercised channels`);record.pointer_release=released.pointerDiagnostics.last_release;record.release_reset=activeChannels.every(index=>released.values[index]===0);
    return moved;
  }

  const aTarget=neutral();aTarget[4]=1;
  await exerciseMouse({label:'a_prismatic',node:'00_A_Button_VISUAL_UNCALIBRATED',motionType:'prismatic',channel:4,targetState:aTarget,activeChannels:[4],assertMoved:observed=>observed.values[4]>.5});

  const triggerTarget=neutral();triggerTarget[10]=.8;
  await exerciseMouse({label:'left_trigger_revolute',node:'11_Trigger_L_VISUAL_UNCALIBRATED',motionType:'revolute',channel:10,targetState:triggerTarget,activeChannels:[10],cameraView:{azimuth_deg:90,elevation_deg:35,distance_span:2.4},assertMoved:observed=>observed.values[10]>.5});
  await resetInspectionCamera();

  const stickTarget=neutral();stickTarget[0]=.45;stickTarget[1]=-.35;
  const stickMoved=await exerciseMouse({label:'left_stick_2d',node:'09_Stick_L_VISUAL_UNCALIBRATED',motionType:'stick_2d_inverse_projection',channel:0,targetState:stickTarget,activeChannels:[0,1],drag2d:true,assertMoved:observed=>observed.pointerDiagnostics.last_move?.solver?.reached===true&&observed.values[0]>0&&observed.values[1]<0});
  const stickRecord=mouseInteractionChecks.at(-1),minimumSingular=stickRecord.pointer_down.projection.singular_values_px_per_signal[1],stickSignalError=Math.hypot(stickMoved.values[0]-stickTarget[0],stickMoved.values[1]-stickTarget[1]),stickSignalTolerance=2*.1/minimumSingular;
  assert.ok(stickRecord.pointer_move.solver.error_px<=.1,'left stick solver exceeded its documented 0.1 px reach threshold');assert.ok(stickSignalError<=stickSignalTolerance,`left stick signal error ${stickSignalError} exceeds Jacobian-derived gate ${stickSignalTolerance}`);stickRecord.signal_error_norm=stickSignalError;stickRecord.signal_error_gate={formula:'2 * solveDrag2D reach threshold (0.1 px) / pointerdown minimum singular value (px/signal)',minimum_singular_px_per_signal:minimumSingular,tolerance:stickSignalTolerance};

  const dpadTarget=neutral();dpadTarget[19]=1;
  await exerciseMouse({label:'dpad_difference',node:'06_D-Pad_VISUAL_UNCALIBRATED',motionType:'difference_channel_revolute',channel:19,targetState:dpadTarget,activeChannels:[18,19],assertMoved:observed=>observed.values[19]>.5&&observed.values[18]===0});

  // Synthetic device path exercises concurrent controls and exact GLB nodes;
  // it is not reported as a real USB-controller test.
  await inject({axes:[.25,-.35,-.4,.2],buttons:{0:1,4:1,6:.5,7:.8,12:1,15:1}});await new Promise(resolve=>setTimeout(resolve,150));state=await inspect();
  assert.ok(state.values.filter(value=>Math.abs(value)>1e-6).length>=9);assert.ok(state.parts.every(part=>part.matrix.every(Number.isFinite)));
  const concurrentShot=await call('Page.captureScreenshot',{format:'png'});await writeFile(join(output,'estimated_v0_concurrent_input.png'),Buffer.from(concurrentShot.data,'base64'));
  const concurrentCenters=Object.fromEntries(state.parts.map(part=>[part.name,part.worldCenter]));
  const waitAnimationFrames=count=>{assert.ok(Number.isInteger(count)&&count>0);return evaluate(`new Promise(resolve=>{let remaining=${count};function next(){if(--remaining<=0)resolve();else requestAnimationFrame(next)}requestAnimationFrame(next)})`);};
  await waitAnimationFrames(30);const idleBefore=await inspect();await waitAnimationFrames(30);const idleAfter=await inspect(),idleRenderCheck={animation_ticks_observed:idleAfter.renderDiagnostics.animation_tick_count-idleBefore.renderDiagnostics.animation_tick_count,renders_observed:idleAfter.renderDiagnostics.render_count-idleBefore.renderDiagnostics.render_count,before:idleBefore.renderDiagnostics,after:idleAfter.renderDiagnostics};
  assert.ok(idleRenderCheck.animation_ticks_observed>=20,'idle render probe did not observe enough animation ticks');assert.equal(idleRenderCheck.renders_observed,0,'viewer continued issuing WebGL renders while scene and input were unchanged');state=idleAfter;
  assert.deepEqual(runtimeFailures,[]);assert.deepEqual(resourceFailures,[]);
  const browser=await call('Browser.getVersion'),threeRevision=await evaluate("import('three').then(module=>module.REVISION)");
  const centerDisplacements=Object.fromEntries(Object.keys(concurrentCenters).map(name=>[name,Math.hypot(...concurrentCenters[name].map((value,index)=>value-baselineCenters[name][index]))]));
  const result={schema_version:2,passed:true,profile_id:state.profileId,variant_id:state.activeVariantId,visual_parts:state.parts.length,runtime:{browser,three_revision:threeRevision,viewer_url:viewerUrl,requested_navigation_url:navigation.url,navigation_url:actualNavigationUrl,cdp_url:cdpUrl,cdp_target_owned_by_harness:true},source_binding:sourceBinding,critical_resource_validation:true,external_asset_bindings:state.verifiedBindings,real_glb_loaded:true,material_stats:state.materialStats,embedded_material_path:state.materialStats.unique_texture_count>0,neutral_nodes_match_identity_rest:true,synthetic_standard_gamepad_to_mesh:channelMatrixChecks.length===21&&channelMatrixChecks.every(check=>check.max_abs_matrix_error<=check.tolerance&&check.matrix_displacement_from_rest>check.tolerance),synthetic_standard_gamepad_all_21_channel_matrix_checks:channelMatrixChecks,real_cdp_mouse_to_signal:true,real_cdp_mouse_left_stick_to_lx_ly:true,mouse_release_reset:mouseInteractionChecks.length===4&&mouseInteractionChecks.every(check=>check.release_reset),real_cdp_mouse_tested_controls:['a','left_trigger','left_stick','dpad'],real_cdp_mouse_tested_motion_types:['prismatic','revolute','stick_2d','difference_channels'],real_cdp_mouse_interactions:mouseInteractionChecks,visible_surface_pick_verified:mouseInteractionChecks.every(check=>check.pick.first_hit.node===check.node&&check.pick.clearance_px>0),pointerdown_selection_verified:mouseInteractionChecks.every(check=>check.pointer_down.selected_node===check.node),screen_projection_diagnostics_recorded:mouseInteractionChecks.every(check=>check.pointer_down.projection?.degenerate===false),idle_render_quiescent:idleRenderCheck.renders_observed===0,idle_render_check:idleRenderCheck,concurrent_input_probe:true,concurrent_center_displacements_m:centerDisplacements,real_controller_tested:false,physical_acceptance:false,runtime_failures:runtimeFailures,resource_failures:resourceFailures};
  await writeFile(join(output,'browser_v0_harness.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({...result,output}));
}catch(error){harnessFailed=true;throw error;}finally{
  if(evaluate)await evaluate("delete navigator.getGamepads;delete window.testPad").catch(()=>{});client?.close();if(page?.id)try{await closeCdpTarget(cdpUrl,page.id);}catch(error){if(!harnessFailed)throw error;console.error(`CDP target cleanup also failed: ${error.message}`);}
}
