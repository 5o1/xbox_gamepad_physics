#!/usr/bin/env bash
# Private checkout adapter only; installed local mode never reads this config.
set -euo pipefail
TASK_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SITE_CONFIG=${TELEOP_SITE_CONFIG:-$TASK_ROOT/configs/local/teleop_site.env}
[[ -f $SITE_CONFIG ]] || { echo "Missing explicit site configuration: $SITE_CONFIG; see configs/teleop_site.example.env for the template" >&2; exit 2; }
export PYTHONPATH="$TASK_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$TASK_ROOT"
exec python3 -m xbox_gamepad_physics teleop --mode remote --site "$SITE_CONFIG" --render-candidate "${TELEOP_RENDER_CANDIDATE:-rt}" "$@"
