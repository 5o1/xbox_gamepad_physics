"""Automatic free-space protection geometry, in global millimetres.

The original body B is removed after constructing each geometric primitive.
No collision hull is changed. Boolean operations use installed manifold3d.
"""
from pathlib import Path
import itertools
import json
import math
import time
import numpy as np
import trimesh
import manifold3d as m
from .baseline_control import solid, mesh_of

PRIMARY_DOCS = [
    "https://manifoldcad.org/docs/html/classmanifold_1_1_manifold.html",
    "https://manifoldcad.org/docs/html/classmanifold_1_1_cross_section.html",
]


def union(items):
    items = list(items)
    result=m.Manifold.batch_boolean(items, m.OpType.Add) if items else m.Manifold()
    if result.status()!=m.Error.NoError:
        raise ValueError(f'Protection Boolean failed: {result.status()}')
    return result


def basis(direction):
    """Columns form an orthonormal frame whose z axis is outward direction."""
    z = np.asarray(direction, float); z /= np.linalg.norm(z)
    seed = np.eye(3)[int(np.argmin(abs(z)))]
    x = np.cross(seed, z); x /= np.linalg.norm(x)
    return np.column_stack([x, np.cross(z, x), z])


def prism(triangle, direction, length):
    """Closed swept triangle, with exact (nonflat) starting surface."""
    vertices = np.vstack([triangle, triangle + np.asarray(direction) * length])
    return solid(trimesh.convex.convex_hull(vertices))


def approach(mesh, direction, settings, body=None):
    """Union outward-facing face prisms, clipped to inset projected footprint.

    The start is the actual sloping triangle, rather than an arbitrary single
    height plane. No handpicked face or component-dependent threshold is used.
    """
    frame = basis(direction)
    normals = mesh.face_normals @ frame[:, 2]
    selected = normals >= math.cos(math.radians(settings['top_normal_max_angle_deg']))
    # Keep only the visible directional envelope; hidden stem shoulders are
    # not the cap top. Ray casts are on original closed control geometry.
    control_solid = solid(mesh)
    extent = np.ptp(mesh.vertices, axis=0).sum() + 1
    if body is not None:
        shell=mesh_of(body)
        extent=float(np.maximum(mesh.bounds[1],shell.bounds[1]).sum()-
                     np.minimum(mesh.bounds[0],shell.bounds[0]).sum()+1)
    for index in np.flatnonzero(selected):
        center = mesh.triangles[index].mean(axis=0)
        start = center + frame[:, 2] * 1e-5
        if control_solid.ray_cast(start, start + frame[:, 2]*extent):
            selected[index] = False
        if body is not None and body.ray_cast(start,start+frame[:,2]*extent):
            selected[index]=False
    triangles = mesh.triangles[selected]
    if not len(triangles):
        return m.Manifold(),m.Manifold(),dict(direction_outward=frame[:,2].tolist(),
            selected_top_faces=0,projected_top_area_mm2=0.,inset_area_mm2=0.,
            top_rule='no externally visible facing surface along this direction')
    projected = [triangle @ frame[:, :2] for triangle in triangles]
    cross = m.CrossSection.batch_boolean(
        [m.CrossSection([p]) for p in projected], m.OpType.Add)
    inset = cross.offset(-settings['cross_section_inset_mm'], m.JoinType.Miter)
    if inset.is_empty():
        raise ValueError('Top-face inset is empty')
    local = mesh.vertices @ frame
    low, high = local[:, 2].min() - 1, local[:, 2].max() + settings['approach_length_mm'] + 1
    clip = inset.extrude(high-low).translate([0, 0, low]).transform(
        np.column_stack([frame, np.zeros(3)]))
    length = settings['approach_length_mm']
    channel = union(prism(t, frame[:, 2], length) for t in triangles) ^ clip
    near = union(prism(t, frame[:, 2], settings['near_top_depth_mm'])
                 for t in triangles) ^ clip
    return channel, near, {
        'direction_outward': frame[:, 2].tolist(),
        'selected_top_faces': int(selected.sum()),
        'projected_top_area_mm2': float(cross.area()),
        'inset_area_mm2': float(inset.area()),
        'top_rule': 'normal dot direction >= cos(config angle), face-centroid ray unobstructed by original control and body to outside assembly AABB; actual triangle start heights; projected footprint inset clips face prisms',
    }


def joint_chain(motion, name):
    child = {j['child']: j for j in motion['joints']}
    chain = []
    while name != 'controller_body':
        joint = child[name]; chain.append(joint); name = joint['parent']
    return list(reversed(chain))


def direction_for(mesh, chain):
    """Approach opposite inward movement; sticks/dpad use neutral cap +z."""
    terminal = chain[-1]
    if terminal['type'] == 'prismatic':
        return -np.array(terminal['axis']), 'opposite terminal prismatic axis'
    if len(chain) > 1:
        return np.array([0., 0., 1.]), 'two-axis rocking pad: neutral +z face; radial motion has no single press axis'
    velocity = np.cross(terminal['axis'], mesh.center_mass - np.array(terminal['origin'])*1000)
    return -velocity / np.linalg.norm(velocity), 'opposite neutral centroid instantaneous hinge velocity axis cross (centroid-pivot)'


def translation_sweep(control, direction, distance):
    """Exact polyhedral sweep along one straight segment, rather than poses."""
    if distance==0:
        return control
    mesh=mesh_of(control)
    facing=mesh.face_normals@direction>1e-10
    return union([control]+[prism(t,direction,distance) for t in mesh.triangles[facing]])


def chain_transform(chain, values):
    transform=np.eye(4)
    for joint in chain:
        origin=trimesh.transformations.euler_matrix(*joint.get('rpy',(0,0,0)))
        origin[:3,3]=np.array(joint['origin'])*1000
        q=values.get(joint['name'],0.)
        motion=np.eye(4)
        if joint['type']=='prismatic':
            motion[:3,3]=np.array(joint['axis'])*q*1000
        elif joint['type']=='revolute':
            motion=trimesh.transformations.rotation_matrix(q,joint['axis'])
        transform=transform@origin@motion
    return transform


def sweep(mesh, chain, motion, settings):
    """All radial disk interiors plus exact click segment; bounded outer sweep."""
    control=solid(mesh)
    translations=[j for j in chain if j['type']=='prismatic']
    travel=0.
    for joint in translations:
        # Current contract has a terminal prismatic axis in the neutral frame.
        frame=chain_transform(chain[:chain.index(joint)+1],{})
        axis=frame[:3,:3]@joint['axis']
        low,high=joint['lower']*1000,joint['upper']*1000
        control=control.translate(axis*low)
        control=translation_sweep(control,axis,high-low)
        travel+=high-low
    revolutes=[j for j in chain if j['type']=='revolute']
    if not revolutes:
        return control,control,dict(poses=1,translation_exact=True,
            discretization_error_bound_mm=0.,conservative_extra_distance_bound_mm=0.)
    neutral=chain_transform(chain,{})
    inverse=np.linalg.inv(neutral)
    step=math.radians(settings['sweep_rotation_step_deg'])
    if len(revolutes)==2:
        ids={j['name'] for j in revolutes}
        radial=next(c for c in motion['joint_space_constraints'] if c['type']=='radial' and set(c['joint_ids'])==ids)
        radius=radial['radius'];nr=max(1,math.ceil(radius/step))
        nphi=max(4,math.ceil(360/settings['radial_azimuth_step_deg']))
        delta_r=radius/nr;delta_phi=2*math.pi/nphi
        coordinates=[(0.,0.)]+[(r*math.cos(phi),r*math.sin(phi))
            for r in np.linspace(0,radius,nr+1)[1:]
            for phi in np.arange(nphi)*delta_phi]
        values=[dict(zip([j['name'] for j in revolutes],q)) for q in coordinates]
        # Two current axes are co-located. Each angular derivative's lever arm
        # is bounded by the same R even after the other axis rotates.
        pivot=chain_transform(chain[:1],{})[:3,3]
        for joint in revolutes[1:]:
            if np.linalg.norm(joint['origin'])>1e-12:
                raise ValueError('Radial sweep bound requires co-located pivots')
        lever=float(np.linalg.norm(mesh.vertices-pivot,axis=1).max()+travel)
        parameter_bound=delta_r/2+2*radius*math.sin(delta_phi/4)
        error=lever*math.sqrt(2)*parameter_bound
        info=dict(radial_radius_rad=radius,radial_intervals=nr,azimuth_samples=nphi,
                  radial_step_rad=delta_r,azimuth_step_rad=delta_phi,
                  parameter_disk_cover_radius_rad=parameter_bound,
                  lever_bound_mm=lever,
                  bound_derivation='R * sqrt(2) * (dr/2 + 2*r*sin(dphi/4)); every radial disk point has a nearest sampled radius/azimuth')
    elif len(revolutes)==1:
        joint=revolutes[0];count=max(1,math.ceil((joint['upper']-joint['lower'])/step))
        q=np.linspace(joint['lower'],joint['upper'],count+1)
        values=[{joint['name']:x} for x in q]
        pivot=chain_transform(chain[:chain.index(joint)+1],{})[:3,3]
        lever=float(np.linalg.norm(mesh.vertices-pivot,axis=1).max()+travel)
        actual_step=(joint['upper']-joint['lower'])/count
        error=2*lever*math.sin(actual_step/4)
        info=dict(angular_step_rad=actual_step,lever_bound_mm=lever,
                  bound_derivation='2*R*sin(dtheta/4), nearest endpoint pose is at most dtheta/2 away')
    else:
        raise ValueError('Unsupported rotational joint chain')
    # A cube [-epsilon,+epsilon]^3 contains a Euclidean epsilon ball. Dilation
    # before rotation remains an outer bound; its corners can add sqrt(3)*eps.
    padding=m.Manifold.cube([2*error]*3,center=True)
    padded=control.minkowski_sum(padding)
    if padded.status()!=m.Error.NoError:
        raise ValueError(f'Sweep dilation failed: {padded.status()}')
    sampled=[];outer=[]
    for q in values:
        transform=chain_transform(chain,q)@inverse
        sampled.append(control.transform(transform[:3,:]))
        outer.append(padded.transform(transform[:3,:]))
    return union(sampled),union(outer),dict(info,poses=len(values),translation_exact=True,
        discretization_error_bound_mm=error,
        conservative_extra_distance_bound_mm=math.sqrt(3)*error,
        padding='Minkowski cube enclosing the discretization-error ball')


def vertical_roof(body):
    """Filled solid below body's +Z directional envelope and its XY footprint."""
    mesh=mesh_of(body);length=np.ptp(mesh.vertices[:,2])+1
    facing=mesh.face_normals[:,2]>1e-10
    roof=union([body]+[prism(t,[0,0,-1],length) for t in mesh.triangles[facing]])
    footprints=m.CrossSection.batch_boolean([m.CrossSection([t[:,:2]])
        for t in mesh.triangles[facing]],m.OpType.Add)
    return roof,footprints


def cap_gap(control, body, roof, footprint, settings):
    """Space below downward-facing stick brim and above the body roof.

    Vertical shadows follow each actual underside triangle. Removing the
    control excludes its stem; removing the filled body roof excludes everything
    below the first body surface, including buried bottom faces of the stem.
    This polyhedral construction is exact; no height slices are used.
    """
    mesh=mesh_of(control);body_mesh=mesh_of(body)
    facing=mesh.face_normals[:,2]<=-math.cos(math.radians(settings['cap_underside_max_angle_deg']))
    low=body_mesh.bounds[0,2];high=mesh.bounds[1,2]
    columns=union(prism(t,[0,0,-1],high-low+1) for t in mesh.triangles[facing])
    clip=footprint.extrude(high-low).translate([0,0,low])
    raw=(columns^clip)-roof-control
    parts=raw.decompose()
    removed=[part for part in parts if part.volume()<=settings['minimum_volume_mm3']]
    raw=union(part for part in parts if part.volume()>settings['minimum_volume_mm3'])
    return raw,dict(underside_faces=int(facing.sum()),
        rule='downward-normal brim-face vertical shadow, within body XY footprint, above filled +Z body roof, minus neutral control',
        removed_numerical_components=len(removed),
        removed_absolute_volume_mm3=float(sum(abs(part.volume()) for part in removed)),
        component_volume_tolerance_mm3=settings['minimum_volume_mm3'],
        discretization_error_bound_mm=0.)


def generate(cfg, output=None):
    """Return (space meshes in mm, metadata); preserve failed gates as evidence."""
    started = time.perf_counter()
    settings = cfg['protection']
    output = Path(output or cfg['output']); destination = output / 'protection'
    destination.mkdir(parents=True, exist_ok=True)
    originals = {}
    for path in sorted(Path(cfg['inputs']['meshbase']).glob('*.obj')):
        mesh = trimesh.load(path, force='mesh', process=False); mesh.vertices *= 1000
        originals[path.stem] = mesh
    body = union(solid(originals[n]) for n in cfg['baseline_control']['shell_components'])
    motion = json.loads(Path(cfg['inputs']['motion_contract']).read_text())
    spaces, records, failures = {}, [], []
    raw_channels={}
    for name, mesh in originals.items():
        if name in cfg['baseline_control']['shell_components']: continue
        chain = joint_chain(motion, name)
        direction, rule = direction_for(mesh, chain)
        candidates=[]
        for sign in (1,-1):
            candidate_direction=sign*direction
            channel,near,info=approach(mesh,candidate_direction,settings,body)
            free,near_free=channel-body,near-body
            fraction=float(free.volume()/channel.volume()) if channel.volume()>0 else 0.
            near_fraction=float(near_free.volume()/near.volume()) if near.volume()>0 else 0.
            # Near-prism volume / thickness is projected externally accessible
            # top area. This incorporates the requested inset and sloping tops.
            score=info['projected_top_area_mm2']
            candidates.append(dict(sign=sign,channel=channel,near=near,info=info,
                record=dict(direction_outward=candidate_direction.tolist(),
                    external_accessible_area_mm2=score,retained_fraction=fraction,
                    near_top_free_fraction=near_fraction)))
        chosen=max(candidates,key=lambda c:c['record']['external_accessible_area_mm2'])
        channel,near,info=chosen['channel'],chosen['near'],chosen['info']
        free, near_free = channel-body, near-body
        volume, near_volume = channel.volume(), near.volume()
        record = {'control': name, 'approach': {
            **info, 'direction_rule': rule+'; compare both signs by exterior accessible top area',
            'direction_candidates':[c['record'] for c in candidates],
            'reversed_from_motion_rule':chosen['sign']==-1,
            'raw_volume_mm3': volume, 'protected_volume_mm3': free.volume(),
            'retained_fraction': free.volume()/volume if volume>0 else 0.,
            'near_top_raw_volume_mm3': near_volume,
            'near_top_free_volume_mm3': near_free.volume(),
            'near_top_free_fraction': near_free.volume()/near_volume if near_volume>0 else 0.,
        }}
        if (volume<=0 or near_volume<=0 or free.volume()/volume < settings['approach_min_free_fraction'] or
                near_free.volume()/near_volume < settings['near_top_min_free_fraction']):
            failures.append(name)
        for kind, value in [('approach',free),('approach_raw',channel),('approach_near_top',near_free)]:
            key = name+':'+kind; result=mesh_of(value); spaces[key]=result
            result.export(destination / (key.replace(':','__')+'.obj'))
        records.append(record)
        raw_channels[name]=channel
        print(json.dumps(record), flush=True)
    # Stop before swept-volume processing if ANY chosen approach is empty.
    if not failures:
        roof,footprint=vertical_roof(body)
        for record in records:
            name=record['control'];mesh=originals[name]
            sampled,outer,info=sweep(mesh,joint_chain(motion,name),motion,settings)
            record['sweep']=dict(info,sampled_volume_mm3=float(sampled.volume()),
                raw_volume_mm3=float(outer.volume()),protected_volume_mm3=float((outer-body).volume()),
                retained_fraction=float((outer-body).volume()/outer.volume()))
            gap=m.Manifold()
            if name.endswith('_stick'):
                gap,gap_info=cap_gap(solid(mesh),body,roof,footprint,settings)
                record['cap_gap']=dict(gap_info,raw_volume_mm3=float(gap.volume()),
                    protected_volume_mm3=float((gap-body).volume()),
                    retained_fraction=float((gap-body).volume()/gap.volume()) if gap.volume()>0 else 0.)
            combined=union([outer,raw_channels[name],gap])
            free=combined-body
            record['combined']=dict(raw_volume_mm3=float(combined.volume()),
                protected_volume_mm3=float(free.volume()),retained_fraction=float(free.volume()/combined.volume()))
            sampled_combined=union([sampled,raw_channels[name],gap])-body
            for kind,value in [('sweep',outer-body),('sweep_sampled',sampled-body),
                    ('cap_gap',gap-body),('combined',free),('combined_sampled',sampled_combined)]:
                if kind=='cap_gap' and not name.endswith('_stick'):continue
                result=mesh_of(value);key=name+':'+kind;spaces[key]=result
                result.export(destination/(key.replace(':','__')+'.obj'))
            print(f'protection sweep {name}: poses={info["poses"]}, error_bound={info["discretization_error_bound_mm"]:.6f} mm',flush=True)
    metadata = {'units': {'length':'mm','volume':'mm^3'},
        'definition':'P=(sweep union approach union cap_gap)-B; B=original shell union front plate',
        'controls':records, 'protection_gate_passed':not failures,'gate_passed':not failures,
        'failed_approach_controls':failures, 'primary_docs':PRIMARY_DOCS,
        'elapsed_seconds':time.perf_counter()-started,
        'scope':'bounded continuous-motion outer envelope; direction and near-top retention gates',
        'directions_reversed':[r['control'] for r in records if r['approach']['reversed_from_motion_rule']],
        'config':settings}
    (output/'protection.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    return spaces, metadata
