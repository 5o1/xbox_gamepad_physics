// Software fixtures only. This surrogate is independent of the browser viewer.
import {toCoordinate,toSignal} from '../scripts/coordinate_mapping.mjs';
const joints=Array.from({length:21},(_,channel)=>({channel,
  q0:channel<4?-.2:0, q1:channel<4?.3:.004,
  evidence:'Synthetic cross-language fixture, NOT Xbox parameters'}));
const states=Array.from({length:9},(_,k)=>joints.map(j=>j.channel<4?-1+k/4:k/8));
const coordinates=states.map(s=>joints.map(j=>toCoordinate(j.channel,j.q0,j.q1,s[j.channel])));
const signals=coordinates.map(q=>joints.map((j,i)=>toSignal(j.channel,j.q0,j.q1,q[i])));
console.log(JSON.stringify({joints,states,coordinates,signals}));
