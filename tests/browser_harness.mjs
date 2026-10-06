// Synthetic browser integration test, NOT a physical-controller acceptance test.
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
const pages=await (await fetch('http://127.0.0.1:9227/json/list')).json();
const page=pages.find(p=>p.type==='page'&&p.url==='http://127.0.0.1:9876/');
assert.ok(page,'Dedicated test browser page missing');
const socket=new WebSocket(page.webSocketDebuggerUrl);
await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));
let id=0;const pending=new Map();
socket.addEventListener('message',e=>{const r=JSON.parse(e.data);if(pending.has(r.id)){const {resolve,reject,timer}=pending.get(r.id);pending.delete(r.id);clearTimeout(timer);r.error?reject(Error(JSON.stringify(r.error))):resolve(r.result);}});
function call(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error(`Timeout: ${method}`));},20000);pending.set(n,{resolve,reject,timer});socket.send(JSON.stringify({id:n,method,params}));});}
async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
const inspect=()=>evaluate("import('/app.mjs').then(m=>m.inspect())");
const startedAt=new Date().toISOString();
let stage='http_health';
try{
  const health=await fetch('http://127.0.0.1:9876/');
  assert.equal(health.status,200,'Viewer HTTP service unavailable');
  stage='page_navigation';
  await call('Page.navigate',{url:'http://127.0.0.1:9876/'});
  stage='document_readiness';
  await call('Page.bringToFront');
  for(let i=0;i<60;i++){
    if(await evaluate("document.readyState==='complete' && !!document.getElementById('rig')"))break;
    await new Promise(r=>setTimeout(r,500));
  }
  assert.ok(await evaluate("!!document.getElementById('rig')"),'Viewer document did not load');
  stage='asset_readiness';
  let state;
  for(let i=0;i<60;i++){state=await inspect();if(state.ready)break;await new Promise(r=>setTimeout(r,500));}
  assert.equal(state.ready,true);assert.equal(state.parts.length,42);
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
  await writeFile('/tmp/xbox-viewer-mouse-test.png',Buffer.from(mouseShot.data,'base64'));
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',x,y:y-40,button:'left',buttons:0,clickCount:1});
  state=await inspect();assert.equal(state.values[4],0);
  const lifecycleResults=[];
  stage='input_lifecycle';
  for(const [name,expression,reason] of [
    ['blur_handler',"window.dispatchEvent(new Event('blur'))",'focus_loss'],
    ['pointer_cancel_handler',"document.querySelector('canvas').dispatchEvent(new PointerEvent('pointercancel'))",'pointer_cancel'],
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
  await writeFile('/tmp/xbox-viewer-tested.png',Buffer.from(screenshot.data,'base64'));
  const result={mesh_count:42,synthetic_mouse_to_signal:true,synthetic_signal_to_mesh:true,synthetic_compound_axis_drag:true,simultaneous_two_axis_pointer_drag:true,two_axis_release_reset:true,compound_pose_matches_independent_formula:true,release_reset:true,disconnect_reset:true,lifecycle_browser_checks:lifecycleResults,lifecycle_scope:'Actual CDP mouse drag and native pointer capture; blur/cancel/device-selection handlers dispatched as DOM test events, not OS event generation',real_controller_tested:false,target_rig_calibrated:false};
  await writeFile(new URL('../results/browser_harness.json',import.meta.url),JSON.stringify(result,null,2)+'\n');
  await writeFile(new URL('../results/browser_last_attempt.json',import.meta.url),JSON.stringify({startedAt,finishedAt:new Date().toISOString(),passed:true,stage:'complete',physicalAcceptance:false},null,2)+'\n');
  console.log(JSON.stringify(result));
}catch(error){
  await writeFile(new URL('../results/browser_last_attempt.json',import.meta.url),JSON.stringify({startedAt,finishedAt:new Date().toISOString(),passed:false,stage,error:String(error),physicalAcceptance:false,previousHarnessResult:'Historical result only; does not verify current code'},null,2)+'\n');
  throw error;
}finally{
  await evaluate("delete navigator.getGamepads;delete window.testPad;location.reload()").catch(()=>{});
  socket.close();
}
