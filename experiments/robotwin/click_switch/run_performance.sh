#!/bin/bash
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
set -eu
CLICK_ROOT=$NODE_WORK/station-rtf-20261110-s
CLICK_OUTPUT="$CLICK_ROOT/code/build/experiments/station_rtf/click_switch"
CLICK_LAUNCH="$CLICK_ROOT/code/experiments/robotwin/click_switch/run_remote.sh"
CLICK_PROBE="$CLICK_ROOT/support/reports/2026-11-09-realtime-input-lag/engine_probe.py"
ulimit -c 0
for CLICK_SOLVER in 64-16 10-1; do
 CLICK_POS=${CLICK_SOLVER%-*}; CLICK_VEL=${CLICK_SOLVER#*-}
 for CLICK_CONDITION in static active contact; do
  CLICK_NAME="hybrid-$CLICK_SOLVER-$CLICK_CONDITION-r1"
  bash "$CLICK_LAUNCH" -X faulthandler -u -m experiments.robotwin.click_switch.run --mode hybrid --entry benchmark --aq-probe "$CLICK_PROBE" --condition "$CLICK_CONDITION" --iterations "$CLICK_POS" "$CLICK_VEL" --steps 3000 --repetitions 3 --output "$CLICK_OUTPUT/$CLICK_NAME" > "$CLICK_OUTPUT/$CLICK_NAME.log" 2>&1
 done
done
