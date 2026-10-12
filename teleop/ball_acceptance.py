"""Run isolated real teleop sphere cases and collect failures without stopping."""
import argparse
import asyncio
import json
import math
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request
from .ball_probe import CASES,case_spec,threshold,target_value
from .ball_browser import check
from .site import require,profile_command


def acceptance_threshold(channel):
    if channel and channel.startswith('dpad_'):
        reference=Path(__file__).resolve().parents[1]/'references/full_controls.json'
        return float(json.loads(reference.read_text())['signal_policy']['dpad_contact_closure']['threshold'])
    return threshold(channel)


def scoring_misfires(spec, signals):
    allowed={spec['channel']}
    if spec['kind']=='stick':
        side=spec['channel'].rsplit('_',1)[0]
        allowed|={side+'_x',side+'_y'}
    return {n:v for n,v in signals.items() if n not in allowed and abs(v)>=acceptance_threshold(n)}


def evaluate(name, rows, browser):
    spec=case_spec(name)
    # The transition row describes the completed last press step (age < 0).
    # Count only complete physics steps with the target held fixed.
    hold=[r for r in rows if r['probe']['phase']=='hold' and r['probe'].get('phase_age_s',0)>=0]
    # Score the last 0.5 s before withdrawal, after settling for the photograph.
    stable=hold[-125:]
    values=[target_value(spec,r['signals'],r['probe']['events']) for r in stable]
    bad={n:max(abs(r['signals'][n]) for r in stable) for n in stable[0]['signals']
         if any(n in scoring_misfires(spec,r['signals']) for r in stable)}
    withdraw=next(r['step'] for r in rows if r['probe']['phase']=='withdraw')
    observe=[r for r in rows if r['probe']['phase']=='observe']
    neutral=next((r for i,r in enumerate(observe) if all(abs(target_value(spec,x['signals'],x['probe']['events']))<=1e-4 for x in observe[i:])),None)
    # Return deadline is after the sphere completes withdrawal, not at its start.
    return_time=(neutral['step']-observe[0]['step'])*.004 if neutral else None
    internal=max(r['gamepad_internal_pairs'] for r in rows)
    reached=min(values)>=acceptance_threshold(spec['channel'])
    centered=return_time is not None and return_time<=.5
    result={'case':name,'target_channel':spec['channel'],'target_min':min(values),'target_max':max(values),
            'signals_at_photo':browser['overlay_applied']['meta']['signals'],
            'event_at_photo':browser['overlay_applied']['meta']['probe']['events'],
            'target_threshold':acceptance_threshold(spec['channel']),
            'dpad_bottomed_noncritical':max(values)>=.9 if spec['kind']=='dpad' else None,
            'signal_passed':reached,'misfires':bad,'no_misfires':not bad,
            'overlay_passed':browser['overlay_passed'],'overlay_unexpected':browser['unexpected_components'],
            'overlay_color':browser['overlay_color'],
            'canonical_32_exact':browser['all_inputs_canonical_32_from_rendered_signals'],
            'return_time_after_withdraw_s':return_time,'return_from_start_s':(neutral['step']-withdraw)*.004 if neutral else None,
            'return_passed':centered,'internal_pairs':internal,
            'contacted_links':sorted({b for r in rows for c in r['contacts'] for b in c['bodies'] if b!='test_ball'}),
            'max_penetration_m':max((max(0,-p['separation_m']) for r in rows for c in r['contacts'] for p in c['points']),default=0),
            'max_force_n':max(math.sqrt(sum(v*v for v in r['probe']['force_n'])) for r in rows),
            'hold_sim_seconds':len(hold)*.004,'withdraw_step':withdraw,'steps':len(rows)}
    result['termination']=next((r['probe']['termination'] for r in rows if r['probe'].get('termination')),None)
    result['joint_limit_excess']={name:max(r.get('joint_limit_excess',{}).get(name,0) for r in rows)
                                for name in {name for r in rows for name in r.get('joint_limit_excess',{})}}
    result['passed']=reached and not bad and browser['overlay_passed'] and result['canonical_32_exact'] and centered and internal==0
    return result


def run_case(name, output, remote_root, gpu, local_port, remote_port, radius_m=None, collision="sdf", plan_directory=None, simulation_python=None):
    output.mkdir(parents=True,exist_ok=True)
    slug=name.lower();remote=remote_root+'/'+slug
    ssh=['ssh','-p',require('TELEOP_SSH_PORT'),'-i',require('TELEOP_SSH_IDENTITY'),'-o','IdentitiesOnly=yes','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no','-o','PreferredAuthentications=publickey','-o','BatchMode=yes']
    destination=require('TELEOP_SSH_USER')+'@'+require('TELEOP_GPU_HOST')
    command=f"cd {shlex.quote(require('TELEOP_REMOTE_REPO'))} && export TELEOP_SITE_CONFIG={shlex.quote(require('TELEOP_REMOTE_ROOT')+'/site.env')} XBOX_GAMEPAD_PHYSICS_RESOURCES={shlex.quote(require('TELEOP_RESOURCE_ROOT'))} && {shlex.quote(require('TELEOP_STREAM_PYTHON'))} -u -m teleop.stream.gateway --run {shlex.quote(remote)} --gpu {gpu} --port {remote_port} --render-candidate rt --ball-case {shlex.quote(name)}"
    command+=' --collision '+shlex.quote(collision)
    if simulation_python:command+=' --simulation-python '+shlex.quote(simulation_python)
    if plan_directory:command+=' --ball-plan '+shlex.quote(str(Path(plan_directory)/(name+'.json')))
    if radius_m is not None:command+=' --ball-radius-m '+str(radius_m)
    url=f'http://127.0.0.1:{local_port}/'
    log=(output/'gateway.log').open('w');tlog=(output/'tunnel.log').open('w')
    service=subprocess.Popen(profile_command(command),stdout=log,stderr=subprocess.STDOUT)
    tunnel=subprocess.Popen(ssh+['-T','-L',f'127.0.0.1:{local_port}:127.0.0.1:{remote_port}',destination,'cat'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=tlog)
    try:
        for _ in range(60):
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url+'health',timeout=1) as r:
                    health=json.load(r)
                if health['ready']:break
            except (OSError,ValueError):pass
            if service.poll() is not None:raise RuntimeError((output/'gateway.log').read_text())
            time.sleep(1)
        else:raise RuntimeError('health not ready')
        browser=asyncio.run(check(url,name,output))
    finally:
        subprocess.run(['curl','--noproxy','*','-sS','-X','POST',url+'shutdown?run='+slug],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:service.wait(timeout=25)
        except subprocess.TimeoutExpired:service.terminate();service.wait(timeout=5)
        tunnel.terminate();tunnel.wait(timeout=5);log.close();tlog.close()
        subprocess.run(['rsync','-a','--exclude=*.mmap','--exclude=record.jsonl','--exclude=physics_timing.jsonl','--exclude=render_timing.jsonl','--exclude=stream_timing.jsonl',
                        '-e',shlex.join(ssh),destination+':'+remote+'/',str(output/'server')+'/'],check=True)
    rows=[json.loads(l) for l in (output/'server/ball_trace.jsonl').open()]
    result=evaluate(name,rows,browser);(output/'result.json').write_text(json.dumps(result,indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cases',nargs='+',choices=CASES,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--remote-subdir',required=True)
    p.add_argument('--gpu',type=int,required=True);p.add_argument('--local-port',type=int,required=True);p.add_argument('--remote-port',type=int,required=True);p.add_argument('--radius-m',type=float);p.add_argument('--collision',choices=['coacd','sdf'],default='sdf');p.add_argument('--plan-directory')
    p.add_argument('--sapien',choices=['3.0.3','3.0.0b1'],default='3.0.3')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);results=[]
    if a.sapien=='3.0.0b1' and a.collision!='coacd':p.error('SDF requires 3.0.3; explicitly select --collision coacd for the legacy environment')
    for name in a.cases:
        try:r=run_case(name,a.output/name,require('TELEOP_REMOTE_ROOT')+'/'+a.remote_subdir,a.gpu,a.local_port,a.remote_port,a.radius_m,a.collision,a.plan_directory,
                       require('TELEOP_LEGACY_PYTHON') if a.sapien=='3.0.0b1' else None)
        except Exception as error:
            r={'case':name,'passed':False,'execution_error':str(error)}
            (a.output/name/'error.json').write_text(json.dumps(r,indent=2))
        results.append(r);(a.output/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps(r),flush=True)
