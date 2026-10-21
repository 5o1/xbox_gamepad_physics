// Feed the existing project overlay the exact canonical frame used by the video.
(() => {
const player = document.getElementById('player');
const overlay = document.getElementById('gamepad-overlay');
const status = document.getElementById('overlay-status');
const pair = document.getElementById('pair-event');
let source = null;
let frames = null;
let lastIndex = -1;
let applying = false;
let presentedTime = 0;
player.addEventListener('loadstart', () => { presentedTime = 0; });
if (player.requestVideoFrameCallback) {
  const presented = (_now, metadata) => {
    presentedTime = metadata.mediaTime;
    player.requestVideoFrameCallback(presented);
  };
  player.requestVideoFrameCallback(presented);
}

async function loadSource() {
  const current = player.getAttribute('src');
  if (current === source) return;
  source = current;
  frames = null;
  lastIndex = -1;
  status.textContent = '正在载入对应的32维信号…';
  const name = current.replace(/^slow\//, 'slow_').replace(/\.mp4$/, '.json');
  try {
    const response = await fetch(`signals/${name}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const trace = await response.json();
    if (player.getAttribute('src') === current) frames = trace;
  } catch (error) {
    if (player.getAttribute('src') === current) status.textContent = `信号载入失败：${error.message}`;
  }
}

async function update() {
  await loadSource();
  const adapter = overlay.contentWindow?.__gamepadOverlayAdapter;
  if (frames && adapter?.ready && !applying) {
    const time = player.requestVideoFrameCallback ? presentedTime : player.currentTime;
    const index = Math.min(frames.frames.length-1, Math.max(0, Math.round(time*frames.fps)));
    if (index !== lastIndex) {
      const frame = frames.frames[index];
      applying = true;
      try {
        await adapter.applyFrame(frame);
        lastIndex = index;
        pair.textContent = Number(frame.events?.pair_bind_connect ?? 0).toFixed(4);
        status.textContent = `${frame.case} · 32维 / ${frame.available_mask.filter(Boolean).length}维可用 · ${frame.telemetry.phase}`;
        status.dataset.frameIndex = String(index);
      } catch (error) {
        status.textContent = `Overlay显示失败：${error.message}`;
      } finally {
        applying = false;
      }
    }
  }
  requestAnimationFrame(update);
}
if (location.protocol === 'file:') {
  status.textContent = 'Overlay需要通过本地HTTP服务打开；视频仍可直接播放。';
} else {
  overlay.src = '/viewer/gamepad_overlay/index.html?view=overlay&source=canonical&theme=research';
  requestAnimationFrame(update);
}
})();
