"""Author native USD in an externally launched Isaac application.

No importer, scene creation, stepping, or mass estimation is performed here.
SI values cross the USD angular boundary once: rad -> degree and K/D -> per degree.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from ..backends.common.collision import bind_collision_to_links, iter_frozen_hulls
from ..backends.common.transforms import neutral_link_poses, point


@dataclass(frozen=True)
class UsdArtifact:
    usd_path: Path
    root_prim_path: str
    link_paths: dict[str, str]
    joint_paths: dict[str, str]
    root_mode: str
    collision_mode: str


def _known(parameter, field):
    if parameter.value is None:
        raise ValueError(f"{field}: {parameter.missing_reason}; SDK defaults are not a fallback")
    return parameter.value


def _gltf_arrays(path):
    """Read the frozen common visual exporter format without an SDK importer."""
    import numpy as np
    doc = json.loads(path.read_text())
    buffers = [(path.parent / b['uri']).read_bytes() for b in doc['buffers']]
    def array(index):
        a = doc['accessors'][index]
        if 'sparse' in a:
            raise ValueError('sparse visual accessors are unsupported')
        v = doc['bufferViews'][a['bufferView']]
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
        dtype = np.dtype({5123: '<u2', 5125: '<u4', 5126: '<f4'}[a['componentType']])
        return np.ndarray((a['count'], width), dtype, buffers[v['buffer']],
                          offset=v.get('byteOffset', 0)+a.get('byteOffset', 0),
                          strides=(v.get('byteStride', width*dtype.itemsize), dtype.itemsize)).copy()
    for node in doc['nodes']:
        if any(k in node for k in ('matrix', 'translation', 'rotation', 'scale')):
            raise ValueError('common visual geometry must have baked node transforms')
        for primitive in doc['meshes'][node['mesh']]['primitives']:
            if primitive.get('mode', 4) != 4:
                raise ValueError('visual geometry must be triangles')
            a = primitive['attributes']
            uv = array(a['TEXCOORD_0'])
            uv[:, 1] = 1-uv[:, 1]
            yield array(a['POSITION']), array(a['NORMAL']), uv, array(primitive['indices']).ravel()


def _axis_quaternion(axis):
    """Rotate +X onto a source axis, preserving near-antiparallel components.

    Gf.Rotation's parallel-axis tolerance discards small source tilt. atan2
    avoids that tolerance and remains stable near both zero and pi.
    """
    x, y, z = axis
    length = math.sqrt(x*x+y*y+z*z)
    x, y, z = x/length, y/length, z/length
    cross_norm = math.hypot(y, z)
    if cross_norm == 0:
        return (1., 0., 0., 0.) if x > 0 else (0., 0., 0., 1.)
    half = .5*math.atan2(cross_norm, x)
    scale = math.sin(half)/cross_norm
    return (math.cos(half), 0., -z*scale, y*scale)


def build_usd(output_path, *, motion, physical, appearance, collision_sources,
              visual_directory, root_mode='fixed', collision_mode='coacd', sdf_options=None,
              contact_offsets=None, collision_overrides=None):
    """Build a full-controls asset; caller owns AppLauncher and all runtime state.

    SDF is opt-in and requires explicit native cook settings. Its default-readiness
    gate belongs to B2-B4. Unknown unsupported parameters stay null in the sidecar.
    """
    if root_mode not in {'fixed', 'free'}:
        raise ValueError("root_mode must be 'fixed' or 'free'")
    if collision_mode not in {'coacd', 'sdf'}:
        raise ValueError("collision_mode must be 'coacd' or 'sdf'")
    if collision_mode == 'sdf' and not sdf_options:
        raise ValueError('SDF requires explicit cook settings; it has not passed the default gate')
    if physical.profile != motion.profile or motion.profile != 'full_controls':
        raise ValueError('B1 requires matching full_controls motion and physical descriptions')
    collision_overrides = collision_overrides or {}
    components = {source.component for source in collision_sources}
    if not set(collision_overrides) <= components:
        raise ValueError('collision override refers to an unknown common component')
    poses = neutral_link_poses(motion)
    if {x.name for x in physical.links} != set(poses):
        raise ValueError('physical and motion link sets differ')
    if set(physical.return_laws) != set(motion.joint_by_name):
        raise ValueError('physical and motion joint sets differ')
    if any(p.link not in poses for p in appearance.parts):
        raise ValueError('appearance must be bound to the common motion links')
    for name, law in physical.return_laws.items():
        for field in ('initial_position', 'neutral_target', 'stiffness', 'drive_damping',
                      'passive_damping', 'effort_limit', 'velocity_limit'):
            _known(getattr(law, field), f'{name}.{field}')
        for field in ('dry_friction_effort', 'armature'):
            if getattr(law, field).value is not None:
                raise ValueError(f'{name}.{field}: no verified Isaac mapping in B1')
    # pxr is deliberately imported only inside the platform-process entry point.
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, PhysxSchema, Gf, Sdf, Vt, Tf
    import numpy as np
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(output))
    root = '/Gamepad'
    root_prim = UsdGeom.Xform.Define(stage, root).GetPrim()
    stage.SetDefaultPrim(root_prim)
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.)
    UsdPhysics.ArticulationRootAPI.Apply(root_prim)
    PhysxSchema.PhysxArticulationAPI.Apply(root_prim).CreateEnabledSelfCollisionsAttr(False)
    link_paths = {name: root+'/Links/'+Tf.MakeValidIdentifier(name) for name in poses}
    joint_paths = {j.name: root+'/Joints/'+Tf.MakeValidIdentifier(j.name) for j in motion.joints}
    def quat(value):
        return Gf.Quatf(float(value[0]), Gf.Vec3f(*value[1:]))
    def xform(path, pose):
        xf = UsdGeom.Xform.Define(stage, path)
        xf.AddTranslateOp().Set(Gf.Vec3d(*pose.position_m))
        xf.AddOrientOp().Set(quat(pose.orientation_wxyz))
        return xf
    for record in physical.links:
        p = xform(link_paths[record.name], poses[record.name]).GetPrim()
        UsdPhysics.RigidBodyAPI.Apply(p)
        mass = UsdPhysics.MassAPI.Apply(p)
        mass.CreateMassAttr(float(_known(record.mass_kg, record.name+'.mass')))
        mass.CreateCenterOfMassAttr(Gf.Vec3f(*_known(record.com_m, record.name+'.com')))
        mass.CreateDiagonalInertiaAttr(Gf.Vec3f(*_known(record.principal_inertia_kg_m2, record.name+'.inertia')))
        mass.CreatePrincipalAxesAttr(quat(_known(record.principal_to_link_wxyz, record.name+'.principal_axes')))
    for j in motion.joints:
        angular = j.kind == 'revolute'
        cls = UsdPhysics.RevoluteJoint if angular else UsdPhysics.PrismaticJoint
        usd = cls.Define(stage, joint_paths[j.name])
        usd.CreateBody0Rel().SetTargets([link_paths[j.parent]])
        usd.CreateBody1Rel().SetTargets([link_paths[j.child]])
        # USD joint axes are positive cardinal axes. Rotate both joint frames to
        # represent arbitrary/sign-flipped common axes without changing q signs.
        from ..backends.common.transforms import multiply
        qr = _axis_quaternion(j.axis)
        usd.CreateAxisAttr('X')
        usd.CreateLocalPos0Attr(Gf.Vec3f(*j.origin))
        usd.CreateLocalPos1Attr(Gf.Vec3f(0))
        usd.CreateLocalRot0Attr(quat(multiply(j.origin_orientation_wxyz, qr)))
        usd.CreateLocalRot1Attr(quat(qr))
        scale = 180/math.pi if angular else 1.
        usd.CreateLowerLimitAttr(j.lower*scale)
        usd.CreateUpperLimitAttr(j.upper*scale)
        law = physical.return_laws[j.name]
        drive = UsdPhysics.DriveAPI.Apply(usd.GetPrim(), 'angular' if angular else 'linear')
        drive.CreateTypeAttr('force')
        drive.CreateStiffnessAttr(law.stiffness.value/scale)
        drive.CreateDampingAttr(law.drive_damping.value/scale)
        drive.CreateMaxForceAttr(law.effort_limit.value)
        drive.CreateTargetPositionAttr(law.neutral_target.value*scale)
        drive.CreateTargetVelocityAttr(0.)
        PhysxSchema.PhysxJointAPI.Apply(usd.GetPrim()).CreateMaxJointVelocityAttr(law.velocity_limit.value*scale)
        # Sim 5.1 ships this codeless schema in PhysxSchemaAddition. The native
        # experimental Articulation API uses the same linear/angular instances.
        axis_name = 'angular' if angular else 'linear'
        usd.GetPrim().ApplyAPI('PhysxJointAxisAPI', axis_name)
        usd.GetPrim().CreateAttribute(
            f'physxJointAxis:{axis_name}:viscousFrictionCoefficient',
            Sdf.ValueTypeNames.Float, custom=False).Set(law.passive_damping.value/scale)

    if root_mode == 'fixed':
        joint = UsdPhysics.FixedJoint.Define(stage, root+'/Joints/world_fixed')
        joint.CreateBody1Rel().SetTargets([link_paths['controller_body']])
        joint.CreateLocalPos0Attr(Gf.Vec3f(0))
        joint.CreateLocalPos1Attr(Gf.Vec3f(0))
    materials = {}
    visual_root = Path(visual_directory).resolve()
    for desc in appearance.materials:
        path = root+'/Looks/'+Tf.MakeValidIdentifier(desc.name)
        mat = UsdShade.Material.Define(stage, path)
        reader = UsdShade.Shader.Define(stage, path+'/st')
        reader.CreateIdAttr('UsdPrimvarReader_float2')
        reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
        reader.CreateOutput('result', Sdf.ValueTypeNames.Float2)
        surf = UsdShade.Shader.Define(stage, path+'/Surface')
        surf.CreateIdAttr('UsdPreviewSurface')
        textures = {t.role: t for t in desc.textures}
        factors = {k: _known(v, desc.name+'.'+k) for k, v in desc.factors.items()}
        def texture(role, suffix, color_space='raw', scale=(1,1,1,1), bias=(0,0,0,0)):
            t = textures[role]
            if t.uv_set != 0 or t.transform:
                raise ValueError('B1 supports the frozen untransformed UV0 textures')
            sh = UsdShade.Shader.Define(stage, path+'/'+suffix)
            sh.CreateIdAttr('UsdUVTexture')
            sh.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(visual_root/t.resource)))
            sh.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set(color_space)
            sh.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), 'result')
            sh.CreateInput('wrapS', Sdf.ValueTypeNames.Token).Set('repeat')
            sh.CreateInput('wrapT', Sdf.ValueTypeNames.Token).Set('repeat')
            sh.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*scale))
            sh.CreateInput('bias', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*bias))
            sh.CreateOutput('rgb', Sdf.ValueTypeNames.Float3)
            for c in ('r', 'g', 'b', 'a'):
                sh.CreateOutput(c, Sdf.ValueTypeNames.Float)
            return sh
        def connect(name, typ, sh, channel):
            surf.CreateInput(name, typ).ConnectToSource(sh.ConnectableAPI(), channel)
        surf.CreateInput('useSpecularWorkflow', Sdf.ValueTypeNames.Int).Set(0)
        connect('diffuseColor', Sdf.ValueTypeNames.Color3f, texture('baseColor', 'base', 'sRGB', tuple(factors['baseColor'])), 'rgb')
        orm = texture('metallicRoughness', 'orm', scale=(1, factors['roughness'], factors['metallic'], 1))
        connect('roughness', Sdf.ValueTypeNames.Float, orm, 'g')
        connect('metallic', Sdf.ValueTypeNames.Float, orm, 'b')
        ao = factors['occlusionStrength']
        connect('occlusion', Sdf.ValueTypeNames.Float, texture('metallicRoughness', 'ao', scale=(ao,ao,ao,1), bias=(1-ao,1-ao,1-ao,0)), 'r')
        normal_scale = factors['normalScale']
        connect('normal', Sdf.ValueTypeNames.Normal3f, texture('normal', 'normal', scale=(2*normal_scale,2*normal_scale,2,1), bias=(-normal_scale,-normal_scale,-1,0)), 'rgb')
        emit = [v*factors['emissiveStrength'] for v in factors['emissive']]
        connect('emissiveColor', Sdf.ValueTypeNames.Color3f, texture('emissive', 'emissive', 'sRGB', (*emit,1)), 'rgb')
        # Preserve the reviewed RGB specular texture evidence. PreviewSurface's
        # metallic workflow cannot fully reproduce KHR dielectric F0 semantics.
        connect('specularColor', Sdf.ValueTypeNames.Color3f, texture('specular', 'specular', 'sRGB'), 'rgb')
        surf.CreateInput('opacity', Sdf.ValueTypeNames.Float).Set(float(_known(desc.constant_coverage, desc.name+'.coverage')))
        surf.CreateInput('opacityThreshold', Sdf.ValueTypeNames.Float).Set(0.)
        surf.CreateOutput('surface', Sdf.ValueTypeNames.Token)
        mat.CreateSurfaceOutput().ConnectToSource(surf.ConnectableAPI(), 'surface')
        materials[desc.name] = mat
    shadow_paths = []
    for part in appearance.parts:
        parent = link_paths[part.link]+'/Visual/'+Tf.MakeValidIdentifier(part.name)
        xf = xform(parent, part.local_pose)
        xf.AddScaleOp().Set(Gf.Vec3f(part.meters_per_native_unit))
        for group in part.groups:
            for index, (points, normals, uv, indices) in enumerate(_gltf_arrays(visual_root/group.geometry_resource)):
                mesh = UsdGeom.Mesh.Define(stage, parent+'/'+group.material+'_'+str(index))
                mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points.astype(np.float32)))
                mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(normals.astype(np.float32)))
                mesh.SetNormalsInterpolation('vertex')
                mesh.CreateFaceVertexCountsAttr([3]*(len(indices)//3))
                mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(indices.astype(np.int32)))
                mesh.CreateSubdivisionSchemeAttr('none')
                desc = next(m for m in appearance.materials if m.name == group.material)
                mesh.CreateDoubleSidedAttr(desc.double_sided)
                UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray, 'vertex').Set(Vt.Vec2fArray.FromNumpy(uv))
                UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(materials[group.material])
                if desc.alpha_mode == 'BLEND':
                    if part.name not in {f'{i:02d}_{n}_Button_VISUAL_UNCALIBRATED' for i,n in ((0,'A'),(1,'B'),(13,'X'),(15,'Y'))}:
                        raise ValueError('unreviewed BLEND geometry: selective shadow rule needs review')
                    # B1b no_shadow control: letters are on OPAQUE geometry.
                    UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('doNotCastShadows', Sdf.ValueTypeNames.Bool, 'constant').Set(True)
                    shadow_paths.append(str(mesh.GetPath()))
    contact_materials = {}
    for desc in physical.contact_materials:
        mat = UsdShade.Material.Define(stage, root+'/Looks/Contact_'+Tf.MakeValidIdentifier(desc.material_id))
        api = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
        api.CreateStaticFrictionAttr(float(_known(desc.static_friction, 'static_friction')))
        api.CreateDynamicFrictionAttr(float(_known(desc.dynamic_friction, 'dynamic_friction')))
        api.CreateRestitutionAttr(float(_known(desc.restitution, 'restitution')))
        for field in ('rolling_resistance_length', 'torsional_resistance_length'):
            if getattr(desc, field).value is not None:
                raise ValueError(f'{field}: no verified Isaac mapping in B1')
        contact_materials[desc.material_id] = mat
    if set(contact_materials) != {'controller'}:
        raise ValueError('expected the common controller contact material')
    hull_count = 0
    for instance in bind_collision_to_links(collision_sources, motion):
        override = collision_overrides.get(instance.component, {})
        if set(override) - {'collision_mode', 'sdf_options'}:
            raise ValueError('unsupported component collision override')
        mode = override.get('collision_mode', collision_mode)
        sdf_settings = override.get('sdf_options', sdf_options)
        if mode not in {'coacd', 'sdf'} or (mode == 'sdf' and not sdf_settings):
            raise ValueError('component requires coacd or explicit SDF cook settings')
        geometry = []
        if mode == 'coacd':
            geometry = [(h.vertices, h.faces) for h in iter_frozen_hulls(instance.source)]
        else:
            from ..backends.common.collision import _objects
            geometry = [(v, f) for path in instance.source.triangle_shells for _,v,f in _objects(instance.source.root/path)]
        for i, (vertices, faces) in enumerate(geometry):
            path = link_paths[instance.link]+'/Collision/'+Tf.MakeValidIdentifier(instance.component)+'_'+str(i)
            mesh = UsdGeom.Mesh.Define(stage, path)
            mesh.CreatePointsAttr([Gf.Vec3f(*point(instance.source_to_link, v)) for v in vertices])
            mesh.CreateFaceVertexCountsAttr([3]*len(faces))
            mesh.CreateFaceVertexIndicesAttr([v for f in faces for v in f])
            mesh.CreateSubdivisionSchemeAttr('none')
            mesh.CreatePurposeAttr('guide')
            UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
            if contact_offsets is not None:
                if set(contact_offsets) != {'contact_offset_m', 'rest_offset_m'}:
                    raise ValueError('contact_offsets needs both explicit length Parameters')
                values = {}
                for key, parameter in contact_offsets.items():
                    if parameter.unit != 'm':
                        raise ValueError('contact offsets must use metres')
                    values[key] = _known(parameter, key)
                if not 0 <= values['rest_offset_m'] < values['contact_offset_m']:
                    raise ValueError('require 0 <= rest offset < contact offset')
                policy = PhysxSchema.PhysxCollisionAPI.Apply(mesh.GetPrim())
                policy.CreateContactOffsetAttr(values['contact_offset_m'])
                policy.CreateRestOffsetAttr(values['rest_offset_m'])

            UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr('convexHull' if mode == 'coacd' else 'sdf')
            if mode == 'sdf':
                sdf = PhysxSchema.PhysxSDFMeshCollisionAPI.Apply(mesh.GetPrim())
                fields = {'resolution': sdf.CreateSdfResolutionAttr, 'subgrid_resolution': sdf.CreateSdfSubgridResolutionAttr,
                          'bits_per_pixel': sdf.CreateSdfBitsPerSubgridPixelAttr, 'margin': sdf.CreateSdfMarginAttr,
                          'narrow_band_thickness': sdf.CreateSdfNarrowBandThicknessAttr}
                settings = dict(sdf_settings)
                if 'spacing_m' in settings:
                    spacing = settings.pop('spacing_m')
                    if not isinstance(spacing,(int,float)) or spacing <= 0 or not math.isfinite(spacing) or 'resolution' in settings:
                        raise ValueError('spacing_m must be a positive candidate, exclusive with resolution')
                    extent = max(max(v[a] for v in vertices)-min(v[a] for v in vertices) for a in range(3))
                    settings['resolution'] = max(2, math.ceil(extent/spacing))
                if set(settings) != set(fields):
                    raise ValueError('SDF needs spacing_m or resolution plus subgrid_resolution/bits_per_pixel/margin/narrow_band_thickness')
                for key, method in fields.items():
                    method(settings[key])
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(contact_materials['controller'], materialPurpose='physics')
            hull_count += 1
    stage.GetRootLayer().Save()
    artifact = UsdArtifact(output, root, link_paths, joint_paths, root_mode, collision_mode)
    sidecar = {**asdict(artifact), 'usd_path': output.name, 'physical': asdict(physical),
               'collision_shapes': hull_count, 'shadow_disabled_meshes': shadow_paths,
               'shadow_basis': 'mb_ib1b: only the four BLEND domes; letters remain on OPAQUE geometry',
               'passive_damping_binding': 'USD PhysxJointAxisAPI per degree; Isaac Lab viscous_friction uses original SI; not drive damping',
               'unknown_backend_parameters': {'contact_offset_m': None, 'rest_offset_m': None,
                   'joint_load_dependent_friction_coefficient': None},
               'unknown_reason': 'No adopted Isaac-specific calibration; SDK effective values must be recorded by native validation.',
               'appearance_limitations': ['PreviewSurface metallic workflow is not full KHR dielectric F0 equivalence.'],
               'sdf_default_gate_passed': False,
               'sdf_candidate_settings': sdf_options,
               'component_collision_overrides': collision_overrides,
               'contact_offsets': {k: asdict(v) for k,v in contact_offsets.items()} if contact_offsets else None}
    output.with_suffix('.json').write_text(json.dumps(sidecar, indent=2)+'\n')
    return artifact
