#!/usr/bin/env bash
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
# Invoke only on the designated compute node; no station, renderer or GPU.
set -euo pipefail
run_root=$NODE_WORK/station-rtf-20261110-k
output_name=${1:?supply a fresh output directory name}
shift
export CUDA_VISIBLE_DEVICES='' DISPLAY='' PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$run_root/code:$run_root/code/src"
cd "$run_root/code"
exec taskset -c 9 $NODE_ENVS/sapien-3.0.3concon-xgp0.4.2-py310/bin/python \
  -m experiments.robotwin.station_rtf.probe_k.run \
  --resources $NODE_WORK/task-am-0.4.2/workspace/assets/xbox_gamepad_physics_v0.4.2/resources \
  --output "$run_root/$output_name" "$@"
