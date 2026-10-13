"""Run P1 reproduction, protection calibration and candidate acceptance."""
import argparse
import json
from pathlib import Path
import numpy as np
import trimesh
import yaml
from .io import load_hulls
from .metrics import error_field


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['reproduce', 'baseline-control', 'fields', 'protect', 'analyze'])
    parser.add_argument('--config', default='configs/collision_opt.yaml')
    parser.add_argument('--hulls', nargs='+', help='candidate directory or component OBJ file list')
    parser.add_argument('--output', help='candidate analysis output directory')
    parser.add_argument('--reuse-shell-reproduction', action='store_true',
                        help='verify and reuse the existing identical shell samples')
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    if args.command == 'baseline-control':
        from .baseline_control import run
        return run(cfg)
    if args.command in ('fields', 'protect', 'analyze'):
        from .api import sources_for, read_candidates, fields_for, evaluate
        out = Path(args.output or cfg['output'])
        out.mkdir(parents=True, exist_ok=True)
        if args.command == 'fields':
            sources = sources_for(cfg)
            records = read_candidates(cfg['inputs']['hulls'], sources)
            results, _ = fields_for(records, sources, cfg, out, args.reuse_shell_reproduction)
            (out/'baseline_metrics.json').write_text(json.dumps(results, indent=2)+'\n')
            return 0
        from .protection import generate
        spaces, metadata = generate(cfg, out)
        if not metadata.get('gate_passed', False):
            print('Protection retention gate failed; see protection.json', flush=True)
            return 3
        from .intrusion import check_pair
        originals = read_candidates(cfg['inputs']['hulls'], sources_for(cfg))
        control = next(r for r in originals if r['link']=='controller_body' and r['shape_index']==59)
        hull = control['mesh'].copy(); hull.vertices *= 1000
        s = cfg['intrusion']
        metadata['positive_control'] = check_pair(hull, spaces['guide:combined'],
            cfg['protection']['numerical_tolerance_mm'], s['minimum_volume_mm3'], s['lp_tolerance_mm'])
        metadata['positive_control_approach'] = check_pair(hull, spaces['guide:approach'],
            cfg['protection']['numerical_tolerance_mm'], s['minimum_volume_mm3'], s['lp_tolerance_mm'])
        metadata['positive_control_passed'] = metadata['positive_control']['intrudes']
        metadata['reproduction_passed'] = json.loads((Path(cfg['output'])/'reproduction.json').read_text())['reproduction_passed']
        (out/'protection.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
        if not metadata['positive_control_passed']:
            print('Shape 59 Guide positive control FAILED', flush=True)
            return 4
        if args.command == 'protect':
            return 0
        baseline = json.loads((Path(cfg['output'])/'baseline_metrics.json').read_text())
        candidates = args.hulls or [cfg['inputs']['hulls']]
        candidates = candidates[0] if len(candidates)==1 and Path(candidates[0]).is_dir() else candidates
        result = evaluate(candidates,cfg,out,baseline=baseline,spaces=spaces,
            protection_metadata=metadata,reuse_shell=args.reuse_shell_reproduction)
        from .inspection_plots import render_inspection
        render_inspection(sources_for(cfg),read_candidates(candidates,sources_for(cfg)),
                          spaces,result,out/'figures')
        print(json.dumps({k:result[k] for k in ('passed','constraints')},indent=2),flush=True)
        return 0 if result['passed'] else 5
    out = Path(cfg['output'])
    out.mkdir(parents=True, exist_ok=True)
    component = cfg['reproduction']['component']
    source = trimesh.load(Path(cfg['inputs']['meshbase']) / f'{component}.obj',force='mesh')
    hulls = [h for _,h in load_hulls(Path(cfg['inputs']['hulls']) / f'{component}.obj')]
    e = cfg['error_field']
    summary, arrays = error_field(source,hulls,density=e['density_points_per_mm2'],
        source_seed=e['source_seed'],hull_seed=e['hull_seed'],
        coverage_tolerance_m=e['coverage_tolerance_mm']/1000,
        winding_inside_threshold=e['winding_inside_threshold'],hotspot_threshold_mm=e['hotspot_threshold_mm'])
    r = cfg['reproduction']
    summary['reproduction_passed'] = all(round(summary['outward'][key],r['reporting_decimals']) == r['expected_'+key]
                                          for key in ('max_mm','p95_mm'))
    summary['config'] = cfg
    np.savez_compressed(out / f'{component}_error_field.npz',**arrays)
    (out/'reproduction.json').write_text(json.dumps(summary,indent=2)+'\n')
    from .plots import error_projections
    error_projections(source, arrays, out/'figures')
    print(json.dumps({k:summary[k] for k in ('outward','reproduction_passed')},indent=2))
    return 0 if summary['reproduction_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
