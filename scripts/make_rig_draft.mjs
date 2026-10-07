// Inventory of unresolved channels, NOT generated mechanical parameters.
import {AXES,BUTTONS} from '../viewer/gamepad_state.mjs';
console.log(JSON.stringify({schema:1,target:'Xbox One S',
  status:'unresolved_physical_motion',source:'specs/xbox_v1.json; specs/interactive_acceptance.json',
  joints:[],pending:[...AXES,...BUTTONS].map((name,channel)=>({channel,name,
    type:null,meshes:null,axis:null,pivot:null,q0:null,q1:null,
    reason:'尚无完整且有来源的网格绑定、运动轴/轴心及行程组合；保留输入读数，不构造机械动作。'}))},null,2));
