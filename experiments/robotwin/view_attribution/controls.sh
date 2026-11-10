set -eu
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
ATTR_CODE=$NODE_WORK/station-rtf-20261110/code
ATTR_RAW="$ATTR_CODE/build/experiments/station_rtf/view_attribution"
ATTR_RES=$NODE_WORK/task-am-0.4.2/workspace/assets
cd "$ATTR_CODE"
export DISPLAY= CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
export ATTR_OLD_RESOURCES="$ATTR_RES/xbox_gamepad_physics_v0.4.1/resources"
export PYTHONPATH="$ATTR_CODE"
mkdir -p "$ATTR_RAW/input/baseline041"
tar -xzf "$ATTR_RAW/input/baseline041-python.tar.gz" -C "$ATTR_RAW/input/baseline041"
ATTR_NEW_PY=$NODE_ENVS/sapien-3.0.3concon-xgp0.4.2-py310/bin/python
ATTR_OLD_PY=$NODE_ENVS/am-baseline-sapien303-xgp041/bin/python
taskset -c 8 "$ATTR_NEW_PY" -m experiments.robotwin.view_attribution.run --resources "$ATTR_RES/xbox_gamepad_physics_v0.4.2/resources" --output "$ATTR_RAW/C0" > "$ATTR_RAW/C0.log" 2>&1
taskset -c 8 "$ATTR_NEW_PY" -m experiments.robotwin.view_attribution.run --resources "$ATTR_OLD_RESOURCES" --old-source "$ATTR_RAW/input/baseline041/src" --output "$ATTR_RAW/C1-a3" > "$ATTR_RAW/C1-a3.log" 2>&1
taskset -c 8 "$ATTR_OLD_PY" -m experiments.robotwin.view_attribution.run --resources "$ATTR_OLD_RESOURCES" --old-source "$ATTR_RAW/input/baseline041/src" --output "$ATTR_RAW/C1-stock" > "$ATTR_RAW/C1-stock.log" 2>&1
