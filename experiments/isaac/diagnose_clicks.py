"""Read-only native telemetry for the existing frozen click press executor.

Incoming joint wrenches and their DOF projections are total joint quantities,
not separately measured implicit drive forces. Feedforward actuation forces and
Isaac Lab's actuator effort estimates are deliberately not relabeled as drives.
"""
import torch
from tests.acceptance.isaac.executor import IsaacPressExecutor


class NativeClickLoggingExecutor(IsaacPressExecutor):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        art=self.gamepad.articulation
        self._joint_ids=[art.joint_names.index(side+'_stick_'+axis)
                         for side in ('left','right') for axis in ('x','y','click')]
        self._body_ids=[art.body_names.index(side+'_stick') for side in ('left','right')]
        self._unavailable={}
        self._pre=None
        self.native_metadata={
            'joint_names':[art.joint_names[i] for i in self._joint_ids],
            'body_names':[art.body_names[i] for i in self._body_ids],
            'probe_com_transform_native':self.probe.root_physx_view.get_coms()[0].cpu().tolist(),
            'probe_mass_kg':self.probe.root_physx_view.get_masses()[0].cpu().tolist(),
            'projected_joint_force_semantics':'Incoming joint force projected onto the DOF motion direction; not an isolated drive force.',
            'incoming_wrench_semantics':'Total incoming joint force/torque in the child joint frame; not world frame.',
            'pre_state_timing':'At ball_state(), before applying this row force and advancing the native simulation.',
            'post_state_timing':'At sample(), after the native step and caller updates.',
            'unavailable_native_apis':self._unavailable,
            'implicit_drive_force':None,
            'implicit_drive_force_missing_reason':'No isolated native implicit-drive force is read; Isaac Lab applied_torque is an estimate.'}
        self.native_metadata['native_drive_readback']={
            name:getattr(art.root_physx_view,name)()[0,self._joint_ids].cpu().tolist()
            for name in ('get_dof_stiffnesses','get_dof_dampings','get_dof_max_forces','get_dof_max_velocities')}
        import omni.usd
        from pxr import PhysxSchema
        api=PhysxSchema.PhysxArticulationAPI(
            omni.usd.get_context().get_stage().GetPrimAtPath(art.cfg.prim_path))
        self.native_metadata['configured_actor_solver_iterations']={
            'position':api.GetSolverPositionIterationCountAttr().Get(),
            'velocity':api.GetSolverVelocityIterationCountAttr().Get(),
            'source':'Authored USD articulation properties, not a runtime solver-island count.'}

    def _state(self):
        art=self.gamepad.articulation
        return {
            'probe_link_state_w':self.probe.data.root_link_state_w[0].cpu().tolist(),
            'probe_com_state_w':self.probe.data.root_com_state_w[0].cpu().tolist(),
            'probe_controller_position_w':self.probe.data.root_pos_w[0].cpu().tolist(),
            'probe_controller_velocity_w':self.probe.data.root_lin_vel_w[0].cpu().tolist(),
            'joint_positions':art.data.joint_pos[0,self._joint_ids].cpu().tolist(),
            'joint_velocities':art.data.joint_vel[0,self._joint_ids].cpu().tolist(),
            'cap_link_poses_w':torch.cat((art.data.body_link_pos_w[0,self._body_ids],
                                        art.data.body_link_quat_w[0,self._body_ids]),-1).cpu().tolist()}

    def ball_state(self):
        state=super().ball_state()
        self._pre=self._state()
        return state

    def _force(self,name,selection):
        if name in self._unavailable:return None
        getter=getattr(self.gamepad.articulation.root_physx_view,name,None)
        if getter is None:
            self._unavailable[name]='Method not present in the installed native tensor API.'
            return None
        try:
            value=getter()[0,selection].cpu()
        except Exception as error:
            self._unavailable[name]=type(error).__name__+': '+str(error)
            return None
        if not bool(torch.isfinite(value).all()):
            raise RuntimeError(name+' returned nonfinite force telemetry')
        return value.tolist()

    def sample(self):
        row=super().sample()
        row['native_click_diagnostic']={
            'pre':self._pre,'post':self._state(),
            'projected_joint_forces':self._force('get_dof_projected_joint_forces',self._joint_ids),
            'incoming_joint_wrenches':self._force('get_link_incoming_joint_force',self._body_ids)}
        return row


def run_constant_hold_case(executor,suite,case,sink,*,axial_only=False):
    """Use the shared trajectory/scorer, changing only the hold force command.

    The constant is the last original press command, not a fitted load. Keep the
    would-be PD command in the trace so this diagnostic cannot masquerade as the
    frozen acceptance runner.
    """
    from tests.acceptance.runner import PressTrajectory,ball_force
    from tests.acceptance.scoring import target_value,score_case
    import math
    executor.reset_case(suite,case)
    trajectory=PressTrajectory(suite,case);rows=[];last_force=None;held_force=None
    norm=math.sqrt(sum(value*value for value in case.plan['direction']))
    direction=tuple(value/norm for value in case.plan['direction'])
    for tick in range(10000):
        target=trajectory.before_step(tick)
        state=executor.ball_state()
        pd_force=ball_force(suite.settings,target,state['position_m'],state['velocity_m_s'],suite.fixture['gravity_m_s2'])
        in_hold=trajectory.phase=='hold'
        if in_hold and held_force is None:held_force=last_force
        force=held_force if in_hold else pd_force
        clipped=False
        if in_hold and axial_only:
            delta=sum((original-current)*axis for original,current,axis in zip(held_force,pd_force,direction))
            force=tuple(current+delta*axis for current,axis in zip(pd_force,direction))
            length=math.sqrt(sum(value*value for value in force))
            if length>suite.settings['force_limit_n']:
                clipped=True
                force=tuple(value*suite.settings['force_limit_n']/length for value in force)
        executor.apply_ball_force(force);executor.step(.004)
        row=dict(executor.sample())
        trajectory.after_step(tick,target_value(case.plan,row['signals'],row['probe']['events']),row['probe']['pose'][:3],force)
        row['step']=tick
        row['probe'].update(phase=trajectory.phase,phase_age_s=(tick-trajectory.phase_start)*.004,
            target_m=target,force_n=force,stroke_m=trajectory.stroke,termination=trajectory.termination,
            diagnostic_pd_force_n=pd_force,diagnostic_constant_hold_applied=in_hold,
            diagnostic_axial_only=axial_only,diagnostic_force_clipped=clipped)
        rows.append(row);sink.write(row);last_force=force
        if trajectory.phase=='done':return score_case(suite,case,rows)
    raise RuntimeError('constant-force diagnostic exceeded the shared case step budget')
