#!/bin/bash
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
set -eu
CLICK_ROOT=$NODE_WORK/station-rtf-20261110-s
CLICK_OUTPUT="$CLICK_ROOT/code/build/experiments/station_rtf/click_switch"
CLICK_LAUNCH="$CLICK_ROOT/code/experiments/robotwin/click_switch/run_remote.sh"
CLICK_PROBE="$CLICK_ROOT/support/reports/2026-11-09-realtime-input-lag/engine_probe.py"
ulimit -c 0
for CLICK_CONFIG in A-64-16 A-10-1 B-10-1; do
 CLICK_LABEL=${CLICK_CONFIG%%-*}
 CLICK_SOLVER=${CLICK_CONFIG#*-};CLICK_POS=${CLICK_SOLVER%-*};CLICK_VEL=${CLICK_SOLVER#*-}
 CLICK_MODE=preload
 if [ "$CLICK_LABEL" = B ]; then CLICK_MODE=hybrid; fi
 CLICK_NAME="deployment-$CLICK_CONFIG-full"
 bash "$CLICK_LAUNCH" -X faulthandler -u -m experiments.robotwin.click_switch.run --mode "$CLICK_MODE" --entry acceptance --deployment-1ms --suite full --iterations "$CLICK_POS" "$CLICK_VEL" --output "$CLICK_OUTPUT/$CLICK_NAME" > "$CLICK_OUTPUT/$CLICK_NAME.log" 2>&1
done
for CLICK_LABEL in A B; do
 CLICK_MODE=preload
 if [ "$CLICK_LABEL" = B ]; then CLICK_MODE=hybrid; fi
 for CLICK_CONDITION in static active contact; do
  CLICK_NAME="awake-$CLICK_LABEL-10-1-$CLICK_CONDITION"
  bash "$CLICK_LAUNCH" -X faulthandler -u -m experiments.robotwin.click_switch.run --mode "$CLICK_MODE" --entry benchmark --always-awake --aq-probe "$CLICK_PROBE" --condition "$CLICK_CONDITION" --iterations 10 1 --steps 3000 --repetitions 3 --output "$CLICK_OUTPUT/$CLICK_NAME" > "$CLICK_OUTPUT/$CLICK_NAME.log" 2>&1
 done
done
