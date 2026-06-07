"""
narravid Web UI — 浏览器里拖图片、写文案、自由编排、一键生成。

用法:
  python webui.py
  python webui.py --port 8080
"""
import argparse
import os
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


# 打包 exe 时自动定位自带 ffmpeg
_base_ff = getattr(sys, '_MEIPASS', None)
if _base_ff and (Path(_base_ff) / 'ffmpeg').is_dir():
    os.environ['PATH'] = str(Path(_base_ff) / 'ffmpeg') + os.pathsep + os.environ.get('PATH', '')

from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'video_auto.py'
OUT_BASE = ROOT / 'rendered' / 'webui'

HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>narravid</title>
<style>
:root {--bg:#f5f3ee;--card:#fff;--ink:#1a1a2e;--muted:#787878;--accent:#c2410c;--border:rgba(0,0,0,.08);--drop:#e8f0fe;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
.app{max-width:1200px;margin:0 auto;padding:24px 20px 80px}
h1{font-size:28px;font-weight:700;margin-bottom:2px}
.sub{color:var(--muted);font-size:14px;margin-bottom:20px}

.topbar{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:16px;padding:16px 18px;background:var(--card);border:1px solid var(--border);border-radius:10px}
.topbar label{font-size:12px;color:var(--muted);display:block;margin-bottom:3px}
.topbar input,.topbar select{font-size:13px;padding:7px 9px;border:1px solid var(--border);border-radius:6px;background:#fafafa}
.topbar input[type=range]{padding:0}
.speed-val{font-size:14px;font-weight:700;min-width:32px;text-align:center}

.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.controls button{font-size:13px;padding:8px 18px;border:1px solid var(--border);border-radius:6px;background:var(--card);cursor:pointer;transition:.15s;display:flex;align-items:center;gap:6px}
.controls button:hover{background:#f0ede6}
.controls button.accent{background:var(--accent);color:#fff;border-color:var(--accent)}
.controls button.accent:hover{opacity:.9}
.controls .sep{width:1px;height:24px;background:var(--border)}
.controls .count{font-size:13px;color:var(--muted)}

/* drop zone */
.drop-zone{border:2px dashed var(--border);border-radius:10px;padding:28px;text-align:center;color:var(--muted);font-size:14px;margin-bottom:14px;transition:.2s;display:none}
.drop-zone.active{display:block;border-color:var(--accent);background:var(--drop);color:var(--ink)}
.drop-zone.dragover{border-color:var(--accent);background:#fdf2e9}

/* scene cards */
.scene-list{display:flex;flex-direction:column;gap:10px}
.scene-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px;display:flex;gap:12px;align-items:stretch;transition:box-shadow .2s,opacity .2s}
.scene-card:hover{box-shadow:0 2px 12px rgba(0,0,0,.06)}
.scene-card.dragging{opacity:.4}
.scene-card .handle{cursor:grab;color:var(--muted);font-size:20px;display:flex;align-items:center;user-select:none;padding:0 2px;min-width:20px}
.scene-card .handle:active{cursor:grabbing}
.scene-card .num{font-size:12px;font-weight:700;color:var(--muted);min-width:22px;text-align:center}
.scene-card .thumb{width:90px;height:56px;border-radius:6px;border:1px solid var(--border);background:#fafafa center/cover;flex-shrink:0;cursor:pointer;position:relative;overflow:hidden}
.scene-card .thumb::after{content:'点击换图';position:absolute;inset:0;background:rgba(0,0,0,.5);color:#fff;font-size:11px;display:flex;align-items:center;justify-content:center;opacity:0;transition:.2s}
.scene-card .thumb:hover::after{opacity:1}
.scene-card .thumb.dropping{background:var(--drop) !important}
.scene-card .body{flex:1;display:flex;flex-direction:column;gap:8px;min-width:0}
.scene-card .path-row{display:flex;gap:8px;align-items:center}
.scene-card .path-input{flex:1;font-size:12px;padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:#fafafa;color:var(--muted)}
.scene-card textarea{width:100%;font-size:14px;padding:9px 11px;border:1px solid var(--border);border-radius:6px;background:#fafafa;resize:vertical;min-height:52px;font-family:inherit;line-height:1.6}
.scene-card .hold{width:62px;font-size:12px;padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:#fafafa}
.scene-card .del-btn{background:none;border:none;color:#c0392b;cursor:pointer;font-size:20px;padding:0 4px;opacity:.5;align-self:flex-start}
.scene-card .del-btn:hover{opacity:1}

/* status bar */
.status{position:fixed;bottom:0;left:0;right:0;background:#1a1a2e;color:#fff;padding:14px 24px;font-size:14px;display:none;align-items:center;gap:12px;z-index:100}
.status.show{display:flex}
.status .spinner{width:18px;height:18px;border:2px solid rgba(255,255,255,.2);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.status .msg{flex:1}
.status .cancel{color:#e74c3c;cursor:pointer;font-weight:700}
.result{position:fixed;bottom:60px;left:50%;transform:translateX(-50%);color:#fff;padding:12px 28px;border-radius:10px;font-size:15px;display:none;z-index:101;cursor:pointer}
.result.show{display:block}
.result a{color:#fff;font-weight:700;text-decoration:underline}
</style>
</head>
<body>
<div class="app">
<h1>narravid</h1>
<div class="sub">拖图片到场景卡片 → 写文案 → 自由排序 → 一键生成解说视频</div>

<div class="topbar">
  <div>
    <label>音色</label>
    <select id="voice"><option value="zh-CN-XiaoxiaoNeural">Xiaoxiao (女·温暖)</option><option value="zh-CN-XiaoyiNeural">Xiaoyi (女·活泼)</option><option value="zh-CN-YunxiNeural">Yunxi (男·轻快)</option><option value="zh-CN-YunyangNeural">Yunyang (男·专业)</option><option value="zh-CN-YunjianNeural">Yunjian (男·热情)</option></select>
  </div>
  <div>
    <label>语速 <span class="speed-val" id="speedVal">1.5</span></label>
    <input type="range" id="speed" min="0.8" max="2.2" step="0.05" value="1.5" style="width:100px">
  </div>
  <div><label>标题</label><input type="text" id="titleCard" placeholder="留空则无标题页" style="width:140px"></div>
  <div><label>BGM</label><input type="text" id="bgm" placeholder="可选 mp3 路径" style="width:130px"></div>
  <div style="display:flex;align-items:flex-end"><label style="display:flex;align-items:center;gap:5px;cursor:pointer;margin-bottom:0;font-size:13px"><input type="checkbox" id="burnSubs" checked> 烧录字幕</label></div>
</div>

<div class="controls">
  <button onclick="batchAdd()" class="accent">📁 批量添加图片</button>
  <button onclick="addScene()">＋ 添加空场景</button>
  <span class="sep"></span>
  <span class="count" id="sceneCount">0 个场景</span>
  <span style="flex:1"></span>
  <button id="renderBtn" onclick="render()" class="accent">▶ 生成视频</button>
</div>

<div class="drop-zone" id="dropZone">拖图片到这里，自动创建场景</div>
<div class="scene-list" id="sceneList"></div>
</div>

<div class="status" id="status"><div class="spinner"></div><div class="msg" id="statusMsg">准备中…</div><div class="cancel" onclick="cancelRender()">✕</div></div>
<div class="result" id="resultBox" onclick="this.classList.remove('show')"></div>

<script>
let scenes=[], renderId=null, pollTimer=null;
let dragIdx=null;

const El=id=>document.getElementById(id);

function init(){
  document.getElementById('speed').oninput=function(){El('speedVal').textContent=this.value};
  // global drop zone
  const dz=El('dropZone');
  document.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('active')});
  document.addEventListener('dragleave',e=>{if(e.target===document.documentElement)dz.classList.remove('active')});
  document.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('active');handleFiles(e.dataTransfer.files)});
  dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover')});
  dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));
  dz.addEventListener('drop',e=>{e.preventDefault();e.stopPropagation();dz.classList.remove('dragover','active');handleFiles(e.dataTransfer.files)});
  addScene(); addScene(); addScene();
}
function handleFiles(files){
  for(let f of Array.from(files)){
    if(!f.type.startsWith('image/'))continue;
    scenes.push({image:f.path||f.name,text:'',hold_sec:0});
  }
  renderList();
}
function batchAdd(){
  let input=document.createElement('input');input.type='file';input.multiple=true;input.accept='image/*';
  input.onchange=()=>handleFiles(input.files);
  input.click();
}
function addScene(img,text,hold){
  scenes.push({image:img||'',text:text||'',hold_sec:hold||0});
  renderList();
}
function removeScene(i){scenes.splice(i,1);renderList();}
function chooseImage(i){
  let input=document.createElement('input');input.type='file';input.accept='image/*';
  input.onchange=()=>{if(input.files[0]){scenes[i].image=input.files[0].path||input.files[0].name;renderList();}};
  input.click();
}

// drag reorder
function dragStart(i,e){dragIdx=i;e.target.closest('.scene-card').classList.add('dragging');e.dataTransfer.effectAllowed='move'}
function dragOver(e){e.preventDefault();e.dataTransfer.dropEffect='move'}
function dragEnd(e){e.target.closest('.scene-card')?.classList.remove('dragging');dragIdx=null}
function dropOn(i,e){
  e.preventDefault();e.stopPropagation();
  if(dragIdx===null||dragIdx===i)return;
  let item=scenes.splice(dragIdx,1)[0];
  scenes.splice(i,0,item);
  renderList();
}
// image drop on card
function cardImageDrop(i,e){
  e.preventDefault();e.stopPropagation();
  let files=e.dataTransfer.files;
  if(files.length>0&&files[0].type.startsWith('image/')){
    scenes[i].image=files[0].path||files[0].name;
    renderList();
  }
}

function renderList(){
  let h='';
  scenes.forEach((s,i)=>{
    let img=s.image?`<div class="thumb" style="background-image:url('file://${escAttr(s.image)}')" onclick="chooseImage(${i})" ondragover="event.target.closest('.thumb').classList.add('dropping')" ondragleave="event.target.closest('.thumb').classList.remove('dropping')" ondrop="cardImageDrop(${i},event)"></div>`:'<div class="thumb" onclick="chooseImage('+i+')" ondrop="cardImageDrop('+i+',event)" ondragover="event.preventDefault()"></div>';
    h+=`<div class="scene-card" draggable="true" ondragstart="dragStart(${i},event)" ondragover="dragOver(event)" ondragend="dragEnd(event)" ondrop="dropOn(${i},event)">
      <div class="handle" title="拖拽排序">⠿</div>
      <div class="num">#${i+1}</div>
      ${img}
      <div class="body">
        <div class="path-row">
          <input class="path-input" value="${esc(s.image)}" placeholder="图片路径（也可拖图片到这行）" onchange="scenes[${i}].image=this.value" readonly>
          <input class="hold" type="number" placeholder="多停" value="${s.hold_sec||''}" onchange="scenes[${i}].hold_sec=parseFloat(this.value)||0" title="停秒数">
          <button class="del-btn" onclick="removeScene(${i})" title="删除">×</button>
        </div>
        <textarea placeholder="解说文案（按句号自动切字幕）。留空 = 只展示图片不出声" onchange="scenes[${i}].text=this.value">${esc(s.text)}</textarea>
      </div>
    </div>`;
  });
  El('sceneList').innerHTML=h;
  El('sceneCount').textContent=scenes.length+' 个场景';
  // update nums after reorder
  renderNums();
}
function renderNums(){
  document.querySelectorAll('.scene-card .num').forEach((el,i)=>{el.textContent='#'+(i+1)});
}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function escAttr(s){return (s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'")}

async function render(){
  let valid=scenes.filter(s=>s.image);
  if(!valid.length){alert('请至少添加一张图片');return}
  const manifest={title:"narravid Video",width:1920,height:1080,tts_engine:"edge",
    voice:El('voice').value,
    speech_speed:parseFloat(El('speed').value),
    burn_subtitles:El('burnSubs').checked,
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold_sec||0}))};
  const bgm=El('bgm').value.trim();
  const titleCard=El('titleCard').value.trim();
  const body={manifest,bgm:bgm||null,title_card:titleCard||null};

  renderId='r'+Math.random().toString(36).slice(2,8);
  El('status').classList.add('show');El('statusMsg').textContent='正在生成视频…';El('renderBtn').disabled=true;

  try{
    const r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,render_id:renderId})});
    const data=await r.json();
    if(data.error)throw new Error(data.error);
    renderId=data.render_id;
    pollRender();
  }catch(e){
    El('status').classList.remove('show');El('renderBtn').disabled=false;
    alert('启动失败: '+e.message);
  }
}

function pollRender(){
  if(!renderId)return;
  fetch('/api/status/'+renderId).then(r=>r.json()).then(data=>{
    if(data.error){doneRender(data.error);return}
    El('statusMsg').textContent=data.progress||'渲染中…';
    if(data.done){doneRender(null,data.video,data.srt);return}
    pollTimer=setTimeout(pollRender,800);
  }).catch(()=>{pollTimer=setTimeout(pollRender,1000)});
}

function doneRender(err,video,srt){
  clearTimeout(pollTimer);El('status').classList.remove('show');El('renderBtn').disabled=false;renderId=null;
  let box=El('resultBox');
  if(err){box.textContent='失败: '+err;box.style.background='#e74c3c';box.classList.add('show')}
  else{box.innerHTML='✅ 完成！ <a href="'+video+'" download>下载视频</a>';box.style.background='#27ae60';box.classList.add('show')}
}
function cancelRender(){
  if(renderId)fetch('/api/cancel/'+renderId,{method:'POST'});
  clearTimeout(pollTimer);El('status').classList.remove('show');El('renderBtn').disabled=false;renderId=null;
}
init();
</script>
</body>
</html>'''

# ── API 后端（同 v1，保持不变）──────────────────────────────────

JOBS = {}
SCRIPT_DIR = ROOT

class APIHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/' or path == '/index.html':
            self._send_html(HTML)
        elif path.startswith('/api/status/'):
            rid = path.split('/')[-1]
            job = JOBS.get(rid)
            if not job:
                self._send_json({'error': 'not found'}, 404)
                return
            done = not (job['proc'] and job['proc'].poll() is None)
            resp = {'done': done, 'progress': job.get('progress', ''), 'video': job.get('video'), 'srt': job.get('srt')}
            if done and job['proc']:
                if job['proc'].returncode == 0:
                    resp['video'] = job.get('video', '')
                    resp['srt'] = job.get('srt', '')
                else:
                    stderr = job['proc'].stderr.read().decode('utf-8', errors='ignore')[-300:] if job['proc'].stderr else ''
                    resp['error'] = f'渲染失败 (code {job["proc"].returncode}): {stderr[-150:]}'
            self._send_json(resp)
        elif self.path.startswith('/rendered/'):
            fp = ROOT / self.path.lstrip('/')
            if fp.exists():
                self.send_response(200)
                ct = 'video/mp4' if fp.suffix == '.mp4' else 'text/plain'
                self.send_header('Content-Type', ct)
                self.send_header('Content-Disposition', f'attachment; filename="{fp.name}"')
                self.end_headers()
                self.wfile.write(fp.read_bytes())
            else:
                self._send_json({'error': 'file not found'}, 404)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/render':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            manifest = data.get('manifest', {})
            bgm = data.get('bgm')
            title_card = data.get('title_card')
            rid = data.get('render_id', str(uuid.uuid4()))
            out_dir = OUT_BASE / rid
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = out_dir / 'manifest.json'
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            cmd = [sys.executable, str(SCRIPT), str(manifest_path), '--output-dir', str(out_dir)]
            if bgm: cmd += ['--bgm', bgm]
            if title_card: cmd += ['--title-card', title_card]
            if not manifest.get('burn_subtitles', True): cmd += ['--no-burn']
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(SCRIPT_DIR))
            JOBS[rid] = {'proc': proc, 'progress': 'TTS 生成中…', 'out_dir': str(out_dir), 'video': '', 'srt': ''}
            def monitor():
                job = JOBS.get(rid)
                if not job: return
                try:
                    proc.wait(timeout=600)
                    mp4s = sorted(out_dir.glob('*.mp4'))
                    srts = sorted(out_dir.glob('*.srt'))
                    if mp4s: job['video'] = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\', '/')
                    if srts: job['srt'] = '/' + str(srts[0].relative_to(ROOT)).replace('\\', '/')
                    job['progress'] = '完成'
                except subprocess.TimeoutExpired:
                    proc.kill(); job['progress'] = '超时'
            threading.Thread(target=monitor, daemon=True).start()
            self._send_json({'render_id': rid, 'status': 'started'})
        elif parsed.path.startswith('/api/cancel/'):
            rid = parsed.path.split('/')[-1]
            job = JOBS.get(rid)
            if job and job['proc']:
                job['proc'].kill(); job['progress'] = '已取消'
            self._send_json({'status': 'cancelled'})
        else:
            self._send_json({'error': 'not found'}, 404)

    def _send_html(self, html):
        self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    def _send_json(self, data, code=200):
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    def log_message(self, fmt, *args): pass

def main():
    parser = argparse.ArgumentParser(description='narravid Web UI'); parser.add_argument('--port', type=int, default=5000); parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args(); OUT_BASE.mkdir(parents=True, exist_ok=True)
    server = HTTPServer((args.host, args.port), APIHandler)
    url = f'http://{args.host}:{args.port}'
    print(f'\n  narravid Web UI 已启动'); print(f'  → 浏览器已自动打开，如未打开请访问 {url}\n')
    import webbrowser; webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\n已停止'); server.shutdown()

if __name__ == '__main__': main()
