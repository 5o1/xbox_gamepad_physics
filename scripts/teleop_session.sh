#!/usr/bin/env bash
set -euo pipefail
CANDIDATE=${TELEOP_RENDER_CANDIDATE:-rt}
COLLISION=sdf
SAPIEN_VERSION=3.0.3
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || { echo '用法: teleop_session.sh [--render raster|rt] [--collision sdf|coacd] [--sapien 3.0.3|3.0.0b1]' >&2; exit 2; }
  case $1 in
    --render) CANDIDATE=$2 ;;
    --collision) COLLISION=$2 ;;
    --sapien) SAPIEN_VERSION=$2 ;;
    *) echo "未知选项: $1" >&2; exit 2 ;;
  esac
  shift 2
done
[[ $COLLISION == sdf || $COLLISION == coacd ]] || { echo '碰撞体只接受 sdf 或 coacd' >&2; exit 2; }
[[ $SAPIEN_VERSION == 3.0.3 || $SAPIEN_VERSION == 3.0.0b1 ]] || { echo 'SAPIEN只接受3.0.3或3.0.0b1' >&2; exit 2; }
[[ $SAPIEN_VERSION != 3.0.0b1 || $COLLISION == coacd ]] || { echo 'SDF需要SAPIEN 3.0.3；旧版本请显式选择 --collision coacd' >&2; exit 2; }
[[ $CANDIDATE == raster || $CANDIDATE == rt ]] || { echo '渲染候选只接受 raster 或 rt' >&2; exit 2; }
TASK_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SITE_CONFIG=${TELEOP_SITE_CONFIG:-$TASK_ROOT/configs/local/teleop_site.env}
[[ -f $SITE_CONFIG ]] || { echo "缺少本地配置 $SITE_CONFIG；请复制并填写 $TASK_ROOT/configs/teleop_site.example.env" >&2; exit 2; }
export TELEOP_SITE_CONFIG="$SITE_CONFIG"
SITE_EXPORTS=$(PYTHONPATH="$TASK_ROOT" python3 -m teleop.site --shell)
eval "$SITE_EXPORTS"
for key in TELEOP_GPU_HOST TELEOP_SSH_PORT TELEOP_SSH_USER TELEOP_SSH_IDENTITY TELEOP_LOGIN_PROFILE TELEOP_REMOTE_ROOT TELEOP_REMOTE_REPO TELEOP_RESOURCE_ROOT TELEOP_BASE_PYTHON TELEOP_STREAM_PYTHON TELEOP_ROBOTWIN_ROOT TELEOP_PORT TELEOP_WSL_PORT TELEOP_WSL_INTERFACE TELEOP_REMOTE_PORT TELEOP_GPU TELEOP_LOCAL_OUTPUT; do
  [[ -n ${!key:-} && ${!key} != *'<'* ]] || { echo "缺少配置 $key；请填写 $TASK_ROOT/configs/teleop_site.example.env" >&2; exit 2; }
done
SIMULATION_PYTHON=$TELEOP_BASE_PYTHON
if [[ $SAPIEN_VERSION == 3.0.0b1 ]]; then
  [[ -n ${TELEOP_LEGACY_PYTHON:-} && $TELEOP_LEGACY_PYTHON != *'<'* ]] || { echo '请填写本地配置 TELEOP_LEGACY_PYTHON' >&2; exit 2; }
  SIMULATION_PYTHON=$TELEOP_LEGACY_PYTHON
fi
REMOTE_ROOT=$TELEOP_REMOTE_ROOT
PROFILE=$TELEOP_LOGIN_PROFILE
LOCAL_PORT=$TELEOP_PORT
WSL_PORT=$TELEOP_WSL_PORT
WSL_ADDRESS=$(ip -4 -o address show dev "$TELEOP_WSL_INTERFACE" | awk '{split($4,a,"/");print a[1]}')
REMOTE_PORT=$TELEOP_REMOTE_PORT
RUN_NAME=${TELEOP_RUN_NAME:-live-$(date +%Y%m%d-%H%M%S)}
[[ "$RUN_NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo '会话名称只接受字母、数字、下划线和短横线'; exit 2; }
GPU=$TELEOP_GPU
LOCAL_OUTPUT=$TELEOP_LOCAL_OUTPUT
[[ $LOCAL_OUTPUT == /* ]] || LOCAL_OUTPUT="$TASK_ROOT/$LOCAL_OUTPUT"
mkdir -p "$LOCAL_OUTPUT"
MANIFEST="$LOCAL_OUTPUT/sync_files.txt"
git -C "$TASK_ROOT" ls-files -z > "$MANIFEST"
git -C "$TASK_ROOT" ls-files --others --exclude-standard -z >> "$MANIFEST"
"$PROFILE" --wohint -n -o BatchMode=yes "mkdir -p '$TELEOP_REMOTE_REPO'"
rsync -a --from0 --files-from="$MANIFEST" -e "ssh -p $TELEOP_SSH_PORT -i '$TELEOP_SSH_IDENTITY' -o IdentitiesOnly=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o PreferredAuthentications=publickey -o BatchMode=yes" \
  "$TASK_ROOT/" "$TELEOP_SSH_USER@$TELEOP_GPU_HOST:$TELEOP_REMOTE_REPO/"
# The private config is copied separately; it is absent from the Git manifest.
rsync -a -e "ssh -p $TELEOP_SSH_PORT -i '$TELEOP_SSH_IDENTITY' -o IdentitiesOnly=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o PreferredAuthentications=publickey -o BatchMode=yes" "$SITE_CONFIG" "$TELEOP_SSH_USER@$TELEOP_GPU_HOST:$REMOTE_ROOT/site.env"
printf -v START 'cd %q && export TELEOP_SITE_CONFIG=%q XBOX_GAMEPAD_PHYSICS_RESOURCES=%q && %q -u -m teleop.stream.gateway --run %q --gpu %q --port %q --render-candidate %q --collision %q --simulation-python %q' "$TELEOP_REMOTE_REPO" "$REMOTE_ROOT/site.env" "$TELEOP_RESOURCE_ROOT" "$TELEOP_STREAM_PYTHON" "$REMOTE_ROOT/$RUN_NAME" "$GPU" "$REMOTE_PORT" "$CANDIDATE" "$COLLISION" "$SIMULATION_PYTHON"
"$PROFILE" --wohint -n -o BatchMode=yes "$START" > "$LOCAL_OUTPUT/$RUN_NAME.log" 2>&1 &
SESSION_PID=$!
cleanup() {
  "$PROFILE" --wohint -n -o BatchMode=yes "curl --noproxy '*' -fsS -X POST 'http://127.0.0.1:$REMOTE_PORT/shutdown?run=$RUN_NAME'" >/dev/null 2>&1 || true
  # The shutdown response acknowledges the request; the remote process still
  # needs to close workers/NVENC. Keep SSH alive to observe its completion.
  for _ in {1..20}; do
    kill -0 "$SESSION_PID" 2>/dev/null || break
    "$PROFILE" --wohint -n -o BatchMode=yes "curl --noproxy '*' -fsS -X POST 'http://127.0.0.1:$REMOTE_PORT/shutdown?run=$RUN_NAME'" >/dev/null 2>&1 || true
    sleep 1
  done
  if kill -0 "$SESSION_PID" 2>/dev/null; then
    echo "本次远端会话未在20秒内完成退出，请检查 $RUN_NAME.log" >&2
  fi
  kill "$SESSION_PID" "${TUNNEL_PID:-$SESSION_PID}" "${RELAY_PID:-$SESSION_PID}" 2>/dev/null || true
  wait "$SESSION_PID" 2>/dev/null || true
  exec 3<&-
  rm -f "${TUNNEL_INPUT_FIFO:-/tmp/teleop-no-fifo}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Opening a command session enables TCP_NODELAY at the OpenSSH server too.
# The idle cat exits on tunnel EOF; fd 3 keeps stdin open without a busy process.
TUNNEL_INPUT_FIFO="$LOCAL_OUTPUT/$RUN_NAME-tunnel.fifo"
mkfifo "$TUNNEL_INPUT_FIFO"
exec 3<>"$TUNNEL_INPUT_FIFO"
ssh -T -p "$TELEOP_SSH_PORT" -i "$TELEOP_SSH_IDENTITY" -o IdentitiesOnly=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o PreferredAuthentications=publickey -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -L "0.0.0.0:$WSL_PORT:127.0.0.1:$REMOTE_PORT" "$TELEOP_SSH_USER@$TELEOP_GPU_HOST" 'cat >/dev/null' <&3 2>"$LOCAL_OUTPUT/$RUN_NAME-tunnel.log" &
TUNNEL_PID=$!
RELAY_SCRIPT=$(wslpath -w "$TASK_ROOT/teleop/windows_relay.ps1")
powershell.exe -NoProfile -NonInteractive -Command "& ([scriptblock]::Create((Get-Content -Raw '$RELAY_SCRIPT'))) -ListenPort $LOCAL_PORT -WslAddress '$WSL_ADDRESS' -WslPort $WSL_PORT" \
  > "$LOCAL_OUTPUT/$RUN_NAME-relay.log" 2>&1 &
RELAY_PID=$!
for attempt in {1..60}; do
  if curl --noproxy '*' -fsS "http://127.0.0.1:$WSL_PORT/health" 2>/dev/null | python3 -c 'import json,sys; h=json.load(sys.stdin); sys.exit(0 if h["ready"] and h.get("run")==sys.argv[1] else 1)' "$RUN_NAME" 2>/dev/null; then
    echo "Windows 浏览器打开 http://localhost:$LOCAL_PORT/ （Ctrl+C 停止本次会话）"
    wait "$TUNNEL_PID"
    exit 0
  fi
  if ! kill -0 "$SESSION_PID" 2>/dev/null; then
    if wait "$SESSION_PID"; then SESSION_STATUS=0; else SESSION_STATUS=$?; fi
    echo "远端会话在就绪前退出，状态=$SESSION_STATUS；会话日志：$LOCAL_OUTPUT/$RUN_NAME.log" >&2
    cat "$LOCAL_OUTPUT/$RUN_NAME.log" >&2
    exit 1
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null || ! kill -0 "$RELAY_PID" 2>/dev/null; then
    cat "$LOCAL_OUTPUT/$RUN_NAME-tunnel.log" >&2
    echo "隧道或 Windows 中继提前退出；中继日志：$LOCAL_OUTPUT/$RUN_NAME-relay.log" >&2
    cat "$LOCAL_OUTPUT/$RUN_NAME-relay.log" >&2
    exit 1
  fi
  sleep 1
done
echo '服务尚未就绪，请查看本次会话日志'
exit 1
