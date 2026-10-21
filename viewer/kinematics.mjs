// Runtime for the explicitly estimated appearance-kinematics profile.
// This is not the canonical physical-asset adapter and never promotes the
// profile's artist/reference priors to measured Xbox mechanics.
import {validateState} from './gamepad_state.mjs';

const finiteVector = (value,length) => Array.isArray(value)&&value.length===length&&value.every(Number.isFinite);
const clamp = (value,lower,upper) => Math.max(lower,Math.min(upper,value));
const jointMap = profile => new Map(profile.joints.map(joint=>[joint.id,joint]));
const EXPECTED_CHANNELS=Object.freeze([
  ['lx','axis',0,0,[-1,1]],['ly','axis',1,1,[-1,1]],['rx','axis',2,2,[-1,1]],['ry','axis',3,3,[-1,1]],
  ['a','button',4,0,[0,1]],['b','button',5,1,[0,1]],['x','button',6,2,[0,1]],['y','button',7,3,[0,1]],
  ['left_shoulder','button',8,4,[0,1]],['right_shoulder','button',9,5,[0,1]],
  ['left_trigger','button',10,6,[0,1]],['right_trigger','button',11,7,[0,1]],
  ['view','button',12,8,[0,1]],['menu','button',13,9,[0,1]],
  ['left_stick_click','button',14,10,[0,1]],['right_stick_click','button',15,11,[0,1]],
  ['dpad_up','button',16,12,[0,1]],['dpad_down','button',17,13,[0,1]],
  ['dpad_left','button',18,14,[0,1]],['dpad_right','button',19,15,[0,1]],['guide','button',20,16,[0,1]],
]);
const NON_SMOOTH_SETS=Object.freeze([
  'linear/event clamp activation boundaries',
  'radial projection boundary where joint-coordinate norm equals radius',
  'difference-channel saturation boundaries where positive-negative equals -1 or +1',
  'difference-channel represented split at zero due to sign branch and max',
]);

function exactVector(actual,expected){return Array.isArray(actual)&&Array.isArray(expected)&&actual.length===expected.length&&actual.every((value,index)=>value===expected[index]);}
function exactKeys(value,keys){return value&&typeof value==='object'&&JSON.stringify(Object.keys(value).sort())===JSON.stringify([...keys].sort());}
function requireParameter(evidence,reference,jointId){
  const record=evidence?.parameters?.[reference];
  if(!record||!Array.isArray(record.evidence)||!record.evidence.length)throw Error(`${jointId}: missing evidence parameter ${reference}`);
  const available=new Set(evidence.evidence_index?.available_ids??[]);
  if(record.evidence.some(id=>!available.has(id)))throw Error(`${jointId}: unresolved evidence ID in ${reference}`);
  return record;
}

export function sourceToGltfVector([x,y,z]) { return [x,z,-y]; }
export function sourceToGltfPoint(point) { return sourceToGltfVector(point); }

export function validateProfile(profile,evidence,nodeNames=null) {
  if(profile?.schema_version!==2||profile?.schema_name!=='appearance_kinematics_runtime')throw Error('Expected appearance kinematics schema 2');
  if(evidence?.schema_version!==1||evidence.profile_id!==profile.profile_id)throw Error('Evidence identity/schema/status mismatch');
  if(JSON.stringify(evidence.source_bindings)!==JSON.stringify(profile.source_bindings))throw Error('Profile/evidence source bindings differ');
  if(!Array.isArray(evidence.evidence_index?.available_ids)||!evidence.evidence_index.available_ids.length||new Set(evidence.evidence_index.available_ids).size!==evidence.evidence_index.available_ids.length)throw Error('Evidence source index is invalid');
  if(!Array.isArray(profile.channels)||profile.channels.length!==EXPECTED_CHANNELS.length)throw Error('Expected exactly 21 standard channels');
  profile.channels.forEach((channel,index)=>{
    const [name,kind,tensorIndex,standardIndex,range]=EXPECTED_CHANNELS[index];
    if(!exactKeys(channel,['name','kind','tensor_index','standard_index','range'])||channel.name!==name||channel.kind!==kind||channel.tensor_index!==tensorIndex||channel.standard_index!==standardIndex||!exactVector(channel.range,range))throw Error(`Channel ${index} differs from the exact standard tensor contract`);
  });
  if(!Array.isArray(profile.nodes)||!Array.isArray(profile.joints)||!Array.isArray(profile.constraints))throw Error('Missing nodes, joints or constraints');
  const physicalEvents=new Map();
  if(!Array.isArray(profile.physical_events))throw Error('Missing physical event declarations');
  for(const event of profile.physical_events){
    if(!exactKeys(event,['name','joint_id','tensor_channel'])||typeof event.name!=='string'||!event.name||typeof event.joint_id!=='string'||event.tensor_channel!==null||physicalEvents.has(event.name))throw Error('Invalid/duplicate physical event declaration');
    physicalEvents.set(event.name,event);
  }
  const nodes=new Map(),ids=new Set(),driven=[],usedEvents=new Set();
  for(const node of profile.nodes){
    if(typeof node.source_node!=='string'||!node.source_node||nodes.has(node.source_node)||!Array.isArray(node.joint_ids))throw Error('Invalid/duplicate visual node');
    if(nodeNames&&!nodeNames.has(node.source_node))throw Error(`Missing GLB node ${node.source_node}`);
    nodes.set(node.source_node,node);
  }
  for(const joint of profile.joints){
    if(typeof joint.id!=='string'||ids.has(joint.id)||!nodes.has(joint.node))throw Error('Invalid/duplicate joint');ids.add(joint.id);
    if(!['prismatic','revolute'].includes(joint.type)||!finiteVector(joint.axis_source,3)||Math.abs(Math.hypot(...joint.axis_source)-1)>1e-6)throw Error(`Invalid axis ${joint.id}`);
    if(!finiteVector(joint.pivot_source_m,3)||!finiteVector(joint.limits,2)||joint.limits[0]>=joint.limits[1])throw Error(`Invalid limits/pivot ${joint.id}`);
    if(joint.unit!==(joint.type==='revolute'?'rad':'m')||typeof joint.parameter_ref!=='string'||typeof joint.axis_parameter_ref!=='string'||typeof joint.pivot_parameter_ref!=='string')throw Error(`Invalid unit/provenance ${joint.id}`);
    const coordinateParameter=requireParameter(evidence,joint.parameter_ref,joint.id),axisParameter=requireParameter(evidence,joint.axis_parameter_ref,joint.id),pivotParameter=requireParameter(evidence,joint.pivot_parameter_ref,joint.id);
    if(!Number.isFinite(coordinateParameter.value)||coordinateParameter.unit!==joint.unit)throw Error(`${joint.id}: coordinate parameter value/unit mismatch`);
    if(axisParameter.unit!=='unit_vector_in_source_world_frame'||pivotParameter.unit!=='m_in_source_world_frame')throw Error(`${joint.id}: axis/pivot evidence unit mismatch`);
    if(!exactVector(axisParameter.value,joint.axis_source)||!exactVector(pivotParameter.value,joint.pivot_source_m))throw Error(`${joint.id}: axis/pivot differs from evidence`);
    const magnitude=coordinateParameter.value;
    if(!(joint.limits[1]===magnitude&&(joint.limits[0]===0||joint.limits[0]===-magnitude)))throw Error(`${joint.id}: limits differ from evidence parameter`);
    const driver=joint.driver;
    if(driver?.kind==='linear_channel'){
      if(!Number.isInteger(driver.channel)||driver.channel<0||driver.channel>=21||!finiteVector(driver.signal_range,2)||driver.signal_range[0]>=driver.signal_range[1])throw Error(`Invalid linear driver ${joint.id}`);
      const channel=profile.channels[driver.channel];
      if(!exactVector(driver.signal_range,channel.range))throw Error(`Driver/channel range mismatch ${joint.id}`);
      if(channel.kind==='axis'&&joint.type!=='revolute')throw Error(`Axis channel requires a revolute preview joint ${joint.id}`);
      driven.push(driver.channel);
    }else if(driver?.kind==='difference_channels'){
      for(const channel of [driver.negative_channel,driver.positive_channel])if(!Number.isInteger(channel)||channel<0||channel>=21)throw Error(`Invalid difference driver ${joint.id}`);
      if(driver.negative_channel===driver.positive_channel)throw Error(`Repeated difference channel ${joint.id}`);
      for(const channel of [driver.negative_channel,driver.positive_channel])if(profile.channels[channel].kind!=='button'||!exactVector(profile.channels[channel].range,[0,1]))throw Error(`Difference driver requires [0,1] button channels ${joint.id}`);
      if(joint.type!=='revolute'||joint.limits[0]!==-joint.limits[1])throw Error(`Difference driver requires a symmetric revolute joint ${joint.id}`);
      driven.push(driver.negative_channel,driver.positive_channel);
    }else if(driver?.kind==='physical_event'){
      if(typeof driver.event!=='string'||!finiteVector(driver.signal_range,2))throw Error(`Invalid physical event ${joint.id}`);
      const declaration=physicalEvents.get(driver.event);
      if(!declaration||declaration.joint_id!==joint.id||usedEvents.has(driver.event)||!exactVector(driver.signal_range,[0,1]))throw Error(`Undeclared or inconsistent physical event ${joint.id}`);
      usedEvents.add(driver.event);
    }else throw Error(`Unknown driver ${joint.id}`);
  }
  if(usedEvents.size!==physicalEvents.size||[...physicalEvents].some(([name,event])=>!usedEvents.has(name)||!ids.has(event.joint_id)))throw Error('Physical event declarations and drivers are not a bijection');
  for(const node of profile.nodes){
    if(node.joint_ids.some(id=>!ids.has(id))||node.joint_ids.some(id=>jointMap(profile).get(id).node!==node.source_node))throw Error(`Invalid node joint list ${node.source_node}`);
    const actual=profile.joints.filter(joint=>joint.node===node.source_node).map(joint=>joint.id);
    if(JSON.stringify(actual)!==JSON.stringify(node.joint_ids))throw Error(`Node joint order mismatch ${node.source_node}`);
  }
  if(JSON.stringify([...driven].sort((a,b)=>a-b))!==JSON.stringify(Array.from({length:21},(_,i)=>i)))throw Error('Every tensor channel must be driven exactly once');
  const constrained=new Set();
  for(const constraint of profile.constraints){
    if(constraint.type!=='radial'||!Array.isArray(constraint.joint_ids)||constraint.joint_ids.length!==2||constraint.joint_ids.some(id=>!ids.has(id))||!Number.isFinite(constraint.radius)||constraint.radius<=0||constraint.projection!=='radial_clamp')throw Error(`Invalid constraint ${constraint.id}`);
    const constrainedJoints=constraint.joint_ids.map(id=>jointMap(profile).get(id));
    if(constraint.unit!=='rad'||constraint.coordinate_space!=='joint_coordinates'||constrainedJoints.some(joint=>joint.type!=='revolute'||joint.unit!=='rad'||joint.parameter_ref!==constraint.parameter_ref))throw Error(`Constraint joint type/unit/parameter mismatch ${constraint.id}`);
    const radiusParameter=requireParameter(evidence,constraint.parameter_ref,constraint.id);
    if(radiusParameter.unit!=='rad'||radiusParameter.value!==constraint.radius||constrainedJoints.some(joint=>joint.limits[0]!==-constraint.radius||joint.limits[1]!==constraint.radius))throw Error(`Constraint radius differs from evidence/joint limits ${constraint.id}`);
    if(constraint.approximation_ref!==null){
      const approximation=evidence.constraint_approximations?.[constraint.approximation_ref];
      if(!approximation||approximation.status!==constraint.model_status||approximation.reference_limit_rad!==constraint.radius)throw Error(`Constraint approximation evidence missing/inconsistent ${constraint.id}`);
      const available=new Set(evidence.evidence_index.available_ids);
      if(!Array.isArray(approximation.evidence)||!approximation.evidence.length||approximation.evidence.some(id=>!available.has(id)))throw Error(`Constraint approximation evidence ID is unresolved ${constraint.id}`);
    }
    if(typeof constraint.model_status!=='string'||!constraint.model_status.endsWith('_not_physical_gate'))throw Error(`Constraint physical status is not fail-closed ${constraint.id}`);
    constraint.joint_ids.forEach(id=>{if(constrained.has(id))throw Error(`Joint constrained twice ${id}`);constrained.add(id);});
  }
  if(profile.visual?.mode!=='gltf_container'||typeof profile.visual.file!=='string'||typeof profile.visual.sha256!=='string'||profile.visual.sha256.length!==64||!Number.isFinite(profile.visual.meters_per_native_unit)||profile.visual.meters_per_native_unit<=0)throw Error('Invalid visual binding');
  return profile;
}

function rawCoordinate(joint,state,events){
  const [lower,upper]=joint.limits,driver=joint.driver;
  if(driver.kind==='linear_channel'){
    const [s0,s1]=driver.signal_range,t=(state[driver.channel]-s0)/(s1-s0);
    return lower+clamp(t,0,1)*(upper-lower);
  }
  if(driver.kind==='difference_channels'){
    const signal=clamp(state[driver.positive_channel]-state[driver.negative_channel],-1,1);
    return signal<0?-signal*lower:signal*upper;
  }
  const value=clamp(Number(events?.[driver.event]??0),driver.signal_range[0],driver.signal_range[1]);
  const t=(value-driver.signal_range[0])/(driver.signal_range[1]-driver.signal_range[0]);
  return lower+t*(upper-lower);
}

export function evaluateProfile(profile,state,events={}){
  validateState(state);
  const coordinates=Object.fromEntries(profile.joints.map(joint=>[joint.id,rawCoordinate(joint,state,events)]));
  const projections=[];
  for(const constraint of profile.constraints){
    const [first,second]=constraint.joint_ids,radius=Math.hypot(coordinates[first],coordinates[second]);
    if(radius>constraint.radius){
      const scale=constraint.radius/radius;coordinates[first]*=scale;coordinates[second]*=scale;
      // Always apply the exact continuous radial projection. Suppress only the
      // diagnostic event for float32 roundoff on a mathematically exact boundary.
      if(radius>constraint.radius*(1+1e-7))projections.push({constraint:constraint.id,input_radius:radius,output_radius:constraint.radius});
    }
  }
  const represented=new Float32Array(21);
  const representedEvents={};
  for(const joint of profile.joints){
    const coordinate=coordinates[joint.id],[lower,upper]=joint.limits,driver=joint.driver;
    if(driver.kind==='linear_channel'){
      const t=(coordinate-lower)/(upper-lower),[s0,s1]=driver.signal_range;
      represented[driver.channel]=clamp(s0+t*(s1-s0),s0,s1);
    }else if(driver.kind==='difference_channels'){
      const signal=coordinate<0?-coordinate/lower:coordinate/upper;
      represented[driver.negative_channel]=Math.max(0,-signal);
      represented[driver.positive_channel]=Math.max(0,signal);
    }else{
      const t=(coordinate-lower)/(upper-lower),[s0,s1]=driver.signal_range;
      representedEvents[driver.event]=clamp(s0+t*(s1-s0),s0,s1);
    }
  }
  return {coordinates,represented,representedEvents,projections};
}

export function nodeSteps(profile,nodeName,evaluation){
  const joints=jointMap(profile),node=profile.nodes.find(item=>item.source_node===nodeName);
  if(!node)throw Error(`Unknown node ${nodeName}`);
  const scale=profile.visual.meters_per_native_unit;
  return node.joint_ids.map(id=>{
    const joint=joints.get(id);
    return {id,type:joint.type,axis:sourceToGltfVector(joint.axis_source),
      pivot:sourceToGltfPoint(joint.pivot_source_m.map(value=>value/scale)),
      q:joint.type==='prismatic'?evaluation.coordinates[id]/scale:evaluation.coordinates[id]};
  });
}

export function configuredChannels(profile){
  const result=new Array(21).fill(false);
  for(const joint of profile.joints){
    const driver=joint.driver;
    if(driver.kind==='linear_channel')result[driver.channel]=true;
    if(driver.kind==='difference_channels'){result[driver.negative_channel]=true;result[driver.positive_channel]=true;}
  }
  return result;
}

export function stateWithJointCoordinate(profile,state,jointId,coordinate){
  validateState(state);const joint=jointMap(profile).get(jointId);if(!joint)throw Error(`Unknown joint ${jointId}`);
  const [lower,upper]=joint.limits,q=clamp(coordinate,lower,upper),driver=joint.driver,next=Float32Array.from(state);
  if(driver.kind==='linear_channel'){
    const [s0,s1]=driver.signal_range;next[driver.channel]=s0+(q-lower)/(upper-lower)*(s1-s0);
  }else if(driver.kind==='difference_channels'){
    const signal=q<0?-q/lower:q/upper;next[driver.negative_channel]=Math.max(0,-signal);next[driver.positive_channel]=Math.max(0,signal);
  }else throw Error('Physical-only event is not a tensor channel');
  validateState(next);return next;
}
