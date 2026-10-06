import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.CHROME_CDP??'http://127.0.0.1:9230';
const url=process.env.REFERENCE_URL??'http://127.0.0.1:9877/sketchfab_reference.html';
const page=await(await fetch(`${base}/json/new?about:blank`,{method:'PUT'})).json();
const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
let seq=0;const pending=new Map(),events=[];ws.addEventListener('message',e=>{const d=JSON.parse(e.data);if(d.id){const p=pending.get(d.id);pending.delete(d.id);d.error?p.reject(d.error):p.resolve(d.result);}else if(['Network.loadingFailed','Runtime.consoleAPICalled','Runtime.exceptionThrown'].includes(d.method))events.push(d);});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
try{
 await call('Network.enable');await call('Runtime.enable');
 await call('Emulation.setDeviceMetricsOverride',{width:1600,height:900,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url});
 const evaluated=await call('Runtime.evaluate',{expression:`new Promise((resolve,reject)=>{const end=Date.now()+90000;function poll(){if(document.body.dataset.error)return reject(Error(document.body.dataset.error));if(window.reference?.ready)return requestAnimationFrame(()=>requestAnimationFrame(()=>resolve({...window.reference,api:undefined})));if(Date.now()>end)return reject(Error('Sketchfab viewer timeout '+JSON.stringify(window.reference)));setTimeout(poll,250)}poll()})`,awaitPromise:true,returnByValue:true});
 if(evaluated.exceptionDetails){console.error(JSON.stringify(events,null,2));throw Error(evaluated.exceptionDetails.exception?.description??evaluated.exceptionDetails.text);}
 const out=new URL('../results/xbox_sketchfab_viewer_reference/',import.meta.url);await mkdir(out,{recursive:true});
 await writeFile(new URL('runtime.json',out),JSON.stringify(evaluated.result.value,null,2));
 // Use Sketchfab's documented renderer screenshot API for the acceptance
 // reference.  A DevTools screenshot includes the embed UI and is retained
 // separately only as browser-context evidence.
 const apiShot=await call('Runtime.evaluate',{
  expression:`new Promise((resolve,reject)=>window.reference.api.getScreenShot(1600,900,'image/png',(error,result)=>error?reject(Error(String(error))):resolve(result)))`,
  awaitPromise:true,
  returnByValue:true,
 });
 if(apiShot.exceptionDetails)throw Error(apiShot.exceptionDetails.exception?.description??apiShot.exceptionDetails.text);
 const dataUrl=apiShot.result.value;
 if(typeof dataUrl!=='string'||!dataUrl.startsWith('data:image/png;base64,'))throw Error('Unexpected Viewer API screenshot result');
 await writeFile(new URL('front.png',out),Buffer.from(dataUrl.slice(dataUrl.indexOf(',')+1),'base64'));
 const browserShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 await writeFile(new URL('browser_context.png',out),Buffer.from(browserShot.data,'base64'));
 console.log(JSON.stringify(evaluated.result.value));
}finally{ws.close();}
