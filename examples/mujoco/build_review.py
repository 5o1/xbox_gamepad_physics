"""Build a contact-video review using the project's canonical signal overlay."""
from pathlib import Path
import argparse
import html
import json
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory
    shutil.copyfile(Path(__file__).with_name('review_overlay.js'), directory/'review_overlay.js')
    manifest = json.loads((directory/'video_manifest.json').read_text())
    results = json.loads(args.results.read_text())
    cases = {item['case']:item for item in results['results']}
    videos = {item['case']:item for item in manifest['cases']}
    entries = []
    for name in ('L3', 'R3', 'Pair'):
        row = cases[name]
        entries.append({'label':name+' 本轮'+('通过' if row['physics_passed'] else '未通过'),
                        'video':videos[name]['video'], 'case':name, 'speed':.5})
    for name in ('L3', 'R3'):
        entries.append({'label':name+' 逐点慢放（全部4 ms记录）',
                        'video':'slow/'+videos[name]['video'], 'case':name, 'speed':.12})
    entries.append({'label':'全部26项合集', 'video':'00_all_26.mp4', 'case':None, 'speed':.5})
    for row in results['results']:
        if row['case'] not in {'L3','R3','Pair'}:
            entries.append({'label':row['case']+' · '+('通过' if row['physics_passed'] else '未通过'),
                            'video':videos[row['case']]['video'], 'case':row['case'], 'speed':.5})
    options=''.join(f'<option value="{i}">{html.escape(item["label"])}</option>' for i,item in enumerate(entries))
    table=[]
    for row in results['results']:
        ok=row['physics_passed']
        table.append(f'<tr><td>{html.escape(row["case"])}</td><td class="'+('pass' if ok else 'fail')+'">'+('通过' if ok else '未通过')+f'</td><td>{row["target_min"]:.6f} / {row["target_threshold"]:.2f}</td><td>'+('通过' if row['baseline_passed'] else '未通过')+'</td></tr>')
    data=json.dumps({'entries':entries,'cases':cases},ensure_ascii=False).replace('</',r'<\/')
    reference = ''
    if all((directory/'reference'/name).is_file() for name in ('mujoco_full.png','mujoco_abxy.png')):
        reference = '''<details><summary>Comparison views · pending appearance review</summary><div style="display:flex;flex-wrap:wrap;gap:16px"><a href="reference/mujoco_full.png" style="max-width:48%"><img src="reference/mujoco_full.png" alt="MuJoCo reference full view" style="width:100%;height:auto"></a><a href="reference/mujoco_abxy.png" style="max-width:48%"><img src="reference/mujoco_abxy.png" alt="MuJoCo reference ABXY close-up" style="width:100%;height:auto"></a></div></details>'''
    page='''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MuJoCo 最新接触测试 · 25/26通过</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#131b25;color:#edf2f8;font:17px/1.6 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1700px;margin:auto;padding:24px}h1{margin:0;font-size:28px}p{margin:10px 0}.muted{color:#b8c6d8}.pass{color:#54ef99}.fail{color:#ff707d}a{color:#91caff}video{display:block;width:100%;background:#202934;border:1px solid #455266}select,button{font:inherit;border:1px solid #61738d;background:#26364a;color:#fff;border-radius:6px;padding:8px 12px}button{cursor:pointer}button:hover{background:#38506e}.controls{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}select{min-width:310px;max-width:100%}#details{padding:10px 0;min-height:44px}table{border-collapse:collapse;width:100%;max-width:1000px}td,th{padding:7px 12px;text-align:left;border-bottom:1px solid #38475b}.dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px}.red{background:#ff2846}.green{background:#28ff6e}summary{cursor:pointer;margin:20px 0 8px}
.review-row{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:16px;align-items:start}.overlay-panel{background:#1d2a39;border:1px solid #455266;padding:12px}.overlay-panel h2{font-size:19px;margin:0}.overlay-panel iframe{display:block;width:100%;height:285px;border:0}#overlay-status{font-size:14px;min-height:45px}@media(max-width:1000px){.review-row{grid-template-columns:1fr}.overlay-panel{max-width:460px}}
</style></head><body><main>
<h1>MuJoCo 最新接触测试 · 2026-10-20</h1>
<p><strong class="pass">25项通过</strong>，<strong class="fail">仅Pair未通过</strong>。SAPIEN原先通过的23项无退化，L3、R3本轮新增通过。</p>
<p class="muted">每幅包含：正对手柄的全身图、接触部位近景、透明碰撞网格侧视图。绿色标题表示本轮成功，红色表示未通过。</p>
<div class="controls"><button data-entry="0">L3</button><button data-entry="1">R3</button><button data-entry="2">Pair</button><button data-entry="3">L3逐点慢放</button><button data-entry="4">R3逐点慢放</button><button data-entry="5">全部26项</button><select id="choice">'''+options+'''</select></div>
<div class="review-row"><video id="player" controls playsinline preload="metadata" poster="L3_hold.png" src="L3_three_views.mp4"></video>
<section class="overlay-panel"><h2>仿真输入 · 项目原有Overlay</h2><iframe id="gamepad-overlay" title="MuJoCo canonical gamepad signals"></iframe><p id="overlay-status">载入32维信号…</p><p>Pair独立事件：<strong id="pair-event">0.0000</strong></p><a href="http://127.0.0.1:8774/traces/index.html">通过本地服务打开Overlay</a></section></div>
<div id="details"></div>
<div class="controls"><button id="hold">跳到保持前1秒</button><button id="start">从头查看</button><a id="download" href="L3_three_views.mp4" download>下载当前视频</a></div>
<p><span class="dot red"></span>外壳触点　<span class="dot green"></span>活动件触点。实心表示有法向力，空心表示零法向力记录；标记覆盖显示，被物体遮挡的点也可见。</p>
<p class="muted">普通视频为0.5倍速；L3/R3逐点慢放为0.12倍速，逐一显示每个4 ms记录点。视频来自这轮实际测试轨迹回放，没有重新跑物理；未记录的0.5 ms子步运动无法从这些视频恢复。</p>
<p class="muted">保持值是0.5秒保持阶段的最低目标信号。1表示满量程，0表示未触发；摇杆方向按目标方向计正负。</p>
<details><summary>查看26项结果</summary><table><thead><tr><th>项目</th><th>本轮</th><th>保持最低值 / 门槛</th><th>SAPIEN基线</th></tr></thead><tbody>'''+''.join(table)+'''</tbody></table></details>
'''+reference+'''<script id="records" type="application/json">'''+data+'''</script>
<script>
const data=JSON.parse(document.querySelector('#records').textContent);
const choice=document.querySelector('#choice'),player=document.querySelector('#player');
let selected=data.entries[0];
function details(){const r=selected.case?data.cases[selected.case]:null;document.querySelector('#details').textContent=r?`${selected.label}：保持最低值 ${r.target_min.toFixed(6)}，门槛 ${r.target_threshold.toFixed(2)}；释放回中${r.return_passed?'通过':'未通过'}。`:'26项连续合集，可使用视频章节跳转。';document.querySelector('#download').href=selected.video;document.querySelector('#hold').disabled=!r;}
function select(i){choice.value=String(i);selected=data.entries[i];player.src=selected.video;player.load();details();}
choice.addEventListener('change',()=>select(Number(choice.value)));
document.querySelectorAll('[data-entry]').forEach(button=>button.addEventListener('click',()=>select(Number(button.dataset.entry))));
document.querySelector('#start').addEventListener('click',()=>{player.currentTime=0;});
document.querySelector('#hold').addEventListener('click',()=>{if(selected.case){const r=data.cases[selected.case];player.currentTime=Math.max(0,r.termination.step*.004/selected.speed-1);}});
details();
</script><script src="review_overlay.js" defer></script></main></body></html>'''
    (directory/'index.html').write_text(page)
    manifest['slow_replays']={'cases':['L3','R3'],'directory':'slow','playback_speed':.12,
                             'all_archived_outer_samples_shown':True,'source_frequency_hz':250}
    (directory/'video_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (directory/'README.md').write_text('''# Current MuJoCo contact review

Open index.html. This is the 2026-10-20 current-parameter round: 25/26 passed,
with Pair still blocked and L3/R3 now passing. Each clip combines three fixed
views; the front camera is normal to the controller face. Titles show green
success or red failure. Red contact markers identify the shell; green markers
identify moving parts. Filled markers have recorded normal force, hollow markers
have zero force; occluded markers are overlaid for inspection.

Normal clips and the chaptered compilation play at 0.5x. The two slow clips
show every archived 0.004 s sample at 0.12x. Unrecorded 0.0005 s substep motion
cannot be recovered. These are kinematic replays of the actual archived run,
not new physics or new scores. Side shells show source triangles, not an SDF
isosurface. Rendering used native MuJoCo classic EGL on GPU 3 only.

To display the existing project SVG overlay synchronized to actual recorded
32-dimensional states, run examples/mujoco/serve_review.py with this directory
and open the printed loopback URL. Direct file opening still plays the videos;
the canonical ES-module overlay requires HTTP. Pair remains a separate event.
''')


if __name__ == '__main__':
    main()
