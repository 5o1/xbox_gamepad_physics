#!/bin/bash
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
set -eu
CLICK_ROOT=$NODE_WORK/station-rtf-20261110-s
export DISPLAY= CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
export GAMEPAD_VLA_WORKSPACE=$NODE_WORK/task-am-0.4.2/workspace
export XBOX_GAMEPAD_PHYSICS_RESOURCES="$GAMEPAD_VLA_WORKSPACE/assets/xbox_gamepad_physics_v0.4.2/resources"
export PYTHONPATH="$CLICK_ROOT/code:$CLICK_ROOT/code/src:$CLICK_ROOT/support/src"
cd "$CLICK_ROOT/support"
exec taskset -c 10 $NODE_ENVS/sapien-3.0.3concon-xgp0.4.2-py310/bin/python "$@"
