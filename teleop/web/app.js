import {CHANNEL_NAMES, canonicalFrameToOverlayState} from '/viewer/gamepad_overlay/canonical_adapter.mjs';
import {installCursor} from './cursor_input.mjs';
const canvas=document.querySelector('#video'), ctx=canvas.getContext('2d',{alpha:false});
const stats={drawDurations:[],panelDurations:[],rafTimes:[],presented:[],decoded:[],received:[],latencies:[],sent:[],errors:[],receivedBytes:0,networkRtt:[],lastFrame:null};
window.teleopStats=stats;
let control, video, seq=0, welcome=false, configured=false, latest=null, lastId=-1;
const metadata=new Map(), pending=new Map(), pingTimes=new Map();
function text(id,value){document.getElementById(id).textContent=value;}
function send(kind,body={}) {
  if(control?.readyState!==WebSocket.OPEN||!welcome)return null;
  const n=++seq, now=performance.now();
  pending.set(n,now); stats.sent.push({seq:n,kind,time:now,...body});
  control.send(JSON.stringify({kind,seq:n,...body}));return n;
}
window.teleopSend=send;
const cursor=installCursor(canvas,{send,isConnected:()=>welcome&&control?.readyState===WebSocket.OPEN,
  mode:value=>text('mode',value),error:value=>stats.errors.push(value)});
window.teleopCursor=cursor;
function stop(reason){cursor.stop(reason);}
for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>{send('view',{view:button.dataset.view});});
for(const name of CHANNEL_NAMES.slice(0,21)) {const div=document.createElement('div');div.className='signal';div.id='channel-'+name;div.innerHTML=`<span>${name}</span><span>0</span>`;document.querySelector('#signals').append(div);}
const decoder=new VideoDecoder({output(frame){stats.decoded.push({timestamp:frame.timestamp,time:performance.now()});if(latest){metadata.delete(latest.timestamp);latest.close();}latest=frame;},error(e){stats.errors.push(String(e));stop('decode-error');text('connection','解码失败');}});
let updateCounter=0;
function panel(m) {
  text('gamepad-freeze',m.gamepad_frozen===false?'可移动':'冻结');
  const active=m.state==='main'?m.main:m.secondary;
  text('active',m.state==='main'?'主夹爪':'副夹爪');text('state',m.state==='main'?'主可控':m.ghost?'主冻结 / 副幽灵':'主冻结 / 副正常');
  text('blocked',m.ghost_blocked?'仍有重叠：'+m.geometry_blockers.join(', '):m.ghost?'幽灵准备中':'正常');
  text('fingers',Object.values(active.joints).map(v=>(v*1000).toFixed(2)+' mm').join(' / '));
  text('pose',active.pose.slice(0,3).map(v=>v.toFixed(4)).join(' '));text('rotation',active.pose.slice(3).map(v=>v.toFixed(3)).join(' '));
  text('step','step '+m.step);text('sequence','输入 '+m.last_input_seq);
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view===m.view));
  const frame=m.canonical_state??{layout_id:'sdl3-gamepad-core-v1',values:CHANNEL_NAMES.map(n=>m.signals[n]??0),available_mask:CHANNEL_NAMES.map(n=>n in m.signals),task_mask:CHANNEL_NAMES.map(n=>n in m.signals),device_id:0};
  canonicalFrameToOverlayState(frame);
  const adapter=document.querySelector('#overlay').contentWindow.__gamepadOverlayAdapter;
  if(adapter?.ready)adapter.applyFrame(frame).catch(e=>stats.errors.push(String(e)));
  for(const [name,value] of Object.entries(m.signals)){const el=document.getElementById('channel-'+name);if(el){el.lastElementChild.textContent=value.toFixed(3);el.classList.toggle('on',Math.abs(value)>.05);}}
}
function present() {
  cursor.flushMouse();
  stats.rafTimes.push(performance.now());
  if(latest){const frame=latest;latest=null;const m=metadata.get(frame.timestamp);metadata.delete(frame.timestamp);
    const drawStart=performance.now();ctx.drawImage(frame,0,0,1280,720);frame.close();stats.drawDurations.push(performance.now()-drawStart);
    if(m&&m.frame_id!==lastId){lastId=m.frame_id;const now=performance.now();stats.lastFrame=m;stats.presented.push({id:m.frame_id,time:now,step:m.step,last_input_seq:m.last_input_seq});
      if(cursor.armed&&m.last_input_seq>=cursor.focusSeq&&m.hold_reason)stop('server-'+m.hold_reason);
      for(const [n,t] of pending){if(m.cancelled_seqs?.includes(n)){pending.delete(n);continue;}if(n<=m.last_input_seq){stats.latencies.push({seq:n,ms:now-t,presentedFrame:m.frame_id});pending.delete(n);}}
      const recent=stats.presented.filter(p=>p.time>=now-1000);text('fps',recent.length+' fps');
      const latency=stats.latencies.at(-1);if(latency)text('latency','响应 '+latency.ms.toFixed(1)+' ms');
      if(++updateCounter%3===0){const panelStart=performance.now();panel(m);stats.panelDurations.push(performance.now()-panelStart);}
    }
  }
  requestAnimationFrame(present);
}
requestAnimationFrame(present);
control=new WebSocket(`ws://${location.host}/control`);
window.teleopDisconnect=()=>control.close();
let heartbeatEnabled=true;window.teleopPauseHeartbeat=()=>{heartbeatEnabled=false;};
control.onmessage=e=>{const m=JSON.parse(e.data);if(m.kind==='welcome'){seq=m.seq_base;welcome=true;text('connection','已连接 · 720p');}if(m.kind==='pong'&&pingTimes.has(m.id)){stats.networkRtt.push(performance.now()-pingTimes.get(m.id));pingTimes.delete(m.id);}};
control.onclose=()=>{stop('control-disconnect');welcome=false;text('mode','连接断开 · 控制停住');text('connection','已断线');};
video=new WebSocket(`ws://${location.host}/video`);video.binaryType='arraybuffer';
video.onmessage=e=>{const bytes=new Uint8Array(e.data), length=new DataView(e.data).getUint32(0), m=JSON.parse(new TextDecoder().decode(bytes.subarray(4,4+length))), data=bytes.subarray(4+length);
  stats.receivedBytes+=bytes.length;m.receivedLocal=performance.now();stats.received.push({id:m.frame_id,time:m.receivedLocal});
  if(!configured){if(!m.key||!m.codec)return;decoder.configure({codec:m.codec,optimizeForLatency:true});configured=true;}
  const timestamp=m.frame_id*16667;metadata.set(timestamp,m);
  decoder.decode(new EncodedVideoChunk({type:m.key?'key':'delta',timestamp,data}));
};
video.onclose=()=>{stop('video-disconnect');text('connection','画面断开');};
setInterval(()=>{if(heartbeatEnabled&&control.readyState===WebSocket.OPEN&&welcome)control.send(JSON.stringify({kind:'heartbeat'}));},50);
setInterval(()=>{if(heartbeatEnabled&&control.readyState===WebSocket.OPEN&&welcome){const id=performance.now();pingTimes.set(id,id);control.send(JSON.stringify({kind:'ping',id}));}},1000);
