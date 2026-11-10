#!/bin/bash
: "${NODE_WORK:?set NODE_WORK to the compute-node work root}" "${NODE_ENVS:?set NODE_ENVS to the compute-node env root}"
set -eu
CLICK_ROOT=$NODE_WORK/station-rtf-20261110-s
CLICK_OUTPUT="$CLICK_ROOT/code/build/experiments/station_rtf/click_switch"
CLICK_LAUNCH="$CLICK_ROOT/code/experiments/robotwin/click_switch/run_remote.sh"
ulimit -c 0
for CLICK_MODE in pure hybrid; do
 for CLICK_SOLVER in 64-16 10-1; do
  CLICK_POS=${CLICK_SOLVER%-*}; CLICK_VEL=${CLICK_SOLVER#*-}
  if [ ! -f "$CLICK_OUTPUT/$CLICK_MODE-$CLICK_SOLVER-t1/summary.json" ]; then
   bash "$CLICK_LAUNCH" -X faulthandler -u -m experiments.robotwin.click_switch.run --mode "$CLICK_MODE" --entry acceptance --suite t1 --iterations "$CLICK_POS" "$CLICK_VEL" --output "$CLICK_OUTPUT/$CLICK_MODE-$CLICK_SOLVER-t1" > "$CLICK_OUTPUT/$CLICK_MODE-$CLICK_SOLVER-t1.log" 2>&1
  fi
  CLICK_RELEASE="$CLICK_MODE-$CLICK_SOLVER-release"
  if [ "$CLICK_MODE-$CLICK_SOLVER" = pure-64-16 ]; then CLICK_RELEASE="$CLICK_RELEASE-r1"; fi
  bash "$CLICK_LAUNCH" -X faulthandler -u -m experiments.robotwin.click_switch.release --mode "$CLICK_MODE" --iterations "$CLICK_POS" "$CLICK_VEL" --output "$CLICK_OUTPUT/$CLICK_RELEASE" > "$CLICK_OUTPUT/$CLICK_RELEASE.log" 2>&1
 done
done
for CLICK_SOLVER in 64-16 10-1; do
 CLICK_POS=${CLICK_SOLVER%-*}; CLICK_VEL=${CLICK_SOLVER#*-}
 bash "$CLICK_LAUNCH" -X faulthandler -u -m experiments.robotwin.click_switch.run --mode hybrid --entry acceptance --suite full --iterations "$CLICK_POS" "$CLICK_VEL" --output "$CLICK_OUTPUT/hybrid-$CLICK_SOLVER-full" > "$CLICK_OUTPUT/hybrid-$CLICK_SOLVER-full.log" 2>&1
done
