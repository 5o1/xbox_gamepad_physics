import {AXES, BUTTONS} from './gamepad_state.mjs';
import {toJoint} from './rig.mjs';

// A configured kinematic coordinate is not an observation of physical motion.
export function describeFrame(frame, joints, mode) {
  const channels = [...AXES, ...BUTTONS].map((name, channel) => {
    const joint = joints.find(j => j.channel === channel);
    const available = frame.valid && frame.available?.[channel] === true;
    return {
      name, available, configured: Boolean(joint),
      input: available ? frame.values[channel] : null,
      represented: available && joint ? frame.values[channel] : null,
      coordinate: available && joint ? toJoint(joint, frame.values[channel]) : null,
      unit: joint ? (joint.type === 'revolute' ? 'rad' : 'm') : null,
      evidence: joint?.evidence ?? null,
    };
  });
  return {mode, valid:frame.valid, reason:frame.reason??null,
    id:frame.id??null, index:frame.index??null, mapping:frame.mapping??null,
    receivedAt:frame.receivedAt??null, deviceTimestamp:frame.deviceTimestamp??null,
    raw:frame.raw??null, channels};
}

export function formatFrame(info) {
  const time = value => value === null ? '未知' : `${value.toFixed(3)} ms`;
  const value = v => v === null ? '—' : v.toFixed(3);
  return `${info.mode} | valid=${info.valid} | ${info.reason??''}\n`+
    `设备：${info.id??'无'}\n映射：${info.mapping??'不适用'}\n`+
    `读取时刻：${time(info.receivedAt)}\n源时间戳：${time(info.deviceTimestamp)}\n`+
    '时间均相对页面时间原点；差值不是实测传输延迟。\n'+
    '通道    输入    已绑定信号   关节坐标\n'+
    info.channels.map(c=>`${c.name.padEnd(7)} ${value(c.input)}  ${value(c.represented)}  `+
      (c.coordinate===null?'—':`${c.coordinate.toPrecision(5)} ${c.unit}`)+
      (!c.configured?' [未绑定动作]':!c.available?' [输入不可用]':'')).join('\n');
}
