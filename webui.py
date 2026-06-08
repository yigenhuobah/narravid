"""
narravid Web UI v4 — 图片上传到服务器、缩略图预览、BGM 文件选择、一键生成。

用法:
  python webui.py
  python webui.py --port 8080
"""
import argparse, base64, json, os, shutil, subprocess, sys, threading, time, uuid
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'video_auto.py'
OUT_BASE = ROOT / 'rendered' / 'webui'
UPLOAD_DIR = OUT_BASE / 'uploads'

# 统一使用 _bundled_ffmpeg 模块定位自带 ffmpeg
try:
    import _bundled_ffmpeg
except ImportError:
    pass

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── 允许 /thumb 访问的目录白名单 ─────────────────────────────────
THUMB_ALLOWED_DIRS = [UPLOAD_DIR.resolve(), (ROOT / 'examples-assets').resolve()]

HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>narravid</title>
<style>
:root{
  --bg:#0f0f13;--surface:#1a1a24;--surface2:#24243a;--ink:#e8e6e1;--muted:#8888a0;
  --accent:#e85d26;--accent2:#ff8c42;--border:rgba(255,255,255,.06);--border2:rgba(255,255,255,.12);
  --radius:12px;--shadow:0 2px 16px rgba(0,0,0,.4);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif;background:var(--bg);color:var(--ink);line-height:1.6;min-height:100vh}

/* ── 顶部标题栏 ── */
.header{padding:28px 24px 0;max-width:1120px;margin:0 auto}
.header h1{font-size:32px;font-weight:800;letter-spacing:-.5px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .sub{color:var(--muted);font-size:14px;margin-top:4px}

/* ── 设置面板 ── */
.panel{max-width:1120px;margin:20px auto 0;padding:0 24px;display:grid;grid-template-columns:1fr 1fr;gap:12px}
.panel .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px}
.panel .card h3{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}
.field:last-child{margin-bottom:0}
.field label{font-size:12px;color:var(--muted);font-weight:500}
.field select,.field input[type=text]{padding:8px 10px;border:1px solid var(--border2);border-radius:8px;background:var(--surface2);color:var(--ink);font-size:13px;outline:none;transition:.15s}
.field select:focus,.field input[type=text]:focus{border-color:var(--accent)}
.field select option{background:var(--surface);color:var(--ink)}
.range-row{display:flex;align-items:center;gap:10px}
.range-row input[type=range]{flex:1;-webkit-appearance:none;height:6px;border-radius:3px;background:var(--surface2);outline:none}
.range-row input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:var(--accent);cursor:pointer;box-shadow:0 0 8px rgba(232,93,38,.4)}
.range-row .val{font-size:14px;font-weight:700;color:var(--accent);min-width:36px;text-align:right}
.chk-row{display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;margin-top:2px}
.chk-row input[type=checkbox]{accent-color:var(--accent);width:16px;height:16px}

/* ── 操作栏 ── */
.actions{max-width:1120px;margin:16px auto 0;padding:0 24px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.btn{padding:9px 20px;border:1px solid var(--border2);border-radius:8px;background:var(--surface);color:var(--ink);cursor:pointer;font-size:13px;font-weight:500;transition:.2s;user-select:none}
.btn:hover{background:var(--surface2);border-color:rgba(255,255,255,.2)}
.btn.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border:none;font-weight:700;padding:10px 28px;font-size:15px;box-shadow:0 4px 20px rgba(232,93,38,.3)}
.btn.primary:hover{opacity:.9;transform:translateY(-1px);box-shadow:0 6px 24px rgba(232,93,38,.4)}
.btn.primary:disabled{opacity:.4;cursor:not-allowed;transform:none}
.btn:disabled{opacity:.35;cursor:not-allowed}
.upload-stats{font-size:12px;color:var(--muted);margin-left:auto}

/* ── 场景列表 ── */
.scenes{max-width:1120px;margin:16px auto 80px;padding:0 24px}
.scene{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;display:flex;gap:14px;align-items:flex-start;margin-bottom:10px;transition:.2s}
.scene:hover{border-color:var(--border2)}
.scene .grip{cursor:grab;color:#555;font-size:20px;padding-top:14px;user-select:none;transition:.15s}
.scene .grip:hover{color:var(--muted)}
.scene .idx{font-size:13px;color:var(--muted);font-weight:700;min-width:24px;padding-top:14px}
.scene .thumb{width:128px;height:80px;border-radius:8px;border:1px solid var(--border2);background:var(--surface2) center/cover;flex-shrink:0;cursor:zoom-in;position:relative;overflow:hidden}
.scene .thumb:hover::after{content:'🔍';position:absolute;inset:0;background:rgba(0,0,0,.55);color:#fff;font-size:22px;display:flex;align-items:center;justify-content:center}
.scene .body{flex:1;display:flex;flex-direction:column;gap:8px;min-width:0}
.scene textarea{width:100%;font-size:14px;padding:10px 12px;border:1px solid var(--border2);border-radius:8px;background:var(--surface2);color:var(--ink);resize:vertical;min-height:56px;font-family:inherit;line-height:1.5;outline:none;transition:.15s}
.scene textarea:focus{border-color:var(--accent);background:rgba(36,36,58,.8)}
.scene textarea::placeholder{color:var(--muted)}
.scene .foot{display:flex;gap:8px;align-items:center;font-size:12px;flex-wrap:wrap}
.scene .foot .path{flex:1;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px;font-size:11px}
.scene .hold-input{width:64px;padding:5px 8px;border:1px solid var(--border2);border-radius:6px;background:var(--surface2);color:var(--ink);font-size:12px;text-align:center}
.scene .foot .btn-sm{padding:4px 10px;font-size:11px;border:1px solid var(--border2);border-radius:6px;background:var(--surface2);color:var(--ink);cursor:pointer;transition:.15s}
.scene .foot .btn-sm:hover{background:var(--accent);color:#fff;border-color:var(--accent)}
.scene .del{background:none;border:none;color:#666;cursor:pointer;font-size:20px;padding:0 2px;transition:.15s}
.scene .del:hover{color:#e74c3c}

/* ── 灯箱 ── */
.lb{position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:200;cursor:pointer;display:flex;align-items:center;justify-content:center;animation:fadeIn .2s}
.lb img{max-width:92vw;max-height:92vh;border-radius:12px;box-shadow:0 8px 60px rgba(0,0,0,.7)}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}

/* ── 底部状态栏 ── */
.status-bar{position:fixed;bottom:0;left:0;right:0;background:var(--surface);border-top:1px solid var(--border2);padding:0;z-index:100;display:none}
.status-bar .progress-track{height:4px;background:var(--surface2)}
.status-bar .progress-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));width:0;transition:width .5s}
.status-bar .status-body{padding:12px 20px;display:flex;align-items:center;gap:12px;font-size:14px}
.status-bar .spin{width:16px;height:16px;border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:sp .6s linear infinite;flex-shrink:0}
@keyframes sp{to{transform:rotate(360deg)}}
.status-bar .msg{flex:1}
.status-bar .cancel-btn{color:#e74c3c;cursor:pointer;font-size:16px;padding:2px 6px;border-radius:4px;transition:.15s}
.status-bar .cancel-btn:hover{background:rgba(231,76,60,.15)}

/* ── 结果提示 ── */
.result{position:fixed;bottom:64px;left:50%;transform:translateX(-50%);color:#fff;padding:14px 28px;border-radius:12px;display:none;z-index:101;cursor:pointer;font-size:14px;font-weight:500;box-shadow:var(--shadow);animation:slideUp .3s}
.result a{color:#fff;font-weight:700;text-decoration:underline}
@keyframes slideUp{from{transform:translateX(-50%) translateY(20px);opacity:0}to{transform:translateX(-50%) translateY(0);opacity:1}}

/* ── 空状态 ── */
.empty{text-align:center;padding:60px 20px;color:var(--muted)}
.empty .icon{font-size:48px;margin-bottom:12px;opacity:.5}
.empty p{font-size:15px;margin-bottom:4px}
.empty .hint{font-size:13px;opacity:.6}

/* ── 响应式 ── */
@media(max-width:768px){
  .panel{grid-template-columns:1fr}
  .scene .thumb{width:80px;height:50px}
  .header h1{font-size:24px}
}
</style>
</head>
<body>

<div class="header">
  <h1>narravid</h1>
  <div class="sub">图片 + 文案 → 解说视频，一键生成</div>
</div>

<div class="panel">
  <div class="card">
    <h3>🎙 语音设置</h3>
    <div class="field">
      <label>TTS 音色</label>
      <select id="v">
        <option value="zh-CN-XiaoxiaoNeural">Xiaoxiao · 女声温暖</option>
        <option value="zh-CN-YunyangNeural">Yunyang · 男声播报</option>
        <option value="zh-CN-YunxiNeural">Yunxi · 男声轻快</option>
        <option value="zh-CN-YunjianNeural">Yunjian · 男声讲述</option>
      </select>
    </div>
    <div class="field">
      <label>语速</label>
      <div class="range-row">
        <input type="range" id="sp" min="0.8" max="2.2" step="0.05" value="1.5">
        <span class="val" id="sv">1.5x</span>
      </div>
    </div>
    <label class="chk-row"><input type="checkbox" id="bs" checked>烧录字幕到视频</label>
  </div>

  <div class="card">
    <h3>🎬 输出设置</h3>
    <div class="field">
      <label>标题页文字</label>
      <input type="text" id="tc" placeholder="留空则不生成标题页">
    </div>
    <div class="field">
      <label>背景音乐 (BGM)</label>
      <input type="file" id="bgm" accept="audio/*" style="font-size:12px;color:var(--muted)">
    </div>
    <div class="field">
      <label>并行线程数</label>
      <select id="wk">
        <option value="1">1 · 串行（调试用）</option>
        <option value="2">2 线程</option>
        <option value="4" selected>4 线程（推荐）</option>
        <option value="8">8 线程</option>
        <option value="16">16 线程</option>
      </select>
    </div>
  </div>
</div>

<div class="actions">
  <button class="btn primary" id="rb" onclick="render()">▶ 生成视频</button>
  <button class="btn" onclick="batch()">+ 添加图片</button>
  <button class="btn" onclick="add()">+ 空场景</button>
  <span class="upload-stats" id="ustats"></span>
</div>

<div class="scenes" id="list"></div>

<div class="status-bar" id="st">
  <div class="progress-track"><div class="progress-fill" id="pf"></div></div>
  <div class="status-body">
    <div class="spin"></div>
    <div class="msg" id="sm">准备中</div>
    <div class="cancel-btn" onclick="cancel()">✕</div>
  </div>
</div>
<div class="result" id="rs" onclick="this.style.display='none'"></div>

<script>
let S=[],rid=null,tmr=null,uploading=0;
const E=id=>document.getElementById(id);

function init(){
  E('sp').oninput=()=>E('sv').textContent=parseFloat(E('sp').value).toFixed(2)+'x';
  add();add();add();
}

async function uploadFile(file){
  return new Promise((resolve,reject)=>{
    let r=new FileReader();
    r.onload=async()=>{
      try{
        let b64=r.result.split(',')[1];
        let resp=await fetch('/api/upload',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({name:file.name,data:b64})});
        let d=await resp.json();
        if(d.error)reject(d.error);else resolve(d.path);
      }catch(e){reject(e.message)}
    };
    r.onerror=()=>reject('read error');
    r.readAsDataURL(file);
  });
}

async function batch(){
  let inp=document.createElement('input');inp.type='file';inp.multiple=true;inp.accept='image/*';
  inp.onchange=async()=>{
    if(!inp.files.length)return;
    let files=Array.from(inp.files);
    uploading=files.length;updateStats();
    let next=0;
    for(let f of files){
      if(!f.type.startsWith('image/')){uploading--;continue}
      let idx=S.findIndex((s,i)=>i>=next&&!s.image);
      let sidx=idx>=0?idx:S.length;
      if(idx<0){S.push({image:'',text:'',hold:0});next=S.length-1}
      else next=idx+1;
      pain();
      try{let path=await uploadFile(f);S[sidx].image=path;S[sidx]._name=f.name}
      catch(e){console.error('upload',e)}
      uploading--;updateStats();pain();
    }
  };
  inp.click();
}

function handleDrop(files){
  let next=0;
  for(let f of Array.from(files)){
    if(!f.type.startsWith('image/'))continue;
    let idx=S.findIndex((s,i)=>i>=next&&!s.image);
    let sidx=idx>=0?idx:S.length;
    if(idx<0){S.push({image:'',text:'',hold:0});next=S.length-1}
    else next=idx+1;
    pain();
    uploading++;updateStats();
    uploadFile(f).then(path=>{S[sidx].image=path;S[sidx]._name=f.name})
    .catch(e=>console.error('upload',e))
    .finally(()=>{uploading--;updateStats();pain()});
  }
}

function add(img,txt,hold){S.push({image:img||'',text:txt||'',hold:hold||0});pain()}
function del(i){S.splice(i,1);pain()}
function chImg(i){
  let inp=document.createElement('input');inp.type='file';inp.accept='image/*';
  inp.onchange=async()=>{
    if(!inp.files[0])return;
    uploading++;updateStats();pain();
    try{let path=await uploadFile(inp.files[0]);S[i].image=path;S[i]._name=inp.files[0].name}
    catch(e){console.error(e)}
    uploading--;updateStats();pain();
  };
  inp.click();
}
function updateStats(){
  E('ustats').textContent=uploading>0?uploading+' 张上传中...':'';
}
function thumbUrl(i){
  let img=S[i].image;
  if(!img)return'';
  return'/thumb?path='+encodeURIComponent(img);
}
function lightbox(i){
  let u=thumbUrl(i);if(!u)return;
  let d=document.createElement('div');d.className='lb';d.onclick=()=>d.remove();
  let el=document.createElement('img');el.src=u;d.appendChild(el);
  document.body.appendChild(d);
}
let dragFrom=null;
function dragS(i){dragFrom=i}
function dropS(i,e){e.preventDefault();if(dragFrom===null||dragFrom===i)return;let t=S.splice(dragFrom,1)[0];S.splice(i,0,t);pain()}

function pain(){
  if(!S.length){
    E('list').innerHTML='<div class="empty"><div class="icon">🎞</div><p>还没有场景</p><div class="hint">点击「添加图片」或将图片拖入此页面</div></div>';
    return;
  }
  let h='';
  S.forEach((s,i)=>{
    let tu=thumbUrl(i);
    let bg=tu?' style="background-image:url('+tu+')"':'';
    let nm=s._name||(s.image?s.image.split('/').pop().split('\\').pop():'');
    h+='<div class="scene" draggable="true" ondragstart="dragS('+i+',event)" ondragover="event.preventDefault()" ondrop="dropS('+i+',event)">'
      +'<div class="grip" title="拖拽排序">⠿</div>'
      +'<div class="idx">#'+(i+1)+'</div>'
      +'<div class="thumb"'+bg+' onclick="lightbox('+i+')"></div>'
      +'<div class="body">'
        +'<textarea placeholder="输入解说文案（按句号自动切字幕）" onchange="S['+i+'].text=this.value">'+esc(s.text)+'</textarea>'
        +'<div class="foot">'
          +'<span class="path">'+esc(nm||'未上传图片')+'</span>'
          +'<input class="hold-input" type="number" placeholder="停顿秒" value="'+(s.hold||'')+'" onchange="S['+i+'].hold=parseFloat(this.value)||0" title="场景末尾额外停留秒数">'
          +'<button class="btn-sm" onclick="chImg('+i+')">换图</button>'
          +'<button class="del" onclick="del('+i+')" title="删除场景">×</button>'
        +'</div>'
      +'</div></div>';
  });
  E('list').innerHTML=h;
}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

/* ── 进度解析 ── */
function parseProgress(text){
  if(!text)return 5;
  let m=text.match(/\[(\d+)\/(\d+)\]/);
  if(m)return Math.round(parseInt(m[1])/parseInt(m[2])*100);
  if(text.includes('完成'))return 100;
  if(text.includes('TTS'))return 15;
  if(text.includes('渲染'))return 50;
  if(text.includes('concat')||text.includes('合并'))return 85;
  return 10;
}

async function render(){
  let valid=S.filter(s=>s.image);
  if(!valid.length){alert('请至少添加一张图片');return}
  if(uploading>0){alert('还有图片在上传中，请稍候');return}
  let bgm=null;
  if(E('bgm').files.length>0){
    try{E('sm').textContent='上传 BGM...';bgm=await uploadFile(E('bgm').files[0])}
    catch(e){alert('BGM 上传失败: '+e);return}
  }
  let m={title:'narravid',width:1920,height:1080,tts_engine:'edge',workers:parseInt(E('wk').value),
    voice:E('v').value,speech_speed:parseFloat(E('sp').value),burn_subtitles:E('bs').checked,
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold||0}))};
  let body={manifest:m,bgm:bgm,title_card:E('tc').value.trim()||null};
  rid='r'+Math.random().toString(36).slice(2,8);
  E('st').style.display='block';E('sm').textContent='正在生成视频...';E('rb').disabled=true;
  E('pf').style.width='2%';
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
    E('pf').style.width=parseProgress(d.progress)+'%';
    if(d.done){done(null,d.video);return}
    tmr=setTimeout(poll,800);
  }).catch(()=>{tmr=setTimeout(poll,1000)});
}
function done(err,video){
  clearTimeout(tmr);E('st').style.display='none';E('rb').disabled=false;rid=null;
  E('pf').style.width='0';
  let b=E('rs');
  if(err){b.textContent='❌ '+err;b.style.background='linear-gradient(135deg,#c0392b,#e74c3c)';b.style.display='block'}
  else{b.innerHTML='✅ 视频已生成！<a href="'+video+'" download>点击下载</a>';b.style.background='linear-gradient(135deg,#1e8449,#27ae60)';b.style.display='block'}
}
function cancel(){if(rid)fetch('/api/cancel/'+rid,{method:'POST'});clearTimeout(tmr);E('st').style.display='none';E('rb').disabled=false;rid=null;E('pf').style.width='0'}
document.addEventListener('dragover',e=>e.preventDefault());
document.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files.length)handleDrop(e.dataTransfer.files)});
init();
</script>
</body>
</html>
'''

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
                fp = Path(img).resolve()
                # 安全检查：只允许白名单目录下的文件
                allowed = any(str(fp).startswith(str(d)) for d in THUMB_ALLOWED_DIRS)
                if not allowed:
                    self._json({'error': 'forbidden'}, 403); return
                if not fp.is_absolute():
                    for base in [Path.cwd(), ROOT]:
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
            # 从进度文件读取实时进度
            progress = j.get('progress', '')
            pf = j.get('progress_file')
            if pf and Path(pf).exists():
                try:
                    progress = Path(pf).read_text(encoding='utf-8').strip() or progress
                except Exception:
                    pass
            resp = {'done': done, 'progress': progress, 'video': j.get('video'), 'srt': j.get('srt')}
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
        try:
            self._do_POST_impl()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({'error': f'server error: {e}'}, 500)

    def _do_POST_impl(self):
        p = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''

        if p.path == '/api/upload':
            data = json.loads(body)
            name = data.get('name', 'image.png')
            b64 = data.get('data', '')
            raw = base64.b64decode(b64)
            fp = UPLOAD_DIR / f'{uuid.uuid4().hex}_{name}'
            fp.write_bytes(raw)
            self._json({'path': str(fp.resolve())})

        elif p.path == '/api/render':
            data = json.loads(body)
            m = data.get('manifest', {})
            bgm = data.get('bgm')
            tc = data.get('title_card')
            rid = data.get('render_id', str(uuid.uuid4()))
            out = OUT_BASE / rid; out.mkdir(parents=True, exist_ok=True)
            mp = out / 'manifest.json'
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
            cmd = [sys.executable, str(SCRIPT), str(mp), '--output-dir', str(out)]
            if bgm:
                bgm_path = Path(bgm)
                if not bgm_path.is_absolute():
                    bgm_path = UPLOAD_DIR / bgm_path
                if bgm_path.exists():
                    cmd += ['--bgm', str(bgm_path.resolve())]
            if tc: cmd += ['--title-card', tc]
            if not m.get('burn_subtitles', True): cmd += ['--no-burn']
            if m.get('tts_engine'): cmd += ['--engine', m['tts_engine']]
            if m.get('voice'): cmd += ['--voice', m['voice']]
            if m.get('speech_speed'): cmd += ['--speed', str(m['speech_speed'])]
            wk = m.get('workers', 4)
            if wk and wk != 1: cmd += ['--workers', str(wk)]
            # stdout → DEVNULL 避免管道死锁；stderr → PIPE 用于错误收集
            # 实时解析 stdout 进度通过临时进度文件实现
            progress_file = out / '_progress.txt'
            progress_file.write_text('TTS 生成中...', encoding='utf-8')
            # 用环境变量传递进度文件路径，让 video_auto.py 能写入进度
            env = os.environ.copy()
            env['NARRAVID_PROGRESS_FILE'] = str(progress_file)
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(ROOT), env=env)
            JOBS[rid] = {'proc': proc, 'progress': 'TTS 生成中...', 'video': '', 'srt': '', 'progress_file': str(progress_file)}
            def mon():
                j = JOBS.get(rid)
                if not j: return
                try:
                    proc.wait(timeout=600)
                    if proc.returncode == 0:
                        mp4s = sorted(out.glob('*.mp4'))
                        if mp4s: j['video'] = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\', '/')
                        j['progress'] = '完成'
                    else:
                        # 渲染失败，不设置 video 和完成标记
                        err = proc.stderr.read().decode('utf-8','ignore')[-200:] if proc.stderr else ''
                        j['progress'] = f'失败 (code {proc.returncode})'
                        j['error'] = err
                except subprocess.TimeoutExpired:
                    proc.kill(); j['progress'] = '超时'
            threading.Thread(target=mon, daemon=True).start()
            self._json({'render_id': rid})

        elif p.path.startswith('/api/cancel/'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if j and j['proc']: j['proc'].kill()
            self._json({'status': 'ok'})

        else:
            self._json({'error': 'not found'}, 404)

    def _html(self, html):
        self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    def _json(self, data, code=200):
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.end_headers()
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
    OUT_BASE.mkdir(parents=True, exist_ok=True); UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    srv = HTTPServer((args.host, args.port), H)
    url = f'http://{args.host}:{args.port}'
    print(f'narravid Web UI: {url}')
    try: import webbrowser; webbrowser.open(url)
    except: pass
    try: srv.serve_forever()
    except KeyboardInterrupt: print('stopped'); srv.shutdown()

if __name__ == '__main__': main()
