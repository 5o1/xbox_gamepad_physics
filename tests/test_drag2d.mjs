import test from 'node:test';
import assert from 'node:assert/strict';
import {solveDrag2D} from '../viewer/drag2d.mjs';
test('one motion recovers both coordinates in a coupled projection',()=>{
  const project=([x,y])=>[40*x+10*y,15*x+50*y];
  const result=solveDrag2D(project,[0,0],project([.4,-.6]));
  assert.ok(result.reached);assert.ok(Math.abs(result.values[0]-.4)<1e-6);assert.ok(Math.abs(result.values[1]+.6)<1e-6);
});
test('nonlinear projection converges from a nonzero pose',()=>{
  const f=([x,y])=>[100*Math.sin(x)+10*y,100*Math.sin(y)+10*x];
  const r=solveDrag2D(f,[.1,-.1],f([.5,.3]));assert.ok(r.reached);
});
test('unreachable and degenerate projections stay finite and bounded',()=>{
  const r=solveDrag2D(q=>q,[0,0],[4,5]);assert.deepEqual(r.values,[1,1]);assert.equal(r.reached,false);
  const s=solveDrag2D(()=>[0,0],[.2,.3],[1,1]);assert.deepEqual(s.values,[.2,.3]);assert.equal(s.reached,false);
});
