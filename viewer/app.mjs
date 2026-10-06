import * as T from 'three';
import {OBJLoader} from 'three/addons/loaders/OBJLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {InputSession, AXES, BUTTONS, neutralState} from './gamepad_state.mjs';
import {loadRig, toJoint, toSignal, carriedJointFrame} from './rig.mjs';
import {solveDrag2D} from './drag2d.mjs';
import {describeFrame, formatFrame} from './diagnostics.mjs';
import {RIGID_VISUAL_GROUPS} from './assembly_constraints.mjs';
const el = id => document.getElementById(id), names = [...AXES, ...BUTTONS];
const scene = new T.Scene(); scene.background = new T.Color('#101820');
const camera = new T.PerspectiveCamera(40, 1, .001, 10); camera.up.set(0,0,1);
const renderer = new T.WebGLRenderer({antialias:true}); el('scene').append(renderer.domElement);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const orbit = new OrbitControls(camera, renderer.domElement);
function resetCamera(){camera.position.set(0,-.27,.13);orbit.target.set(0,0,0);orbit.update();}
resetCamera(); el('camera').onclick = resetCamera;
scene.add(new T.HemisphereLight(0xffffff,0x555577,2));
const light = new T.DirectionalLight(0xffffff,3);light.position.set(-.1,-.2,.3);scene.add(light);
const parts = new Map(), session = new InputSession(), ray = new T.Raycaster();
let joints = [], pending = [], drag = null, selected = null, ready = false, activeVariantId = null;
const jointAvailability=()=>Array.from({length:21},(_,channel)=>joints.some(j=>j.channel===channel));
names.forEach((name,i)=>el('channel').add(new Option(name,String(i))));
const status = text => {el('status').textContent=text;};
function clear(reason){
  const pointer=drag?.pointer;drag=null;orbit.enabled=true;session.clear(reason);
  if(pointer!==undefined&&renderer.domElement.hasPointerCapture(pointer))renderer.domElement.releasePointerCapture(pointer);
}
el('reset').onclick=()=>clear('reset');
el('mode').onchange=()=>{clear('mode_change');session.setMode(el('mode').value);};
el('device').onchange=()=>clear('device_change');
addEventListener('blur',()=>clear('focus_loss'));
document.addEventListener('visibilitychange',()=>{if(document.hidden)clear('hidden');});
function pointerRay(event){const r=renderer.domElement.getBoundingClientRect();ray.setFromCamera(new T.Vector2((event.clientX-r.left)/r.width*2-1,1-(event.clientY-r.top)/r.height*2),camera);}
function partMatrix(name,values){
    const matrix=new T.Matrix4();
    for(const j of joints.filter(j=>j.meshes.includes(name))){
      const q=toJoint(j,values[j.channel])-toJoint(j,0),axis=new T.Vector3(...j.axis),p=new T.Vector3(...j.pivot);
      const step=new T.Matrix4();
      if(j.type==='prismatic')step.makeTranslation(...axis.multiplyScalar(q).toArray());
      else step.makeTranslation(...p.toArray()).multiply(new T.Matrix4().makeRotationAxis(axis,q)).multiply(new T.Matrix4().makeTranslation(...p.negate().toArray()));
      matrix.premultiply(step);
    }
    return matrix;
}
function applyPose(){
  for(const part of parts.values()){
    part.matrix.copy(partMatrix(part.name,session.frame.values));part.matrixAutoUpdate=false;
  }
  scene.updateMatrixWorld(true);
}
renderer.domElement.addEventListener('pointerdown',event=>{
  if(!ready||event.button!==0)return;
  pointerRay(event);const hit=ray.intersectObjects([...parts.values()],true)[0];
  if(!hit)return;
  selected=hit.object.userData.part;
  const candidates=joints.filter(j=>j.meshes.includes(selected));
  const j=candidates.find(j=>j.channel===Number(el('channel').value))??candidates[0];
  el('selection').textContent=JSON.stringify({part:selected,joint:j??null,warning:'运动配置不是动力学标定'},null,2);
  if(session.mode!=='mouse'||!j)return;
  el('channel').value=String(j.channel);orbit.enabled=false;
  const base=j.channel<4?Math.floor(j.channel/2)*2:-1;
  const pair=[base,base+1].map(channel=>candidates.find(k=>k.channel===channel));
  if(base>=0&&el('drag2d').checked&&pair.every(Boolean)){
    const local=hit.point.clone().applyMatrix4(parts.get(selected).matrix.clone().invert());
    drag={pair,local,part:selected,pointer:event.pointerId};
    renderer.domElement.setPointerCapture(event.pointerId);return;
  }
  const frame=carriedJointFrame(joints,j,selected,session.frame.values);
  const axis=new T.Vector3(...frame.axis),pivot=new T.Vector3(...frame.pivot);
  const normal=j.type==='revolute'?axis:camera.getWorldDirection(new T.Vector3());
  const plane=new T.Plane().setFromNormalAndCoplanarPoint(normal,j.type==='revolute'?pivot:hit.point);
  const start=ray.ray.intersectPlane(plane,new T.Vector3());
  if(!start){orbit.enabled=true;return;}
  const denominator=1-axis.dot(normal)**2;
  if(j.type==='prismatic'&&denominator<1e-6){status('当前视角看不到移动轴，请旋转视角。');orbit.enabled=true;return;}
  drag={j,axis,pivot,plane,start,denominator,q:toJoint(j,session.frame.values[j.channel]),pointer:event.pointerId};
  renderer.domElement.setPointerCapture(event.pointerId);
},true);
renderer.domElement.addEventListener('pointermove',event=>{
  if(!drag||event.pointerId!==drag.pointer)return;
  if(drag.pair){
    const state=session.frame.values.slice(),r=renderer.domElement.getBoundingClientRect();
    const project=values=>{
      const trial=state.slice();drag.pair.forEach((j,i)=>trial[j.channel]=values[i]);
      const p=drag.local.clone().applyMatrix4(partMatrix(drag.part,trial)).project(camera);
      return [r.left+(p.x+1)*r.width/2,r.top+(1-p.y)*r.height/2];
    };
    const result=solveDrag2D(project,drag.pair.map(j=>state[j.channel]),[event.clientX,event.clientY]);
    drag.pair.forEach((j,i)=>state[j.channel]=result.values[i]);
    session.updateFromPartPose(state,performance.now(),jointAvailability());applyPose();
    status(`二维拖动投影误差 ${result.errorPx.toFixed(2)} px${result.reached?'':'；可能到达边界或当前视角退化'}`);return;
  }
  pointerRay(event);const current=ray.ray.intersectPlane(drag.plane,new T.Vector3());if(!current)return;
  let delta;
  if(drag.j.type==='prismatic')delta=current.sub(drag.start).dot(drag.axis)/drag.denominator;
  else{const a=drag.start.clone().sub(drag.pivot),b=current.sub(drag.pivot);delta=Math.atan2(drag.axis.dot(a.clone().cross(b)),a.dot(b));}
  const state=session.frame.values.slice();state[drag.j.channel]=toSignal(drag.j,drag.q+delta);
  session.updateFromPartPose(state,performance.now(),jointAvailability());applyPose();
});
function release(event){if(!drag||event.pointerId!==drag.pointer)return;const channels=drag.pair?drag.pair.map(j=>j.channel):[drag.j.channel];drag=null;orbit.enabled=true;if(!el('hold').checked){const state=session.frame.values.slice();channels.forEach(c=>state[c]=0);session.updateFromPartPose(state,performance.now(),jointAvailability());}}
renderer.domElement.addEventListener('pointerup',release);
renderer.domElement.addEventListener('pointercancel',()=>clear('pointer_cancel'));
renderer.domElement.addEventListener('lostpointercapture',()=>{if(drag)clear('capture_lost');});
function installRig(data){
  const parsed=loadRig(data,new Set(parts.keys()),RIGID_VISUAL_GROUPS);
  clear('new_rig');joints=parsed.joints;pending=parsed.pending;
  el('pending').textContent=pending.map(p=>`${names[p.channel]}：${p.reason}`).join('\n')||'没有声明待确认项；不表示配置已覆盖全部控件。';
  status(`已载入 ${joints.length} 个自由度，${pending.length} 个待确认通道；未确认项不产生动作。`);
}
el('rig').onchange=async()=>{try{installRig(JSON.parse(await el('rig').files[0].text()));}catch(e){status(`配置拒绝，保留上次配置：${e.message}`);}};
el('draft').onclick=async()=>{try{const response=await fetch('/1708_draft.json');if(!response.ok)throw Error(`HTTP ${response.status}`);installRig(await response.json());}catch(e){status(`草稿未载入：${e.message}`);}};
async function load(){
  const [registryResponse,inventoryResponse]=await Promise.all([fetch('/registry/asset_index.json'),fetch('/assets/inventory.json')]);
  if(!registryResponse.ok)throw Error(`资产注册表 HTTP ${registryResponse.status}`);
  if(!inventoryResponse.ok)throw Error(`资产清单 HTTP ${inventoryResponse.status}`);
  const registry=await registryResponse.json();activeVariantId=registry.interactive_viewer?.active_variant_id;
  const variant=registry.derived_variants?.[activeVariantId];
  if(!activeVariantId||!variant)throw Error('资产注册表没有有效的 viewer variant');
  const inventoryBytes=await inventoryResponse.arrayBuffer();
  const inventoryDigest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',inventoryBytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
  if(inventoryDigest!==variant.inventory_sha256)throw Error(`资产清单与 ${activeVariantId} 注册哈希不匹配`);
  const inventory=JSON.parse(new TextDecoder().decode(inventoryBytes)),loader=new OBJLoader();
  for(const item of inventory.objects){
    const raw=await (await fetch('/assets/'+encodeURIComponent(item.file))).arrayBuffer();
    const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(x=>x.toString(16).padStart(2,'0')).join('');
    if(digest!==item.sha256)throw Error(`网格哈希不匹配：${item.name}`);
    const part=loader.parse(new TextDecoder().decode(raw));part.name=item.name;
    part.traverse(o=>{if(o.isMesh){o.userData.part=item.name;o.material=new T.MeshStandardMaterial({color:/Thumb|Button|Shoulder|Trigger|DPad/.test(item.name)?0x53bcb5:0x8b929b,roughness:.65,side:T.DoubleSide});}});
    parts.set(item.name,part);scene.add(part);
  }
  ready=true;status(`已核验并载入 ${parts.size} 个网格；variant=${activeVariantId}；尚未配置运动机构。`);
  document.body.dataset.variantId=activeVariantId;
  document.body.dataset.ready='true';
}
let deviceKey='';
function animate(){
  requestAnimationFrame(animate);
  const pads=Array.from(navigator.getGamepads?.()??[]).filter(p=>p?.connected);
  const key=pads.map(p=>`${p.index}:${p.id}`).join('|');
  if(key!==deviceKey){const previous=el('device').value;el('device').replaceChildren();pads.forEach(p=>el('device').add(new Option(`${p.index}: ${p.id}`,String(p.index))));if(pads.some(p=>String(p.index)===previous))el('device').value=previous;deviceKey=key;clear('device_list_change');}
  if(session.mode==='device'&&!document.hidden&&document.hasFocus()){
    try{session.updateDevice(pads.find(p=>String(p.index)===el('device').value)??null,performance.now());}catch(e){clear(e.message);}
  }
  applyPose();
  const diagnostics=describeFrame(session.frame,joints,session.mode);
  el('values').textContent=formatFrame(diagnostics);
  el('raw').textContent=JSON.stringify(diagnostics.raw,null,2);
  const width=el('scene').clientWidth,height=el('scene').clientHeight;
  if(renderer.domElement.width!==Math.round(width*renderer.getPixelRatio())||renderer.domElement.height!==Math.round(height*renderer.getPixelRatio())){renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();}
  orbit.update();renderer.render(scene,camera);
}
load().catch(e=>{status(e.message);document.body.dataset.error=e.message;});animate();

// Read-only inspection for browser harnesses; not an alternate input path.
export function inspect(){
  const r=renderer.domElement.getBoundingClientRect();
  return {ready,activeVariantId,selected,mode:session.mode,values:Array.from(session.frame.values),
    diagnostics:describeFrame(session.frame,joints,session.mode),
    valid:session.frame.valid,reason:session.frame.reason??null,dragging:drag!==null,
    pointerId:drag?.pointer??null,orbitEnabled:orbit.enabled,
    joints:joints.length,pending,parts:[...parts.values()].map(part=>{
      const p=new T.Box3().setFromObject(part).getCenter(new T.Vector3()).project(camera);
      return {name:part.name,screen:[r.left+(p.x+1)*r.width/2,r.top+(1-p.y)*r.height/2],matrix:part.matrix.toArray()};
    })};
}
