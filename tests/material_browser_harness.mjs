import {writeFile,mkdir} from 'node:fs/promises';
const endpoint=process.env.MATERIAL_REVIEW_URL??'http://127.0.0.1:9877/material_check.html';
const target=await(await fetch('http://127.0.0.1:9227/json/new?'+encodeURIComponent(endpoint),{method:'PUT'})).json();
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let seq=0;const pending=new Map();
ws.addEventListener('message',e=>{const d=JSON.parse(e.data);if(d.id){const p=pending.get(d.id);pending.delete(d.id);d.error?p.reject(d.error):p.resolve(d.result);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
try{
await call('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
const result=await call('Runtime.evaluate',{expression:`new Promise((resolve,reject)=>{const end=Date.now()+30000;function tick(){if(document.body.dataset.error)return reject(Error(document.body.dataset.error));if(document.body.dataset.ready)return requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(window.materialAudit)));if(Date.now()>end)return reject(Error('load timeout'));setTimeout(tick,100);}tick();})`,awaitPromise:true,returnByValue:true});
if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));
const audit=result.result.value;
if(audit.checks.meshCount!==16||!audit.checks.allPBRMapsPresent)throw Error('material assertions failed');
const out=new URL('../results/xbox_native_gltf_materials/',import.meta.url);await mkdir(out,{recursive:true});
await writeFile(new URL('runtime_audit.json',out),JSON.stringify(audit,null,2));
for(const [button,file] of [['front','front.png'],['angle','angle.png']]){
 await call('Runtime.evaluate',{expression:`document.querySelector('#${button}').click();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`,awaitPromise:true});
 const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(new URL(file,out),Buffer.from(shot.data,'base64'));
}
await call('Runtime.evaluate',{expression:"document.querySelector('#front').click();window.setDepthDiagnostic(true);document.querySelector('#status').textContent='仅诊断：启用透明材质深度写入，尚未验收';new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))",awaitPromise:true});
const diagnostic=await call('Page.captureScreenshot',{format:'png'});
await writeFile(new URL('depth_write_diagnostic.png',out),Buffer.from(diagnostic.data,'base64'));
console.log(JSON.stringify(audit.checks));
}finally{ws.close();}
