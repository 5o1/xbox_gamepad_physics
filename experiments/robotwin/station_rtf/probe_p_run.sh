set -eu
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
PROBE_ROOT=$NODE_WORK/station-rtf-view-probe-20261110-p
PROBE_PY=$NODE_ENVS/sapien-3.0.3concon-xgp0.4.2-py310/bin/python
PROBE_RES=$NODE_WORK/task-am-0.4.2/workspace/assets/xbox_gamepad_physics_v0.4.2/resources
cd "$PROBE_ROOT/code"
export DISPLAY= CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PROBE_ROOT/code"
for PROBE_ITER in '10 1' '64 16'; do
 set -- $PROBE_ITER
 for PROBE_DT in .004 .001; do
  PROBE_GROUP=final-r1-iters-$1-$2-dt-$PROBE_DT
  taskset -c 8 "$PROBE_PY" -m experiments.robotwin.station_rtf.probe_p --resources "$PROBE_RES" --iterations "$1" "$2" --dt "$PROBE_DT" --force-readback "$PROBE_ROOT/raw/input/force_readback.so" --output "$PROBE_ROOT/raw/$PROBE_GROUP" > "$PROBE_ROOT/raw/$PROBE_GROUP.log" 2>&1
 done
done
