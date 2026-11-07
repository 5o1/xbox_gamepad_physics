"""Centering-curve hook/report; scene, force and frozen scoring stay shared."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import stick_friction_effort_probe as shared

PROTOCOL = Path(__file__).with_name('centering_curve_probe_protocol.json')


def native_drive(joint):
    return dict(stiffness=float(joint.stiffness), damping=float(joint.damping),
                force_limit=float(joint.force_limit), target=joint.get_drive_target().tolist(),
                mode=joint.drive_mode, friction=float(joint.get_friction()),
                friction_params=joint.get_friction_params().tolist())


def curve_hook(e, side, condition, step, stage):
    names=[side+'_stick_'+s for s in ['x','y']]
    if stage=='before' and step==0:
        original={n:native_drive(e.joints[n]) for n in names}
        k=original[names[0]]['stiffness']
        if k!=original[names[1]]['stiffness'] or k<=0:
            raise ValueError('curve requires equal positive native tilt stiffness')
        e._centering_curve_diagnostic=dict(original=original, k=k,
            theta_max=json.loads(PROTOCOL.read_text())['theta_max_rad'])
    state=e._centering_curve_diagnostic
    if stage=='before':
        q=[e.gamepad.joint_position(n) for n in names]
        velocity=[e.gamepad.joint_velocity(n) for n in names]
        radius=math.hypot(*q); theta=state['theta_max']; multiplier=condition['center_multiplier']
        epsilon=theta/multiplier if multiplier is not None else None
        tau_end=state['k']*theta
        if epsilon is None:
            requested=state['k']
        elif radius==0:
            requested=tau_end/(epsilon*math.tanh(theta/epsilon))
        else:
            requested=tau_end*math.tanh(radius/epsilon)/(radius*math.tanh(theta/epsilon))
        if not all(math.isfinite(x) for x in [*q,*velocity,radius,requested]) or requested<=0:
            raise ValueError('nonfinite curve state/stiffness')
        for n in names:
            original=state['original'][n]
            e.joints[n].set_drive_properties(requested, original['damping'],
                force_limit=original['force_limit'],mode='force')
        state['requested']=requested
        result=dict(curve=condition['name'],pre_q_rad=dict(zip(names,q)),
                    pre_qvel_rad_s=dict(zip(names,velocity)),radius_rad=radius,
                    epsilon_rad=epsilon,original_k_nm_per_rad=state['k'],
                    tau_end_nominal_nm=tau_end,K_eff_requested_nm_per_rad=requested)
    else:
        result={}
    drives={n:native_drive(e.joints[n]) for n in names}
    for n,value in drives.items():
        original=state['original'][n]
        if any(value[key]!=original[key] for key in original if key!='stiffness'):
            raise ValueError('curve changed damping/target/cap/mode/friction')
        if value['target']!=[0.] or value['mode']!='force':
            raise ValueError('target zero and native force mode required')
        if value['stiffness']!=float(np.float32(state['requested'])):
            raise ValueError('native stiffness update/readback mismatch')
    result['native_drive_readback']=drives
    if stage=='before':
        result['elastic_torque_estimate_nm']={n:-drives[n]['stiffness']*v for n,v in zip(names,q)}
        result['effort_scope']='Elastic term evaluated at pre-step q; not actual total solver torque.'
    return result


def curve_report(out, registration, results, error=None):
    protocol=registration['protocol']
    old=json.loads((shared.ROOT/protocol['baseline_summary']).read_text())
    baseline={(r['side'],r['direction']):r for r in old['results'] if r['condition']=='effort_7p4'}
    enriched=[]
    for result in results:
        row=dict(result); folder=out/row['condition']/(row['side']+'_'+row['direction'])
        states=[json.loads(line) for line in (folder/'state_trace.jsonl').open()]
        readback=json.loads((folder/'readback.json').read_text())
        names=[row['side']+'_stick_'+s for s in ['x','y']]
        indices=[readback['qf_offsets'][n] for n in names]
        release=[r for r in states if r['phase']=='release']
        q0=np.array([states[499]['q'][n] for n in names])
        norm=float(np.linalg.norm(q0))
        projections=[float(np.array([r['q'][n] for n in names])@q0/norm) for r in release] if norm else []
        row.update(maximum_reverse_joint_projection_deg=math.degrees(max(0.,-min(projections))) if projections else None,
                   release_peak_total_angle_deg=max(r['total_angle_deg'] for r in release),
                   whole_release_max_joint_speed_rad_s=max(abs(r['qvel'][i]) for r in release for i in indices),
                   K_eff_min_nm_per_rad=min(r['step_diagnostics']['before']['K_eff_requested_nm_per_rad'] for r in states),
                   K_eff_max_nm_per_rad=max(r['step_diagnostics']['before']['K_eff_requested_nm_per_rad'] for r in states),
                   prior_effort_7p4_residual_deg=baseline[(row['side'],row['direction'])]['release_max_deg'])
        enriched.append(row)
    indexed={(r['condition'],r['side'],r['direction']):r for r in enriched}
    comparisons=[]
    for side in protocol['sides']:
        for direction in protocol['directions']:
            linear=indexed.get(('linear',side,direction))
            if linear is None:continue
            prior=baseline[(side,direction)]['release_max_deg']
            comparison=dict(side=side,direction=direction,linear_residual_deg=linear['release_max_deg'],
                prior_residual_deg=prior,linear_difference_deg=abs(linear['release_max_deg']-prior),
                linear_reproduced=abs(linear['release_max_deg']-prior)<=.05)
            for curve in ['center_5','center_10']:
                candidate=indexed.get((curve,side,direction))
                comparison[curve]=None if candidate is None else dict(residual_deg=candidate['release_max_deg'],
                    fraction_of_linear=candidate['release_max_deg']/linear['release_max_deg'] if linear['release_max_deg'] else None,
                    below_half=candidate['release_max_deg']<.5*linear['release_max_deg'])
            comparisons.append(comparison)
    baseline_ok=len(comparisons)==6 and all(r['linear_reproduced'] for r in comparisons)
    curve_ok={curve:len(comparisons)==6 and all(r[curve] is not None and r[curve]['below_half'] for r in comparisons)
              for curve in ['center_5','center_10']}
    supported=len(enriched)==18 and baseline_ok and all(curve_ok.values())
    summary=dict(planned_cases=18,completed_cases=len(enriched),critical_error=error,
                 mechanism_supported=bool(supported),linear_reproduction=baseline_ok,
                 center_below_half=curve_ok,comparisons=comparisons,results=enriched,
                 original_cone_return_passed=sum(r['passed'] for r in enriched),
                 diagnostic_proxy_not_identified_hardware=True,production_adoption=False,
                 execution_bug_repairs=protocol['repair_log'])
    shared.write(out/'summary.json',summary)
    if enriched:
        with (out/'SUMMARY.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(enriched[0]));writer.writeheader();writer.writerows(enriched)
    lines=['# 回中力曲线机制对照 A1','','## 数值与失败项','',
           f'登记18组，完成{len(enriched)}组；原圆锥/回中综合通过{summary["original_cone_return_passed"]}/{len(enriched)}。']
    if error:lines.append(f'关键门槛停止：{error["type"]}: {error["message"]}')
    lines += ['', '| 曲线/侧/方向 | 加载峰值° | 回中窗残余最大° | 回中窗最大速度rad/s | 反向投影超调° | 原回中通过 | 到边界 |',
              '|---|---|---|---|---|---|---|']
    for r in enriched:
        lines.append(f"| {r['condition']}/{r['side']}/{r['direction']} | {r['load_peak_deg']:.8g} | {r['release_max_deg']:.8g} | {r['release_max_speed_rad_s']:.8g} | {r['maximum_reverse_joint_projection_deg']} | {r['return_pass']} | {r['boundary_reached']} |")
    lines += ['', '## 按预登记判断假设','',
              f'linear逐方向复现前轮（绝对差≤0.05°）：{baseline_ok}；center_5六方向均低于linear的50%：{curve_ok["center_5"]}；center_10：{curve_ok["center_10"]}。',
              f'完整18组支持本轮机制假设：{supported}。若linear不复现则有实现混杂，不能挑方向或调倍数。',
              '所有条件的原圆锥/回中评分独立保留；没有以机制假设成立替代≤0.1°标准，没有执行T3/T4或生产参数搜索。', '',
              '## 力律与适用性','',
              '按每组native读回的原k定义tau_end=k×theta_max，theta_max=23°。r为两轴关节q的范数；center_5/10采用登记的tanh径向力律，r=0使用解析极限；没有夹紧q或吸附到0。',
              '三条曲线均在每一个scene.step之前调用原生force-mode set_drive_properties更新两轴相同K，保持原D、force_limit及target0。click qf只在加载后设置一次-7.4N并逐步只读核对，未用qf替代弹簧力矩。',
              '轨迹中的弹性力矩是按当前q和读回K计算的估计项，不是求解器实际总力矩，不包含阻尼、摩擦、重力或约束冲量。',
              '**诊断代理曲线不是已验证真实机构。** 5/10是预登记敏感性倍率，0.002N·m为诊断摩擦；原参考14mN·m操作力矩不等于实测纯弹簧力矩。ALPS是参考元件，专利仅说明一种机构可行，不证明Xbox1708采用其结构；±5°不替代本项目≤0.1°标准。实物回中曲线、静/动摩擦及标准适用性仍待核实。', '',
              '## 复用、自行选择与证据','',
              '- 仅向既有诊断run增加可选protocol_path、step_hook、report_fn；旧入口不传这些参数时仍走原协议、原报告、原状态记录，且不调用hook。未改冻结执行器的施力、750步时序或评分。',
              '- 新入口仅实现力律hook和本轮报告；复用旧模块的快照核对、CPU-only场景适配、加载、登记、原始记录、qf持久性及原cone runner。',
              '- 反向超调按释放起点两轴q方向的负投影记录，是关节空间观测；同时保留全释放段最大总倾角和最大关节速度，不新增通过门槛。',
              '- 原模块及原协议运行前副本在reuse/（仅存档，不作为第二套执行实现）；前轮结果摘要清单prior_artifacts_sha256.json，前轮原始文件不覆盖。',
              '- 每组state_trace.jsonl含750步：q/qvel、总倾角、click原始行程与public signal、步前K/弹性项以及步前/步后原生drive读回；trace.jsonl为原cone的500步施力轨迹。',
              '- linear复现和50%判据、原≤0.1°/≤0.01rad/s回中判据均保持登记值；未安装依赖、联网、使用GPU/GUI或启动子agent。', '',
              '## 重现命令','', '```sh',
              'PYTHONDONTWRITEBYTECODE=1 DISPLAY= CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:. \\',
              '  python -m experiments.robotwin.centering_curve_probe \\',
              '  --resources <historical-resource-root> --output <新输出目录>', '```', '',
              '本批完成后停止，不采用生产曲线。原生API、非有限状态、资源或执行器错误停止；残余不改善/振荡/原评分失败均保留并完成登记条件。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    shared.run(args.resources.resolve(),args.output.resolve(),protocol_path=PROTOCOL,
               step_hook=curve_hook,report_fn=curve_report)
