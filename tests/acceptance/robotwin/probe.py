"""Opt-in dynamic sphere contact probe; gamepad joints/targets are never written."""
import json
from collections import deque
import math
from pathlib import Path

BUTTONS = {'A':('a','a_press','south'), 'B':('b','b_press','east'),
           'X':('x','x_press','west'), 'Y':('y','y_press','north'),
           'LB':('left_shoulder','left_shoulder_press','left_shoulder'),
           'RB':('right_shoulder','right_shoulder_press','right_shoulder'),
           'View':('view','view_press','back'), 'Menu':('menu','menu_press','start'),
           'Guide':('guide','guide_press','guide'), 'Pair':('pair','pair_press',None),
           'L3':('left_stick','left_stick_click','left_stick'),
           'R3':('right_stick','right_stick_click','right_stick')}
CASES = list(BUTTONS)
CASES += ['Dpad_'+d for d in ('up','down','left','right')]
CASES += [side+'_'+axis+'_'+sign for side in ('left','right') for axis in ('x','y') for sign in ('pos','neg')]
CASES += ['LT','RT']
# Every value here is a contact-tool test setting, never a hardware parameter.
SETTINGS = {'radius_m':.004,'mass_kg':.05,'stiffness_n_m':3000.,'damping_ns_m':12.,
            'force_limit_n':16.,'approach_clearance_m':.005,'speed_m_s':.005,
            'maximum_stroke_m':.030,'hold_seconds':.5,'observe_seconds':.5,
            'digital_threshold':.95,'analog_threshold':.9,'neutral_epsilon':1e-4}
PRESS_STOP = {'signal_goal':.98, 'blocked_seconds':.1,
              'blocked_range_m':1e-6, 'force_fraction':.95}


class PressStop:
    """Terminate deeper pressing; independent of K13 scoring thresholds."""
    def __init__(self, settings, dt=.004):
        self.settings=settings
        self.window_steps=math.ceil(PRESS_STOP['blocked_seconds']/dt)
        self.samples=deque(maxlen=self.window_steps+1)

    def sample(self, step, value, stroke, progress, force):
        self.samples.append((step,progress,force))
        full=(len(self.samples)==self.window_steps+1 and
              step-self.samples[0][0]>=self.window_steps)
        span=max(x[1] for x in self.samples)-min(x[1] for x in self.samples)
        minimum_force=min(x[2] for x in self.samples)
        if value>=PRESS_STOP['signal_goal']:reason='signal_goal'
        elif full and span<PRESS_STOP['blocked_range_m'] and minimum_force>=self.settings['force_limit_n']*PRESS_STOP['force_fraction']:
            reason='blocked'
        elif stroke>=self.settings['maximum_stroke_m']:reason='maximum_stroke'
        else:return None
        return {'reason':reason,'step':step,'stroke_m':stroke,
                'actual_progress_m':progress,'force_norm_n':force,'signal':value,
                'window_steps':self.samples[-1][0]-self.samples[0][0],
                'window_position_range_m':span,'window_min_force_n':minimum_force}


def case_spec(name):
    if name in BUTTONS:
        link,joint,channel=BUTTONS[name]
        return {'name':name,'link':link,'joint':joint,'channel':channel,'sign':1,'kind':'button'}
    if name.startswith('Dpad_'):
        d=name.split('_')[1];axis='horizontal' if d in ('left','right') else 'vertical'
        return {'name':name,'link':'dpad','joint':'dpad_'+axis,'channel':'dpad_'+d,
                'sign':1 if d in ('right','down') else -1,'kind':'dpad'}
    if name in ('LT','RT'):
        side='left' if name=='LT' else 'right'
        return {'name':name,'link':side+'_trigger','joint':side+'_trigger_hinge','channel':side+'_trigger','sign':1,'kind':'trigger'}
    side,axis,sign=name.split('_')
    return {'name':name,'link':side+'_stick','joint':side+'_stick_'+axis,'channel':side+'_'+axis,
            'sign':1 if sign=='pos' else -1,'kind':'stick'}


def threshold(channel):
    return .9 if channel and (channel.endswith(('_x','_y','trigger'))) else .95


def target_value(spec, signals, events):
    if spec['channel'] is None:return events.get('pair_bind_connect',0)
    # Split D-pad channels are already nonnegative; only signed stick axes
    # need a direction sign. The actuation sign still chooses the contact arm.
    sign=spec['sign'] if spec['kind']=='stick' else 1
    return sign*signals[spec['channel']]


def misfires(spec, signals):
    allowed={spec['channel']}
    # Canonical radial coupling on the two tilt axes of the SAME stick.
    if spec['kind']=='stick':allowed|={spec['channel'][:spec['channel'].rfind('_')]+'_x',spec['channel'][:spec['channel'].rfind('_')]+'_y'}
    return {n:v for n,v in signals.items() if n not in allowed and abs(v)>=threshold(n)}


def cooked_vertices(link):
    import numpy as np
    hulls=[]
    for shape in link.get_collision_shapes():
        t=(link.pose*shape.local_pose).to_transformation_matrix()
        v=np.asarray(shape.get_vertices())*shape.get_scale()
        hulls.append(v@t[:3,:3].T+t[:3,3])
    return hulls


def ray_surface(hulls, center, outward):
    """Outermost convex-hull surface along a specified contact ray."""
    import numpy as np
    from scipy.spatial import ConvexHull
    values=[]
    for vertices in hulls:
        eq=ConvexHull(vertices).equations
        low,high=-float('inf'),float('inf');valid=True
        for plane in eq:
            a=float(plane[:3]@outward);b=float(plane[:3]@center+plane[3])
            if abs(a)<1e-10:
                if b>1e-7:valid=False;break
            elif a>0:high=min(high,-b/a)
            else:low=max(low,-b/a)
        if valid and low<=high:values.append(high)
    if not values:raise ValueError('contact ray misses cooked control geometry')
    return center+max(values)*outward


def contact_plan(gamepad, name, settings):
    import numpy as np
    spec=case_spec(name)
    art=gamepad.articulation
    link=next(l for l in art.get_links() if l.name==spec['link'])
    joint=next(j for j in art.get_active_joints() if j.name==spec['joint'])
    hulls=cooked_vertices(link);vertices=np.concatenate(hulls)
    center=(vertices.min(0)+vertices.max(0))/2
    frame=(joint.get_child_link().pose*joint.get_pose_in_child()).to_transformation_matrix()
    axis=frame[:3,0];pivot=frame[:3,3]
    if spec['kind']=='button':
        direction=axis*spec['sign']
        if name=='Pair':
            # Its exposed back face is on +Y. Keep the tool outside the shell;
            # record the native joint axis separately, without assuming its sign.
            direction=-axis
    elif spec['kind']=='dpad':
        direction=np.array([0,0,-1.])
        arm=np.cross(direction,axis);arm/=np.linalg.norm(arm)
        center[:2]=(pivot+spec['sign']*.008*arm)[:2]
    else:
        lever=center-pivot
        if spec['kind']=='stick':
            center[2]=vertices[:,2].max()-.002
            lever=center-pivot
        direction=np.cross(axis,lever)*spec['sign'];direction/=np.linalg.norm(direction)
    outward=-direction/np.linalg.norm(direction)
    surface=ray_surface(hulls,center,outward)
    start=surface+outward*(settings['radius_m']+settings['approach_clearance_m'])
    return dict(spec,point_m=surface.tolist(),direction=direction.tolist(),start_m=start.tolist(),
                axis_world=axis.tolist(),pivot_m=pivot.tolist(),limits=joint.get_limits().tolist(),
                view='triggers' if name in ('LT','RT','LB','RB','Pair') else 'buttons_close')


class BallProbe:
    def __init__(self, session, run, name, radius_m=None, plan_path=None):
        import numpy as np
        import sapien
        self.session=session;self.settings=dict(SETTINGS)
        if radius_m is not None:self.settings["radius_m"]=radius_m
        self.plan=(json.loads(Path(plan_path).read_text())["plan"] if plan_path else contact_plan(session.gamepad,name,self.settings))
        self.run=Path(run);self.target=np.asarray(self.plan['start_m'])-np.asarray(self.plan['direction'])*.015
        b=session.scene.create_actor_builder()
        b.add_sphere_collision(radius=self.settings['radius_m'],material=session.scene.create_physical_material(.8,.6,0))
        mass=self.settings['mass_kg'];radius=self.settings['radius_m']
        b.set_mass_and_inertia(mass,sapien.Pose(),[2*mass*radius**2/5]*3)
        b.set_initial_pose(sapien.Pose(self.target))
        self.entity=b.build(name='test_ball')
        self.body=self.entity.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
        for shape in self.body.get_collision_shapes():
            shape.set_collision_groups([1,1,0,0]);shape.set_contact_offset(.0002);shape.set_rest_offset(0)
        session.body_ids[self.body]='test_ball'
        self.phase='idle';self.phase_start=0;self.stroke=0.;self.rows=[]
        self.stop=PressStop(self.settings);self.termination=None
        self.joint_limits={j.name:j.get_limits()[0].tolist() for j in session.gamepad.articulation.get_active_joints()}
        self.file=(self.run/'ball_trace.jsonl').open('w')
        (self.run/'ball_plan.json').write_text(json.dumps({'settings':self.settings,'press_stop':PRESS_STOP,
            'plan':self.plan,'gamepad_joint_limits':self.joint_limits},indent=2))

    def request(self, message):
        if message.get('action')=='start' and self.phase=='idle':self.enter('approach')

    def enter(self, phase):
        self.phase=phase;self.phase_start=self.session.index

    def before_step(self):
        import numpy as np
        from xbox_gamepad_physics.teleop.gripper import clip_norm
        dt=.004;age=(self.session.index-self.phase_start)*dt
        start=np.asarray(self.plan['start_m']);direction=np.asarray(self.plan['direction'])
        if self.phase=='approach':
            self.target=start-direction*.015*max(0,1-age/1.)
            if age>=1:self.enter('press')
        elif self.phase=='press':
            self.stroke=min(self.settings['maximum_stroke_m'],self.stroke+self.settings['speed_m_s']*dt)
            self.target=start+direction*self.stroke
        elif self.phase=='hold' and age>=self.settings['hold_seconds']:
            self.retract_start=self.target.copy();self.enter('withdraw')
        elif self.phase=='withdraw':
            # Retract along the contact direction, clearing by the original 5 mm.
            f=min(1,age/.5);self.target=(1-f)*self.retract_start+f*start
            if f==1:self.enter('observe')
        elif self.phase=='observe' and age>=self.settings['observe_seconds']:self.enter('done')
        raw=self.settings['stiffness_n_m']*(self.target-self.body.pose.p)-self.settings['damping_ns_m']*self.body.linear_velocity
        # Compensation is included BEFORE norm clipping; total force remains <=16 N.
        raw+=np.array([0,0,self.settings['mass_kg']*9.81])
        self.force=clip_norm(raw,self.settings['force_limit_n']);self.body.add_force_at_point(self.force,self.body.pose.p)

    def after_step(self, row):
        import numpy as np
        value=target_value(self.plan,row['signals'],self.session.gamepad.physical_events())
        if self.phase=='press':
            progress=float((self.body.pose.p-np.asarray(self.plan['start_m']))@np.asarray(self.plan['direction']))
            self.termination=self.stop.sample(row['step'],value,self.stroke,progress,float(np.linalg.norm(self.force)))
            if self.termination:self.enter('hold')
        snapshot={'case':self.plan['name'],'phase':self.phase,'phase_age_s':(self.session.index-1-self.phase_start)*.004,
                  'pose':list(map(float,(*self.body.pose.p,*self.body.pose.q))),
                  'target_m':self.target.tolist(),'force_n':self.force.tolist(),'stroke_m':self.stroke,
                  'radius_m':self.settings['radius_m'],'view':self.plan['view'],
                  'events':self.session.gamepad.physical_events(),'target_value':value,
                  'termination':self.termination}
        excess={name:max(lower-row['gamepad']['joints'][name],row['gamepad']['joints'][name]-upper)
                for name,(lower,upper) in self.joint_limits.items()
                if not lower<=row['gamepad']['joints'][name]<=upper}
        trace={'step':row['step'],'probe':snapshot,'signals':row['signals'],'joints':row['gamepad']['joints'],
               'canonical_state':row['canonical_state'],
               'contacts':[c for c in row['contacts'] if 'test_ball' in c['bodies']],
               'gamepad_internal_pairs':row['gamepad_internal_pairs'],'joint_limit_excess':excess}
        self.file.write(json.dumps(trace)+'\n');self.rows.append(trace)
        if self.phase=='done':self.file.flush()
        return snapshot
