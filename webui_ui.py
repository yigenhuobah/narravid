"""WebUI HTML/JS template (kept as one string for single-file packaging)."""

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
.header{padding:28px 24px 0;max-width:1120px;margin:0 auto;display:flex;align-items:flex-end;gap:14px;flex-wrap:wrap}
.header h1{font-size:32px;font-weight:800;letter-spacing:-.5px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .sub{color:var(--muted);font-size:14px;padding-bottom:4px}

/* ── 设置面板 ── */
.panel{max-width:1120px;margin:20px auto 0;padding:0 24px;display:grid;grid-template-columns:1fr 1fr;gap:12px}
.panel .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px}
.panel .card h3{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}
.field:last-child{margin-bottom:0}
.field label{font-size:12px;color:var(--muted);font-weight:500}
.field select,.field input[type=text],.field input[type=number]{padding:8px 10px;border:1px solid var(--border2);border-radius:8px;background:var(--surface2);color:var(--ink);font-size:13px;outline:none;transition:.15s}
.field select:focus,.field input:focus{border-color:var(--accent)}
.field select option{background:var(--surface);color:var(--ink)}
.range-row{display:flex;align-items:center;gap:10px}
.range-row input[type=range]{flex:1;-webkit-appearance:none;height:6px;border-radius:3px;background:var(--surface2);outline:none}
.range-row input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:var(--accent);cursor:pointer;box-shadow:0 0 8px rgba(232,93,38,.4)}
.range-row .val{font-size:14px;font-weight:700;color:var(--accent);min-width:36px;text-align:right}
.chk-row{display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;margin-top:2px}
.chk-row input[type=checkbox]{accent-color:var(--accent);width:16px;height:16px}
.inline-row{display:flex;gap:8px;align-items:flex-end}
.inline-row .field{flex:1;margin-bottom:0}

/* ── 操作栏 ── */
.actions{max-width:1120px;margin:16px auto 0;padding:0 24px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.btn{padding:9px 20px;border:1px solid var(--border2);border-radius:8px;background:var(--surface);color:var(--ink);cursor:pointer;font-size:13px;font-weight:500;transition:.2s;user-select:none}
.btn:hover{background:var(--surface2);border-color:rgba(255,255,255,.2)}
.btn.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border:none;font-weight:700;padding:10px 28px;font-size:15px;box-shadow:0 4px 20px rgba(232,93,38,.3)}
.btn.primary:hover{opacity:.9;transform:translateY(-1px);box-shadow:0 6px 24px rgba(232,93,38,.4)}
.btn.primary:disabled{opacity:.4;cursor:not-allowed;transform:none}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn.sm{padding:5px 12px;font-size:12px}
.upload-stats{font-size:12px;color:var(--muted);margin-left:auto}

/* ── 场景列表 ── */
.scenes{max-width:1120px;margin:16px auto 80px;padding:0 24px}
.scene{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;display:flex;gap:14px;align-items:flex-start;margin-bottom:10px;transition:.2s}
.scene:hover{border-color:var(--border2)}
.scene.drag-over{border-color:var(--accent);border-style:dashed;opacity:.7}
.scene .grip{cursor:grab;color:#555;font-size:20px;padding-top:14px;user-select:none;transition:.15s}
.scene .grip:hover{color:var(--muted)}
.scene .idx{font-size:13px;color:var(--muted);font-weight:700;min-width:24px;padding-top:14px}
.scene .thumb{width:128px;height:80px;border-radius:8px;border:1px solid var(--border2);background-color:var(--surface2);background-position:center;background-size:cover;background-repeat:no-repeat;flex-shrink:0;cursor:zoom-in;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center}
.scene .thumb img{width:100%;height:100%;object-fit:cover;border-radius:7px}
.scene .thumb:hover::after{content:'🔍';position:absolute;inset:0;background:rgba(0,0,0,.55);color:#fff;font-size:22px;display:flex;align-items:center;justify-content:center;z-index:2}
.scene .thumb .loader{width:20px;height:20px;border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:sp .6s linear infinite}
.scene .thumb.has-img .loader{display:none}
.scene .thumb .thumb-ph{color:var(--muted);font-size:28px;font-weight:300;line-height:1;user-select:none}
.scene .thumb:not(.has-img){cursor:pointer}
.scene .thumb:not(.has-img):hover::after{content:none}
.scene .body{flex:1;display:flex;flex-direction:column;gap:8px;min-width:0}
.scene textarea{width:100%;font-size:14px;padding:10px 12px;border:1px solid var(--border2);border-radius:8px;background:var(--surface2);color:var(--ink);resize:vertical;min-height:56px;font-family:inherit;line-height:1.5;outline:none;transition:.15s}
.scene textarea:focus{border-color:var(--accent);background:rgba(36,36,58,.8)}
.scene textarea::placeholder{color:var(--muted)}
.scene .foot{display:flex;gap:8px;align-items:center;font-size:12px;flex-wrap:wrap}
.scene .foot .path{flex:1;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px;font-size:11px}
.scene .foot .path.err{color:#e74c3c}
.scene .hold-input{width:100px;padding:5px 8px;border:1px solid var(--border2);border-radius:6px;background:var(--surface2);color:var(--ink);font-size:12px;text-align:center}
.scene .foot .btn-sm{padding:4px 10px;font-size:11px;border:1px solid var(--border2);border-radius:6px;background:var(--surface2);color:var(--ink);cursor:pointer;transition:.15s}
.scene .foot .btn-sm:hover{background:var(--accent);color:#fff;border-color:var(--accent)}
.scene .del{background:none;border:none;color:#666;cursor:pointer;font-size:20px;padding:0 2px;transition:.15s}
.scene .del:hover{color:#e74c3c}

/* ── 灯箱 ── */
.lb{position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:200;cursor:pointer;display:flex;align-items:center;justify-content:center;animation:fadeIn .2s}
.lb img{max-width:92vw;max-height:92vh;border-radius:12px;box-shadow:0 8px 60px rgba(0,0,0,.7)}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}

/* ── Toast 提示 ── */
.toast{position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:10px;color:#fff;font-size:13px;font-weight:500;z-index:300;box-shadow:var(--shadow);animation:toastIn .3s;max-width:360px;word-break:break-all}
.toast.error{background:linear-gradient(135deg,#c0392b,#e74c3c)}
.toast.warn{background:linear-gradient(135deg,#d4a017,#f1c40f);color:#333}
.toast.ok{background:linear-gradient(135deg,#1e8449,#27ae60)}
@keyframes toastIn{from{transform:translateX(40px);opacity:0}to{transform:translateX(0);opacity:1}}

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

/* ── 结果面板 ── */
.result{position:fixed;bottom:64px;left:50%;transform:translateX(-50%);color:#fff;padding:14px 28px;border-radius:12px;display:none;z-index:101;cursor:pointer;font-size:14px;font-weight:500;box-shadow:var(--shadow);animation:slideUp .3s;max-width:90vw;text-align:center}
@keyframes slideUp{from{transform:translateX(-50%) translateY(20px);opacity:0}to{transform:translateX(-50%) translateY(0);opacity:1}}

/* ── 视频预览 ── */
.preview{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:250;background:var(--surface);border:1px solid var(--border2);border-radius:16px;padding:16px;box-shadow:0 12px 80px rgba(0,0,0,.8);max-width:90vw;max-height:90vh;display:none}
.preview video{max-width:80vw;max-height:70vh;border-radius:8px;background:#000}
.preview .pv-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-size:14px;font-weight:600}
.preview .pv-close{cursor:pointer;font-size:20px;padding:2px 8px;border-radius:4px;transition:.15s}
.preview .pv-close:hover{background:rgba(255,255,255,.1)}
.preview .pv-actions{display:flex;gap:8px;margin-top:10px;justify-content:flex-end}

/* ── 空状态 ── */
.empty{text-align:center;padding:60px 20px;color:var(--muted)}
.empty .icon{font-size:48px;margin-bottom:12px;opacity:.5}
.empty p{font-size:15px;margin-bottom:4px}
.empty .hint{font-size:13px;opacity:.6}

/* ── 字幕样式编辑器 ── */
.subtitle-card{max-width:1120px;margin:12px auto 0;padding:0 24px}
.subtitle-card .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px}
.subtitle-card .card h3{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
.sub-style-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px}
.sub-style-grid .field{margin-bottom:0}
.sub-style-grid .field select,.sub-style-grid .field input[type=number]{width:100%}
.color-field{display:flex;align-items:center;gap:6px}
.color-field input[type=color]{width:32px;height:32px;border:1px solid var(--border2);border-radius:6px;background:none;cursor:pointer;padding:1px}
.color-field input[type=text]{flex:1;font-size:12px;padding:6px 8px;border:1px solid var(--border2);border-radius:6px;background:var(--surface2);color:var(--ink);outline:none;font-family:monospace}
.sub-preview{background:#000;border-radius:8px;padding:20px;text-align:center;margin-top:8px;position:relative;overflow:hidden;min-height:80px;display:flex;align-items:flex-end;justify-content:center}
.sub-preview .preview-text{font-size:18px;font-weight:600;line-height:1.4;padding:8px 16px;border-radius:4px;transition:.2s;max-width:80%}
.sub-style-actions{display:flex;gap:8px;margin-top:8px}
.sub-style-actions .btn{padding:5px 12px;font-size:12px}

/* ── 模板对话框 ── */
.dialog-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:280;display:flex;align-items:center;justify-content:center}
.dialog{background:var(--surface);border:1px solid var(--border2);border-radius:16px;padding:24px;min-width:320px;max-width:500px;max-height:70vh;overflow-y:auto;box-shadow:0 12px 80px rgba(0,0,0,.8)}
.dialog h2{font-size:18px;font-weight:700;margin-bottom:16px}
.dialog .tpl-item{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;cursor:pointer;transition:.15s}
.dialog .tpl-item:hover{border-color:var(--accent);background:var(--surface2)}
.dialog .tpl-item .tpl-info{flex:1;min-width:0}
.dialog .tpl-item .tpl-name{font-weight:600;font-size:14px}
.dialog .tpl-item .tpl-name.editing{outline:1px solid var(--accent);background:var(--surface2);padding:2px 6px;border-radius:4px}
.dialog .tpl-item .tpl-meta{font-size:12px;color:var(--muted)}
.dialog .tpl-item .tpl-actions{display:flex;gap:4px;align-items:center}
.dialog .tpl-item .tpl-btn{color:#666;cursor:pointer;font-size:14px;padding:2px 6px;border-radius:4px;transition:.15s}
.dialog .tpl-item .tpl-btn:hover{color:var(--accent);background:rgba(232,93,38,.1)}
.dialog .tpl-item .tpl-btn.del:hover{color:#e74c3c;background:rgba(231,76,60,.1)}
.dialog .tpl-empty{color:var(--muted);text-align:center;padding:20px;font-size:14px}
.dialog .tpl-save-row{display:flex;gap:8px;margin-top:12px}
.dialog .tpl-save-row input{flex:1}

/* ── 响应式 ── */
@media(max-width:768px){
  .panel{grid-template-columns:1fr}
  .sub-style-grid{grid-template-columns:1fr}
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
        <input type="range" id="sp" min="0.5" max="3.0" step="0.05" value="1.5">
        <span class="val" id="sv">1.5x</span>
      </div>
    </div>
    <label class="chk-row"><input type="checkbox" id="bs" checked>烧录字幕到视频</label>
  </div>

  <div class="card">
    <h3>🎬 输出设置</h3>
    <div class="field">
      <label>分辨率</label>
      <select id="res">
        <option value="1920x1080" selected>1080p 横屏 (1920×1080)</option>
        <option value="1280x720">720p 横屏 (1280×720)</option>
        <option value="1080x1920">1080p 竖屏 (1080×1920)</option>
        <option value="1080x1080">方形 (1080×1080)</option>
      </select>
    </div>
    <div class="inline-row">
      <div class="field">
        <label>标题页</label>
        <input type="text" id="tc" placeholder="留空跳过">
      </div>
      <div class="field" style="max-width:70px">
        <label>秒</label>
        <input type="number" id="tcd" value="3" min="1" max="30" step="0.5">
      </div>
    </div>
    <div class="inline-row">
      <div class="field">
        <label>封尾页</label>
        <input type="text" id="ec" placeholder="留空跳过（如：感谢观看）">
      </div>
      <div class="field" style="max-width:70px">
        <label>秒</label>
        <input type="number" id="ecd" value="3" min="1" max="30" step="0.5">
      </div>
    </div>
    <div class="field">
      <label>BGM</label>
      <div style="display:flex;gap:8px;align-items:center">
        <select id="bgmSel" style="flex:1;font-size:12px;padding:6px 8px;border:1px solid var(--border2);border-radius:8px;background:var(--surface2);color:var(--ink);outline:none">
          <option value="">无 BGM</option>
        </select>
        <label class="btn sm" style="white-space:nowrap;cursor:pointer">上传<input type="file" id="bgmFile" accept="audio/*" style="display:none"></label>
      </div>
    </div>
    <div class="field">
      <label>BGM 音量</label>
      <div class="range-row">
        <input type="range" id="bvol" min="0" max="1" step="0.05" value="0.25">
        <span class="val" id="bv">25%</span>
      </div>
    </div>
    <div class="field">
      <label>并行线程</label>
      <select id="wk">
        <option value="1">1 · 串行</option>
        <option value="2">2</option>
        <option value="4" selected>4 · 推荐</option>
        <option value="8">8</option>
      </select>
    </div>
  </div>
</div>

<!-- 字幕样式编辑器 -->
<div class="subtitle-card">
  <div class="card">
    <h3>✏ 字幕样式</h3>
    <div class="sub-style-grid">
      <div class="field">
        <label>字体</label>
        <select id="ssFont">
          <option value="Microsoft YaHei">微软雅黑</option>
          <option value="SimHei">黑体</option>
          <option value="SimSun">宋体</option>
          <option value="KaiTi">楷体</option>
          <option value="Noto Sans SC">思源黑体 / Noto</option>
          <option value="Noto Sans CJK SC">Noto Sans CJK SC</option>
          <option value="PingFang SC">苹方</option>
          <option value="WenQuanYi Micro Hei">文泉驿微米黑</option>
        </select>
      </div>
      <div class="field">
        <label>字号</label>
        <input type="number" id="ssSize" value="16" min="8" max="72" step="1">
      </div>
      <div class="field">
        <label>描边粗细</label>
        <input type="number" id="ssOutline" value="1" min="0" max="10" step="0.5">
      </div>
      <div class="field">
        <label>文字颜色</label>
        <div class="color-field">
          <input type="color" id="ssColorPicker" value="#FFFFFF">
          <input type="text" id="ssColor" value="FFFFFF" maxlength="6">
        </div>
      </div>
      <div class="field">
        <label>描边颜色</label>
        <div class="color-field">
          <input type="color" id="ssOutlinePicker" value="#000000">
          <input type="text" id="ssOutlineColor" value="000000" maxlength="6">
        </div>
      </div>
      <div class="field">
        <label>底部边距</label>
        <input type="number" id="ssMargin" value="30" min="0" max="200" step="5">
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:8px">
      <label class="chk-row" style="margin:0"><input type="checkbox" id="ssBold">粗体</label>
      <div class="field" style="margin:0;flex:0 0 auto">
        <label>对齐</label>
        <select id="ssAlign" style="font-size:12px;padding:5px 8px">
          <option value="2" selected>底部居中</option>
          <option value="1">底部左对齐</option>
          <option value="3">底部右对齐</option>
          <option value="8">顶部居中</option>
          <option value="5">居中</option>
        </select>
      </div>
    </div>
    <div class="sub-preview" id="subPrev">
      <div class="preview-text" id="subPrevText" style="font-family:'Microsoft YaHei',sans-serif;font-size:18px;color:#FFFFFF;text-shadow:0 0 1px #000,0 0 1px #000,0 0 1px #000,0 0 1px #000">字幕预览效果</div>
    </div>
    <div class="sub-style-actions">
      <button class="btn" onclick="resetSubStyle()">重置默认</button>
      <span style="flex:1"></span>
      <span id="ssInfo" style="font-size:11px;color:var(--muted);align-self:center">实时预览字幕样式</span>
    </div>
  </div>
</div>

<div class="actions">
  <button class="btn primary" id="rb" onclick="render()">▶ 生成视频</button>
  <button class="btn" onclick="batch()">+ 添加图片</button>
  <button class="btn" onclick="add()">+ 空场景</button>
  <button class="btn" onclick="showTemplates()">📋 模板</button>
  <button class="btn" onclick="exportProject()">📦 导出工程</button>
  <button class="btn" onclick="importProject()">📥 导入工程</button>
  <button class="btn" onclick="cleanOld()">🗑 清理旧文件</button>
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

<!-- 视频预览 -->
<div class="preview" id="pv">
  <div class="pv-head"><span>预览</span><div class="pv-close" onclick="closePreview()">✕</div></div>
  <video id="pvVid" controls></video>
  <div class="pv-actions">
    <button class="btn" onclick="closePreview()">关闭</button>
    <button class="btn primary" id="pvDl" onclick="dlVideo()">⬇ 下载</button>
  </div>
</div>

<script>
let scenes=[],rid=null,tmr=null,uploading=0,bgmList=[],currentVideo='',ttsEngine='edge';
const byId=id=>document.getElementById(id);
/* hold_sec wire field; legacy templates may still send hold. Do not use || (0 is valid). */
function sceneHoldSec(s){
  if(!s)return 0;
  let v=(s.hold_sec!==undefined&&s.hold_sec!==null&&s.hold_sec!=='')?s.hold_sec:s.hold;
  let n=parseFloat(v);
  return (isFinite(n)&&n>0)?n:0;
}

const MAX_IMG=20*1024*1024, MAX_BGM=50*1024*1024;

/* ── Toast ── */
function toast(msg,type){
  let d=document.createElement('div');d.className='toast '+(type||'error');d.textContent=msg;
  document.body.appendChild(d);
  setTimeout(()=>{d.style.opacity='0';d.style.transition='opacity .3s';setTimeout(()=>d.remove(),300)},4000);
}

/* ── 字幕样式编辑器 ── */
function defaultSubFont(){
  const p=navigator.platform||'';
  if(/Win/i.test(p))return 'Microsoft YaHei';
  if(/Mac/i.test(p))return 'PingFang SC';
  return 'Noto Sans CJK SC';
}
const SUB_DEFAULT={font:defaultSubFont(),size:16,color:'FFFFFF',outlineColor:'000000',outline:1,margin:30,align:2,bold:false};
let subStyle={...SUB_DEFAULT};

/* ASS/libass 颜色为 &HAABBGGRR（BGR），UI 拾色器是 RRGGBB，需交换 R/B */
function hexToASS(h, alpha){
  h=(h||'FFFFFF').replace(/[^0-9A-Fa-f]/g,'').toUpperCase().padStart(6,'0').slice(0,6);
  let rr=h.slice(0,2),gg=h.slice(2,4),bb=h.slice(4,6);
  let aa=(alpha||'00').toUpperCase();
  return '&H'+aa+bb+gg+rr;
}
function assToHex(ass){
  // 从 &HAABBGGRR 或 6 位 BBGGRR 还原 RRGGBB
  let m=(ass||'').toUpperCase().match(/&H([0-9A-F]{2})?([0-9A-F]{6})/);
  if(!m)return null;
  let bgr=m[2],bb=bgr.slice(0,2),gg=bgr.slice(2,4),rr=bgr.slice(4,6);
  return rr+gg+bb;
}

function buildSubStyleStr(){
  let s='FontName='+subStyle.font+',FontSize='+subStyle.size+
    ',PrimaryColour='+hexToASS(subStyle.color,'00')+
    ',OutlineColour='+hexToASS(subStyle.outlineColor,'64')+
    ',BorderStyle=3,Outline='+subStyle.outline+',Shadow=0'+
    ',MarginV='+subStyle.margin+',Alignment='+subStyle.align;
  if(subStyle.bold)s+=',Bold=1';
  return s
}

function updateSubPreview(){
  let el=byId('subPrevText');
  el.style.fontFamily="'"+subStyle.font+"',sans-serif";
  el.style.fontSize=Math.round(subStyle.size*1.1)+'px';
  el.style.color='#'+subStyle.color;
  el.style.fontWeight=subStyle.bold?'700':'400';
  // 模拟描边：用多层 text-shadow
  let o=subStyle.outline;
  if(o>0){
    let oc='#'+subStyle.outlineColor;
    let shadows=[];
    let steps=Math.ceil(o*2);
    for(let dx=-steps;dx<=steps;dx++)for(let dy=-steps;dy<=steps;dy++){
      if(dx*dx+dy*dy<=steps*steps)shadows.push(dx+'px '+dy+'px 0 '+oc);
    }
    el.style.textShadow=shadows.join(',');
  }else{el.style.textShadow='none'}
  // 对齐
  let alignMap={'2':'center','1':'left','3':'right','8':'center','5':'center'};
  let vAlignMap={'2':'flex-end','1':'flex-end','3':'flex-end','8':'flex-start','5':'center'};
  el.style.textAlign=alignMap[subStyle.align]||'center';
  byId('subPrev').style.alignItems=vAlignMap[subStyle.align]||'flex-end';
}

function bindSubStyleControls(){
  byId('ssFont').onchange=e=>{subStyle.font=e.target.value;updateSubPreview()};
  byId('ssSize').oninput=e=>{subStyle.size=parseInt(e.target.value)||16;updateSubPreview()};
  byId('ssOutline').oninput=e=>{subStyle.outline=parseFloat(e.target.value)||0;updateSubPreview()};
  byId('ssMargin').oninput=e=>{subStyle.margin=parseInt(e.target.value)||0;updateSubPreview()};
  byId('ssAlign').onchange=e=>{subStyle.align=parseInt(e.target.value);updateSubPreview()};
  byId('ssBold').onchange=e=>{subStyle.bold=e.target.checked;updateSubPreview()};
  // 颜色联动
  byId('ssColorPicker').oninput=e=>{subStyle.color=e.target.value.slice(1).toUpperCase();byId('ssColor').value=subStyle.color;updateSubPreview()};
  byId('ssColor').oninput=e=>{let v=e.target.value.replace(/[^0-9A-Fa-f]/g,'').slice(0,6).toUpperCase();e.target.value=v;if(v.length===6){subStyle.color=v;byId('ssColorPicker').value='#'+v;updateSubPreview()}};
  byId('ssOutlinePicker').oninput=e=>{subStyle.outlineColor=e.target.value.slice(1).toUpperCase();byId('ssOutlineColor').value=subStyle.outlineColor;updateSubPreview()};
  byId('ssOutlineColor').oninput=e=>{let v=e.target.value.replace(/[^0-9A-Fa-f]/g,'').slice(0,6).toUpperCase();e.target.value=v;if(v.length===6){subStyle.outlineColor=v;byId('ssOutlinePicker').value='#'+v;updateSubPreview()}};
}

function resetSubStyle(){
  subStyle={...SUB_DEFAULT};
  byId('ssFont').value=subStyle.font;byId('ssSize').value=subStyle.size;
  byId('ssOutline').value=subStyle.outline;byId('ssMargin').value=subStyle.margin;
  byId('ssAlign').value=subStyle.align;byId('ssBold').checked=subStyle.bold;
  byId('ssColor').value=subStyle.color;byId('ssColorPicker').value='#'+subStyle.color;
  byId('ssOutlineColor').value=subStyle.outlineColor;byId('ssOutlinePicker').value='#'+subStyle.outlineColor;
  updateSubPreview();
  toast('已重置为默认样式','ok');
}

function applySubStyleFromStr(str){
  if(!str)return;
  let m;
  if(m=str.match(/FontName=([^,]+)/))subStyle.font=m[1];
  if(m=str.match(/FontSize=(\d+)/))subStyle.size=parseInt(m[1]);
  // PrimaryColour / OutlineColour 按 ASS BGR 解析回 RRGGBB
  if(m=str.match(/PrimaryColour=(&H[0-9A-Fa-f]+)/)){let hx=assToHex(m[1]);if(hx)subStyle.color=hx}
  if(m=str.match(/OutlineColour=(&H[0-9A-Fa-f]+)/)){let hx=assToHex(m[1]);if(hx)subStyle.outlineColor=hx}
  if(m=str.match(/Outline=([\d.]+)/))subStyle.outline=parseFloat(m[1]);
  if(m=str.match(/MarginV=(\d+)/))subStyle.margin=parseInt(m[1]);
  if(m=str.match(/Alignment=(\d+)/))subStyle.align=parseInt(m[1]);
  if(m=str.match(/Bold=(\d+)/))subStyle.bold=m[1]==='1';
  // 同步 UI
  byId('ssFont').value=subStyle.font;byId('ssSize').value=subStyle.size;
  byId('ssOutline').value=subStyle.outline;byId('ssMargin').value=subStyle.margin;
  byId('ssAlign').value=subStyle.align;byId('ssBold').checked=subStyle.bold;
  byId('ssColor').value=subStyle.color;byId('ssColorPicker').value='#'+subStyle.color;
  byId('ssOutlineColor').value=subStyle.outlineColor;byId('ssOutlinePicker').value='#'+subStyle.outlineColor;
  updateSubPreview();
}

function init(){
  byId('sp').oninput=()=>byId('sv').textContent=parseFloat(byId('sp').value).toFixed(2)+'x';
  byId('bvol').oninput=()=>byId('bv').textContent=Math.round(parseFloat(byId('bvol').value)*100)+'%';
  byId('bgmFile').onchange=uploadBGM;
  // 按平台默认字幕字体选中对应 option（无则保留列表第一项语义由 subStyle 决定）
  try{byId('ssFont').value=subStyle.font}catch(e){}
  bindSubStyleControls();
  updateSubPreview();
  add();add();add();
  loadBGMList();
  checkTTS();
}
async function checkTTS(){
  try{
    let r=await fetch('/api/tts-check');if(!r.ok)return;
    let d=await r.json();
    ttsEngine=(d.engine==='none'||!d.engine)?'edge':d.engine;
    document.querySelectorAll('.header .sub').forEach(el=>{el.textContent+=el.textContent?' · ':'';el.textContent+=d.label||''});
    if(d.engine==='none'){toast(d.label||'无可用 TTS，请安装 edge-tts','warn')}
  }catch(e){}
}

/* ── BGM 管理 ── */
async function uploadBGM(){
  let f=byId('bgmFile').files[0];if(!f)return;
  if(f.size>MAX_BGM){toast('BGM 文件超过 50MB 限制','warn');return}
  try{
    let b64=await fileToB64(f);
    let resp=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:f.name,data:b64,kind:'bgm'})});
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    let d=await resp.json();
    await loadBGMList();
    byId('bgmSel').value=d.path;
    toast('BGM 上传成功','ok');
  }catch(e){toast('BGM 上传失败: '+e)}
}
async function loadBGMList(){
  try{
    let resp=await fetch('/api/bgm-list');if(!resp.ok)return;
    bgmList=await resp.json();
    let sel=byId('bgmSel'),cur=sel.value;
    sel.innerHTML='<option value="">无 BGM</option>';
    bgmList.forEach(b=>{
      let o=document.createElement('option');o.value=b.path;o.textContent=b.name;
      sel.appendChild(o);
    });
    if(cur)sel.value=cur;
  }catch(e){}
}
function fileToB64(f){return new Promise((ok,no)=>{let r=new FileReader();r.onload=()=>ok(r.result.split(',')[1]);r.onerror=()=>no('读取失败');r.readAsDataURL(f)})}

/* ── 图片上传 ── */
async function uploadFile(file){
  let maxSz=file.type.startsWith('video/')?60*1024*1024:MAX_IMG;
  if(file.size>maxSz)throw (file.type.startsWith('video/')?'视频 ':'图片 ')+file.name+' 超过大小限制';
  return new Promise((resolve,reject)=>{
    let r=new FileReader();
    r.onload=async()=>{
      try{
        let b64=r.result.split(',')[1];
        let resp=await fetch('/api/upload',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({name:file.name,data:b64})});
        if(!resp.ok){reject('上传失败 (HTTP '+resp.status+')');return}
        let d=await resp.json();
        if(d.error)reject(d.error);else resolve(d.path);
      }catch(e){reject(e.message||String(e))}
    };
    r.onerror=()=>reject('文件读取失败');
    r.readAsDataURL(file);
  });
}

async function batch(){
  let inp=document.createElement('input');inp.type='file';inp.multiple=true;inp.accept='image/*,video/*';
  inp.onchange=async()=>{
    if(!inp.files.length)return;
    let files=Array.from(inp.files).filter(f=>{
      let maxSz=f.type.startsWith('video/')?60*1024*1024:MAX_IMG;
      return (f.type.startsWith('image/')||f.type.startsWith('video/'))&&f.size<=maxSz;
    });
    if(!files.length){toast('未选择有效文件（图片<20MB，视频<60MB）','warn');return}
    uploading=files.length;updateStats();
    let next=0;
    for(let f of files){
      let idx=scenes.findIndex((s,i)=>i>=next&&!s.image);
      let sidx=idx>=0?idx:scenes.length;
      if(idx<0){scenes.push({image:'',text:'',hold_sec:0,_loading:true})}
      scenes[sidx]._loading=true;
      next=(idx>=0?idx:sidx)+1;
      paintScenes();
      try{let path=await uploadFile(f);scenes[sidx].image=path;scenes[sidx]._name=f.name;scenes[sidx]._loading=false}
      catch(e){console.error('upload',e);toast('上传失败: '+e);scenes[sidx]._loading=false;scenes[sidx]._error=true}
      uploading--;updateStats();paintScenes();
    }
  };
  inp.click();
}

function handleDrop(files){
  let imgs=Array.from(files).filter(f=>f.type.startsWith('image/')||f.type.startsWith('video/'));
  if(!imgs.length)return;
  let next=0;
  for(let f of imgs){
    let idx=scenes.findIndex((s,i)=>i>=next&&!s.image);
    let sidx=idx>=0?idx:scenes.length;
    if(idx<0){scenes.push({image:'',text:'',hold_sec:0,_loading:true})}
    scenes[sidx]._loading=true;
    next=(idx>=0?idx:sidx)+1;
    uploading++;updateStats();paintScenes();
    uploadFile(f).then(path=>{scenes[sidx].image=path;scenes[sidx]._name=f.name;scenes[sidx]._loading=false})
    .catch(e=>{console.error('upload',e);toast('上传失败: '+e);scenes[sidx]._loading=false;scenes[sidx]._error=true})
    .finally(()=>{uploading--;updateStats();paintScenes()});
  }
}

function add(img,txt,hold){scenes.push({image:img||'',text:txt||'',hold_sec:hold||0});paintScenes()}
function del(i){scenes.splice(i,1);paintScenes()}
function chImg(i){
  let inp=document.createElement('input');inp.type='file';inp.accept='image/*,video/*';
  inp.onchange=async()=>{
    if(!inp.files[0])return;
    scenes[i]._loading=true;uploading++;updateStats();paintScenes();
    try{let path=await uploadFile(inp.files[0]);scenes[i].image=path;scenes[i]._name=inp.files[0].name;scenes[i]._loading=false}
    catch(e){console.error(e);toast('换图失败: '+e);scenes[i]._loading=false}
    uploading--;updateStats();paintScenes();
  };
  inp.click();
}
function updateStats(){byId('ustats').textContent=uploading>0?uploading+' 张上传中...':'';}
function thumbUrl(i){let img=scenes[i].image;if(!img)return'';return'/thumb?path='+encodeURIComponent(img);}
function isVideo(path){return/\.(mp4|mov|mkv|avi|webm|flv)$/i.test(path||'')}
function lightbox(i){
  let img=scenes[i].image;if(!img)return;
  let d=document.createElement('div');d.className='lb';d.onclick=()=>d.remove();
  if(isVideo(img)){
    let v=document.createElement('video');v.src=thumbUrl(i);v.controls=true;v.style.maxWidth='90vw';v.style.maxHeight='80vh';d.appendChild(v);
  }else{
    let el=document.createElement('img');el.src=thumbUrl(i);d.appendChild(el);
  }
  document.body.appendChild(d);
}

/* ── 拖拽排序 ── */
let dragFrom=null,dragOverIdx=null;
function dragS(i,e){dragFrom=i;e.dataTransfer.effectAllowed='move'}
function dragEnter(i){if(dragFrom===null||dragFrom===i)return;dragOverIdx=i;
  document.querySelectorAll('.scene').forEach(el=>el.classList.remove('drag-over'));
  document.querySelectorAll('.scene')[i]?.classList.add('drag-over');
}
function dragLV(){document.querySelectorAll('.scene').forEach(el=>el.classList.remove('drag-over'))}
function dropS(i,e){e.preventDefault();dragLV();if(dragFrom===null||dragFrom===i)return;
  let t=scenes.splice(dragFrom,1)[0];scenes.splice(i,0,t);paintScenes();dragFrom=null;dragOverIdx=null}

function paintScenes(){
  if(!scenes.length){
    byId('list').innerHTML='<div class="empty"><div class="icon">🎞</div><p>还没有场景</p><div class="hint">点击「添加图片」上传图片或视频，或将文件拖入此页面</div></div>';
    return;
  }
  let h='';
  scenes.forEach((s,i)=>{
    let tu=thumbUrl(i);
    let hasImg=!!tu;
    let vid=isVideo(s.image);
    let cls='thumb'+(hasImg?' has-img':'');
    let inner='';
    if(hasImg){
      if(vid){
        inner='<video src="'+tu+'" muted preload="metadata" onerror="this.style.display=\'none\'"></video>';
      }else{
        inner='<img src="'+tu+'" alt="场景'+(i+1)+'" onerror="this.style.display=\'none\';this.parentNode.classList.remove(\'has-img\')">';
      }
    }else if(s._loading){
      inner='<div class="loader"></div>';
    }else{
      inner='<div class="thumb-ph" title="点击换图上传">+</div>';
    }
    let nm=s._name||(s.image?s.image.split('/').pop().split('\\').pop():'');
    let pathCls='path'+(s._error?' err':'');
    h+='<div class="scene" draggable="true" ondragstart="dragS('+i+',event)" ondragover="event.preventDefault();dragEnter('+i+')" ondragleave="dragLV()" ondrop="dropS('+i+',event)">'
      +'<div class="grip" title="拖拽排序">⠿</div>'
      +'<div class="idx">#'+(i+1)+'</div>'
      +'<div class="'+cls+'" onclick="'+(hasImg?'lightbox('+i+')':'chImg('+i+')')+'">'+inner+'</div>'
      +'<div class="body">'
        +'<textarea placeholder="输入解说文案（按句自动切字幕，逗号长句智能断句）" oninput="scenes['+i+'].text=this.value">'+esc(s.text)+'</textarea>'
        +'<div class="foot">'
          +'<span class="'+pathCls+'">'+esc(nm||(s._loading?'上传中...':(s._error?'上传失败':'未上传文件')))+'</span>'
          +'<input class="hold-input" type="number" placeholder="停顿秒" value="'+(s.hold_sec||'')+'" oninput="scenes['+i+'].hold_sec=parseFloat(this.value)||0" title="场景末尾额外停留秒数">'
          +'<button class="btn-sm" onclick="chImg('+i+')">换图</button>'
          +'<button class="del" onclick="del('+i+')" title="删除场景">×</button>'
        +'</div>'
      +'</div></div>';
  });
  byId('list').innerHTML=h;
}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}

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

/* ── 渲染 ── */
let userCancelled=false; // 硬闸：取消后忽略成功 status，禁止重叠 render
async function render(){
  if(byId('rb').disabled)return; // 进行中/取消中禁止重叠
  // 实时从 DOM 读取 textarea 值（防止 oninput 未同步的场景）
  document.querySelectorAll('.scene textarea').forEach((ta,i)=>{if(scenes[i])scenes[i].text=ta.value});
  let valid=scenes.filter(s=>s.image);
  if(!valid.length){alert('请至少添加一张图片');return}
  if(uploading>0){alert('还有图片在上传中，请稍候');return}
  let skipped=scenes.length-valid.length;
  if(skipped>0){toast('已跳过 '+skipped+' 个未上传媒体的场景','warn')}
  let bgm=byId('bgmSel').value||null;
  let res=(byId('res').value||'1920x1080').split('x');
  let subStyleStr=buildSubStyleStr();
  let m={title:'narravid',width:parseInt(res[0]),height:parseInt(res[1]),tts_engine:ttsEngine,workers:parseInt(byId('wk').value),
    voice:byId('v').value,speech_speed:parseFloat(byId('sp').value),burn_subtitles:byId('bs').checked,
    bgm_volume:parseFloat(byId('bvol').value),card_duration:parseFloat(byId('tcd').value),
    end_card_duration:parseFloat(byId('ecd').value),
    subtitle_style:subStyleStr,
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:sceneHoldSec(s)}))};
  let body={manifest:m,bgm:bgm,
    title_card:byId('tc').value.trim()||null,
    end_card:byId('ec').value.trim()||null,
    card_duration:parseFloat(byId('tcd').value),
    end_card_duration:parseFloat(byId('ecd').value)};
  userCancelled=false;
  rid='r'+Math.random().toString(36).slice(2,8);
  byId('st').style.display='block';byId('sm').textContent='正在生成视频...';byId('rb').disabled=true;
  byId('pf').style.width='2%';
  try{
    let r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,render_id:rid})});
    let d=await r.json();
    if(d.error)throw new Error(d.error);
    // 若 await 期间用户已取消：用服务端 id 再发一次 cancel，勿启动成功轮询
    if(userCancelled){
      const realId=d.render_id||rid;
      if(realId)fetch('/api/cancel/'+realId,{method:'POST'});
      rid=null;byId('st').style.display='none';byId('rb').disabled=false;byId('pf').style.width='0';
      return;
    }
    rid=d.render_id;poll();
  }catch(e){
    if(userCancelled){rid=null;byId('st').style.display='none';byId('rb').disabled=false;return}
    done(e.message)
  }
}
function poll(){
  if(!rid||userCancelled)return;
  const pollRid=rid;
  fetch('/api/status/'+pollRid).then(r=>r.json()).then(d=>{
    // 用户已点取消或开始了新任务：丢弃过期响应（含成功）
    if(rid!==pollRid||userCancelled)return;
    // 超时诊断优先于 cancelled 标志（后端可能两者并存）
    if(d.error&&String(d.error).indexOf('超时')>=0){done(d.error);return}
    if(d.cancelled||(d.error&&String(d.error).indexOf('取消')>=0)){done('已取消',null,true);return}
    if(d.error){done(d.error);return}
    byId('sm').textContent=d.progress||'渲染中';
    byId('pf').style.width=parseProgress(d.progress)+'%';
    if(d.done){
      if(d.cancelled||(d.progress&&d.progress.indexOf('取消')>=0)){done('已取消',null,true);return}
      if(!d.video&&!d.error){done(d.progress&&d.progress.indexOf('失败')>=0?d.progress:'渲染结束但未生成视频');return}
      done(null,d.video);return
    }
    tmr=setTimeout(poll,800);
  }).catch(()=>{if(rid===pollRid&&!userCancelled)tmr=setTimeout(poll,1000)});
}
function done(err,video,asCancel){
  clearTimeout(tmr);byId('st').style.display='none';byId('rb').disabled=false;rid=null;userCancelled=false;
  byId('pf').style.width='0';
  let b=byId('rs');
  if(asCancel||(err&&String(err).indexOf('取消')>=0)){
    b.textContent='⏹ 已取消';b.style.background='linear-gradient(135deg,#7f8c8d,#95a5a6)';b.style.display='block';
  }else if(err){
    b.textContent='❌ '+err;b.style.background='linear-gradient(135deg,#c0392b,#e74c3c)';b.style.display='block'
  }else{
    currentVideo=video||'';
    b.textContent='✅ 视频已生成！';b.style.background='linear-gradient(135deg,#1e8449,#27ae60)';b.style.display='block';
    if(video){showPreview(video)}
  }
}
function cancel(){
  const cancelRid=rid;
  userCancelled=true; // 硬闸：后续 poll 成功一律丢弃
  clearTimeout(tmr);
  if(cancelRid)fetch('/api/cancel/'+cancelRid,{method:'POST'});
  byId('st').style.display='none';byId('pf').style.width='0';
  // 取消期间保持按钮禁用，直到确认服务端登记或超时，避免重叠 render
  let b=byId('rs');
  b.textContent='⏹ 已取消';b.style.background='linear-gradient(135deg,#7f8c8d,#95a5a6)';b.style.display='block';
  // 稍后释放按钮并清 rid（render await 返回时也会处理）
  setTimeout(()=>{
    if(rid===cancelRid)rid=null;
    byId('rb').disabled=false;
    userCancelled=false;
  },2000);
}

/* ── 视频预览 ── */
function showPreview(url){
  byId('pvVid').src=url;byId('pv').style.display='block';
}
function closePreview(){byId('pvVid').pause();byId('pvVid').src='';byId('pv').style.display='none'}
function dlVideo(){if(currentVideo){let a=document.createElement('a');a.href=currentVideo;a.download='';a.click()}}

/* ── 模板 ── */
async function showTemplates(){
  let tplList=await fetch('/api/templates').then(r=>r.json()).catch(()=>[]);
  let overlay=document.createElement('div');overlay.className='dialog-overlay';overlay.onclick=e=>{if(e.target===overlay)overlay.remove()};
  let dlg=document.createElement('div');dlg.className='dialog';
  let h='<h2>📋 模板</h2>';
  if(!tplList.length){h+='<div class="tpl-empty">暂无保存的模板</div>'}
  else{tplList.forEach((t,i)=>{
    h+='<div class="tpl-item" onclick="loadTemplate(\''+t.id+'\')">'+
      '<div class="tpl-info">'+
      '<div class="tpl-name" id="tplName_'+t.id+'">'+esc(t.name)+'</div>'+
      '<div class="tpl-meta">'+t.count+' 场景 · '+t.date+'</div>'+
      '</div>'+
      '<div class="tpl-actions">'+
      '<div class="tpl-btn" title="重命名" data-id="'+t.id+'" data-name="'+esc(t.name).replace(/'/g,'&#39;')+'">✎</div>'+
      '<div class="tpl-btn del" title="删除" data-del="'+t.id+'">✕</div>'+
      '</div></div>'
  })}
  h+='<div class="tpl-save-row"><input id="tplName" placeholder="模板名称" style="padding:8px 10px;border:1px solid var(--border2);border-radius:8px;background:var(--surface2);color:var(--ink);font-size:13px;outline:none"><button class="btn primary sm" onclick="saveTemplate()">保存当前</button></div>';
  dlg.innerHTML=h;overlay.appendChild(dlg);document.body.appendChild(overlay);
  // 事件委托：重命名和删除按钮
  dlg.querySelectorAll('.tpl-btn[title="重命名"]').forEach(btn=>{
    btn.onclick=function(ev){ev.stopPropagation();renameTemplate(this.dataset.id,this.dataset.name)};
  });
  dlg.querySelectorAll('.tpl-btn[title="删除"]').forEach(btn=>{
    btn.onclick=function(ev){ev.stopPropagation();delTemplate(this.dataset.del)};
  });
}
async function saveTemplate(){
  let name=byId('tplName')?.value?.trim()||('模板 '+(new Date().toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})));
  // 实时读 textarea
  document.querySelectorAll('.scene textarea').forEach((ta,i)=>{if(scenes[i])scenes[i].text=ta.value});
  let data={name,scenes:scenes.filter(s=>s.image).map(s=>({text:s.text,image:s.image,hold_sec:sceneHoldSec(s)})),
    voice:byId('v').value,speed:byId('sp').value,burn:byId('bs').checked,
    resolution:byId('res').value,title_card:byId('tc').value,end_card:byId('ec').value,
    card_duration:byId('tcd').value,end_card_duration:byId('ecd').value,
    bgm:byId('bgmSel').value||'',bgm_volume:byId('bvol').value,workers:byId('wk').value,
    subtitle_style:buildSubStyleStr()};
  await fetch('/api/templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  toast('模板已保存','ok');
  document.querySelector('.dialog-overlay')?.remove();
}
async function loadTemplate(id){
  let t=await fetch('/api/templates/'+id).then(r=>r.json());
  if(t.scenes){scenes=t.scenes.map(s=>({image:s.image||'',text:s.text||'',hold_sec:sceneHoldSec(s)}));paintScenes()}
  if(t.voice)byId('v').value=t.voice;
  if(t.speed)byId('sp').value=t.speed,byId('sv').textContent=parseFloat(t.speed).toFixed(2)+'x';
  if(t.burn!==undefined)byId('bs').checked=t.burn;
  if(t.resolution)byId('res').value=t.resolution;
  if(t.title_card!==undefined)byId('tc').value=t.title_card||'';
  if(t.end_card!==undefined)byId('ec').value=t.end_card||'';
  if(t.card_duration!==undefined&&t.card_duration!==null&&t.card_duration!=='')byId('tcd').value=t.card_duration;
  if(t.end_card_duration!==undefined&&t.end_card_duration!==null&&t.end_card_duration!=='')byId('ecd').value=t.end_card_duration;
  if(t.bgm_volume!==undefined)byId('bvol').value=t.bgm_volume,byId('bv').textContent=Math.round(parseFloat(t.bgm_volume)*100)+'%';
  if(t.workers)byId('wk').value=t.workers;
  if(t.subtitle_style)applySubStyleFromStr(t.subtitle_style);
  // BGM：列表可能尚未含该路径，直接挂 option
  if(t.bgm){
    await loadBGMList();
    let sel=byId('bgmSel'),found=false;
    for(let opt of sel.options){
      if(opt.value===t.bgm||(opt.value&&t.bgm.endsWith((opt.value.split(/[\\/]/).pop()||'')))){
        opt.selected=true;found=true;break
      }
    }
    if(!found){
      let o=document.createElement('option');
      o.value=t.bgm;o.textContent=t.bgm.split(/[\\/]/).pop()||'模板 BGM';
      sel.appendChild(o);sel.value=t.bgm;
    }else{sel.value=t.bgm}
  }
  document.querySelector('.dialog-overlay')?.remove();
  toast('模板已加载','ok');
}
async function delTemplate(id){
  await fetch('/api/templates/'+id,{method:'DELETE'});
  document.querySelector('.dialog-overlay')?.remove();
  showTemplates();
}
async function renameTemplate(id,oldName){
  let el=byId('tplName_'+id);
  el.classList.add('editing');
  el.contentEditable=true;el.focus();document.execCommand('selectAll',false,null);
  let done=false;
  const finish=async()=>{if(done)return;done=true;
    el.contentEditable=false;el.classList.remove('editing');
    let newName=el.textContent.trim();
    if(!newName||newName===oldName){el.textContent=oldName;return}
    try{
      let r=await fetch('/api/templates/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:newName})});
      if(r.ok){toast('已重命名','ok');showTemplates()}
      else{el.textContent=oldName;toast('重命名失败','error')}
    }catch(e){el.textContent=oldName;toast('重命名失败: '+e,'error')}
  };
  el.onblur=finish;
  el.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();el.blur()}if(e.key==='Escape'){el.textContent=oldName;el.blur()}};
  el.onpaste=e=>{e.preventDefault();const txt=(e.clipboardData||window.clipboardData).getData('text');document.execCommand('insertText',false,txt)};
}

/* ── 导出/导入工程 ── */
async function exportProject(){
  document.querySelectorAll('.scene textarea').forEach((ta,i)=>{if(scenes[i])scenes[i].text=ta.value});
  let valid=scenes.filter(s=>s.image);
  if(!valid.length){toast('没有场景可导出','warn');return}
  let res=(byId('res').value||'1920x1080').split('x');
  let m={title:'narravid',width:parseInt(res[0]),height:parseInt(res[1]),tts_engine:ttsEngine,workers:parseInt(byId('wk').value),
    voice:byId('v').value,speech_speed:parseFloat(byId('sp').value),burn_subtitles:byId('bs').checked,
    bgm_volume:parseFloat(byId('bvol').value),card_duration:parseFloat(byId('tcd').value),
    end_card_duration:parseFloat(byId('ecd').value),
    title_card:byId('tc').value.trim()||'',
    end_card:byId('ec').value.trim()||'',
    subtitle_style:buildSubStyleStr(),
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:sceneHoldSec(s)}))};
  let bgm=byId('bgmSel').value||null;
  toast('正在打包...','info');
  try{
    let resp=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({manifest:m,bgm:bgm,title_card:m.title_card||null,end_card:m.end_card||null,
        card_duration:m.card_duration,end_card_duration:m.end_card_duration})});
    if(!resp.ok){let d=await resp.json().catch(()=>({}));toast(d.error||'导出失败','error');return}
    let blob=await resp.blob();
    let url=URL.createObjectURL(blob);
    let a=document.createElement('a');a.href=url;a.download='narravid_project.zip';
    document.body.appendChild(a);a.click();a.remove();
    URL.revokeObjectURL(url);
    toast('已导出工程','ok');
  }catch(e){toast('导出失败: '+e,'error')}
}

async function importProject(){
  let inp=document.createElement('input');inp.type='file';inp.accept='.zip';
  inp.onchange=async()=>{
    if(!inp.files.length)return;
    let f=inp.files[0];
    // 后端 Content-Length 上限 60MB，且 body 为 base64（约 ×4/3），zip 需更小
    const MAX_IMPORT_ZIP=40*1024*1024;
    if(f.size>MAX_IMPORT_ZIP){toast('文件过大（上限约40MB，受上传编码限制）','warn');return}
    let b64=await fileToB64(f);
    toast('正在导入...','info');
    try{
      let resp=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({data:b64})});
      let d=await resp.json().catch(()=>({}));
      if(!resp.ok||d.error){toast(d.error||('导入失败 HTTP '+resp.status),'error');return}
      // 加载 manifest 到 UI
      let m=d.manifest;
      scenes=m.scenes.map(s=>({image:s.image,text:s.text||'',hold_sec:sceneHoldSec(s)}));
      if(m.tts_engine)ttsEngine=m.tts_engine;
      if(m.voice)byId('v').value=m.voice;
      if(m.speech_speed!==undefined&&m.speech_speed!==null&&m.speech_speed!==''){byId('sp').value=m.speech_speed;byId('sv').textContent=parseFloat(m.speech_speed).toFixed(2)+'x'}
      if(m.workers!==undefined&&m.workers!==null&&m.workers!=='')byId('wk').value=m.workers;
      if(m.burn_subtitles!==undefined)byId('bs').checked=m.burn_subtitles;
      if(m.bgm_volume!==undefined){byId('bvol').value=m.bgm_volume;byId('bv').textContent=Math.round(parseFloat(m.bgm_volume)*100)+'%'}
      if(m.card_duration!==undefined)byId('tcd').value=m.card_duration;
      if(m.end_card_duration!==undefined)byId('ecd').value=m.end_card_duration;
      if(m.title_card)byId('tc').value=m.title_card;
      if(m.end_card)byId('ec').value=m.end_card;
      if(m.subtitle_style)applySubStyleFromStr(m.subtitle_style);
      if(m.width&&m.height){
        let res=m.width+'x'+m.height;
        for(let opt of byId('res').options){if(opt.value===res)opt.selected=true}
      }
      // BGM：列表可能不含 project 子目录文件，直接挂上 option
      if(d.bgm){
        await loadBGMList();
        let sel=byId('bgmSel'),found=false;
        for(let opt of sel.options){
          if(opt.value===d.bgm||(opt.value&&d.bgm.endsWith(opt.value.split(/[\\/]/).pop()))){
            opt.selected=true;found=true;break
          }
        }
        if(!found){
          let o=document.createElement('option');
          o.value=d.bgm;o.textContent=d.bgm.split(/[\\/]/).pop()||'导入的 BGM';
          sel.appendChild(o);sel.value=d.bgm;
        }else{sel.value=d.bgm}
      }
      paintScenes();toast('已导入工程（'+scenes.length+' 个场景）','ok');
    }catch(e){toast('导入失败: '+e,'error')}
  };
  inp.click();
}

/* ── 清理旧文件 ── */
async function cleanOld(){
  if(!confirm('清理旧渲染文件？将保留最近 5 个及进行中任务，其余成片目录会被删除。'))return;
  try{
    let r=await fetch('/api/clean',{method:'POST'});let d=await r.json();
    toast(d.message||'已清理',d.error?'error':'ok');
  }catch(e){toast('清理失败: '+e,'error')}
}

document.addEventListener('dragover',e=>e.preventDefault());
document.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files.length)handleDrop(e.dataTransfer.files)});
init();
</script>
</body>
</html>
'''

