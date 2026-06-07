"""
narravid Web UI v3 — 图片上传、缩略图预览、BGM 文件选择、一键生成。

用法:
  python webui.py
  python webui.py --port 8080
"""
import argparse, json, os, shutil, subprocess, sys, threading, time, uuid
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'video_auto.py'
OUT_BASE = ROOT / 'rendered' / 'webui'

# 打包 exe 时自动定位自带 ffmpeg
_ff = getattr(sys, '_MEIPASS', None)
if _ff and (Path(_ff) / 'ffmpeg').is_dir():
    os.environ['PATH'] = str(Path(_ff) / 'ffmpeg') + os.pathsep + os.environ.get('PATH', '')

HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>narravid</title>
<style>
:root{--bg:#f5f3ee;--card:#fff;--ink:#1a1a2e;--muted:#787878;--accent:#c2410c;--border:rgba(0,0,0,.08)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
.app{max-width:1100px;margin:0 auto;padding:24px 20px 80px}
h1{font-size:28px;margin-bottom:2px}
.sub{color:var(--muted);font-size:14px;margin-bottom:18px}

.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-bottom:14px;padding:14px 16px;background:var(--card);border:1px solid var(--border);border-radius:10px;font-size:13px}
.bar label{font-size:11px;color:var(--muted);display:block;margin-bottom:2px}
.bar select,.bar input{padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:#fafafa;font-size:13px}
.bar input[type=range]{padding:0}
.btn{padding:7px 16px;border:1px solid var(--border);border-radius:6px;background:var(--card);cursor:pointer;font-size:13px;transition:.15s}
.btn:hover{background:#f0ede6}
.btn.a{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn.a:hover{opacity:.9}
.row{gap:8px;display:flex;flex-wrap:wrap;align-items:center;margin-bottom:10px}

.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px;display:flex;gap:10px;align-items:flex-start;margin-bottom:8px}
.card .grip{cursor:grab;color:#ccc;font-size:18px;padding-top:8px;user-select:none}
.card .n{font-size:12px;color:var(--muted);min-width:20px;padding-top:9px}
.card .thumb{width:100px;height:62px;border-radius:6px;border:1px solid var(--border);background:#f0f0f0 center/cover;flex-shrink:0;cursor:zoom-in;position:relative}
.card .thumb:hover::after{content:'\1F50D';position:absolute;inset:0;background:rgba(0,0,0,.5);color:#fff;font-size:20px;display:flex;align-items:center;justify-content:center}
.card .body{flex:1;display:flex;flex-direction:column;gap:6px;min-width:0}
.card .body textarea{width:100%;font-size:13px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:#fafafa;resize:vertical;min-height:50px;font-family:inherit}
.card .foot{display:flex;gap:6px;align-items:center;font-size:11px}
.card .foot input{flex:1;padding:5px 7px;border:1px solid var(--border);border-radius:4px;background:#fafafa;font-size:11px;color:var(--muted)}
.card .del{background:none;border:none;color:#c0392b;cursor:pointer;font-size:18px;opacity:.5;padding:0 4px}
.card .del:hover{opacity:1}

.lb{position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:200;cursor:pointer;display:flex;align-items:center;justify-content:center}
.lb img{max-width:92vw;max-height:92vh;border-radius:10px;box-shadow:0 4px 40px rgba(0,0,0,.5)}

.status{position:fixed;bottom:0;left:0;right:0;background:#1a1a2e;color:#fff;padding:14px 20px;font-size:14px;display:none;align-items:center;gap:10px;z-index:100}
.status .spin{width:16px;height:16px;border:2px solid rgba(255,255,255,.2);border-top-color:#fff;border-radius:50%;animation:s .6s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
.result{position:fixed;bottom:56px;left:50%;transform:translateX(-50%);color:#fff;padding:12px 24px;border-radius:10px;display:none;z-index:101;cursor:pointer;font-size:14px}
.result a{color:#fff;font-weight:700}
</style>
</head>
<body>
<div class="app">
<h1>narravid</h1><div class="sub">拖图片到下方 → 写文案 → 点生成</div>

<div class="bar">
<div><label>音色</label><select id="v"><option value="zh-CN-XiaoxiaoNeural">Xiaoxiao(女·温)</option><option value="zh-CN-YunyangNeural">Yunyang(男·专)</option><option value="zh-CN-YunxiNeural">Yunxi(男·轻)</option></select></div>
<div><label>语速 <b id="sv">1.5</b></label><input type="range" id="sp" min="0.8" max="2.2" step="0.05" value="1.5" style="width:90px"></div>
<div><label>标题</label><input id="tc" placeholder="可选" style="width:100px"></div>
<div><label>BGM</label><input type="file" id="bgm" accept="audio/*" style="width:160px;font-size:11px"></div>
<div style="display:flex;align-items:flex-end"><label style="cursor:pointer;font-size:13px;display:flex;gap:4px"><input type="checkbox" id="bs" checked>烧录字幕</label></div>
</div>

<div class="row">
  <button class="btn a" onclick="batch()">+ 批量添加图片</button>
  <button class="btn" onclick="add()">+ 空场景</button>
  <button class="btn a" id="rb" onclick="render()">▶ 生成视频</button>
</div>

<div id="list"></div>
</div>

<div class="status" id="st"><div class="spin"></div><div id="sm">准备中</div><span onclick="cancel()" style="color:#e74c3c;cursor:pointer">✕</span></div>
<div class="result" id="rs" onclick="this.style.display='none'"></div>
<script>
let S=[],rid=null,tmr=null;
const E=id=>document.getElementById(id);

function init(){
  E('sp').oninput=()=>E('sv').textContent=E('sp').value;
  add();add();add();
}
function batch(){
  let i=document.createElement('input');i.type='file';i.multiple=true;i.accept='image/*';
  i.onchange=()=>handleImg(i.files);i.click();
}
function add(img,txt,hold){S.push({image:img||'',text:txt||'',hold:hold||0});pain()}
function del(i){S.splice(i,1);pain()}
function chImg(i){
  let inp=document.createElement('input');inp.type='file';inp.accept='image/*';
  inp.onchange=()=>{if(inp.files[0]){S[i].image=inp.files[0].name;upImg(i,inp.files[0])}};
  inp.click();
}
let imgCache={};
function upImg(i,file){
  let r=new FileReader();r.onload=()=>{imgCache[S[i].image]=r.result;pain()};
  if(file)r.readAsDataURL(file);
}
function handleImg(files){
  let next=0;
  for(let f of Array.from(files)){
    if(!f.type.startsWith('image/'))continue;
    let idx=S.findIndex((s,i)=>i>=next&&!s.image);
    if(idx>=0){S[idx].image=f.name;upImg(idx,f);next=idx+1}
    else{S.push({image:f.name,text:'',hold:0});upImg(S.length-1,f)}
  }
  pain();
}
function thumbUrl(i){
  let img=S[i].image;
  if(!img)return'';
  if(imgCache[img])return imgCache[img];
  return'/thumb?path='+encodeURIComponent(img);
}
function lightbox(i){
  let u=thumbUrl(i);if(!u)return;
  let d=document.createElement('div');d.className='lb';d.onclick=()=>d.remove();
  let el=document.createElement('img');el.src=u;d.appendChild(el);
  document.body.appendChild(d);
}
let dragFrom=null;
function dragS(i,e){dragFrom=i}
function dropS(i,e){e.preventDefault();if(dragFrom===null||dragFrom===i)return;let t=S.splice(dragFrom,1)[0];S.splice(i,0,t);pain()}
function pain(){
  let h='';
  S.forEach((s,i)=>{
    let tu=thumbUrl(i);
    let bg=tu?' style="background-image:url('+tu+')"':'';
    let path=s.image||'';
    h+='<div class="card" draggable="true" ondragstart="dragS('+i+',event)" ondragover="event.preventDefault()" ondrop="dropS('+i+',event)">'
      +'<div class="grip">\u281F</div><div class="n">#'+(i+1)+'</div>'
      +'<div class="thumb"'+bg+' onclick="lightbox('+i+')"></div>'
      +'<div class="body">'
        +'<textarea placeholder="解说文案（按句号切字幕）。留空=只展示图片" onchange="S['+i+'].text=this.value">'+esc(s.text)+'</textarea>'
        +'<div class="foot">'
          +'<span>'+esc(path)+'</span>'
          +'<input type="number" placeholder="多停秒" style="width:60px" value="'+(s.hold||'')+'" onchange="S['+i+'].hold=parseFloat(this.value)||0">'
          +'<button class="btn" onclick="chImg('+i+')" style="font-size:11px;padding:3px 8px">换图</button>'
          +'<button class="del" onclick="del('+i+')">×</button>'
        +'</div>'
      +'</div></div>';
  });
  E('list').innerHTML=h;
}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

async function render(){
  let valid=S.filter(s=>s.image);
  if(!valid.length){alert('请至少添加一张图片');return}
  let bgm=null;
  if(E('bgm').files.length>0)bgm=E('bgm').files[0].name;
  let m={title:'narravid',width:1920,height:1080,tts_engine:'edge',
    voice:E('v').value,speech_speed:parseFloat(E('sp').value),burn_subtitles:E('bs').checked,
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold||0}))};
  let body={manifest:m,bgm:bgm,title_card:E('tc').value.trim()||null};
  rid='r'+Math.random().toString(36).slice(2,8);
  E('st').style.display='flex';E('sm').textContent='正在生成视频...';E('rb').disabled=true;
  try{
    let r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,render_id:rid})});
    let d=await r.json();
    if(d.error)throw new Error(d.error);
    rid=d.render_id;poll();
  }catch(e){done(e.message)}
}
function poll(){
  if(!rid)return;
  fetch('/api/status/'+rid).then(r=>r.json()).then(d=>{
    if(d.error){done(d.error);return}
    E('sm').textContent=d.progress||'渲染中';
    if(d.done){done(null,d.video);return}
    tmr=setTimeout(poll,800);
  }).catch(()=>{tmr=setTimeout(poll,1000)});
}
function done(err,video){
  clearTimeout(tmr);E('st').style.display='none';E('rb').disabled=false;rid=null;
  let b=E('rs');
  if(err){b.textContent='失败: '+err;b.style.background='#e74c3c';b.style.display='block'}
  else{b.innerHTML='完成！<a href="'+video+'" download>下载视频</a>';b.style.background='#27ae60';b.style.display='block'}
}
function cancel(){if(rid)fetch('/api/cancel/'+rid,{method:'POST'});clearTimeout(tmr);E('st').style.display='none';E('rb').disabled=false;rid=null}
document.addEventListener('dragover',e=>e.preventDefault());
document.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files.length)handleImg(e.dataTransfer.files)});
init();
</script>
</body>
</html>'''

JOBS = {}

class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == '/' or p.path == '/index.html':
            self._html(HTML)
        elif p.path.startswith('/thumb'):
            qs = urllib.parse.parse_qs(p.query)
            img = qs.get('path', [None])[0]
            if img:
                fp = Path(img)
                # also try relative to cwd and ROOT
                if not fp.is_absolute():
                    for base in [Path.cwd(), ROOT, ROOT / 'examples-assets']:
                        cand = base / fp
                        if cand.exists(): fp = cand; break
                if fp.exists():
                    self._file(fp, 'image/png' if fp.suffix=='.png' else 'image/jpeg')
                    return
            self._json({'error':'not found'}, 404)
        elif p.path.startswith('/api/status/'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if not j: self._json({'error':'not found'}, 404); return
            done = not (j['proc'] and j['proc'].poll() is None)
            resp = {'done': done, 'progress': j.get('progress',''), 'video': j.get('video'), 'srt': j.get('srt')}
            if done and j['proc']:
                if j['proc'].returncode == 0:
                    resp['video'] = j.get('video','')
                else:
                    err = j['proc'].stderr.read().decode('utf-8','ignore')[-300:] if j['proc'].stderr else ''
                    resp['error'] = f'渲染失败 (code {j["proc"].returncode}): {err[-150:]}'
            self._json(resp)
        elif p.path.startswith('/rendered/'):
            fp = ROOT / p.path.lstrip('/')
            if fp.exists(): self._file(fp, 'video/mp4' if fp.suffix=='.mp4' else 'text/plain')
            else: self._json({'error':'not found'}, 404)
        else:
            super().do_GET()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length',0))
        body = self.rfile.read(length) if length else b''
        if p.path == '/api/render':
            data = json.loads(body)
            m = data.get('manifest',{})
            # 把所有图片路径转为绝对路径，避免 video_auto.py 解析错
            for s in m.get('scenes',[]):
                img = s.get('image','')
                if img and not Path(img).is_absolute():
                    resolved = Path(img).resolve()
                    if resolved.exists():
                        s['image'] = str(resolved)
            bgm = data.get('bgm')
            tc = data.get('title_card')
            rid = data.get('render_id', str(uuid.uuid4()))
            out = OUT_BASE / rid; out.mkdir(parents=True, exist_ok=True)
            mp = out / 'manifest.json'
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
            cmd = [sys.executable, str(SCRIPT), str(mp), '--output-dir', str(out)]
            if bgm: cmd += ['--bgm', bgm]
            if tc: cmd += ['--title-card', tc]
            if not m.get('burn_subtitles',True): cmd += ['--no-burn']
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT))
            JOBS[rid] = {'proc': proc, 'progress': 'TTS 生成中...', 'video': '', 'srt': ''}
            def mon():
                j = JOBS.get(rid)
                if not j: return
                try:
                    proc.wait(timeout=600)
                    mp4s = sorted(out.glob('*.mp4'))
                    if mp4s: j['video'] = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\','/')
                    j['progress'] = '完成'
                except subprocess.TimeoutExpired:
                    proc.kill(); j['progress'] = '超时'
            threading.Thread(target=mon, daemon=True).start()
            self._json({'render_id': rid})
        elif p.path.startswith('/api/cancel/'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if j and j['proc']: j['proc'].kill()
            self._json({'status':'ok'})
        else:
            self._json({'error':'not found'}, 404)

    def _html(self, html):
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    def _json(self, data, code=200):
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    def _file(self, fp, ct):
        self.send_response(200); self.send_header('Content-Type', ct)
        self.send_header('Content-Disposition', f'attachment; filename="{fp.name}"')
        self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers(); self.wfile.write(fp.read_bytes())
    def log_message(self, fmt, *args): pass

def main():
    ap = argparse.ArgumentParser(description='narravid Web UI')
    ap.add_argument('--port', type=int, default=5000); ap.add_argument('--host', default='127.0.0.1')
    args = ap.parse_args()
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    srv = HTTPServer((args.host, args.port), H)
    url = f'http://{args.host}:{args.port}'
    print(f'narravid Web UI: {url}')
    try:
        import webbrowser; webbrowser.open(url)
    except Exception:
        pass
    try: srv.serve_forever()
    except KeyboardInterrupt: print('stopped'); srv.shutdown()

if __name__ == '__main__': main()
