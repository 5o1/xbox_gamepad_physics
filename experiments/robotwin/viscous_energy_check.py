"""Small no-work viscous matrix using the delivered a1 minimal fixture."""
import argparse,importlib.util,json,math,hashlib,inspect
from pathlib import Path
import numpy as np

def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def run(source,out,construct_inertia=False,compare_channels=False):
 protocol={'id':'viscous_energy_supervisor1_v1','fixture_source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'solvers':['PGS','TGS'],'dt_s':[1/480,.004],'inertias_kgm2':[1e-4,8e-7],'initial_velocities_rad_s':[-1,1],'viscous_Nms_rad':[0,16*.00023384842283830882],'steps':100,'no_drive_contact_gravity_or_external_work':True,'inertia_basis':'Original dimensions fixture1e-4; documented numerical effective tilt inertia8e-7 probes full-model-scale b*dt/I, not hardware identification.','references':'Analytic exp(-b*dt/I); whole-step backward Euler;32-position-substep backward Euler. Explicit Euler recorded only as invalid coarse-step comparator, never used to claim an API bug.','physical_check':'Kinetic energy may not increase without external work, allowing absolute1e-12J float floor; report sign/decay and reference errors, do not cherry-pick one integrator reference after results.'}
 protocol['sapien_version']=__import__('importlib.metadata',fromlist=['version']).version('sapien');protocol['channels']=['native_friction','native_drive_damping'] if compare_channels else ['native_friction'];protocol['drive_effort_cap_Nm']=.024;protocol['inertia_initialization']='builder-time replacement in original fixture body' if construct_inertia else 'post-build native set_inertia';save(out/'registration.json',protocol);spec=importlib.util.spec_from_file_location('delivered_minimal_fixture',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);results=[]
 for channel in protocol['channels']:
  for tgs in [False,True]:
   for dt in [1/480,.004]:
    for inertia in [1e-4,8e-7]:
     for velocity in [-1,1]:
      for b in [0,16*.00023384842283830882]:

       if construct_inertia:
        text=inspect.getsource(module.fixture).replace('rod.set_mass_and_inertia(.01, sapien.Pose(), [1e-4]*3)','rod.set_mass_and_inertia(.01, sapien.Pose(), [requested_inertia]*3)');scope=dict(module.__dict__);scope['requested_inertia']=inertia;exec(compile(text,'<original fixture, requested inertia at build>','exec'),scope);scene,art,j=scope['fixture']('new',0,dt,tgs)
       else:
        scene,art,j=module.fixture('new',0,dt,tgs);j.child_link.set_inertia([inertia]*3)
       j.set_drive_properties(0,b if channel=='native_drive_damping' else 0,force_limit=.024,mode='force');j.set_drive_target(0);j.set_friction(0);j.set_friction_params(0,0,b if channel=='native_friction' else 0);art.set_qpos([0,0]);art.set_qvel([0,velocity]);art.set_qf([0,0]);I=float(j.child_link.inertia[0]);name=f'{channel}_{"TGS" if tgs else "PGS"}_dt{dt}_I{inertia}_v{velocity}_b{b}';rows=[]
       for i in range(100):
        before=float(art.get_qvel()[1]);qbefore=float(art.get_qpos()[1]);scene.step();after=float(art.get_qvel()[1]);lam=b*dt/I;r={'step':i,'q_before':qbefore,'q_after':float(art.get_qpos()[1]),'v_before':before,'v_after':after,'energy_before_j':.5*I*before**2,'energy_after_j':.5*I*after**2,'click_qvel':float(art.get_qvel()[0]),'analytic_v_after':before*math.exp(-lam),'backward_euler_v_after':before/(1+lam),'substep_BE_v_after':before*(1+lam/art.get_solver_position_iterations())**(-art.get_solver_position_iterations()),'explicit_euler_v_after_NOT_scoring':before*(1-lam)};rows.append(r)
       summary={'id':name,'channel':channel,'requested_b_Nms_rad':b,'solver':'TGS' if tgs else 'PGS','dt_s':dt,'inertia_readback_kgm2':I,'viscous_readback_Nms_rad':float(j.get_friction_params()[2]),'lambda_bdt_I':b*dt/I,'initial_velocity':velocity,'first':rows[0],'final':rows[-1],'energy_monotone':all(r['energy_after_j']<=r['energy_before_j']+1e-12 for r in rows),'largest_energy_increase_j':max(r['energy_after_j']-r['energy_before_j'] for r in rows),'max_contact_pairs':len(scene.get_contacts()),'qf':art.get_qf().tolist(),'drive_K_D':[j.stiffness,j.damping],'position_velocity_iterations':[art.get_solver_position_iterations(),art.get_solver_velocity_iterations()]}
       folder=out/name;save(folder/'summary.json',summary)
       with (folder/'trace.jsonl').open('w') as f:
        for r in rows:f.write(json.dumps(r)+'\n')
       results.append(summary);save(out/'results.json',{'results':results});print(json.dumps({k:summary[k] for k in ['id','lambda_bdt_I','energy_monotone','largest_energy_increase_j']}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--construct-inertia',action='store_true');p.add_argument('--compare-channels',action='store_true');a=p.parse_args();run(a.source.resolve(),a.output.resolve(),a.construct_inertia,a.compare_channels)
