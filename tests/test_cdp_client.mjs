import assert from 'node:assert/strict';
import test from 'node:test';
import {closeCdpTarget, connectCdp, describeRuntimeException, evaluateCdp} from './cdp_client.mjs';

class FakeWebSocket {
  static CONNECTING=0;
  static OPEN=1;
  static CLOSED=3;

  constructor() {
    this.readyState=FakeWebSocket.CONNECTING;
    this.listeners=new Map();
    queueMicrotask(()=>{this.readyState=FakeWebSocket.OPEN;this.emit('open',{});});
  }

  addEventListener(type,listener,options={}) {
    const wrapped=options.once?(event=>{this.removeEventListener(type,wrapped);listener(event);}):listener;
    this.listeners.set(type,[...(this.listeners.get(type)??[]),wrapped]);
  }

  removeEventListener(type,listener) {
    this.listeners.set(type,(this.listeners.get(type)??[]).filter(item=>item!==listener));
  }

  emit(type,event) {
    for(const listener of [...(this.listeners.get(type)??[])])listener(event);
  }

  send(raw) {
    const request=JSON.parse(raw);
    if(request.method==='Hang')return;
    if(request.method==='Close'){
      queueMicrotask(()=>{this.readyState=FakeWebSocket.CLOSED;this.emit('close',{code:1006});});
      return;
    }
    queueMicrotask(()=>this.emit('message',{data:JSON.stringify({id:request.id,result:{result:{value:request.params.expression??request.method}}})}));
  }

  close() {
    if(this.readyState===FakeWebSocket.CLOSED)return;
    this.readyState=FakeWebSocket.CLOSED;
    this.emit('close',{code:1000});
  }
}

test('CDP client evaluates expressions, emits events, and times out bounded calls',async()=>{
  const client=await connectCdp('ws://fake',{timeoutMs:50,WebSocketImpl:FakeWebSocket});
  assert.equal(await evaluateCdp(client,'2 + 2'),'2 + 2');
  let observed=null;
  client.onEvent(message=>{observed=message;});
  client.socket.emit('message',{data:JSON.stringify({method:'Network.loadingFailed',params:{errorText:'fixture'}})});
  assert.equal(observed.method,'Network.loadingFailed');
  await assert.rejects(client.call('Hang',{}, {timeout:5}),/CDP timeout.*Hang/);
  client.close();
});

test('CDP close rejects an outstanding RPC',async()=>{
  const client=await connectCdp('ws://fake',{timeoutMs:50,WebSocketImpl:FakeWebSocket});
  await assert.rejects(client.call('Close'),/CDP WebSocket closed/);
});

test('CDP open timeout closes a socket that never connects',async()=>{
  class NeverOpenWebSocket {
    static CONNECTING=0;
    static OPEN=1;
    static CLOSED=3;
    static instance=null;
    constructor(){
      this.readyState=NeverOpenWebSocket.CONNECTING;
      this.listeners=new Map();
      this.closed=false;
      NeverOpenWebSocket.instance=this;
    }
    addEventListener(type,listener){this.listeners.set(type,[...(this.listeners.get(type)??[]),listener]);}
    removeEventListener(type,listener){this.listeners.set(type,(this.listeners.get(type)??[]).filter(item=>item!==listener));}
    close(){this.closed=true;this.readyState=NeverOpenWebSocket.CLOSED;}
  }
  await assert.rejects(
    connectCdp('ws://never',{timeoutMs:5,WebSocketImpl:NeverOpenWebSocket}),
    /open timeout/,
  );
  assert.equal(NeverOpenWebSocket.instance.closed,true);
});

test('created CDP target is closed through the bounded HTTP endpoint',async()=>{
  let observed;
  await closeCdpTarget('http://127.0.0.1:9222','target/id',{
    fetchImpl:async(url,options)=>{observed={url:String(url),options};return {ok:true,status:200};},
  });
  assert.equal(observed.url,'http://127.0.0.1:9222/json/close/target%2Fid');
  assert.ok(observed.options.signal);
});

test('runtime exceptions retain the browser description and stack location',()=>{
  assert.deepEqual(describeRuntimeException({
    text:'Uncaught',
    exception:{description:'TypeError: synthetic failure'},
    url:'http://127.0.0.1/app.mjs',
    lineNumber:12,
    columnNumber:34,
    stackTrace:{callFrames:[{
      functionName:'onPointerMove',
      url:'http://127.0.0.1/app.mjs',
      lineNumber:11,
      columnNumber:9,
    }]},
  }),{
    text:'Uncaught',
    description:'TypeError: synthetic failure',
    value:null,
    url:'http://127.0.0.1/app.mjs',
    lineNumber:12,
    columnNumber:34,
    stack:[{
      functionName:'onPointerMove',
      url:'http://127.0.0.1/app.mjs',
      lineNumber:11,
      columnNumber:9,
    }],
  });
});
