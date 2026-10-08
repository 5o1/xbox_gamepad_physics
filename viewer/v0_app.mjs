import * as T from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {CyclesView} from './cycles_view.mjs';
import {InputSession,AXES,BUTTONS,neutralState} from './gamepad_state.mjs';
import {solveDrag2D,projectUnitDisk} from './drag2d.mjs';
import {configuredChannels,evaluateProfile,nodeSteps,validateProfile} from './schema2_runtime.mjs';

const el=id=>document.getElementById(id),displayNames=[...AXES,...BUTTONS];
const scene=new T.Scene();scene.background=new T.Color('#101820');
const camera=new T.PerspectiveCamera(40,1,.001,10);camera.up.set(0,0,1);
const renderer=new CyclesView(el('scene'));
let approvedRender=null;
const orbit=new OrbitControls(camera,renderer.domElement);orbit.enableDamping=true;
const session=new InputSession(),ray=new T.Raycaster(),parts=new Map(),restMatrices=new Map();
let profile=null,evidence=null,model=null,activeVariantId=null,ready=false,drag=null,selected=null,lastEvaluation=null,pairValue=0;
let renderRequested=true,framePending=false,verifiedBindings=null;
const status=text=>{el('status').textContent=text;};
function devicePollingActive(){return session.mode==='device'&&!document.hidden&&document.hasFocus();}
function scheduleFrame(){
  if(framePending)return;framePending=true;requestAnimationFrame(animate);
}
function requestRender(reason='render_request'){renderRequested=true;scheduleFrame(reason);}
displayNames.forEach((name,index)=>el('channel').add(new Option(name,String(index))));

async function digest(bytes){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(value=>value.toString(16).padStart(2,'0')).join('');}
function resetCamera(){
  if(approvedRender&&profile){
    const scale=profile.visual.meters_per_native_unit,view=approvedRender.camera;
    camera.position.fromArray(view.position).multiplyScalar(scale);orbit.target.fromArray(view.target).multiplyScalar(scale);
    camera.fov=view.fov_degrees;camera.updateProjectionMatrix();orbit.update();requestRender();return;
  }
  if(!model){camera.position.set(0,-.27,.13);orbit.target.set(0,0,0);orbit.update();requestRender();return;}
  model.updateMatrixWorld(true);const box=new T.Box3().setFromObject(model),center=box.getCenter(new T.Vector3()),size=box.getSize(new T.Vector3()),span=Math.max(size.x,size.y,size.z);
  orbit.target.copy(center);camera.position.set(center.x,center.y-span*1.35,center.z+span*1.95);camera.near=Math.max(.0001,span/1000);camera.far=Math.max(10,span*20);camera.updateProjectionMatrix();orbit.update();requestRender();
}
resetCamera();el('camera').onclick=resetCamera;
function clear(reason){
  const pointer=drag?.pointer;drag=null;orbit.enabled=true;session.clear(reason);pairValue=0;
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
function oneAxisProjection(nodeName,local,base,channel){
  const [low,high]=profile.channels[channel].range,lowState=Float32Array.from(base),highState=Float32Array.from(base);lowState[channel]=low;highState[channel]=high;
  const lowScreen=projectPickedPoint(nodeName,local,lowState),highScreen=projectPickedPoint(nodeName,local,highState),dx=highScreen[0]-lowScreen[0],dy=highScreen[1]-lowScreen[1],denominator=dx*dx+dy*dy;
  return {channel,range:[low,high],low_screen:lowScreen,high_screen:highScreen,screen_displacement_px:[dx,dy],screen_span_px:Math.sqrt(denominator),denominator,degenerate:denominator<1e-5};
}
function updateMouseState(state){session.updateFromPartPose(state,performance.now(),configuredChannels(profile));applyPose();}

renderer.domElement.addEventListener('pointerdown',event=>{
  if(!ready||event.button!==0)return;pointerRay(event);const hits=ray.intersectObjects([...parts.values()],true),hit=hits[0];if(!hit)return;
  selected=hit.object.userData.profileNode;const nodeRecord=profile.nodes.find(node=>node.source_node===selected),candidates=profile.joints.filter(joint=>joint.node===selected),selectedChannel=Number(el('channel').value);
  let joint=candidates.find(candidate=>jointChannels(candidate).includes(selectedChannel))??candidates.find(candidate=>jointChannels(candidate).length);
  el('selection').textContent=JSON.stringify({node:nodeRecord,selected_joint:joint??null,parameter:joint?evidence.parameters[joint.parameter_ref]:null,warning:'运动仅为 estimated-v0；不是目标手柄的实测机械参数'},null,2);
  if(session.mode!=='mouse'||!joint)return;
  const local=parts.get(selected).worldToLocal(hit.point.clone()),control=nodeRecord.control;
  if(el('drag2d').checked&&['left_stick','right_stick'].includes(control)){
    const channels=control==='left_stick'?[0,1]:[2,3];
    drag={kind:'two',channels,local,node:selected,pointer:event.pointerId};
  }else{
    const channels=jointChannels(joint);if(!channels.length)return;
    const channel=channels.includes(selectedChannel)?selectedChannel:channels[0];
    el('channel').value=String(channel);drag={kind:'one',channel,local,node:selected,base:Float32Array.from(session.frame.values),pointer:event.pointerId};
  }
  orbit.enabled=false;renderer.domElement.setPointerCapture(event.pointerId);
},true);

renderer.domElement.addEventListener('pointermove',event=>{
  if(!drag||event.pointerId!==drag.pointer)return;
  if(drag.kind==='two'){
    const state=Float32Array.from(session.frame.values),project=values=>{const trial=Float32Array.from(state);drag.channels.forEach((channel,index)=>trial[channel]=values[index]);return projectPickedPoint(drag.node,drag.local,trial);};
    const result=solveDrag2D(project,drag.channels.map(channel=>state[channel]),[event.clientX,event.clientY],{constrain:projectUnitDisk});drag.channels.forEach((channel,index)=>state[channel]=result.values[index]);updateMouseState(state);
    status(`二维拖动投影误差 ${result.errorPx.toFixed(2)} px；${lastEvaluation.projections.length?'当前状态已投影到运动边界':'未触发边界投影'}`);return;
  }
  const channel=drag.channel,[low,high]=profile.channels[channel].range,projection=oneAxisProjection(drag.node,drag.local,drag.base,channel),a=projection.low_screen,[dx,dy]=projection.screen_displacement_px,denominator=projection.denominator;
  if(denominator<1e-5){status('当前视角下该运动在屏幕上的投影退化，请旋转视角。');return;}
  const t=Math.max(0,Math.min(1,((event.clientX-a[0])*dx+(event.clientY-a[1])*dy)/denominator)),state=Float32Array.from(drag.base);state[channel]=low+t*(high-low);updateMouseState(state);
});
function release(event){if(!drag||event.pointerId!==drag.pointer)return;const channels=drag.kind==='two'?drag.channels:[drag.channel];drag=null;orbit.enabled=true;if(!el('hold').checked){const state=Float32Array.from(session.frame.values);channels.forEach(channel=>state[channel]=0);updateMouseState(state);}}
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
  const renderResponse=await fetch('/approved/approved_render.json');if(!renderResponse.ok)throw Error('无法读取用户确认的渲染方案');approvedRender=await renderResponse.json();
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
  // Reuse the original, previously audited material. Blender's static export
  // changed KHR_materials_specular from intensity-in-alpha to specular color.
  const sourceUrl='/source/xbox_one_s_controllergamepad_animated.glb';
  const sourceResponse=await fetch(sourceUrl);if(!sourceResponse.ok)throw Error(`Source GLB HTTP ${sourceResponse.status}`);
  const sourceBytes=await sourceResponse.arrayBuffer(),sourceHash=await digest(sourceBytes);
  if(sourceHash!==profile.source_bindings.source_glb_sha256)throw Error('原始材质 GLB 哈希不匹配');
  const sourceGltf=await new GLTFLoader().parseAsync(sourceBytes,'/source/');
  const sourceMaterial=await sourceGltf.parser.getDependency('material',0);
  // Retain the source material metadata for inspection and picking. The visible
  // image and transparency are rendered by Cycles from the packed .blend.
  const exportedMaterials=new Set();
  model.traverse(object=>{if(object.isMesh){exportedMaterials.add(object.material);object.material=sourceMaterial;}});
  for(const material of exportedMaterials)material.dispose();
  sourceGltf.scene.traverse(object=>{if(object.isMesh)object.geometry.dispose();});
  for(const record of profile.nodes){
    const node=model.getObjectByName(record.source_node);if(!node)throw Error(`GLB 缺少节点：${record.source_node}`);node.updateMatrix();restMatrices.set(record.source_node,node.matrix.clone());node.matrixAutoUpdate=false;
    node.traverse(object=>{if(object.isMesh)object.userData.profileNode=record.source_node;});parts.set(record.source_node,node);
  }
  verifiedBindings={
    inventory:{url:'/assets/inventory.json',actual_sha256:inventoryHash,expected_sha256:variant.inventory_sha256},
    profile:{url:'/registry/'+binding.path,actual_sha256:profileHash,expected_sha256:binding.sha256},
    evidence:{url:'/evidence/'+evidenceRelative.slice('sources/'.length),actual_sha256:evidenceHash,expected_sha256:profile.parameter_source_sha256},
    visual:{url:'/assets/'+profile.visual.file,actual_sha256:glbHash,expected_sha256:profile.visual.sha256},
    material:{url:sourceUrl,actual_sha256:sourceHash,expected_sha256:profile.source_bindings.source_glb_sha256},
  };
  validateProfile(profile,evidence,new Set(parts.keys()));ready=true;session.updateFromPartPose(neutralState(),performance.now(),configuredChannels(profile));applyPose();resetCamera();
  el('limits').textContent=JSON.stringify({acceptance:profile.acceptance,unknown_physical_parameters:evidence.unknown_physical_parameters,scale_fit:evidence.scale_fit},null,2);
  status(`已核验 16 部件材质 GLB、schema-2 estimated-v0 配置和参数证据；variant=${activeVariantId}`);document.body.dataset.ready='true';document.body.dataset.variantId=activeVariantId;
}

function valuesChanged(before,after){return before.length!==after.length||before.some((value,index)=>value!==after[index]);}
let deviceKey='';function animate(){
  framePending=false;const beforeValues=Array.from(session.frame.values),pads=Array.from(navigator.getGamepads?.()??[]).filter(pad=>pad?.connected),keyValue=pads.map(pad=>`${pad.index}:${pad.id}`).join('|');
  if(keyValue!==deviceKey){const previous=el('device').value;el('device').replaceChildren();pads.forEach(pad=>el('device').add(new Option(`${pad.index}: ${pad.id}`,String(pad.index))));if(pads.some(pad=>String(pad.index)===previous))el('device').value=previous;deviceKey=keyValue;if(session.mode==='device')clear('device_list_change');}
  if(session.mode==='device'&&!document.hidden&&document.hasFocus()){try{session.updateDevice(pads.find(pad=>String(pad.index)===el('device').value)??null,performance.now());}catch(error){clear(error.message);}}
  if(valuesChanged(beforeValues,session.frame.values))applyPose();updateReadouts();
  const width=Math.floor(Math.min(el('scene').clientWidth,el('scene').clientHeight*16/9)),height=Math.round(width*9/16),resized=renderer.domElement.width!==width||renderer.domElement.height!==height;if(resized){renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();requestRender();}
  const orbitChanged=orbit.update();if(renderRequested||orbitChanged){if(ready)renderer.render(parts,camera,profile.visual.meters_per_native_unit);renderRequested=false;}
  if(orbitChanged)scheduleFrame('orbit_damping');
  if(devicePollingActive())scheduleFrame('device_poll');
}
load().catch(error=>{status(error.message);document.body.dataset.error=error.message;});scheduleFrame('startup');
if(new URLSearchParams(location.search).get('debug')==='1'){
  import('./v0_debug.mjs').then(({installViewerDebug})=>installViewerDebug({
    scene,camera,renderer,orbit,parts,restMatrices,
    getState:()=>({ready,activeVariantId,profile,model,session,lastEvaluation,pairValue,selected,drag,deviceKey,verifiedBindings,cycles:{frame:renderer.frame,request:renderer.request,running:renderer.running,error:renderer.lastError}}),
    projectPickedPoint,resetCamera,requestRender,
  })).catch(error=>{document.body.dataset.error=`debug module: ${error.message}`;});
}
