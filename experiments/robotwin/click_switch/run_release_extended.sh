#!/bin/bash
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
set -eu
CLICK_ROOT=$NODE_WORK/station-rtf-20261110-s
CLICK_OUTPUT="$CLICK_ROOT/code/build/experiments/station_rtf/click_switch"
CLICK_LAUNCH="$CLICK_ROOT/code/experiments/robotwin/click_switch/run_remote.sh"
ulimit -c 0
CLICK_MODE=${1:-hybrid}
for CLICK_SOLVER in 64-16 10-1; do
 CLICK_POS=${CLICK_SOLVER%-*}; CLICK_VEL=${CLICK_SOLVER#*-}
 CLICK_NAME="$CLICK_MODE-$CLICK_SOLVER-release-30s"
 bash "$CLICK_LAUNCH" -X faulthandler -u -m experiments.robotwin.click_switch.release --mode "$CLICK_MODE" --iterations "$CLICK_POS" "$CLICK_VEL" --duration-s 30 --output "$CLICK_OUTPUT/$CLICK_NAME" > "$CLICK_OUTPUT/$CLICK_NAME.log" 2>&1
done
