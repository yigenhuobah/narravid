"""
narravid Web UI — 浏览器里拖图片、写文案、点生成，一行命令都不用敲。

用法:
  python webui.py
  python webui.py --port 8080

然后打开浏览器访问 http://localhost:5000
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'video_auto.py'
OUT_BASE = ROOT / 'rendered' / 'webui'

# ── 内嵌前端 HTML ────────────────────────────────────────────────

HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>narravid</title>
<style>
:root {--bg:#f5f3ee;--card:#fff;--ink:#1a1a2e;--muted:#787878;--accent:#c2410c;--border:rgba(0,0,0,.08);}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
.app{max-width:1100px;margin:0 auto;padding:24px 20px 80px}
h1{font-size:28px;font-weight:700;margin-bottom:4px}
.sub{color:var(--muted);font-size:14px;margin-bottom:24px}

.topbar{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:20px;padding:18px 20px;background:var(--card);border:1px solid var(--border);border-radius:10px}
.topbar label{font-size:12px;color:var(--muted);display:block;margin-bottom:4px}
.topbar input,.topbar select{font-size:14px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:#fafafa;min-width:120px}
.topbar input[type=range]{min-width:80px;padding:0}
.speed-val{font-size:14px;font-weight:700;min-width:36px;text-align:center}

.controls{margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap}
.controls button{font-size:13px;padding:8px 18px;border:1px solid var(--border);border-radius:6px;background:var(--card);cursor:pointer;transition:.15s}
.controls button:hover{background:#f0ede6}
.controls button.accent{background:var(--accent);color:#fff;border-color:var(--accent)}
.controls button.accent:hover{opacity:.9}

.scene-list{display:flex;flex-direction:column;gap:14px}
.scene-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 18px;display:flex;gap:16px;align-items:flex-start}
.scene-card .num{font-size:13px;font-weight:700;color:var(--muted);min-width:24px;padding-top:10px}
.scene-card .body{flex:1;display:flex;flex-direction:column;gap:10px}
.scene-card .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.scene-card input[type=text]{flex:1;font-size:13px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:#fafafa}
.scene-card textarea{width:100%;font-size:14px;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:#fafafa;resize:vertical;min-height:60px;font-family:inherit;line-height:1.6}
.scene-card .hold{width:70px}
.scene-card .del-btn{background:none;border:none;color:#c0392b;cursor:pointer;font-size:18px;padding:4px 8px;opacity:.6}
.scene-card .del-btn:hover{opacity:1}

.status{position:fixed;bottom:0;left:0;right:0;background:#1a1a2e;color:#fff;padding:14px 24px;font-size:14px;display:none;align-items:center;gap:12px;z-index:100}
.status.show{display:flex}
.status .spinner{width:18px;height:18px;border:2px solid rgba(255,255,255,.2);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.status .msg{flex:1}
.status .cancel{color:#e74c3c;cursor:pointer;font-weight:700}
.result{position:fixed;bottom:60px;left:50%;transform:translateX(-50%);background:#27ae60;color:#fff;padding:12px 28px;border-radius:10px;font-size:15px;display:none;z-index:101;cursor:pointer}
.result.show{display:block}
</style>
</head>
<body>
<div class="app">
<h1>narravid</h1>
<div class="sub">图片 + 文案 → 解说视频，浏览器里一键生成</div>

<div class="topbar">
  <div>
    <label>音色</label>
    <select id="voice"><option value="zh-CN-XiaoxiaoNeural">Xiaoxiao (女·温暖)</option><option value="zh-CN-XiaoyiNeural">Xiaoyi (女·活泼)</option><option value="zh-CN-YunxiNeural">Yunxi (男·轻快)</option><option value="zh-CN-YunyangNeural">Yunyang (男·专业)</option><option value="zh-CN-YunjianNeural">Yunjian (男·热情)</option></select>
  </div>
  <div>
    <label>语速</label>
    <div style="display:flex;align-items:center;gap:8px">
      <input type="range" id="speed" min="0.8" max="2.2" step="0.05" value="1.5">
      <span class="speed-val" id="speedVal">1.5</span>
    </div>
  </div>
  <div>
    <label>标题文字</label>
    <input type="text" id="titleCard" placeholder="可选，留空则不生成" style="width:180px">
  </div>
  <div>
    <label>背景音乐</label>
    <input type="text" id="bgm" placeholder="可选，mp3 路径" style="width:160px">
  </div>
  <div style="display:flex;align-items:flex-end">
    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin-bottom:0;font-size:14px">
      <input type="checkbox" id="burnSubs" checked> 烧录字幕
    </label>
  </div>
</div>

<div class="controls">
  <button onclick="addScene()" class="accent">+ 添加场景</button>
  <button id="renderBtn" onclick="render()">▶ 生成视频</button>
</div>

<div class="scene-list" id="sceneList"></div>
</div>

<div class="status" id="status"><div class="spinner"></div><div class="msg" id="statusMsg">准备中…</div><div class="cancel" onclick="cancelRender()">取消</div></div>
<div class="result" id="resultBox" onclick="this.classList.remove('show')"></div>

<script>
let scenes=[];
let renderId=null,pollTimer=null,statusEl,resultEl,statusMsg;

function init(){
  statusEl=document.getElementById('status');resultEl=document.getElementById('resultBox');statusMsg=document.getElementById('statusMsg');
  document.getElementById('speed').oninput=function(){document.getElementById('speedVal').textContent=this.value};
  addScene();addScene();addScene();
}
function addScene(img,text,hold){
  scenes.push({image:img||'',text:text||'',hold_sec:hold||0});
  renderList();
}
function removeScene(i){scenes.splice(i,1);renderList();}
function renderList(){
  let h='';
  scenes.forEach((s,i)=>{
    h+=`<div class="scene-card">
      <div class="num">${i+1}</div>
      <div class="body">
        <div class="row">
          <input type="text" placeholder="图片路径（拖图片到桌面 → 复制路径粘贴到这里）" value="${esc(s.image)}" onchange="scenes[${i}].image=this.value">
          <input class="hold" type="number" placeholder="多停秒" value="${s.hold_sec||''}" onchange="scenes[${i}].hold_sec=parseFloat(this.value)||0" title="解说结束后额外停留秒数">
          <button class="del-btn" onclick="removeScene(${i})" title="删除">×</button>
        </div>
        <textarea placeholder="解说文案（按句号自动切字幕）。留空则只展示图片不出声" onchange="scenes[${i}].text=this.value">${esc(s.text)}</textarea>
      </div>
    </div>`;
  });
  document.getElementById('sceneList').innerHTML=h;
}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

async function render(){
  const manifest={title:"narravid Video",width:1920,height:1080,tts_engine:"edge",
    voice:document.getElementById('voice').value,
    speech_speed:parseFloat(document.getElementById('speed').value),
    burn_subtitles:document.getElementById('burnSubs').checked,
    scenes:scenes.filter(s=>s.image).map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold_sec||0}))};
  const bgm=document.getElementById('bgm').value.trim();
  const titleCard=document.getElementById('titleCard').value.trim();
  const body={manifest,bgm:bgm||null,title_card:titleCard||null};

  renderId=uuid();
  statusEl.classList.add('show');statusMsg.textContent='正在生成视频…';
  document.getElementById('renderBtn').disabled=true;

  try{
    const r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,render_id:renderId})});
    const data=await r.json();
    if(data.error){throw new Error(data.error);}
    renderId=data.render_id;
    pollRender();
  }catch(e){
    statusEl.classList.remove('show');
    document.getElementById('renderBtn').disabled=false;
    alert('启动失败: '+e.message);
  }
}

function uuid(){return 'xxxx-xxxx'.replace(/x/g,()=>(Math.random()*16|0).toString(16));}

function pollRender(){
  if(!renderId)return;
  fetch('/api/status/'+renderId).then(r=>r.json()).then(data=>{
    if(data.error){doneRender(data.error);return;}
    statusMsg.textContent=data.progress||'渲染中…';
    if(data.done){doneRender(null,data.video,data.srt);return;}
    pollTimer=setTimeout(pollRender,800);
  }).catch(()=>{pollTimer=setTimeout(pollRender,1000);});
}

function doneRender(err,video,srt){
  clearTimeout(pollTimer);
  statusEl.classList.remove('show');
  document.getElementById('renderBtn').disabled=false;
  renderId=null;
  if(err){
    resultEl.textContent='失败: '+err;resultEl.style.background='#e74c3c';resultEl.classList.add('show');
  }else{
    let msg='生成完成！';
    if(srt){msg+=` 字幕已保存。`;}
    resultEl.innerHTML=msg+` <a href="${video}" download style="color:#fff;text-decoration:underline;font-weight:700">下载视频</a>`;
    resultEl.style.background='#27ae60';resultEl.classList.add('show');
  }
}

function cancelRender(){
  if(renderId){fetch('/api/cancel/'+renderId,{method:'POST'});}
  clearTimeout(pollTimer);
  statusEl.classList.remove('show');
  document.getElementById('renderBtn').disabled=false;
  renderId=null;
}
init();
</script>
</body>
</html>'''

# ── API 后端 ──────────────────────────────────────────────────────

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
            done = not job['proc'].poll() if job['proc'] else True
            resp = {
                'done': done,
                'progress': job.get('progress', ''),
                'video': job.get('video'),
                'srt': job.get('srt'),
            }
            if done and job['proc']:
                if job['proc'].returncode == 0:
                    resp['video'] = job.get('video', '')
                    resp['srt'] = job.get('srt', '')
                else:
                    stderr = job['proc'].stderr.read().decode('utf-8', errors='ignore')[-500:] if job['proc'].stderr else ''
                    resp['error'] = f'渲染失败 (code {job["proc"].returncode}): {stderr[-200:]}'
            self._send_json(resp)
        elif self.path.startswith('/rendered/'):
            # serve rendered files
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
            if bgm:
                cmd += ['--bgm', bgm]
            if title_card:
                cmd += ['--title-card', title_card]
            if not manifest.get('burn_subtitles', True):
                cmd += ['--no-burn']

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(SCRIPT_DIR))
            JOBS[rid] = {
                'proc': proc,
                'progress': 'TTS 生成中…',
                'out_dir': str(out_dir),
                'video': '',
                'srt': '',
            }

            # background thread to monitor progress
            def monitor():
                job = JOBS.get(rid)
                if not job:
                    return
                try:
                    proc.wait(timeout=600)
                    # find output files
                    mp4s = sorted(out_dir.glob('*.mp4'))
                    srts = sorted(out_dir.glob('*.srt'))
                    if mp4s:
                        job['video'] = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\', '/')
                    if srts:
                        job['srt'] = '/' + str(srts[0].relative_to(ROOT)).replace('\\', '/')
                    job['progress'] = '完成'
                except subprocess.TimeoutExpired:
                    proc.kill()
                    job['progress'] = '超时'

            threading.Thread(target=monitor, daemon=True).start()

            self._send_json({'render_id': rid, 'status': 'started'})

        elif parsed.path.startswith('/api/cancel/'):
            rid = parsed.path.split('/')[-1]
            job = JOBS.get(rid)
            if job and job['proc']:
                job['proc'].kill()
                job['progress'] = '已取消'
            self._send_json({'status': 'cancelled'})
        else:
            self._send_json({'error': 'not found'}, 404)

    def _send_html(self, html: str):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, fmt, *args):
        pass  # 静音 HTTP 日志


def main():
    parser = argparse.ArgumentParser(description='narravid Web UI')
    parser.add_argument('--port', type=int, default=5000, help='端口 (默认 5000)')
    parser.add_argument('--host', default='127.0.0.1', help='绑定地址')
    args = parser.parse_args()

    OUT_BASE.mkdir(parents=True, exist_ok=True)

    server = HTTPServer((args.host, args.port), APIHandler)
    url = f'http://{args.host}:{args.port}'
    print(f'\n  narravid Web UI 已启动')
    print(f'  → 浏览器已自动打开，如未打开请访问 {url}\n')

    # 自动打开浏览器
    import webbrowser
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
        server.shutdown()


if __name__ == '__main__':
    main()
