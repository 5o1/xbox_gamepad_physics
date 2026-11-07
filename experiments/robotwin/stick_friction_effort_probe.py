"""Bounded full-model effort-friction diagnosis using the existing cone runner."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import traceback
from datetime import datetime, timezone
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name('stick_friction_effort_probe_protocol.json')
CONE_PROTOCOL = ROOT/'tests/acceptance/robotwin/stick_cone_production_protocol.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def snapshot_check(resources, protocol):
    """Read the actual inputs; no lazy builder or resource preparation."""
    profile = resources/'robotwin/full_controls'
    manifest = json.loads((profile/'manifest.json').read_text())
    motion_path = resources/manifest['motion_contract']
    motion = json.loads(motion_path.read_text())
    urdf = ET.parse(profile/'mobility.urdf').getroot()
    dynamics = {r['name']: r for r in manifest['joint_dynamics']}
    records = []
    for side in protocol['sides']:
        chain = [(side+'_stick_click', 'prismatic', 'controller_body', side+'_stick_x_frame'),
                 (side+'_stick_x', 'revolute', side+'_stick_x_frame', side+'_stick_y_frame'),
                 (side+'_stick_y', 'revolute', side+'_stick_y_frame', side+'_stick')]
        for name, kind, parent, child in chain:
            j = urdf.find(f"joint[@name='{name}']")
            if j is None or (j.attrib['type'], j.find('parent').attrib['link'],
                             j.find('child').attrib['link']) != (kind, parent, child):
                raise ValueError(f'resource chain mismatch: {name}')
            records.append(dict(name=name, type=kind, parent=parent, child=child))
        click = urdf.find(f"joint[@name='{side}_stick_click']")
        if [float(v) for v in click.find('axis').attrib['xyz'].split()] != [0, 0, -1]:
            raise ValueError('click axis is not shell-fixed -Z')
        limit = click.find('limit').attrib
        if float(limit['lower']) != 0 or float(limit['upper']) != .0004:
            raise ValueError('click travel mismatch')
        d = dynamics[side+'_stick_click']
        if (d['stiffness'], d['target'], d['friction']) != (1000, 0, 0):
            raise ValueError('click spring/target mismatch')
        for suffix in ['x', 'y']:
            if dynamics[side+'_stick_'+suffix]['friction'] != .1:
                raise ValueError('baseline tilt coefficient mismatch')
    opts = manifest['backend_options']['robotwin']
    if opts['stick_click_preload']['generalized_preload_n'] != {
            'left_stick_click': -7.4, 'right_stick_click': -7.4}:
        raise ValueError('preload policy mismatch')
    constraints = [c for c in motion['joint_space_constraints'] if c['type']=='shaft_tilt_limit']
    if len(constraints) != 2 or any(c['max_angle_rad'] != math.radians(23) for c in constraints):
        raise ValueError('23 degree cone mismatch')
    paths = [profile/'manifest.json', profile/'mobility.urdf', motion_path]
    paths += [profile/p for p in manifest['required_files']]
    paths += [resources/manifest['visual_binding']['source']]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    hashes = {str(p.relative_to(resources)): digest(p) for p in sorted(set(paths))}
    for relative in ['robotwin/full_controls/manifest.json', 'robotwin/full_controls/mobility.urdf',
                     manifest['motion_contract']]:
        if digest(resources/relative) != digest(ROOT/'build/resources'/relative):
            raise ValueError(f'snapshot differs from current input: {relative}')
    return dict(resource_root=str(resources), chains=records, input_sha256=hashes,
                click_spring=dynamics['left_stick_click'], backend_options=opts)


def report(out, registration, results, error=None):
    lines = ['# 完整手柄 TGS 新摩擦诊断 A1', '', '## 失败项与执行状态', '']
    failed = [r for r in results if not r['passed']]
    if error:
        lines.append(f"关键门槛/执行异常，已停止：`{error['type']}: {error['message']}`。")
    lines.append(f'登记30组；完成{len(results)}组；原圆锥/回中综合不通过{len(failed)}组。')
    if failed:
        lines.append('')
        lines += ['| 条件/侧/方向 | 到边界 | 上界 | 回中 |', '|---|---|---|---|']
        for r in failed:
            lines.append(f"| {r['condition']}/{r['side']}/{r['direction']} | {r['boundary_reached']} | {r['upper_bound_pass']} | {r['return_pass']} |")
    by = {(r['condition'], r['side'], r['direction']): r for r in results}
    comparison = []
    for side in registration['protocol']['sides']:
        for direction in registration['protocol']['directions']:
            keys = [(c, side, direction) for c in ['legacy_7p4','effort_7p4','zero_7p4']]
            if all(k in by for k in keys):
                a,b,c = [by[k] for k in keys]
                comparison.append(dict(side=side, direction=direction,
                    legacy_peak_deg=a['load_peak_deg'], effort_peak_deg=b['load_peak_deg'],
                    zero_peak_deg=c['load_peak_deg'],
                    effort_and_zero_move=b['load_peak_deg']>=1 and c['load_peak_deg']>=1,
                    legacy_near_lock=a['load_peak_deg']<1))
    h1 = (len(comparison)==6 and all(r['effort_and_zero_move'] and r['legacy_near_lock'] for r in comparison))
    summary = dict(planned_cases=30, completed_cases=len(results), critical_error=error,
                   cone_return_passed=sum(r['passed'] for r in results), results=results,
                   H1=dict(complete_comparisons=len(comparison), supported=bool(h1), comparisons=comparison),
                   H2='Observational only; full-angle variation is not a friction-capacity measurement.',
                   production_adoption=False, false_click_acceptance_tested=False,
                   execution_bug_repairs=registration['protocol']['repair_log'])
    write(out/'summary.json', summary)
    if results:
        with (out/'SUMMARY.csv').open('w', newline='') as f:
            fields = list(results[0]); writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader(); writer.writerows(results)
    lines += ['', '## 假设与观测', '',
              f'H1登记对照完成{len(comparison)}/6；按原≥1°诊断门槛支持H1：{h1}。不符合项不删除。',
              '该结论只涉及可运动性，原圆锥/回中评分独立保留；本轮没有执行T3/T4，不能宣布误触修复。', '',
              '| 条件/侧/方向 | 加载峰值° | 稳态范围° | 回中最大° | 加载click原始比例最大值 | public signal最大值 |',
              '|---|---|---|---|---|---|']
    for r in results:
        lines.append(f"| {r['condition']}/{r['side']}/{r['direction']} | {r['load_peak_deg']:.8g} | {r['steady_min_deg']:.8g}–{r['steady_max_deg']:.8g} | {r['release_max_deg']:.8g} | {r['load_max_raw_fraction']:.8g} | {r['load_max_signal']:.8g} |")
    lines += ['', 'H2仅报告0/2/7.4N跨预压曲线。完整机构含回中弹簧和distance闭环，总角度差不能直接解释成摩擦额度差；<5%接口力律证据仍引用已独立验收的最小模型。',
              '圆锥/回中失败的内部原因本轮没有进一步定位；未读到独立摩擦容量，不用incoming wrench反算。未调参追通过。', '',
              '## 我自行做出的选择', '',
              '- 仅在本诊断入口替换executor使用的场景工厂为显式CPU-only Scene，避免原render=False路径仍默认创建RenderSystem；PhysxCpuSystem继承原配置，未设新的物理参数。',
              '- 复用cone.run的施力、时序、几何及评分；仅在loader完成、首次settle前修改登记字段，并用step观察器记录全程原生状态。',
              '- 不生成全量图片，不安装依赖，不联网，不使用GPU；0.002N·m仅为诊断值。', '',
              '## 证据与重现', '',
              '`registration.json`保存运行前协议/摘要、引用协议和输入快照；各条件下六组`readback.json`记录变更前后及完整策略；`state_trace.jsonl`覆盖750步含settle，`trace.jsonl`为原cone执行器500步施力轨迹，可按登记索引连接。',
              '每步qf只读核对持久性，不逐帧重新施加。原cone评分见各条件`results.json`。本轮无生产参数采用。', '',
              '```sh', 'PYTHONDONTWRITEBYTECODE=1 DISPLAY= CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:. \\',
              '  python -m experiments.robotwin.stick_friction_effort_probe \\',
              '  --resources <historical-resource-root> --output <新的输出目录>', '```', '',
              '全部30组结束后停止；关键门槛失败则保留已完成项和异常，剩余组不冒充通过。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')


def run(resources, out, *, protocol_path=None, step_hook=None, report_fn=None):
    protocol_file = Path(protocol_path) if protocol_path is not None else PROTOCOL
    reporter = report if report_fn is None else report_fn
    protocol = json.loads(protocol_file.read_text()); cp = json.loads(CONE_PROTOCOL.read_text())
    out.mkdir(parents=True, exist_ok=True)
    registration = dict(registered_at_utc=datetime.now(timezone.utc).isoformat(),
                        protocol=protocol, protocol_sha256=digest(protocol_file),
                        cone_protocol=cp, cone_protocol_sha256=digest(CONE_PROTOCOL),
                        script_sha256=digest(Path(__file__)), cwd=str(ROOT))
    if protocol_path is not None:
        registration['entrypoint_sha256'] = digest(ROOT/protocol['entrypoint'])
    write(out/'registration.json', registration)
    results=[]; current=None
    try:
        if os.environ.get('DISPLAY') or os.environ.get('CUDA_VISIBLE_DEVICES') != '':
            raise ValueError('Run with DISPLAY empty and CUDA_VISIBLE_DEVICES empty')
        os.environ['XBOX_GAMEPAD_PHYSICS_RESOURCES'] = str(resources)
        inputs = snapshot_check(resources, protocol)
        write(out/'resource_snapshot.json', inputs)
        import numpy as np
        import sapien
        from tests.acceptance.records import ResultSink
        from tests.acceptance.robotwin import executor as ex
        from tests.acceptance.robotwin import stick_cone_production as cone
        from experiments.robotwin.joint_readback import policy
        if sapien.__version__ != '3.0.3+concon.physx5.6.1.a1' or sapien.physx.is_gpu_enabled():
            raise ValueError('wrong wheel or GPU physics enabled')
        for name in ['set_friction_params','get_friction_params']:
            if not callable(getattr(sapien.physx.PhysxArticulationJoint, name, None)):
                raise ValueError(f'native API unavailable: {name}')
        registration['runtime'] = dict(sapien_version=sapien.__version__, physx_version=sapien.physx.version(),
            python=sys.version, prefix=sys.prefix, friction_api_doc=sapien.physx.PhysxArticulationJoint.set_friction_params.__doc__)
        registration['reused_sources_sha256'] = {str(p.relative_to(ROOT)): digest(p) for p in [
            ROOT/'tests/acceptance/robotwin/executor.py', ROOT/'tests/acceptance/robotwin/stick_click.py',
            ROOT/'tests/acceptance/robotwin/stick_cone_production.py',
            ROOT/'src/xbox_gamepad_physics/robotwin/scene.py']}
        write(out/'registration.json', registration)
        original_setup=cone.setup; original_load=ex.RobotwinPressExecutor.setup

        def state_policy(e):
            value=policy(e)
            for n,j in e.joints.items():
                value[n]['friction_params']=j.get_friction_params().tolist()
            return dict(joints=value, qf=e.art.get_qf().tolist(),
                qpos=e.art.get_qpos().tolist(), qvel=e.art.get_qvel().tolist(),
                links={n:dict(mass=float(l.mass),inertia=l.inertia.tolist(),
                    cmass_p=l.cmass_local_pose.p.tolist(),cmass_q=l.cmass_local_pose.q.tolist()) for n,l in e.links.items()},
                solver_position_iterations=e.art.solver_position_iterations,
                solver_velocity_iterations=e.art.solver_velocity_iterations,sleep_threshold=e.art.sleep_threshold,
                cone_mapping=e.gamepad._shaft_limit_mapping)

        def cpu_scene(**kwargs):
            if kwargs.get('render') is not False:
                raise ValueError('unexpected renderer request')
            scene=sapien.Scene([sapien.physx.PhysxCpuSystem()])
            scene.set_timestep(kwargs['timestep'])
            return scene

        def close_current():
            nonlocal current
            if current is not None:
                c=current; current=None
                c['e'].scene.step=c['actual_step']; c['sink'].close()
                if step_hook is not None:
                    end=state_policy(c['e'])
                    stable=json.loads(json.dumps(end))
                    for suffix in ['x','y']:
                        n=c['metadata']['side']+'_stick_'+suffix
                        stable['joints'][n]['stiffness']=c['metadata']['after']['joints'][n]['stiffness']
                    for field in ['qpos','qvel']:
                        stable[field]=c['metadata']['after'][field]
                    c['metadata']['end_policy']=end
                    c['metadata']['only_hook_stiffness_changed_at_end']=stable==c['metadata']['after']
                    if stable!=c['metadata']['after']:
                        raise ValueError('step hook changed an unregistered field')
                c['metadata'].update(steps=c['count'],qf_persisted=True,finite_states=True)
                write(c['folder']/'readback.json',c['metadata'])

        for condition in protocol['conditions']:
            case_index=0; cases=[]
            def make(side,hold=False):
                nonlocal current,case_index
                close_current()
                expected_side=cp['sides'][case_index//len(cp['directions'])]
                direction=cp['directions'][case_index%len(cp['directions'])]
                if side != expected_side or hold:
                    raise ValueError('cone setup sequence changed')
                case_index+=1
                folder=out/condition['name']/(side+'_'+direction)
                def loaded(e,*args,**kwargs):
                    nonlocal current
                    original_load(e,*args,**kwargs)
                    config=e.scene.physx_system.config
                    if type(e.scene.physx_system).__name__ != 'PhysxCpuSystem' or not config.enable_tgs:
                        raise ValueError('CPU production TGS is required')
                    if e.dt != cp['dt_s'] or config.gravity.tolist()!=[0,0,float(np.float32(-9.81))]:
                        raise ValueError('dt/gravity mismatch')
                    before=state_policy(e)
                    offsets={}; offset=0
                    for j in e.art.get_active_joints():
                        if j.dof != 1: raise ValueError('expected scalar joints')
                        offsets[j.name]=offset;offset+=j.dof
                    if len(offsets)!=20 or any(j['friction_params'] != [0,0,0] for j in before['joints'].values()):
                        raise ValueError('baseline joint count/new params mismatch')
                    for s in protocol['sides']:
                        if before['qf'][offsets[s+'_stick_click']] != float(np.float32(-7.4)):
                            raise ValueError('loaded preload mismatch')
                    expected=json.loads(json.dumps(before))
                    for suffix in ['x','y']:
                        name=side+'_stick_'+suffix;j=e.joints[name]
                        if j.get_friction() != float(np.float32(.1)):
                            raise ValueError('baseline legacy tilt mismatch')
                        j.set_friction(condition['legacy_coefficient'])
                        j.set_friction_params(*condition['friction_params'])
                        expected['joints'][name]['friction']=float(np.float32(condition['legacy_coefficient']))
                        expected['joints'][name]['friction_params']=[float(np.float32(x)) for x in condition['friction_params']]
                    qf=e.art.get_qf().copy();qf[offsets[side+'_stick_click']]=condition['click_qf_n']
                    e.art.set_qf(qf);expected['qf']=qf.tolist()
                    after=state_policy(e)
                    metadata=dict(condition=condition,side=side,direction=direction,
                        before=before,after=after,only_registered_fields_changed=after==expected,
                        physics_system=type(e.scene.physx_system).__name__,dt_s=e.dt,
                        scene_config={n:getattr(config,n) for n in ['enable_tgs','enable_pcm','enable_ccd','enable_enhanced_determinism','enable_friction_every_iteration']},
                        gravity=config.gravity.tolist(),runtime=registration['runtime'],
                        qf_offsets=offsets,scene_factory='explicit CPU-only; no RenderSystem',
                        force_record='original trace.jsonl force_world_n/point_world_m; no force implementation replaced')
                    write(folder/'readback.json',metadata)
                    if after!=expected:raise ValueError('unexpected parameter mutation')
                    c=dict(e=e,folder=folder,metadata=metadata,sink=ResultSink(folder/'state_trace.jsonl'),
                           count=0,actual_step=e.scene.step,clicks=[])
                    current=c;cases.append(c)
                    def observed_step():
                        extra = step_hook(e, side, condition, c['count'], 'before') if step_hook is not None else None
                        c['actual_step']()
                        q=e.art.get_qpos();v=e.art.get_qvel();force=e.art.get_qf()
                        if not all(np.isfinite(x).all() for x in [q,v,force]):
                            raise ValueError('nonfinite native state')
                        if force.tolist()!=after['qf']:
                            raise ValueError('persistent qf changed during step')
                        clicks={s:dict(q_m=e.gamepad.joint_position(s+'_stick_click'),
                            raw_fraction=e.gamepad.joint_position(s+'_stick_click')/.0004,
                            public_signal=e.gamepad.gamepad_state().channel(s+'_stick')) for s in protocol['sides']}
                        matrix=e.links[side+'_stick'].entity_pose.to_transformation_matrix()
                        ref=e.links['controller_body'].entity_pose.to_transformation_matrix()
                        if not np.isfinite(matrix).all() or not np.isfinite(ref).all():
                            raise ValueError('nonfinite link transform')
                        axis=matrix[:3,2].astype(float);r=ref[:3,2].astype(float)
                        angle=math.degrees(math.acos(float(np.clip(axis@r/np.linalg.norm(axis)/np.linalg.norm(r),-1,1))))
                        i=c['count'];phase='settle' if i<250 else ('load' if i<500 else 'release')
                        row=dict(step_including_settle=i,time_including_settle_s=(i+1)*e.dt,
                            phase=phase,cone_trace_index=None if i<250 else i-250,
                            total_angle_deg=angle,q=e.gamepad.joint_positions(),
                            qvel=v.tolist(),qf=force.tolist(),click=clicks)
                        if step_hook is not None:
                            row['step_diagnostics']={'before':extra,
                                'after':step_hook(e,side,condition,c['count'],'after')}
                        if not all(math.isfinite(x) for d in clicks.values() for x in d.values()):
                            raise ValueError('nonfinite click state/signal')
                        c['sink'].write(row);c['clicks'].append((phase,clicks[side]));c['count']+=1
                    e.scene.step=observed_step
                with patch.object(ex,'create_scene',cpu_scene),patch.object(ex.RobotwinPressExecutor,'setup',loaded):
                    return original_setup(side,hold=hold)
            try:
                with patch.object(cone,'setup',make):
                    cone.run(out/condition['name'])
                close_current()
                raw=json.loads((out/condition['name']/'results.json').read_text())['results']
                if len(raw)!=6 or len(cases)!=6:raise ValueError('incomplete condition matrix')
                for row,c in zip(raw,cases):
                    if c['count']!=750:raise ValueError('unexpected step count')
                    loaded=[r for phase,r in c['clicks'] if phase=='load']
                    release=[r for phase,r in c['clicks'] if phase=='release']
                    results.append(dict(condition=condition['name'],**row,
                        load_max_raw_fraction=max(r['raw_fraction'] for r in loaded),
                        load_max_signal=max(r['public_signal'] for r in loaded),
                        release_max_raw_fraction=max(r['raw_fraction'] for r in release),
                        release_max_signal=max(r['public_signal'] for r in release),
                        registered_fields_only=True,qf_persisted=True,steps=c['count']))
                # Do not retain scenes through diagnostic bookkeeping.
                for c in cases:c.pop('e');c.pop('actual_step')
                reporter(out,registration,results)
            finally:
                close_current()
        final_hashes={r:digest(resources/r) for r in inputs['input_sha256']}
        if final_hashes!=inputs['input_sha256']:raise ValueError('read-only snapshot changed')
        write(out/'snapshot_unchanged.json',dict(unchanged=True,file_count=len(final_hashes)))
    except Exception as exc:
        if current is not None:
            current['e'].scene.step=current['actual_step'];current['sink'].close()
        error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        write(out/'critical_error.json',error);reporter(out,registration,results,error)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.resources.resolve(),args.output.resolve())
