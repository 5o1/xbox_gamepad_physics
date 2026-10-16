"""Shared test-tool state machine; native executors own scenes and contacts."""
from __future__ import annotations
from collections import deque
import math
from typing import Protocol


class PressExecutor(Protocol):
    def reset_case(self,suite,case): ...
    def ball_state(self): ...
    def apply_ball_force(self,force_n): ...
    def step(self,dt_s): ...
    def sample(self): ...


def ball_force(settings,target,position,velocity,gravity=(0.,0.,-9.81)):
    raw=[settings["stiffness_n_m"]*(t-p)-settings["damping_ns_m"]*v-settings["mass_kg"]*g
         for t,p,v,g in zip(target,position,velocity,gravity)]
    norm=math.sqrt(sum(v*v for v in raw))
    scale=min(1.,settings["force_limit_n"]/norm) if norm else 1.
    return tuple(v*scale for v in raw)


class PressStop:
    def __init__(self,settings,press_stop=None,dt=.004):
        self.settings=settings
        self.policy=press_stop or {"signal_goal":.98,"blocked_seconds":.1,"blocked_range_m":1e-6,"force_fraction":.95}
        self.window_steps=math.ceil(self.policy["blocked_seconds"]/dt)
        self.samples=deque(maxlen=self.window_steps+1)

    def sample(self,step,value,stroke,progress,force):
        self.samples.append((step,progress,force))
        full=(len(self.samples)==self.window_steps+1 and step-self.samples[0][0]>=self.window_steps)
        span=max(x[1] for x in self.samples)-min(x[1] for x in self.samples)
        minimum=min(x[2] for x in self.samples)
        if value>=self.policy["signal_goal"]: reason="signal_goal"
        elif full and span<self.policy["blocked_range_m"] and minimum>=self.settings["force_limit_n"]*self.policy["force_fraction"]: reason="blocked"
        elif stroke>=self.settings["maximum_stroke_m"]: reason="maximum_stroke"
        else: return None
        return {"reason":reason,"step":step,"stroke_m":stroke,"actual_progress_m":progress,
                "force_norm_n":force,"signal":value,"window_steps":self.samples[-1][0]-self.samples[0][0],
                "window_position_range_m":span,"window_min_force_n":minimum}


class PressTrajectory:
    def __init__(self,suite,case,*,start_step=0):
        self.suite,self.case=suite,case
        self.dt=.004
        self.phase="approach"
        self.phase_start=start_step
        self.stroke=0.
        self.target=tuple(s-d*.015 for s,d in zip(case.plan["start_m"],case.plan["direction"]))
        self.stop=PressStop(suite.settings,suite.press_stop,self.dt)
        self.termination=None

    def enter(self,phase,step):
        self.phase,self.phase_start=phase,step

    def before_step(self,step):
        age=(step-self.phase_start)*self.dt
        start=self.case.plan["start_m"];direction=self.case.plan["direction"]
        if self.phase=="approach":
            self.target=tuple(s-d*.015*max(0.,1-age) for s,d in zip(start,direction))
            if age>=1:self.enter("press",step)
        elif self.phase=="press":
            self.stroke=min(self.suite.settings["maximum_stroke_m"],self.stroke+self.suite.settings["speed_m_s"]*self.dt)
            self.target=tuple(s+d*self.stroke for s,d in zip(start,direction))
        elif self.phase=="hold" and age>=self.suite.settings["hold_seconds"]:
            self.retract_start=self.target;self.enter("withdraw",step)
        elif self.phase=="withdraw":
            fraction=min(1.,age/.5)
            self.target=tuple((1-fraction)*p+fraction*s for p,s in zip(self.retract_start,start))
            if fraction==1:self.enter("observe",step)
        elif self.phase=="observe" and age>=self.suite.settings["observe_seconds"]:
            self.enter("done",step)
        return self.target

    def after_step(self,step,value,position,force):
        if self.phase=="press":
            progress=sum((p-s)*d for p,s,d in zip(position,self.case.plan["start_m"],self.case.plan["direction"]))
            self.termination=self.stop.sample(step,value,self.stroke,progress,math.sqrt(sum(v*v for v in force)))
            if self.termination:self.enter("hold",step+1)


def run_case(executor,suite,case,sink,*,maximum_steps=10000):
    from .scoring import target_value,score_case
    executor.reset_case(suite,case)
    trajectory=PressTrajectory(suite,case)
    samples=[]
    for step in range(maximum_steps):
        target=trajectory.before_step(step)
        state=executor.ball_state()
        force=ball_force(suite.settings,target,state["position_m"],state["velocity_m_s"],suite.fixture["gravity_m_s2"])
        executor.apply_ball_force(force)
        executor.step(.004)
        row=dict(executor.sample())
        trajectory.after_step(step,target_value(case.plan,row["signals"],row["probe"]["events"]),row["probe"]["pose"][:3],force)
        row["step"]=step
        row["probe"].update(phase=trajectory.phase,phase_age_s=(step-trajectory.phase_start)*.004,
                            target_m=target,force_n=force,stroke_m=trajectory.stroke,termination=trajectory.termination)
        samples.append(row);sink.write(row)
        if trajectory.phase=="done":return score_case(suite,case,samples)
    raise RuntimeError("press case exceeded the explicit step budget")
