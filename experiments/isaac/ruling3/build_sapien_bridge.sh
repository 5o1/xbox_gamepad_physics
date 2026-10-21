#!/usr/bin/env bash
set -eu
eval "$(python3 -m xbox_gamepad_physics.teleop.site --shell)"
: "${TELEOP_BASE_PYTHON:?Configure the existing SAPIEN interpreter}"
: "${TELEOP_LOCAL_OUTPUT:?Configure the build output directory}"
: "${TELEOP_EIGEN_INCLUDE:?Configure the Eigen include directory}"
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$TELEOP_LOCAL_OUTPUT"
cd "$TELEOP_LOCAL_OUTPUT"
sdk=$("$TELEOP_BASE_PYTHON" -c 'import sapien,pathlib;print(pathlib.Path(sapien.__file__).parent)')
pyinc=$("$TELEOP_BASE_PYTHON" -c 'import sysconfig;print(sysconfig.get_path("include"))')
pbinc=$("$TELEOP_BASE_PYTHON" -c 'import pybind11;print(pybind11.get_include())')
suffix=$("$TELEOP_BASE_PYTHON" -c 'import sysconfig;print(sysconfig.get_config_var("EXT_SUFFIX"))')
g++ -std=c++20 -O2 -DNDEBUG -shared -fPIC \
 -I"$pyinc" -I"$pbinc" -I"$sdk/include" -I"$sdk/include/physx/include" -I"$TELEOP_EIGEN_INCLUDE" \
 "$script_dir/sapien_sdf_bridge.cpp" -L"$sdk/../sapien.libs" -lsapien \
 -Wl,-rpath,"$sdk/../sapien.libs" -o "sapien_sdf_bridge$suffix"
