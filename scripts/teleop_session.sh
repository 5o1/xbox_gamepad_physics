#!/usr/bin/env bash
# Private checkout adapter only; installed local mode never reads this config.
set -euo pipefail
TASK_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SITE_CONFIG=${TELEOP_SITE_CONFIG:-$TASK_ROOT/configs/local/teleop_site.env}
[[ -f $SITE_CONFIG ]] || { echo "缺少显式站点配置：$SITE_CONFIG；模板见 configs/teleop_site.example.env" >&2; exit 2; }
export PYTHONPATH="$TASK_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$TASK_ROOT"
exec python3 -m xbox_gamepad_physics teleop --mode remote --site "$SITE_CONFIG" --render-candidate "${TELEOP_RENDER_CANDIDATE:-rt}" "$@"
