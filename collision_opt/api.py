"""Checkout-only P2/P3 acceptance API. Meshes are global neutral coordinates, m.

evaluate accepts a directory of component OBJ files, a file list, or a mapping
component -> file list. Mapping preserves source-component attribution when
files are split/renamed. Same-link hulls may be attributed to multiple source
components; every component is checked against its unchanged source baseline.
Missing gates or unmatched cooking evidence never imply acceptance.
"""
import json
from pathlib import Path

import numpy as np
import trimesh

from .io import load_hulls
from .metrics import error_field, stats_mm, winding, sample


def sources_for(cfg):
    return {p.stem: trimesh.load(p, force='mesh', process=False)
            for p in sorted(Path(cfg['inputs']['meshbase']).glob('*.obj'))}


def read_candidates(value, components):
    if isinstance(value, (str, Path)):
        path = Path(value)
        value = sorted(path.glob('*.obj')) if path.is_dir() else [path]
    if not isinstance(value, dict):
        groups = {}
        for path in value:
            groups.setdefault(Path(path).stem, []).append(path)
    else:
        groups = {name: [paths] if isinstance(paths, (str, Path)) else paths
                  for name, paths in value.items()}
    if set(groups) != set(components):
        raise ValueError(f'Component attribution differs: missing={set(components)-set(groups)}, '
                         f'unknown={set(groups)-set(components)}')
    records, shape_offset = [], 0
    order = sorted(groups, key=lambda n: (n not in ('shell','shell_front_plate'),
                                         n == 'shell_front_plate', n))
    for name in order:
        pieces = [(p, label, mesh) for p in groups[name] for label, mesh in load_hulls(p)]
        if not pieces:
            raise ValueError(f'No hulls attributed to {name}')
        link = 'controller_body' if name in ('shell','shell_front_plate') else name
        for i, (path, label, mesh) in enumerate(pieces):
            records.append(dict(component=name, hull_index=i, hull_name=label, link=link,
                shape_index=shape_offset+i if link == 'controller_body' else i,
                file=str(path), mesh=mesh))
        if link == 'controller_body':
            shape_offset += len(pieces)
    return records


def fields_for(records, sources, cfg, output=None, reuse_shell=False):
    results, arrays = {}, {}
    settings = cfg['error_field']
    output = Path(output) if output else None
    if output:
        (output/'fields').mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        hulls = [r['mesh'] for r in records if r['component']==name]
        cached = False
        if reuse_shell and name == cfg['reproduction']['component']:
            root = Path(cfg['output'])
            summary = json.loads((root/'reproduction.json').read_text())
            data = dict(np.load(root/f'{name}_error_field.npz'))
            # Validate sampled inputs/parameters instead of a hash or unchecked cache.
            cached = all(settings.get(k)==v for k,v in summary['config']['error_field'].items()) and np.array_equal(
                data['source'], sample(source,settings['source_seed'],settings['density_points_per_mm2']))
            if cached:
                pieces = [sample(h,settings['hull_seed']+i,settings['density_points_per_mm2'])
                          for i,h in enumerate(hulls)]
                cached = np.array_equal(data['points'],np.concatenate(pieces))
        if not cached:
            summary, data = error_field(source,hulls,
                density=settings['density_points_per_mm2'],source_seed=settings['source_seed'],
                hull_seed=settings['hull_seed'],coverage_tolerance_m=settings['coverage_tolerance_mm']/1000,
                winding_inside_threshold=settings['winding_inside_threshold'],
                hotspot_threshold_mm=settings['hotspot_threshold_mm'])
        summary = {k:v for k,v in summary.items() if k not in ('config','reproduction_passed')}
        external=data['outward_mm'][data['winding']<=settings['winding_inside_threshold']]
        bins=settings['distribution_bins_mm']
        summary['outward_distribution']=dict(bin_edges_mm=bins,
            counts=np.histogram(external,bins=bins)[0].tolist(),
            above_last_bin=int((external>bins[-1]).sum()))
        results[name], arrays[name] = summary, data
        if output:
            np.savez_compressed(output/'fields'/f'{name}.npz',**data)
            (output/'fields'/f'{name}.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(f'field {name}: {summary["outward"]}; uncovered={summary["source_uncovered_samples"]}',flush=True)
    return results, arrays


def opening_metrics(sources, fields, cfg, protection_metadata=None):
    """Historical 8.7 ROI, now reported for every control; neutral pose only."""
    settings = cfg['openings']
    field = fields['shell']
    selected = field['outward_mm'] > settings['hotspot_threshold_mm']
    points = field['points'][selected]
    values = field['outward_mm'][selected]
    hidden = np.zeros(len(points),dtype=bool)
    # Historical scope includes front plate as an occluder.
    for name, mesh in sources.items():
        if name == 'shell':
            continue
        lo, hi = mesh.bounds
        ids = np.flatnonzero(np.all(points >= lo-1e-4,axis=1)&np.all(points <= hi+1e-4,axis=1))
        hidden[ids[winding(points[ids],mesh.triangles)>.5]] = True
    visible, outward = points[~hidden], values[~hidden]
    rows = []
    for name, mesh in sources.items():
        if name in cfg['baseline_control']['shell_components']:
            continue
        lo, hi = mesh.bounds*1000
        xy = visible[:,:2]*1000
        mask = np.all(xy >= lo[:2]-settings['xy_margin_mm'],axis=1)&np.all(
            xy <= hi[:2]+settings['xy_margin_mm'],axis=1)&(
            visible[:,2]*1000 > settings['minimum_z_mm'])
        rows.append(dict(control=name,**stats_mm(outward[mask])))
    directional=[]
    if protection_metadata is not None:
        from .protection import basis
        all_external=field['winding']<=cfg['error_field']['winding_inside_threshold']
        full_points=field['points'][all_external]
        full_values=field['outward_mm'][all_external]
        full_hidden=np.zeros(len(full_points),dtype=bool)
        for name,mesh in sources.items():
            if name=='shell':continue
            lo,hi=mesh.bounds
            ids=np.flatnonzero(np.all(full_points>=lo-1e-4,axis=1)&np.all(full_points<=hi+1e-4,axis=1))
            full_hidden[ids[winding(full_points[ids],mesh.triangles)>.5]]=True
        full_points,full_values=full_points[~full_hidden]*1000,full_values[~full_hidden]
        for record in protection_metadata['controls']:
            name=record['control'];frame=basis(record['approach']['direction_outward'])
            control=sources[name].vertices*1000@frame;projected=full_points@frame
            low,high=control.min(axis=0),control.max(axis=0)
            sel=np.all(projected[:,:2]>=low[:2]-settings['xy_margin_mm'],axis=1)&np.all(
                projected[:,:2]<=high[:2]+settings['xy_margin_mm'],axis=1)&(
                projected[:,2]>=low[2]-settings['xy_margin_mm'])&(
                projected[:,2]<=high[2]+settings['xy_margin_mm'])
            directional.append(dict(control=name,**stats_mm(full_values[sel]),
                hotspots=stats_mm(full_values[sel&(full_values>settings['hotspot_threshold_mm'])]),
                direction_outward=frame[:,2].tolist()))
    return dict(method='8.7: outside controls/plate, outward>threshold, control XY AABB + margin, z>minimum; overlapping ROIs',
                scope='neutral geometry; includes narrow gaps; top-facing ROI is inapplicable to some rear controls',
                hotspots=len(points), hidden_hotspots=int(hidden.sum()), openings=rows,
                directional_openings=directional,
                directional_method='all external shell samples outside controls/plate; control AABB in chosen approach frame expanded by configured margin on all axes; overlapping ROIs')


def decide(metrics, baseline, intrusion, protection_ok, calibration_ok,
           cooking, vertex_limit=255, metric_tolerance_mm=1e-6):
    constraints = {}
    constraints['accuracy'] = all(name in baseline and all(
        value['outward'][key] <= baseline[name]['outward'][key]+metric_tolerance_mm
        for key in ('max_mm','p95_mm')) for name,value in metrics.items())
    constraints['coverage_sampled'] = all(v['source_uncovered_samples']==0 for v in metrics.values())
    constraints['protection'] = protection_ok and not any(r['intrudes'] for r in intrusion)
    constraints['calibration'] = calibration_ok
    constraints['input_vertex_limit'] = all(h['vertices']<=vertex_limit for v in metrics.values() for h in v['hulls'])
    constraints['cooking'] = (cooking is not None and cooking.get('matched_input',False)
        and all(r['cooked_vertices']<=vertex_limit for r in cooking['hulls']))
    return dict(passed=all(constraints.values()), constraints=constraints,
                coverage_claim='sampled containment only',
                verdict='pass' if all(constraints.values()) else 'fail')


def match_cooking(records, evidence_path):
    """Evidence includes exact global input arrays; changed candidates need recooking."""
    path=Path(evidence_path)
    inputs=path.with_name('cooking_inputs_global.npz')
    if not path.exists() or not inputs.exists():
        return None
    evidence=json.loads(path.read_text())
    arrays=np.load(inputs)
    if len(evidence['hulls'])!=len(records):
        return dict(evidence,matched_input=False)
    by_key={(r['component'],r['hull_index']):r for r in evidence['hulls']}
    matched=True
    for r in records:
        key=(r['component'],r['hull_index']);prefix=f'{key[0]}_{key[1]}'
        if key not in by_key or prefix+'_v' not in arrays:
            matched=False;break
        if not np.array_equal(r['mesh'].vertices,arrays[prefix+'_v']) or not np.array_equal(
                r['mesh'].faces,arrays[prefix+'_f']):
            matched=False;break
    return dict(evidence,matched_input=matched)


def evaluate(hulls, config, output=None, *, baseline, spaces,
             protection_metadata, cooking=None, reuse_shell=False):
    """Stable API: candidate directory/list/mapping -> JSON-compatible metrics/verdict.

    Protection spaces and baseline are explicit, reusable calibrated inputs.
    They must be generated from the fixed original meshbase/motion contract.
    `spaces` are mm; candidate OBJ/source meshes are m.
    """
    from .intrusion import inspect_body
    from .symmetry import classify
    cfg=config
    sources=sources_for(cfg)
    records=read_candidates(hulls,sources)
    output=Path(output) if output else None
    if output:
        output.mkdir(parents=True,exist_ok=True)
    if cooking is None:
        cooking=match_cooking(records,cfg['cooking']['evidence'])
    if cooking and cooking.get('matched_input'):
        shape_ids={(r['component'],r['hull_index']):r['shape_index'] for r in cooking['hulls']}
        for r in records:
            r['shape_index']=shape_ids[(r['component'],r['hull_index'])]
    metrics, fields=fields_for(records,sources,cfg,output,reuse_shell)
    intrusions=inspect_body(records,spaces,cfg)
    symmetry=classify(records,sources,cfg['symmetry'])
    calibration_ok=bool(protection_metadata.get('positive_control_passed',False)) and (
        bool(protection_metadata.get('reproduction_passed',False)))
    verdict=decide(metrics,baseline,intrusions,protection_metadata.get('gate_passed',False),
                   calibration_ok,cooking,cfg['cooking']['vertex_limit'],
                   cfg['error_field']['comparison_tolerance_mm'])
    by_sym={(r['component'],r['hull_index']):r for r in symmetry}
    by_cook={(r['component'],r['hull_index']):r for r in cooking['hulls']} if cooking and cooking.get('matched_input') else {}
    rows=[]
    for r in records:
        key=(r['component'],r['hull_index'])
        error=metrics[r['component']]['hulls'][r['hull_index']]
        hits=[i for i in intrusions if (i['component'],i['hull_index'])==key and i['intrudes']]
        rows.append({k:v for k,v in r.items() if k!='mesh'} | dict(error=error,
            symmetry=by_sym[key],cooking=by_cook.get(key),intrusions=hits,
            intrusion_checked=r['link']=='controller_body'))
    result=dict(schema_version=1,**verdict,units=dict(length='mm',volume='mm^3',input_coordinates='global neutral m'),
        components=metrics,hulls=rows,intrusion_pairs=intrusions,
        openings=opening_metrics(sources,fields,cfg,protection_metadata),protection=protection_metadata,
        cooking_matched_input=bool(cooking and cooking.get('matched_input')),config=cfg)
    if output:
        (output/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def analyze(hulls, config, output=None):
    """One-call public entry point: directory/file list -> metrics and verdict.

    Baseline and spaces are computed from the fixed original sources, and the
    original body shape 59 calibrates the checker, even for repaired candidates.
    Calibration failure stops before candidate inspection with a failed verdict.
    """
    import yaml
    from .protection import generate
    from .intrusion import check_pair
    cfg=yaml.safe_load(Path(config).read_text()) if isinstance(config,(str,Path)) else config
    output=Path(output or cfg['output'])
    originals=read_candidates(cfg['inputs']['hulls'],sources_for(cfg))
    baseline,_=fields_for(originals,sources_for(cfg),cfg,output,reuse_shell=True)
    r=cfg['reproduction']
    reproduced=all(round(baseline[r['component']]['outward'][key],r['reporting_decimals'])==r['expected_'+key]
                   for key in ('max_mm','p95_mm'))
    if not reproduced:
        return dict(schema_version=1,passed=False,verdict='fail',stop_reason='baseline reproduction failed',components=baseline)
    spaces,metadata=generate(cfg,output)
    if not metadata['gate_passed']:
        return dict(schema_version=1,passed=False,verdict='fail',stop_reason='protection retention failed',protection=metadata)
    evidence=match_cooking(originals,cfg['cooking']['evidence'])
    if not evidence or not evidence['matched_input']:
        return dict(schema_version=1,passed=False,verdict='fail',stop_reason='shape-59 native index calibration evidence missing')
    native=next(r for r in evidence['hulls'] if r['link']=='controller_body' and r['shape_index']==59)
    original=next(r for r in originals if r['component']==native['component'] and r['hull_index']==native['hull_index'])
    mesh=original['mesh'].copy();mesh.vertices*=1000
    s=cfg['intrusion']
    control=check_pair(mesh,spaces['guide:combined'],cfg['protection']['numerical_tolerance_mm'],
                       s['minimum_volume_mm3'],s['lp_tolerance_mm'])
    metadata.update(positive_control=control,positive_control_passed=control['intrudes'],reproduction_passed=reproduced)
    if not control['intrudes']:
        return dict(schema_version=1,passed=False,verdict='fail',stop_reason='shape-59 Guide positive control failed',protection=metadata)
    result=evaluate(hulls,cfg,output,baseline=baseline,spaces=spaces,protection_metadata=metadata)
    from .inspection_plots import render_inspection
    result['figures']=render_inspection(sources_for(cfg),read_candidates(hulls,sources_for(cfg)),
                                       spaces,result,output/'figures')
    (output/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
