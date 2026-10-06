import test from 'node:test';
import assert from 'node:assert/strict';
import {readStandardGamepad, InputSession} from '../viewer/gamepad_state.mjs';
import {describeFrame, formatFrame} from '../viewer/diagnostics.mjs';
const pad=()=>({connected:true,id:'fixture',index:0,mapping:'standard',timestamp:0,
  axes:[.3,0,0,0],buttons:Array.from({length:16},()=>({value:.25,pressed:false,touched:true}))});
const j={channel:10,type:'prismatic',q0:0,q1:.004,evidence:'Software fixture, not Xbox parameter'};
test('raw browser snapshot stays separate from Float32 and preserves missing Guide',()=>{
  const p=pad(),f=readStandardGamepad(p,20),d=describeFrame(f,[j],'device');
  p.axes[0]=1;p.buttons[0].value=1;
  assert.equal(d.raw.axes[0],.3);assert.equal(d.raw.buttons[0].value,.25);
  assert.equal(d.raw.buttons[0].touched,true);
  assert.equal(d.channels[0].represented,null);
  assert.equal(d.channels[10].represented,.25);assert.equal(d.channels[10].coordinate,.001);
  assert.equal(d.channels[10].unit,'m');assert.equal(d.channels[20].input,null);
  assert.equal(d.deviceTimestamp,0);assert.equal(d.receivedAt,20);
  assert.match(formatFrame(d),/源时间戳：0.000 ms/);
});
test('unrecognized mapping remains inspectable but does not drive the asset',()=>{
  const p=pad();p.mapping='';p.axes.push(.7);
  const d=describeFrame(readStandardGamepad(p,20),[j],'device');
  assert.equal(d.valid,false);assert.equal(d.mapping,'');assert.equal(d.raw.axes.length,5);
  assert.ok(d.channels.every(c=>c.input===null&&c.represented===null&&c.coordinate===null));
});
test('lifecycle clear removes previous raw data and timestamps',()=>{
  const s=new InputSession();s.setMode('device');s.updateDevice(pad(),20);s.clear('focus_loss');
  const d=describeFrame(s.frame,[j],s.mode);
  assert.equal(d.raw,null);assert.equal(d.receivedAt,null);assert.equal(d.deviceTimestamp,null);
  assert.equal(d.reason,'focus_loss');assert.match(formatFrame(d),/源时间戳：未知/);
});
