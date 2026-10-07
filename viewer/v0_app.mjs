import * as T from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {InputSession,AXES,BUTTONS,neutralState} from './gamepad_state.mjs';
import {solveDrag2D} from './drag2d.mjs';
import {configuredChannels,evaluateProfile,nodeSteps,validateProfile} from './schema2_runtime.mjs';

const el=id=>document.getElementById(id),displayNames=[...AXES,...BUTTONS];
const scene=new T.Scene();scene.background=new T.Color('#101820');
const camera=new T.PerspectiveCamera(40,1,.001,10);camera.up.set(0,0,1);
const renderer=new T.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1;
el('scene').append(renderer.domElement);
// Explicit r180 MeshStandardMaterial/MeshPhysicalMaterial texture slots.  Do
// not infer texture use from generic object enumeration: the acceptance check
// is about documented material inputs, not incidental property enumerability.
const textureSlots=['map','lightMap','aoMap','emissiveMap','bumpMap','normalMap','displacementMap','roughnessMap','metalnessMap','alphaMap','envMap','anisotropyMap','clearcoatMap','clearcoatRoughnessMap','clearcoatNormalMap','iridescenceMap','iridescenceThicknessMap','sheenColorMap','sheenRoughnessMap','transmissionMap','thicknessMap','specularIntensityMap','specularColorMap'];
const environment=new RoomEnvironment();const pmrem=new T.PMREMGenerator(renderer);scene.environment=pmrem.fromScene(environment).texture;environment.dispose();pmrem.dispose();
scene.add(new T.HemisphereLight(0xffffff,0x556270,1.25));const key=new T.DirectionalLight(0xffffff,1.5);key.position.set(-.12,-.2,.3);scene.add(key);
const orbit=new OrbitControls(camera,renderer.domElement);orbit.enableDamping=true;
const session=new InputSession(),ray=new T.Raycaster(),parts=new Map(),restMatrices=new Map();
let profile=null,evidence=null,model=null,activeVariantId=null,ready=false,drag=null,selected=null,lastEvaluation=null,pairValue=0;
let renderRequested=true,renderCount=0,animationTickCount=0,framePending=false,lastScheduleReason='startup';
let pointerDiagnostics={sequence:0,down:null,last_move:null,last_release:null,last_clear:null};
let verifiedBindings=null,materialStats=null;
const status=text=>{el('status').textContent=text;};
function devicePollingActive(){return session.mode==='device'&&!document.hidden&&document.hasFocus();}
function scheduleFrame(reason='event'){
  lastScheduleReason=reason;if(framePending)return;framePending=true;requestAnimationFrame(animate);
}
function requestRender(reason='render_request'){renderRequested=true;scheduleFrame(reason);}
displayNames.forEach((name,index)=>el('channel').add(new Option(name,String(index))));

async function digest(bytes){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(value=>value.toString(16).padStart(2,'0')).join('');}
function resetCamera(){
  if(!model){camera.position.set(0,-.27,.13);orbit.target.set(0,0,0);orbit.update();requestRender();return;}
  model.updateMatrixWorld(true);const box=new T.Box3().setFromObject(model),center=box.getCenter(new T.Vector3()),size=box.getSize(new T.Vector3()),span=Math.max(size.x,size.y,size.z);
  orbit.target.copy(center);camera.position.set(center.x,center.y-span*1.35,center.z+span*1.95);camera.near=Math.max(.0001,span/1000);camera.far=Math.max(10,span*20);camera.updateProjectionMatrix();orbit.update();requestRender();
}
resetCamera();el('camera').onclick=resetCamera;
function clear(reason){
  const pointer=drag?.pointer;pointerDiagnostics.last_clear={reason,while_dragging:drag!==null,pointer:pointer??null,at_ms:performance.now()};drag=null;orbit.enabled=true;session.clear(reason);pairValue=0;
  if(pointer!==undefined&&renderer.domElement.hasPointerCapture(pointer))renderer.domElement.releasePointerCapture(pointer);
  applyPose();
}
el('reset').onclick=()=>clear('reset');
el('mode').onchange=()=>{clear('mode_change');session.setMode(el('mode').value);scheduleFrame('mode_change');};
el('device').onchange=()=>clear('device_change');
addEventListener('blur',()=>clear('focus_loss'));
addEventListener('focus',()=>scheduleFrame('focus_recovery'));
for(const type of ['gamepadconnected','gamepaddisconnected'])addEventListener(type,()=>scheduleFrame(type));
document.addEventListener('visibilitychange',()=>{if(document.hidden)clear('hidden');else scheduleFrame('visibility_recovery');});
addEventListener('resize',()=>requestRender('window_resize'));
new ResizeObserver(()=>requestRender('scene_resize')).observe(el('scene'));
orbit.addEventListener('change',()=>requestRender('orbit_change'));

function jointChannels(joint){
  const driver=joint.driver;
  return driver.kind==='linear_channel'?[driver.channel]:driver.kind==='difference_channels'?[driver.negative_channel,driver.positive_channel]:[];
}
function poseMatrix(nodeName,state=session.frame.values){
  const evaluation=evaluateProfile(profile,state,{pair_bind_connect:pairValue}),steps=nodeSteps(profile,nodeName,evaluation),rest=restMatrices.get(nodeName)??new T.Matrix4();
  if(!steps.length)return {matrix:rest.clone(),evaluation};
  const pivot=new T.Vector3(...steps[0].pivot),matrix=new T.Matrix4().makeTranslation(...pivot.toArray());
  for(const step of steps){
    const p=new T.Vector3(...step.pivot);if(p.distanceTo(pivot)>1e-7)throw Error(`同一可见节点的关节 pivot 不一致：${nodeName}`);
    const axis=new T.Vector3(...step.axis);
    matrix.multiply(step.type==='revolute'?new T.Matrix4().makeRotationAxis(axis,step.q):new T.Matrix4().makeTranslation(...axis.multiplyScalar(step.q).toArray()));
  }
  matrix.multiply(new T.Matrix4().makeTranslation(...pivot.clone().negate().toArray())).multiply(rest);
  return {matrix,evaluation};
}
function applyPose(){
  if(!ready)return;
  lastEvaluation=evaluateProfile(profile,session.frame.values,{pair_bind_connect:pairValue});
  for(const [name,node] of parts)node.matrix.copy(poseMatrix(name,session.frame.values).matrix);
  scene.updateMatrixWorld(true);requestRender();
}
function screenRay(clientX,clientY){const rect=renderer.domElement.getBoundingClientRect();ray.setFromCamera(new T.Vector2((clientX-rect.left)/rect.width*2-1,1-(clientY-rect.top)/rect.height*2),camera);}
function pointerRay(event){screenRay(event.clientX,event.clientY);}
function projectPickedPoint(nodeName,local,state){
  const node=parts.get(nodeName),world=node.parent.matrixWorld.clone().multiply(poseMatrix(nodeName,state).matrix),point=local.clone().applyMatrix4(world).project(camera),rect=renderer.domElement.getBoundingClientRect();
  return [rect.left+(point.x+1)*rect.width/2,rect.top+(1-point.y)*rect.height/2];
}
function hitRecordsAt(clientX,clientY){
  screenRay(clientX,clientY);return ray.intersectObjects([...parts.values()],true).map(hit=>({
    node:hit.object.userData.profileNode??null,object:hit.object.name||null,distance:hit.distance,
    point_world:hit.point.toArray(),
  }));
}
function oneAxisProjection(nodeName,local,base,channel){
  const [low,high]=profile.channels[channel].range,lowState=Float32Array.from(base),highState=Float32Array.from(base);lowState[channel]=low;highState[channel]=high;
  const lowScreen=projectPickedPoint(nodeName,local,lowState),highScreen=projectPickedPoint(nodeName,local,highState),dx=highScreen[0]-lowScreen[0],dy=highScreen[1]-lowScreen[1],denominator=dx*dx+dy*dy;
  return {channel,range:[low,high],low_screen:lowScreen,high_screen:highScreen,screen_displacement_px:[dx,dy],screen_span_px:Math.sqrt(denominator),denominator,degenerate:denominator<1e-5};
}
function twoAxisProjection(nodeName,local,base,channels){
  const columns=channels.map(channel=>{const [low,high]=profile.channels[channel].range,lowState=Float32Array.from(base),highState=Float32Array.from(base);lowState[channel]=low;highState[channel]=high;const a=projectPickedPoint(nodeName,local,lowState),b=projectPickedPoint(nodeName,local,highState),scale=high-low;return {channel,range:[low,high],low_screen:a,high_screen:b,screen_derivative_px_per_signal:[(b[0]-a[0])/scale,(b[1]-a[1])/scale]};});
  const [[a,c],[b,d]]=columns.map(column=>column.screen_derivative_px_per_signal),determinant=a*d-b*c,frobeniusSquared=a*a+b*b+c*c+d*d,discriminant=Math.max(0,frobeniusSquared*frobeniusSquared-4*determinant*determinant),largest=Math.sqrt(Math.max(0,(frobeniusSquared+Math.sqrt(discriminant))/2)),smallest=Math.sqrt(Math.max(0,(frobeniusSquared-Math.sqrt(discriminant))/2));
  return {channels,columns,determinant_px2_per_signal2:determinant,singular_values_px_per_signal:[largest,smallest],condition_number:smallest>0?largest/smallest:null,degenerate:!Number.isFinite(determinant)||Math.abs(determinant)<1e-8};
}
function screenBoundsForNode(nodeName){
  const rect=renderer.domElement.getBoundingClientRect(),box=new T.Box3().setFromObject(parts.get(nodeName)),corners=[];
  for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){const point=new T.Vector3(x,y,z).project(camera);corners.push([rect.left+(point.x+1)*rect.width/2,rect.top+(1-point.y)*rect.height/2]);}
  return {left:Math.max(rect.left,Math.min(...corners.map(point=>point[0]))),right:Math.min(rect.right,Math.max(...corners.map(point=>point[0]))),top:Math.max(rect.top,Math.min(...corners.map(point=>point[1]))),bottom:Math.min(rect.bottom,Math.max(...corners.map(point=>point[1])))};
}
function updateMouseState(state){session.updateFromPartPose(state,performance.now(),configuredChannels(profile));applyPose();}

renderer.domElement.addEventListener('pointerdown',event=>{
  if(!ready||event.button!==0)return;pointerRay(event);const hits=ray.intersectObjects([...parts.values()],true),hit=hits[0];if(!hit)return;
  selected=hit.object.userData.profileNode;const nodeRecord=profile.nodes.find(node=>node.source_node===selected),candidates=profile.joints.filter(joint=>joint.node===selected),selectedChannel=Number(el('channel').value);
  let joint=candidates.find(candidate=>jointChannels(candidate).includes(selectedChannel))??candidates.find(candidate=>jointChannels(candidate).length);
  el('selection').textContent=JSON.stringify({node:nodeRecord,selected_joint:joint??null,parameter:joint?evidence.parameters[joint.parameter_ref]:null,warning:'运动仅为 estimated-v0；不是目标手柄的实测机械参数'},null,2);
  pointerDiagnostics.sequence+=1;pointerDiagnostics.down={sequence:pointerDiagnostics.sequence,screen:[event.clientX,event.clientY],hit_count:hits.length,hits:hits.slice(0,8).map(item=>({node:item.object.userData.profileNode??null,object:item.object.name||null,distance:item.distance})),selected_node:selected,selected_joint:joint?.id??null,requested_channel:selectedChannel,mode:session.mode,at_ms:performance.now(),projection:null};
  if(session.mode!=='mouse'||!joint)return;
  const local=parts.get(selected).worldToLocal(hit.point.clone()),control=nodeRecord.control;
  if(el('drag2d').checked&&['left_stick','right_stick'].includes(control)){
    const channels=control==='left_stick'?[0,1]:[2,3];
    drag={kind:'two',channels,local,node:selected,pointer:event.pointerId};
    pointerDiagnostics.down.projection=twoAxisProjection(selected,local,session.frame.values,channels);
  }else{
    const channels=jointChannels(joint);if(!channels.length)return;
    const channel=channels.includes(selectedChannel)?selectedChannel:channels[0];
    el('channel').value=String(channel);drag={kind:'one',channel,local,node:selected,base:Float32Array.from(session.frame.values),pointer:event.pointerId};
    pointerDiagnostics.down.projection=oneAxisProjection(selected,local,drag.base,channel);
  }
  pointerDiagnostics.down.local_point=local.toArray();pointerDiagnostics.down.drag_kind=drag.kind;pointerDiagnostics.down.effective_channels=drag.kind==='two'?[...drag.channels]:[drag.channel];
  orbit.enabled=false;renderer.domElement.setPointerCapture(event.pointerId);
},true);

renderer.domElement.addEventListener('pointermove',event=>{
  if(!drag||event.pointerId!==drag.pointer)return;
  if(drag.kind==='two'){
    const state=Float32Array.from(session.frame.values),project=values=>{const trial=Float32Array.from(state);drag.channels.forEach((channel,index)=>trial[channel]=values[index]);return projectPickedPoint(drag.node,drag.local,trial);};
    const result=solveDrag2D(project,drag.channels.map(channel=>state[channel]),[event.clientX,event.clientY]);drag.channels.forEach((channel,index)=>state[channel]=result.values[index]);updateMouseState(state);
    pointerDiagnostics.last_move={sequence:pointerDiagnostics.sequence,screen:[event.clientX,event.clientY],kind:'two',channels:[...drag.channels],solver:{values:[...result.values],error_px:result.errorPx,reached:result.reached},at_ms:performance.now()};
    status(`二维拖动投影误差 ${result.errorPx.toFixed(2)} px；${lastEvaluation.projections.length?'当前状态已投影到运动边界':'未触发边界投影'}`);return;
  }
  const channel=drag.channel,[low,high]=profile.channels[channel].range,projection=oneAxisProjection(drag.node,drag.local,drag.base,channel),a=projection.low_screen,[dx,dy]=projection.screen_displacement_px,denominator=projection.denominator;
  if(denominator<1e-5){status('当前视角下该运动在屏幕上的投影退化，请旋转视角。');return;}
  const t=Math.max(0,Math.min(1,((event.clientX-a[0])*dx+(event.clientY-a[1])*dy)/denominator)),state=Float32Array.from(drag.base);state[channel]=low+t*(high-low);updateMouseState(state);
  pointerDiagnostics.last_move={sequence:pointerDiagnostics.sequence,screen:[event.clientX,event.clientY],kind:'one',channel,t,projection,at_ms:performance.now()};
});
function release(event){if(!drag||event.pointerId!==drag.pointer)return;const channels=drag.kind==='two'?drag.channels:[drag.channel];pointerDiagnostics.last_release={sequence:pointerDiagnostics.sequence,screen:[event.clientX,event.clientY],channels:[...channels],held:el('hold').checked,at_ms:performance.now()};drag=null;orbit.enabled=true;if(!el('hold').checked){const state=Float32Array.from(session.frame.values);channels.forEach(channel=>state[channel]=0);updateMouseState(state);}}
renderer.domElement.addEventListener('pointerup',release);renderer.domElement.addEventListener('pointercancel',()=>clear('pointer_cancel'));renderer.domElement.addEventListener('lostpointercapture',()=>{if(drag)clear('capture_lost');});

for(const type of ['pointerdown','pointerup','pointercancel','pointerleave'])el('pair').addEventListener(type,event=>{
  if(session.mode!=='mouse')return;pairValue=type==='pointerdown'?1:0;if(type==='pointerdown')event.currentTarget.setPointerCapture(event.pointerId);applyPose();
});

function formatValues(){
  if(!profile||!lastEvaluation)return '';
  const raw=session.frame.values,represented=lastEvaluation.represented,rows=displayNames.map((name,index)=>`${name.padEnd(7)} ${raw[index].toFixed(3).padStart(7)} ${represented[index].toFixed(3).padStart(7)}`);
  const projected=lastEvaluation.projections.length?`\n边界投影：${lastEvaluation.projections.map(item=>item.constraint).join(', ')}`:'\n边界投影：无';
  return `${session.mode} | valid=${session.frame.valid} | ${session.frame.reason??''}\n通道       原始输入  实际表示\n${rows.join('\n')}${projected}\nPair事件：${lastEvaluation.representedEvents.pair_bind_connect.toFixed(3)}`;
}
function updateReadouts(){
  const valuesText=formatValues(),rawText=JSON.stringify(session.frame.raw??null,null,2);if(el('values').textContent!==valuesText)el('values').textContent=valuesText;if(el('raw').textContent!==rawText)el('raw').textContent=rawText;
}

async function load(){
  const [registryResponse,inventoryResponse]=await Promise.all([fetch('/registry/asset_index.json'),fetch('/assets/inventory.json')]);
  if(!registryResponse.ok||!inventoryResponse.ok)throw Error('资产注册表或外部清单不可用');
  const registry=await registryResponse.json(),inventoryBytes=await inventoryResponse.arrayBuffer(),inventoryHash=await digest(inventoryBytes),allowed=new Set([registry.interactive_viewer?.active_variant_id,...(registry.interactive_viewer?.allowed_variant_ids??[])]);
  const matches=Object.entries(registry.derived_variants??{}).filter(([id,variant])=>allowed.has(id)&&variant.inventory_sha256===inventoryHash);
  if(matches.length!==1)throw Error(`外部清单必须唯一匹配一个允许的 viewer variant；当前匹配 ${matches.length} 个`);
  [activeVariantId]=matches[0];const variant=matches[0][1],binding=variant.viewer_profile;if(!binding)throw Error('当前 variant 没有 schema-2 viewer profile');
  const profileResponse=await fetch('/registry/'+binding.path);if(!profileResponse.ok)throw Error(`viewer profile HTTP ${profileResponse.status}`);const profileBytes=await profileResponse.arrayBuffer(),profileHash=await digest(profileBytes);if(profileHash!==binding.sha256)throw Error('viewer profile 哈希不匹配');
  profile=JSON.parse(new TextDecoder().decode(profileBytes));
  const evidenceRelative=profile.parameter_source;if(!evidenceRelative.startsWith('sources/'))throw Error('参数证据路径不安全');const evidenceResponse=await fetch('/evidence/'+evidenceRelative.slice('sources/'.length));if(!evidenceResponse.ok)throw Error(`参数证据 HTTP ${evidenceResponse.status}`);const evidenceBytes=await evidenceResponse.arrayBuffer(),evidenceHash=await digest(evidenceBytes);if(evidenceHash!==profile.parameter_source_sha256)throw Error('参数证据哈希不匹配');evidence=JSON.parse(new TextDecoder().decode(evidenceBytes));
  if(profile.source_bindings.static_inventory_sha256!==inventoryHash)throw Error('profile 与外部清单绑定不一致');
  const glbResponse=await fetch('/assets/'+encodeURIComponent(profile.visual.file));if(!glbResponse.ok)throw Error(`GLB HTTP ${glbResponse.status}`);const glbBytes=await glbResponse.arrayBuffer(),glbHash=await digest(glbBytes);if(glbHash!==profile.visual.sha256)throw Error('GLB 哈希不匹配');
  const gltf=await new Promise((resolve,reject)=>new GLTFLoader().parse(glbBytes,'/assets/',resolve,reject));model=gltf.scene;model.rotation.x=profile.visual.gltf_to_viewer_rotation_x_rad;model.scale.setScalar(profile.visual.meters_per_native_unit);scene.add(model);model.updateMatrixWorld(true);
  for(const record of profile.nodes){
    const node=model.getObjectByName(record.source_node);if(!node)throw Error(`GLB 缺少节点：${record.source_node}`);node.updateMatrix();restMatrices.set(record.source_node,node.matrix.clone());node.matrixAutoUpdate=false;
    node.traverse(object=>{if(object.isMesh)object.userData.profileNode=record.source_node;});parts.set(record.source_node,node);
  }
  const materialNames=new Set(),textures=new Set(),usedTextureSlots=new Set();let meshCount=0,materialSlotCount=0;
  model.traverse(object=>{if(!object.isMesh)return;meshCount++;for(const material of Array.isArray(object.material)?object.material:[object.material]){if(!material)continue;materialSlotCount++;materialNames.add(material.name);for(const slot of textureSlots){const texture=material[slot];if(texture?.isTexture){textures.add(texture.uuid);usedTextureSlots.add(slot);}}}});
  materialStats={mesh_count:meshCount,material_slot_count:materialSlotCount,unique_material_names:[...materialNames].sort(),used_texture_slots:[...usedTextureSlots].sort(),unique_texture_count:textures.size};
  verifiedBindings={
    inventory:{url:'/assets/inventory.json',actual_sha256:inventoryHash,expected_sha256:variant.inventory_sha256},
    profile:{url:'/registry/'+binding.path,actual_sha256:profileHash,expected_sha256:binding.sha256},
    evidence:{url:'/evidence/'+evidenceRelative.slice('sources/'.length),actual_sha256:evidenceHash,expected_sha256:profile.parameter_source_sha256},
    visual:{url:'/assets/'+profile.visual.file,actual_sha256:glbHash,expected_sha256:profile.visual.sha256},
  };
  validateProfile(profile,evidence,new Set(parts.keys()));ready=true;session.updateFromPartPose(neutralState(),performance.now(),configuredChannels(profile));applyPose();resetCamera();
  el('limits').textContent=JSON.stringify({acceptance:profile.acceptance,unknown_physical_parameters:evidence.unknown_physical_parameters,scale_fit:evidence.scale_fit},null,2);
  status(`已核验 16 部件材质 GLB、schema-2 estimated-v0 配置和参数证据；variant=${activeVariantId}`);document.body.dataset.ready='true';document.body.dataset.variantId=activeVariantId;
}

function valuesChanged(before,after){return before.length!==after.length||before.some((value,index)=>value!==after[index]);}
let deviceKey='';function animate(){
  framePending=false;animationTickCount++;const beforeValues=Array.from(session.frame.values),pads=Array.from(navigator.getGamepads?.()??[]).filter(pad=>pad?.connected),keyValue=pads.map(pad=>`${pad.index}:${pad.id}`).join('|');
  if(keyValue!==deviceKey){const previous=el('device').value;el('device').replaceChildren();pads.forEach(pad=>el('device').add(new Option(`${pad.index}: ${pad.id}`,String(pad.index))));if(pads.some(pad=>String(pad.index)===previous))el('device').value=previous;deviceKey=keyValue;if(session.mode==='device')clear('device_list_change');}
  if(session.mode==='device'&&!document.hidden&&document.hasFocus()){try{session.updateDevice(pads.find(pad=>String(pad.index)===el('device').value)??null,performance.now());}catch(error){clear(error.message);}}
  if(valuesChanged(beforeValues,session.frame.values))applyPose();updateReadouts();
  const width=el('scene').clientWidth,height=el('scene').clientHeight,resized=renderer.domElement.width!==Math.round(width*renderer.getPixelRatio())||renderer.domElement.height!==Math.round(height*renderer.getPixelRatio());if(resized){renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();requestRender();}
  const orbitChanged=orbit.update();if(renderRequested||orbitChanged){renderer.render(scene,camera);renderCount++;renderRequested=false;}
  if(orbitChanged)scheduleFrame('orbit_damping');
  if(devicePollingActive())scheduleFrame('device_poll');
}
load().catch(error=>{status(error.message);document.body.dataset.error=error.message;});scheduleFrame('startup');

export function inspect(){
  const rect=renderer.domElement.getBoundingClientRect(),view=camera.position.clone().sub(orbit.target),horizontal=Math.hypot(view.x,view.y);
  return {ready,activeVariantId,profileId:profile?.profile_id??null,mode:session.mode,frame:{valid:session.frame.valid,reason:session.frame.reason??null,source:session.frame.source??null},deviceKey,values:Array.from(session.frame.values),represented:Array.from(lastEvaluation?.represented??neutralState()),projections:lastEvaluation?.projections??[],pair:lastEvaluation?.representedEvents?.pair_bind_connect??0,selected,dragging:drag!==null,pointerDiagnostics:structuredClone(pointerDiagnostics),renderDiagnostics:{animation_tick_count:animationTickCount,render_count:renderCount,render_requested:renderRequested,frame_pending:framePending,last_schedule_reason:lastScheduleReason,loop_policy:{mouse:'event_driven',device:'continuous_while_visible_and_focused',active:devicePollingActive()?'device_poll':'event_driven',document_hidden:document.hidden,document_has_focus:document.hasFocus()}},verifiedBindings,materialStats,camera:{position:camera.position.toArray(),target:orbit.target.toArray(),elevation_deg:T.MathUtils.radToDeg(Math.atan2(view.z,horizontal))},parts:[...parts].map(([name,node])=>{const box=new T.Box3().setFromObject(node),worldCenter=box.getCenter(new T.Vector3()),point=worldCenter.clone().project(camera);return {name,screen:[rect.left+(point.x+1)*rect.width/2,rect.top+(1-point.y)*rect.height/2],matrix:node.matrix.toArray(),restMatrix:restMatrices.get(name).toArray(),worldCenter:worldCenter.toArray(),worldBounds:[box.min.toArray(),box.max.toArray()]};})};
}

// Deterministically find an interior pixel whose nearest ray hit belongs to
// the requested visible node. Tests still dispatch real CDP mouse events at
// the returned pixel; this helper does not select or move a part.
export function findVisiblePick(nodeName,gridSize=31){
  if(!ready||!parts.has(nodeName))throw Error(`unknown or unavailable node: ${nodeName}`);if(!Number.isInteger(gridSize)||gridSize<5||gridSize>61)throw Error('gridSize must be an integer in [5, 61]');
  scene.updateMatrixWorld(true);const bounds=screenBoundsForNode(nodeName);if(!(bounds.right>bounds.left&&bounds.bottom>bounds.top))throw Error(`node has no on-canvas screen bounds: ${nodeName}`);
  const successes=[],failures=[];
  for(let row=0;row<gridSize;row++)for(let column=0;column<gridSize;column++){
    const screen=[bounds.left+(column+.5)*(bounds.right-bounds.left)/gridSize,bounds.top+(row+.5)*(bounds.bottom-bounds.top)/gridSize],hits=hitRecordsAt(...screen),sample={screen,first_node:hits[0]?.node??null};
    (sample.first_node===nodeName?successes:failures).push(sample);
  }
  if(!successes.length)throw Error(`node has no verified visible-surface sample: ${nodeName}`);
  const edgeDistanceSquared=([x,y])=>Math.min((x-bounds.left)**2,(bounds.right-x)**2,(y-bounds.top)**2,(bounds.bottom-y)**2);
  for(const sample of successes){sample.clearance_squared=Math.min(edgeDistanceSquared(sample.screen),...failures.map(other=>(sample.screen[0]-other.screen[0])**2+(sample.screen[1]-other.screen[1])**2));}
  successes.sort((a,b)=>b.clearance_squared-a.clearance_squared||a.screen[1]-b.screen[1]||a.screen[0]-b.screen[0]);const chosen=successes[0],hits=hitRecordsAt(...chosen.screen),hit=hits[0],local=parts.get(nodeName).worldToLocal(new T.Vector3(...hit.point_world));
  return {node:nodeName,screen:chosen.screen,local_point:local.toArray(),first_hit:hit,screen_bounds:bounds,grid_size:gridSize,visible_samples:successes.length,total_samples:gridSize*gridSize,clearance_px:Math.sqrt(chosen.clearance_squared)};
}

export function projectInteractionPoint(nodeName,localPoint,state){
  if(!ready||!parts.has(nodeName))throw Error(`unknown or unavailable node: ${nodeName}`);if(!Array.isArray(localPoint)||localPoint.length!==3||localPoint.some(value=>!Number.isFinite(value)))throw Error('localPoint must contain three finite values');if(!Array.isArray(state)||state.length!==21||state.some(value=>!Number.isFinite(value)))throw Error('state must contain 21 finite values');
  return projectPickedPoint(nodeName,new T.Vector3(...localPoint),Float32Array.from(state));
}

// Deterministic camera placement for browser diagnostics. Angles and distance
// are review-view settings only; they are not controller geometry parameters.
export function setInspectionCamera({azimuth_deg,elevation_deg,distance_span=2.4}){
  if(!ready)throw Error('viewer is not ready');if(![azimuth_deg,elevation_deg,distance_span].every(Number.isFinite)||elevation_deg<=-89||elevation_deg>=89||distance_span<=0)throw Error('invalid inspection camera');
  model.updateMatrixWorld(true);const box=new T.Box3().setFromObject(model),center=box.getCenter(new T.Vector3()),size=box.getSize(new T.Vector3()),span=Math.max(size.x,size.y,size.z),azimuth=T.MathUtils.degToRad(azimuth_deg),elevation=T.MathUtils.degToRad(elevation_deg),distance=span*distance_span,horizontal=distance*Math.cos(elevation);
  orbit.target.copy(center);camera.position.set(center.x+horizontal*Math.cos(azimuth),center.y+horizontal*Math.sin(azimuth),center.z+distance*Math.sin(elevation));camera.near=Math.max(.0001,span/1000);camera.far=Math.max(10,span*20);camera.updateProjectionMatrix();orbit.update();camera.updateMatrixWorld(true);scene.updateMatrixWorld(true);requestRender();
  return {azimuth_deg,elevation_deg,distance_span,position:camera.position.toArray(),target:orbit.target.toArray()};
}

export function resetInspectionCamera(){resetCamera();camera.updateMatrixWorld(true);scene.updateMatrixWorld(true);return inspect().camera;}
