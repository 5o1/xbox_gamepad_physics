"""Package only approved inputs; never run resource builders or CoACD."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from xbox_gamepad_physics.resources import package_version,release_url


def input_files(root: Path = ROOT) -> list[tuple[Path,str]]:
    asset='assets/xbox_one_s/'
    names=[asset+'README.md',asset+'approved_render.json',
           asset+'source/xbox_one_s_controllergamepad_animated.glb',
           asset+'visual/Xbox_One_S_BatonyRobson_STATIC_VISUAL_UNCALIBRATED.glb',
           asset+'visual/inventory.json',asset+'collision_meshbase/README.md',
           asset+'collision_meshbase/manifest.json',asset+'collision_coacd/README.md',
           asset+'collision_coacd/manifest.json',asset+'render/README.md',
           asset+'render/Xbox_One_S_approved_cycles.blend',
           asset+'render/boiler_room_vertical_fov35_strength_1p0.png','LICENSE']
    base=json.loads((root/asset/'collision_meshbase/manifest.json').read_text())
    names += [asset+'collision_meshbase/'+name for name in base['meshes'].values()]
    hulls=json.loads((root/asset/'collision_coacd/manifest.json').read_text())
    names += [asset+'collision_coacd/'+item['file'] for item in hulls['components'].values()]
    files=[(root/name,name) for name in names]
    files.append((root/asset/'THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md'))
    for path,name in files:
        if not path.is_file():raise FileNotFoundError(f'missing approved input: {name}')
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('input leaves repository')
    return sorted(files,key=lambda pair:pair[1])


def package(output: Path = ROOT/'dist') -> Path:
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    archive=output/f'xbox_gamepad_physics-resources-{package_version()}.zip'
    files=input_files()
    with zipfile.ZipFile(archive.with_suffix('.zip.tmp'),'w',compression=zipfile.ZIP_DEFLATED) as z:
        for path,name in files:z.write(path,name)
    archive.with_suffix('.zip.tmp').replace(archive)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    lock={'kind':'inputs','format_version':1,'version':package_version(),'url':release_url(),
          'sha256':digest,'files':[name for _,name in files]}
    for path in (output/'_resource_lock.json',ROOT/'src/xbox_gamepad_physics/_resource_lock.json'):
        path.write_text(json.dumps(lock,indent=2)+'\n')
    (output/'SHA256SUMS').write_text(f'{digest}  {archive.name}\n')
    print(json.dumps({'archive':str(archive),'files':len(files),'input_bytes':sum(p.stat().st_size for p,_ in files),'zip_bytes':archive.stat().st_size}))
    return archive


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'dist')
    package(p.parse_args().output.resolve())

if __name__=='__main__':main()
