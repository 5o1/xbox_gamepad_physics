"""Compile one read-only native accumulator probe with version-pinned headers."""
import argparse
from pathlib import Path
import subprocess
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
includes=[a.sdk/'physx/include']
includes += sorted(p for p in (a.sdk/'physx').rglob('*') if p.is_dir() and 'windows' not in p.parts)
cmd=['g++','-std=c++17','-O2','-fno-devirtualize','-fno-devirtualize-speculatively','-shared','-fPIC','-DNDEBUG','-DPX_PHYSX_STATIC_LIB','-DPX_PUBLIC_RELEASE=1',*[v for d in includes for v in ['-I',str(d)]],str(Path(__file__).with_name('force_readback.cpp')),'-o',str(a.output)]
result=subprocess.run(cmd)
raise SystemExit(result.returncode)
