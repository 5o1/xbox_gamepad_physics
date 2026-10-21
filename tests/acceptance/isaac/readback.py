"""B1 subsystem-boundary readback; no stepping or stage mutation."""
from __future__ import annotations
import math


def readback_usd(artifact, *, motion, physical, appearance, collision_sources):
    from pxr import Usd, UsdGeom, UsdPhysics, PhysxSchema, Gf
    import numpy as np
    from xbox_gamepad_physics.backends.common.collision import bind_collision_to_links
    from xbox_gamepad_physics.backends.common.transforms import neutral_link_poses, rotate, multiply
    from xbox_gamepad_physics.isaac.constraints import NATIVE_CONE_ANGLE_SCALE, require_supported_constraints
    from pxr import Tf
    stage = Usd.Stage.Open(str(artifact.usd_path))
    comparisons = []
    def compare(label, actual, expected, atol=1e-10):
        a, e = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
        assert a.shape == e.shape and np.allclose(a,e,rtol=3e-6,atol=atol), (label,actual,expected)
        comparisons.append({'field':label,'max_abs':float(np.max(np.abs(a-e))) if a.size else 0.})
    compare('meters_per_unit', UsdGeom.GetStageMetersPerUnit(stage), 1.)
    compare('kilograms_per_unit', UsdPhysics.GetStageKilogramsPerUnit(stage), 1.)
    bodies = [p for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    joints = [p for p in stage.Traverse() if p.IsA(UsdPhysics.RevoluteJoint) or p.IsA(UsdPhysics.PrismaticJoint)]
    assert len(bodies)==len(physical.links)==21 and len(joints)==len(motion.joints)==20
    assert bool(stage.GetPrimAtPath('/Gamepad/Joints/world_fixed')) == (artifact.root_mode=='fixed')
    for limit in require_supported_constraints(motion):
        cone = UsdPhysics.SphericalJoint(stage.GetPrimAtPath(
            '/Gamepad/ShaftLimits/'+Tf.MakeValidIdentifier(limit.name)))
        assert cone and cone.GetExcludeFromArticulationAttr().Get()
        for axis, attribute in enumerate((cone.GetConeAngle0LimitAttr(), cone.GetConeAngle1LimitAttr())):
            compare(limit.name+'.native_half_angle_'+str(axis), attribute.Get(),
                    math.degrees(limit.maximum_rad)*NATIVE_CONE_ANGLE_SCALE)
    poses = neutral_link_poses(motion)
    for record in physical.links:
        p = stage.GetPrimAtPath(artifact.link_paths[record.name])
        api = UsdPhysics.MassAPI(p)
        for name, actual, expected in (
            ('mass',api.GetMassAttr().Get(),record.mass_kg.value),
            ('com',api.GetCenterOfMassAttr().Get(),record.com_m.value),
            ('principal_inertia',api.GetDiagonalInertiaAttr().Get(),record.principal_inertia_kg_m2.value)):
            compare(record.name+'.'+name, actual, expected, atol=1e-13 if name=='principal_inertia' else 1e-10)
        q=api.GetPrincipalAxesAttr().Get()
        quat=(q.GetReal(),*q.GetImaginary())
        matrix=np.column_stack([rotate(quat,v) for v in ((1,0,0),(0,1,0),(0,0,1))])
        inertia=matrix@np.diag(api.GetDiagonalInertiaAttr().Get())@matrix.T
        compare(record.name+'.full_inertia',inertia,record.inertia_com_kg_m2.value,atol=1e-12)
        xf=UsdGeom.Xformable(p)
        compare(record.name+'.neutral_position',xf.GetOrderedXformOps()[0].Get(),poses[record.name].position_m)
    for j in motion.joints:
        p=stage.GetPrimAtPath(artifact.joint_paths[j.name])
        api=(UsdPhysics.RevoluteJoint if j.kind=='revolute' else UsdPhysics.PrismaticJoint)(p)
        assert list(map(str,api.GetBody0Rel().GetTargets()))==[artifact.link_paths[j.parent]]
        assert list(map(str,api.GetBody1Rel().GetTargets()))==[artifact.link_paths[j.child]]
        compare(j.name+'.local_position',api.GetLocalPos0Attr().Get(),j.origin)
        compare(j.name+'.child_anchor',api.GetLocalPos1Attr().Get(),(0,0,0))
        for side,getter,expected in ((0,api.GetLocalRot0Attr,rotate(j.origin_orientation_wxyz,j.axis)),(1,api.GetLocalRot1Attr,j.axis)):
            q=getter().Get();q=(q.GetReal(),*q.GetImaginary())
            compare(j.name+f'.axis{side}',rotate(q,(1,0,0)),expected,atol=3e-7)
        angular=j.kind=='revolute';scale=180/math.pi if angular else 1.
        compare(j.name+'.limits',(api.GetLowerLimitAttr().Get()/scale,api.GetUpperLimitAttr().Get()/scale),(j.lower,j.upper))
        law=physical.return_laws[j.name]
        drive=UsdPhysics.DriveAPI(p,'angular' if angular else 'linear')
        assert drive.GetTypeAttr().Get()=='force'
        for field,actual,expected in (
            ('stiffness',drive.GetStiffnessAttr().Get()*scale,law.stiffness.value),
            ('drive_damping',drive.GetDampingAttr().Get()*scale,law.drive_damping.value),
            ('passive_damping',p.GetAttribute('physxJointAxis:'+('angular' if angular else 'linear')+':viscousFrictionCoefficient').Get()*scale,law.passive_damping.value),
            ('effort',drive.GetMaxForceAttr().Get(),law.effort_limit.value),
            ('target',drive.GetTargetPositionAttr().Get()/scale,law.neutral_target.value),
            ('target_velocity',drive.GetTargetVelocityAttr().Get(),0.),
            ('velocity_limit',PhysxSchema.PhysxJointAPI(p).GetMaxJointVelocityAttr().Get()/scale,law.velocity_limit.value)):
            compare(j.name+'.'+field,actual,expected)
    colliders=[p for p in stage.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI)]
    expected=sum(len(i.source.convex_hulls) for i in bind_collision_to_links(collision_sources,motion))
    assert artifact.collision_mode=='coacd' and len(colliders)==expected
    assert all(UsdPhysics.MeshCollisionAPI(p).GetApproximationAttr().Get()=='convexHull' for p in colliders)
    for c in physical.contact_materials:
        api=UsdPhysics.MaterialAPI(stage.GetPrimAtPath('/Gamepad/Looks/Contact_'+c.material_id))
        compare('contact.static',api.GetStaticFrictionAttr().Get(),c.static_friction.value)
        compare('contact.dynamic',api.GetDynamicFrictionAttr().Get(),c.dynamic_friction.value)
        compare('contact.restitution',api.GetRestitutionAttr().Get(),c.restitution.value)
    visuals=[p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh) and '/Visual/' in str(p.GetPath())]
    shadow=[p for p in visuals if p.GetAttribute('primvars:doNotCastShadows').Get()]
    assert len(visuals)==sum(len(p.groups) for p in appearance.parts)==20
    assert len(shadow)==4 and all('/BLEND_' in str(p.GetPath()) for p in shadow)
    return {'status':'passed','links':len(bodies),'joints':len(joints),'collision_shapes':len(colliders),
        'visual_shapes':len(visuals),'shadow_exceptions':list(map(lambda p:str(p.GetPath()),shadow)),
        'rtol':3e-6,'comparisons':comparisons}


def readback_articulation(articulation, *, motion, physical):
    import numpy as np
    view=articulation.root_physx_view
    names=articulation.joint_names
    checks={}
    def check(name,actual,expected,atol=1e-10):
        a=np.asarray(actual);e=np.asarray(expected)
        assert a.shape==e.shape and np.allclose(a,e,rtol=5e-5,atol=atol),(name,a.tolist(),e.tolist())
        checks[name]={'max_abs':float(np.max(np.abs(a-e))),'actual':a.tolist()}
    def array(t):return t.detach().cpu().numpy()
    for field,getter in (
        ('stiffness',view.get_dof_stiffnesses),('drive_damping',view.get_dof_dampings),
        ('effort_limit',view.get_dof_max_forces),('velocity_limit',view.get_dof_max_velocities)):
        check(field,array(getter())[0],[getattr(physical.return_laws[n],field).value for n in names])
    check('limits',array(view.get_dof_limits())[0],[[motion.joint_by_name[n].lower,motion.joint_by_name[n].upper] for n in names])
    friction=array(view.get_dof_friction_properties())[0]
    check('passive_damping',friction[:,2],[physical.return_laws[n].passive_damping.value for n in names])
    by_link={x.name:x for x in physical.links}
    check('mass',array(view.get_masses())[0],[by_link[n].mass_kg.value for n in articulation.body_names])
    # PhysX tensors return centroidal inertia in the body's local frame.
    check('inertia',array(view.get_inertias())[0].reshape(-1,3,3),[by_link[n].inertia_com_kg_m2.value for n in articulation.body_names],atol=1e-11)
    return {'status':'passed','rtol':5e-5,'checks':checks,
        'effective_joint_friction':friction.tolist(),'effective_armature':array(view.get_dof_armatures())[0].tolist(),
        'is_fixed_base':articulation.is_fixed_base,'joint_names':list(names),'body_names':list(articulation.body_names)}
