"""Export actual recorded canonical states using the video's sample selection.

The existing project overlay consumes these frames unchanged. No signals are
derived from button names, video colors or probe targets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xbox_gamepad_physics.state import GamepadDeviceId, TENSOR_LAYOUT_ID


def export_overlay(trace_root, review_directory):
    trace_root, review_directory = Path(trace_root), Path(review_directory)
    manifest = json.loads((review_directory/'video_manifest.json').read_text())
    output = review_directory/'signals'
    output.mkdir(exist_ok=True)
    traces = {}
    combined = []
    exported = []
    variants = [('', manifest)]
    slow = review_directory/'slow/video_manifest.json'
    if slow.is_file():
        variants.append(('slow_', json.loads(slow.read_text())))
    for prefix, variant in variants:
        for item in variant['cases']:
            name = item['case']
            if name not in traces:
                with (trace_root/name/'trace.jsonl').open() as stream:
                    traces[name] = [json.loads(line) for line in stream]
            rows = traces[name]
            frames = []
            indices = []
            for index in range(item['frames']):
                # Match render_contact_replay.py, including Python tie rounding.
                sample_index = min(len(rows)-1, round(index*variant['playback_speed']/(variant['fps']*.004)))
                sample = rows[sample_index]
                frame = dict(sample['canonical_state'])
                # Earlier archives already contain all values and masks, but
                # predate these two identity fields. Do not re-encode values.
                frame.setdefault('layout_id', TENSOR_LAYOUT_ID)
                frame.setdefault('device_id', int(GamepadDeviceId.XBOX_ONE_S))
                frame['events'] = sample['probe']['events']
                frame['telemetry'] = {'phase':sample['probe']['phase'], 'frame_index':sample['step']}
                frame['case'] = name
                frames.append(frame)
                indices.append(sample_index)
            path = output/(prefix+item['video'].replace('.mp4','.json'))
            path.write_text(json.dumps({'fps':variant['fps'],'frames':frames},separators=(',',':'))+'\n')
            exported.append({'case':name,'video':('slow/' if prefix else '')+item['video'],
                             'signals':str(path.relative_to(review_directory)), 'frames':len(frames),
                             'source_samples':len(rows),'source_trace':str(trace_root/name/'trace.jsonl'),
                             'source_indices':indices})
            if not prefix:
                combined.extend(frames)
    (output/'00_all_26.json').write_text(json.dumps({'fps':manifest['fps'],'frames':combined},separators=(',',':'))+'\n')
    result = {'source':'Recorded canonical_state; values/masks are copied without remapping.',
              'compilation_frames':len(combined),'videos':exported}
    (output/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--traces', type=Path, required=True, help='Press results directory with per-case trace.jsonl files.')
    parser.add_argument('--directory', type=Path, required=True, help='Existing video review directory.')
    args = parser.parse_args()
    result = export_overlay(args.traces, args.directory)
    print(f"Exported {len(result['videos'])} video-aligned canonical traces")


if __name__ == '__main__':
    main()
