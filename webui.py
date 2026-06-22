"""
narravid Web UI v6 — 图片上传、缩略图预览、BGM 管理、在线预览、模板、一键生成。

用法:
  python webui.py
  python webui.py --port 8080
"""
import argparse, base64, io, json, os, re, shutil, sys, threading, time, uuid
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'video_auto.py'
OUT_BASE = ROOT / 'rendered' / 'webui'
UPLOAD_DIR = OUT_BASE / 'uploads'
TEMPLATE_DIR = OUT_BASE / 'templates'

# 统一使用 _bundled_ffmpeg 模块定位自带 ffmpeg
try:
    import _bundled_ffmpeg
except ImportError:
    pass

for d in [OUT_BASE, UPLOAD_DIR, TEMPLATE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── 允许 /thumb 访问的目录白名单 ─────────────────────────────────
THUMB_ALLOWED_DIRS = [UPLOAD_DIR.resolve(), (ROOT / 'examples-assets').resolve()]

# ── 文件大小限制 ─────────────────────────────────────────────────
MAX_IMAGE_SIZE = 20 * 1024 * 1024   # 20 MB (图片)
MAX_VIDEO_SIZE = 60 * 1024 * 1024   # 60 MB (视频)
MAX_BGM_SIZE = 50 * 1024 * 1024     # 50 MB
MAX_UPLOAD_SIZE = 60 * 1024 * 1024  # 总 body 60MB

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
        <input type="range" id="sp" min="0.8" max="2.2" step="0.05" value="1.5">
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
          <option value="Microsoft YaHei" selected>微软雅黑</option>
          <option value="SimHei">黑体</option>
          <option value="SimSun">宋体</option>
          <option value="KaiTi">楷体</option>
          <option value="Noto Sans SC">思源黑体</option>
          <option value="PingFang SC">苹方</option>
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
let S=[],rid=null,tmr=null,uploading=0,bgmList=[],currentVideo='',ttsEngine='edge';
const E=id=>document.getElementById(id);
const MAX_IMG=20*1024*1024, MAX_BGM=50*1024*1024;

/* ── Toast ── */
function toast(msg,type){
  let d=document.createElement('div');d.className='toast '+(type||'error');d.textContent=msg;
  document.body.appendChild(d);
  setTimeout(()=>{d.style.opacity='0';d.style.transition='opacity .3s';setTimeout(()=>d.remove(),300)},4000);
}

/* ── 字幕样式编辑器 ── */
const SUB_DEFAULT={font:'Microsoft YaHei',size:16,color:'FFFFFF',outlineColor:'000000',outline:1,margin:30,align:2,bold:false};
let subStyle={...SUB_DEFAULT};

function hexToASS(h){return '&H00'+h}

function buildSubStyleStr(){
  let s='FontName='+subStyle.font+',FontSize='+subStyle.size+
    ',PrimaryColour='+hexToASS(subStyle.color)+
    ',OutlineColour=&H64'+subStyle.outlineColor+
    ',BorderStyle=3,Outline='+subStyle.outline+',Shadow=0'+
    ',MarginV='+subStyle.margin+',Alignment='+subStyle.align;
  if(subStyle.bold)s+=',Bold=1';
  return s
}

function updateSubPreview(){
  let el=E('subPrevText');
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
  E('subPrev').style.alignItems=vAlignMap[subStyle.align]||'flex-end';
}

function bindSubStyleControls(){
  E('ssFont').onchange=e=>{subStyle.font=e.target.value;updateSubPreview()};
  E('ssSize').oninput=e=>{subStyle.size=parseInt(e.target.value)||16;updateSubPreview()};
  E('ssOutline').oninput=e=>{subStyle.outline=parseFloat(e.target.value)||0;updateSubPreview()};
  E('ssMargin').oninput=e=>{subStyle.margin=parseInt(e.target.value)||0;updateSubPreview()};
  E('ssAlign').onchange=e=>{subStyle.align=parseInt(e.target.value);updateSubPreview()};
  E('ssBold').onchange=e=>{subStyle.bold=e.target.checked;updateSubPreview()};
  // 颜色联动
  E('ssColorPicker').oninput=e=>{subStyle.color=e.target.value.slice(1).toUpperCase();E('ssColor').value=subStyle.color;updateSubPreview()};
  E('ssColor').oninput=e=>{let v=e.target.value.replace(/[^0-9A-Fa-f]/g,'').slice(0,6).toUpperCase();e.target.value=v;if(v.length===6){subStyle.color=v;E('ssColorPicker').value='#'+v;updateSubPreview()}};
  E('ssOutlinePicker').oninput=e=>{subStyle.outlineColor=e.target.value.slice(1).toUpperCase();E('ssOutlineColor').value=subStyle.outlineColor;updateSubPreview()};
  E('ssOutlineColor').oninput=e=>{let v=e.target.value.replace(/[^0-9A-Fa-f]/g,'').slice(0,6).toUpperCase();e.target.value=v;if(v.length===6){subStyle.outlineColor=v;E('ssOutlinePicker').value='#'+v;updateSubPreview()}};
}

function resetSubStyle(){
  subStyle={...SUB_DEFAULT};
  E('ssFont').value=subStyle.font;E('ssSize').value=subStyle.size;
  E('ssOutline').value=subStyle.outline;E('ssMargin').value=subStyle.margin;
  E('ssAlign').value=subStyle.align;E('ssBold').checked=subStyle.bold;
  E('ssColor').value=subStyle.color;E('ssColorPicker').value='#'+subStyle.color;
  E('ssOutlineColor').value=subStyle.outlineColor;E('ssOutlinePicker').value='#'+subStyle.outlineColor;
  updateSubPreview();
  toast('已重置为默认样式','ok');
}

function applySubStyleFromStr(str){
  if(!str)return;
  let m;
  if(m=str.match(/FontName=([^,]+)/))subStyle.font=m[1];
  if(m=str.match(/FontSize=(\d+)/))subStyle.size=parseInt(m[1]);
  if(m=str.match(/PrimaryColour=&H00([0-9A-Fa-f]{6})/))subStyle.color=m[1].toUpperCase();
  if(m=str.match(/OutlineColour=&H64([0-9A-Fa-f]{6})/))subStyle.outlineColor=m[1].toUpperCase();
  if(m=str.match(/Outline=([\d.]+)/))subStyle.outline=parseFloat(m[1]);
  if(m=str.match(/MarginV=(\d+)/))subStyle.margin=parseInt(m[1]);
  if(m=str.match(/Alignment=(\d+)/))subStyle.align=parseInt(m[1]);
  if(m=str.match(/Bold=(\d+)/))subStyle.bold=m[1]==='1';
  // 同步 UI
  E('ssFont').value=subStyle.font;E('ssSize').value=subStyle.size;
  E('ssOutline').value=subStyle.outline;E('ssMargin').value=subStyle.margin;
  E('ssAlign').value=subStyle.align;E('ssBold').checked=subStyle.bold;
  E('ssColor').value=subStyle.color;E('ssColorPicker').value='#'+subStyle.color;
  E('ssOutlineColor').value=subStyle.outlineColor;E('ssOutlinePicker').value='#'+subStyle.outlineColor;
  updateSubPreview();
}

function init(){
  E('sp').oninput=()=>E('sv').textContent=parseFloat(E('sp').value).toFixed(2)+'x';
  E('bvol').oninput=()=>E('bv').textContent=Math.round(parseFloat(E('bvol').value)*100)+'%';
  E('bgmFile').onchange=uploadBGM;
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
    ttsEngine=d.engine||'system';
  document.querySelectorAll('.header .sub').forEach(el=>{el.textContent+=el.textContent?' · ':'';el.textContent+=d.label||''});
  }catch(e){}
}

/* ── BGM 管理 ── */
async function uploadBGM(){
  let f=E('bgmFile').files[0];if(!f)return;
  if(f.size>MAX_BGM){toast('BGM 文件超过 50MB 限制','warn');return}
  try{
    let b64=await fileToB64(f);
    let resp=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:f.name,data:b64,kind:'bgm'})});
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    let d=await resp.json();
    await loadBGMList();
    E('bgmSel').value=d.path;
    toast('BGM 上传成功','ok');
  }catch(e){toast('BGM 上传失败: '+e)}
}
async function loadBGMList(){
  try{
    let resp=await fetch('/api/bgm-list');if(!resp.ok)return;
    bgmList=await resp.json();
    let sel=E('bgmSel'),cur=sel.value;
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
      let idx=S.findIndex((s,i)=>i>=next&&!s.image);
      let sidx=idx>=0?idx:S.length;
      if(idx<0){S.push({image:'',text:'',hold:0,_loading:true})}
      S[sidx]._loading=true;
      next=(idx>=0?idx:sidx)+1;
      pain();
      try{let path=await uploadFile(f);S[sidx].image=path;S[sidx]._name=f.name;S[sidx]._loading=false}
      catch(e){console.error('upload',e);toast('上传失败: '+e);S[sidx]._loading=false;S[sidx]._error=true}
      uploading--;updateStats();pain();
    }
  };
  inp.click();
}

function handleDrop(files){
  let imgs=Array.from(files).filter(f=>f.type.startsWith('image/')||f.type.startsWith('video/'));
  if(!imgs.length)return;
  let next=0;
  for(let f of imgs){
    let idx=S.findIndex((s,i)=>i>=next&&!s.image);
    let sidx=idx>=0?idx:S.length;
    if(idx<0){S.push({image:'',text:'',hold:0,_loading:true})}
    S[sidx]._loading=true;
    next=(idx>=0?idx:sidx)+1;
    uploading++;updateStats();pain();
    uploadFile(f).then(path=>{S[sidx].image=path;S[sidx]._name=f.name;S[sidx]._loading=false})
    .catch(e=>{console.error('upload',e);toast('上传失败: '+e);S[sidx]._loading=false;S[sidx]._error=true})
    .finally(()=>{uploading--;updateStats();pain()});
  }
}

function add(img,txt,hold){S.push({image:img||'',text:txt||'',hold:hold||0});pain()}
function del(i){S.splice(i,1);pain()}
function chImg(i){
  let inp=document.createElement('input');inp.type='file';inp.accept='image/*,video/*';
  inp.onchange=async()=>{
    if(!inp.files[0])return;
    S[i]._loading=true;uploading++;updateStats();pain();
    try{let path=await uploadFile(inp.files[0]);S[i].image=path;S[i]._name=inp.files[0].name;S[i]._loading=false}
    catch(e){console.error(e);toast('换图失败: '+e);S[i]._loading=false}
    uploading--;updateStats();pain();
  };
  inp.click();
}
function updateStats(){E('ustats').textContent=uploading>0?uploading+' 张上传中...':'';}
function thumbUrl(i){let img=S[i].image;if(!img)return'';return'/thumb?path='+encodeURIComponent(img);}
function isVideo(path){return/\.(mp4|mov|mkv|avi|webm|flv)$/i.test(path||'')}
function lightbox(i){
  let img=S[i].image;if(!img)return;
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
  let t=S.splice(dragFrom,1)[0];S.splice(i,0,t);pain();dragFrom=null;dragOverIdx=null}

function pain(){
  if(!S.length){
    E('list').innerHTML='<div class="empty"><div class="icon">🎞</div><p>还没有场景</p><div class="hint">点击「添加图片」上传图片或视频，或将文件拖入此页面</div></div>';
    return;
  }
  let h='';
  S.forEach((s,i)=>{
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
      inner='<div class="loader"></div>';
    }
    let nm=s._name||(s.image?s.image.split('/').pop().split('\\').pop():'');
    let pathCls='path'+(s._error?' err':'');
    h+='<div class="scene" draggable="true" ondragstart="dragS('+i+',event)" ondragover="event.preventDefault();dragEnter('+i+')" ondragleave="dragLV()" ondrop="dropS('+i+',event)">'
      +'<div class="grip" title="拖拽排序">⠿</div>'
      +'<div class="idx">#'+(i+1)+'</div>'
      +'<div class="'+cls+'" onclick="lightbox('+i+')">'+inner+'</div>'
      +'<div class="body">'
        +'<textarea placeholder="输入解说文案（按句自动切字幕，逗号长句智能断句）" oninput="S['+i+'].text=this.value">'+esc(s.text)+'</textarea>'
        +'<div class="foot">'
          +'<span class="'+pathCls+'">'+esc(nm||(s._loading?'上传中...':(s._error?'上传失败':'未上传文件')))+'</span>'
          +'<input class="hold-input" type="number" placeholder="停顿秒" value="'+(s.hold||'')+'" oninput="S['+i+'].hold=parseFloat(this.value)||0" title="场景末尾额外停留秒数">'
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

/* ── 渲染 ── */
async function render(){
  // 实时从 DOM 读取 textarea 值（防止 oninput 未同步的场景）
  document.querySelectorAll('.scene textarea').forEach((ta,i)=>{if(S[i])S[i].text=ta.value});
  let valid=S.filter(s=>s.image);
  if(!valid.length){alert('请至少添加一张图片');return}
  if(uploading>0){alert('还有图片在上传中，请稍候');return}
  let bgm=E('bgmSel').value||null;
  let res=(E('res').value||'1920x1080').split('x');
  let subStyleStr=buildSubStyleStr();
  let m={title:'narravid',width:parseInt(res[0]),height:parseInt(res[1]),tts_engine:ttsEngine,workers:parseInt(E('wk').value),
    voice:E('v').value,speech_speed:parseFloat(E('sp').value),burn_subtitles:E('bs').checked,
    bgm_volume:parseFloat(E('bvol').value),card_duration:parseFloat(E('tcd').value),
    subtitle_style:subStyleStr,
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold||0}))};
  let body={manifest:m,bgm:bgm,
    title_card:E('tc').value.trim()||null,
    end_card:E('ec').value.trim()||null,
    card_duration:parseFloat(E('tcd').value),
    end_card_duration:parseFloat(E('ecd').value)};
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
  else{
    currentVideo=video||'';
    b.textContent='✅ 视频已生成！';b.style.background='linear-gradient(135deg,#1e8449,#27ae60)';b.style.display='block';
    if(video){showPreview(video)}
  }
}
function cancel(){if(rid)fetch('/api/cancel/'+rid,{method:'POST'});clearTimeout(tmr);E('st').style.display='none';E('rb').disabled=false;rid=null;E('pf').style.width='0'}

/* ── 视频预览 ── */
function showPreview(url){
  E('pvVid').src=url;E('pv').style.display='block';
}
function closePreview(){E('pvVid').pause();E('pvVid').src='';E('pv').style.display='none'}
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
  let name=E('tplName')?.value?.trim()||('模板 '+(new Date().toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})));
  // 实时读 textarea
  document.querySelectorAll('.scene textarea').forEach((ta,i)=>{if(S[i])S[i].text=ta.value});
  let data={name,scenes:S.filter(s=>s.image).map(s=>({text:s.text,image:s.image,hold:s.hold})),
    voice:E('v').value,speed:E('sp').value,burn:E('bs').checked,
    resolution:E('res').value,title_card:E('tc').value,end_card:E('ec').value,
    bgm_volume:E('bvol').value,workers:E('wk').value,
    subtitle_style:buildSubStyleStr()};
  await fetch('/api/templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  toast('模板已保存','ok');
  document.querySelector('.dialog-overlay')?.remove();
}
async function loadTemplate(id){
  let t=await fetch('/api/templates/'+id).then(r=>r.json());
  if(t.scenes){S=t.scenes.map(s=>({image:s.image||'',text:s.text||'',hold:s.hold||0}));pain()}
  if(t.voice)E('v').value=t.voice;
  if(t.speed)E('sp').value=t.speed,E('sv').textContent=parseFloat(t.speed).toFixed(2)+'x';
  if(t.burn!==undefined)E('bs').checked=t.burn;
  if(t.resolution)E('res').value=t.resolution;
  if(t.title_card)E('tc').value=t.title_card;
  if(t.end_card)E('ec').value=t.end_card;
  if(t.bgm_volume!==undefined)E('bvol').value=t.bgm_volume,E('bv').textContent=Math.round(parseFloat(t.bgm_volume)*100)+'%';
  if(t.workers)E('wk').value=t.workers;
  if(t.subtitle_style)applySubStyleFromStr(t.subtitle_style);
  document.querySelector('.dialog-overlay')?.remove();
  toast('模板已加载','ok');
}
async function delTemplate(id){
  await fetch('/api/templates/'+id,{method:'DELETE'});
  document.querySelector('.dialog-overlay')?.remove();
  showTemplates();
}
async function renameTemplate(id,oldName){
  let el=E('tplName_'+id);
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
  document.querySelectorAll('.scene textarea').forEach((ta,i)=>{if(S[i])S[i].text=ta.value});
  let valid=S.filter(s=>s.image);
  if(!valid.length){toast('没有场景可导出','warn');return}
  let res=(E('res').value||'1920x1080').split('x');
  let m={title:'narravid',width:parseInt(res[0]),height:parseInt(res[1]),tts_engine:ttsEngine,workers:parseInt(E('wk').value),
    voice:E('v').value,speech_speed:parseFloat(E('sp').value),burn_subtitles:E('bs').checked,
    bgm_volume:parseFloat(E('bvol').value),card_duration:parseFloat(E('tcd').value),
    subtitle_style:buildSubStyleStr(),
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold||0}))};
  let bgm=E('bgmSel').value||null;
  toast('正在打包...','info');
  try{
    let resp=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({manifest:m,bgm:bgm})});
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
    if(f.size>100*1024*1024){toast('文件过大（上限100MB）','warn');return}
    let b64=await fileToB64(f);
    toast('正在导入...','info');
    try{
      let resp=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({data:b64})});
      let d=await resp.json();
      if(d.error){toast(d.error,'error');return}
      // 加载 manifest 到 UI
      let m=d.manifest;
      S=m.scenes.map(s=>({image:s.image,text:s.text,hold:s.hold_sec||0}));
      if(m.tts_engine)ttsEngine=m.tts_engine;
      if(m.voice)E('v').value=m.voice;
      if(m.speech_speed)E('sp').value=m.speech_speed;
      if(m.workers)E('wk').value=m.workers;
      if(m.burn_subtitles!==undefined)E('bs').checked=m.burn_subtitles;
      if(m.bgm_volume!==undefined)E('bvol').value=m.bgm_volume;
      if(m.card_duration!==undefined)E('tcd').value=m.card_duration;
      if(m.width&&m.height){
        let res=m.width+'x'+m.height;
        for(let opt of E('res').options){if(opt.value===res)opt.selected=true}
      }
      // BGM
      if(d.bgm){
        await loadBGMList();
        for(let opt of E('bgmSel').options){if(opt.value===d.bgm||opt.value.endsWith(d.bgm.split(/[\\/]/).pop()))opt.selected=true}
      }
      pain();toast('已导入工程（'+S.length+' 个场景）','ok');
    }catch(e){toast('导入失败: '+e,'error')}
  };
  inp.click();
}

/* ── 清理旧文件 ── */
async function cleanOld(){
  let r=await fetch('/api/clean',{method:'POST'});let d=await r.json();
  toast(d.message||'已清理',d.error?'error':'ok');
}

document.addEventListener('dragover',e=>e.preventDefault());
document.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files.length)handleDrop(e.dataTransfer.files)});
init();
</script>
</body>
</html>
'''

JOBS = {}
RENDER_LOCK = threading.Lock()  # 全局渲染锁：同时只允许一个渲染任务执行


def _check_edge_tts():
    """检测 edge-tts 是否可用，返回 ('edge'|'system', str)"""
    try:
        import edge_tts
        return 'edge', 'Edge TTS'
    except ImportError:
        return 'system', '系统 TTS'


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
                # 安全路径检查：必须严格在允许目录内（用 relative_to 防止前缀绕过）
                allowed = False
                for d in THUMB_ALLOWED_DIRS:
                    try:
                        fp.relative_to(d)
                        allowed = True
                        break
                    except ValueError:
                        pass
                if not allowed:
                    self._json({'error': 'forbidden'}, 403); return
                if fp.exists() and fp.is_file():
                    # 按文件类型设置正确的 Content-Type
                    ext = fp.suffix.lower()
                    if ext in ('.mp4',):
                        ct = 'video/mp4'
                    elif ext in ('.webm',):
                        ct = 'video/webm'
                    elif ext in ('.mov',):
                        ct = 'video/quicktime'
                    elif ext in ('.mkv',):
                        ct = 'video/x-matroska'
                    elif ext == '.png':
                        ct = 'image/png'
                    elif ext in ('.jpg', '.jpeg'):
                        ct = 'image/jpeg'
                    elif ext in ('.gif',):
                        ct = 'image/gif'
                    else:
                        ct = 'application/octet-stream'
                    self._file(fp, ct)
                    return
            self._json({'error': 'not found'}, 404)
        elif p.path.startswith('/api/status/'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if not j:
                self._json({'error': 'not found'}, 404); return
            done = j.get('done', False)
            progress = j.get('progress', '')
            pf = j.get('progress_file')
            if pf and Path(pf).exists():
                try:
                    progress = Path(pf).read_text(encoding='utf-8').strip() or progress
                except Exception:
                    pass
            resp = {'done': done, 'progress': progress, 'video': j.get('video'), 'srt': j.get('srt')}
            if done:
                if j.get('error'):
                    resp['error'] = j['error'][-300:]
                else:
                    video = j.get('video', '')
                    # 回退：如果还没设置 video，直接扫目录
                    if not video:
                        out_dir = j.get('out')
                        if out_dir:
                            mp4s = sorted(Path(out_dir).glob('*.mp4'))
                            if mp4s:
                                video = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\', '/')
                                j['video'] = video
                    resp['video'] = video
                    j['progress'] = j.get('progress') or '完成'
            self._json(resp)
        elif p.path == '/api/bgm-list':
            bgms = []
            for f in sorted(UPLOAD_DIR.glob('*.mp3')) + sorted(UPLOAD_DIR.glob('*.wav')):
                bgms.append({'name': f.name, 'path': str(f.resolve())})
            self._json(bgms)
        elif p.path == '/api/tts-check':
            engine, label = _check_edge_tts()
            self._json({'engine': engine, 'label': label})
        elif p.path.startswith('/api/templates'):
            self._handle_templates_get(p)
        elif p.path.startswith('/rendered/'):
            fp = (ROOT / p.path.lstrip('/')).resolve()
            # 安全路径检查：必须严格在 ROOT 内（防目录穿越）
            try:
                fp.relative_to(ROOT.resolve())
            except ValueError:
                self._json({'error': 'forbidden'}, 403); return
            if fp.exists():
                self._file(fp, 'video/mp4' if fp.suffix == '.mp4' else 'text/plain')
            else:
                self._json({'error': 'not found'}, 404)
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
        if length > MAX_UPLOAD_SIZE:
            self._json({'error': f'文件过大（上限 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）'}, 413)
            return
        body = self.rfile.read(length) if length else b''

        if p.path == '/api/upload':
            data = json.loads(body)
            name = data.get('name', 'image.png')
            b64 = data.get('data', '')
            kind = data.get('kind', 'image')
            try:
                raw = base64.b64decode(b64)
            except Exception:
                self._json({'error': 'base64 解码失败'}, 400); return
            # 大小校验
            if kind == 'bgm' and len(raw) > MAX_BGM_SIZE:
                self._json({'error': f'BGM 文件超过 {MAX_BGM_SIZE // 1024 // 1024}MB 限制'}, 413); return
            elif len(raw) > MAX_VIDEO_SIZE:
                self._json({'error': f'文件超过 {MAX_VIDEO_SIZE // 1024 // 1024}MB 限制'}, 413); return
            # sanitize filename: replace non-ASCII chars to avoid path/encoding issues
            safe_name = re.sub(r'[^\x20-\x7e]', '_', name)
            fp = UPLOAD_DIR / f'{uuid.uuid4().hex}_{safe_name}'
            fp.write_bytes(raw)
            self._json({'path': str(fp.resolve())})

        elif p.path == '/api/render':
            data = json.loads(body)
            m = data.get('manifest', {})
            bgm = data.get('bgm')
            tc = data.get('title_card')
            ec = data.get('end_card')
            rid = data.get('render_id')
            # 防止客户端 render_id 碰撞：如已存在则重新生成
            if rid and rid in JOBS:
                rid = str(uuid.uuid4())
            else:
                rid = rid or str(uuid.uuid4())
            out = OUT_BASE / rid; out.mkdir(parents=True, exist_ok=True)
            mp = out / 'manifest.json'
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
            # 构建命令行参数列表（统一方式，兼容源码和 exe 模式）
            cmd = [str(SCRIPT), str(mp), '--output-dir', str(out)]
            if bgm:
                bgm_path = Path(bgm)
                if not bgm_path.is_absolute():
                    bgm_path = UPLOAD_DIR / bgm_path
                if bgm_path.exists():
                    cmd += ['--bgm', str(bgm_path.resolve())]
                    bvol = m.get('bgm_volume')
                    if bvol is not None and isinstance(bvol, (int, float)) and 0.0 <= bvol <= 1.0:
                        cmd += ['--bgm-volume', str(bvol)]
            if tc:
                # write non-ASCII title card text to temp file to avoid cmdline encoding issues
                if any(ord(c) > 127 for c in tc):
                    tcf = out / '_title_card.txt'
                    tcf.write_text(tc, encoding='utf-8')
                    cmd += ['--title-card-file', str(tcf)]
                else:
                    cmd += ['--title-card', tc]
                cd = data.get('card_duration')
                if cd and isinstance(cd, (int, float)) and cd >= 1.0:
                    cmd += ['--card-duration', str(cd)]
            if ec:
                if any(ord(c) > 127 for c in ec):
                    ecf = out / '_end_card.txt'
                    ecf.write_text(ec, encoding='utf-8')
                    cmd += ['--end-card-file', str(ecf)]
                else:
                    cmd += ['--end-card', ec]
                ecd = data.get('end_card_duration')
                if ecd and isinstance(ecd, (int, float)) and ecd >= 1.0:
                    cmd += ['--end-card-duration', str(ecd)]
            if not m.get('burn_subtitles', True):
                cmd += ['--no-burn']
            # 字幕样式
            ss = m.get('subtitle_style')
            if ss and isinstance(ss, str) and len(ss) < 500:
                cmd += ['--subtitle-style', ss]
            engine = m.get('tts_engine')
            if engine and engine in ('edge', 'system'):
                cmd += ['--engine', engine]
            if m.get('voice'):
                cmd += ['--voice', str(m['voice'])]
            spd = m.get('speech_speed')
            if spd and isinstance(spd, (int, float)) and 0.5 <= spd <= 3.0:
                cmd += ['--speed', str(spd)]
            wk = m.get('workers', 4)
            if wk and isinstance(wk, int) and 1 <= wk <= 32:
                cmd += ['--workers', str(wk)]
            progress_file = out / '_progress.txt'
            progress_file.write_text('初始化...', encoding='utf-8')
            env = os.environ.copy()
            env['NARRAVID_PROGRESS_FILE'] = str(progress_file)

            # 在子线程中直接调用 video_auto.main()，不再用 subprocess
            # 这样 exe 模式下无需依赖 sys.executable 指向 python 解释器
            cancel_event = threading.Event()
            JOBS[rid] = {'proc': None, 'progress': 'TTS 生成中...', 'video': '', 'srt': '',
                         'progress_file': str(progress_file), 'out': out,
                         'cancel_event': cancel_event, 'done': False, 'error': ''}

            # 保存原始 argv 和 cwd，线程结束后恢复
            orig_argv = sys.argv
            orig_cwd = os.getcwd()
            # 环境变量：只设 progress_file，不改全局 os.environ
            progress_env_val = str(progress_file)

            def run_in_thread():
                j = JOBS.get(rid)
                if not j:
                    return
                with RENDER_LOCK:
                    if j.get('done'):
                        return  # 已被取消
                    # 在获取锁之后才重置取消令牌，避免排队期间被前一个任务的取消污染
                    import video_auto as _va
                    _va.CancelToken.reset()
                    try:
                        os.chdir(str(ROOT))
                        sys.argv = cmd
                        # 只设 progress_file 环境变量，不污染全局
                        os.environ['NARRAVID_PROGRESS_FILE'] = progress_env_val
                        _va.main()
                        # 成功完成
                        mp4s = sorted(out.glob('*.mp4'))
                        if mp4s:
                            j['video'] = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\', '/')
                        j['progress'] = '完成'
                    except Exception as e:
                        import traceback
                        tb = traceback.format_exc()
                        err_file = out / '_stderr.log'
                        err_file.write_text(tb, encoding='utf-8', errors='ignore')
                        j['error'] = str(e)[-500:]
                        j['progress'] = f'失败: {e}'[:200]
                    finally:
                        # 恢复原始状态
                        sys.argv = orig_argv
                        os.chdir(orig_cwd)
                        # 恢复 progress_file 环境变量
                        if 'NARRAVID_PROGRESS_FILE' in os.environ:
                            del os.environ['NARRAVID_PROGRESS_FILE']
                        j['done'] = True

            def mon():
                """监控线程：检查进度 + 超时检测"""
                j = JOBS.get(rid)
                if not j:
                    return
                last_progress = ''
                stall_count = 0
                while not j.get('done'):
                    time.sleep(2)
                    if j.get('done'):
                        break
                    current_progress = ''
                    pf = j.get('progress_file')
                    if pf and Path(pf).exists():
                        try:
                            current_progress = Path(pf).read_text(encoding='utf-8').strip()
                        except Exception:
                            pass
                    if current_progress == last_progress:
                        stall_count += 1
                    else:
                        stall_count = 0
                        last_progress = current_progress
                    # 连续 30 次（60 秒）无进度更新则判定卡死
                    if stall_count >= 30:
                        j['error'] = '渲染超时：60 秒无进度更新'
                        j['progress'] = '超时（渲染卡死）'
                        j['done'] = True
                        # 通知渲染线程中断
                        try:
                            import video_auto as _va
                            _va.CancelToken.set_cancelled()
                        except Exception:
                            pass
                        if j.get('cancel_event'):
                            j['cancel_event'].set()
                        return
                    if j.get('cancel_event') and j['cancel_event'].is_set():
                        j['progress'] = '已取消'
                        j['done'] = True
                        return

            # 启动渲染线程和监控线程
            threading.Thread(target=run_in_thread, daemon=True).start()
            threading.Thread(target=mon, daemon=True).start()
            # 延迟清理 JOBS（5 分钟后），避免内存泄漏
            def cleanup_job():
                time.sleep(300)
                j = JOBS.get(rid)
                if j and not j.get('done'):
                    # 任务仍在运行，推迟清理
                    threading.Thread(target=cleanup_job, daemon=True).start()
                    return
                JOBS.pop(rid, None)
            threading.Thread(target=cleanup_job, daemon=True).start()
            self._json({'render_id': rid})

        elif p.path.startswith('/api/cancel'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if j:
                # 先设置取消信号，再标记 done，避免 mon() 提前退出错过取消
                if j.get('cancel_event'):
                    j['cancel_event'].set()
                try:
                    import video_auto as _va
                    _va.CancelToken.set_cancelled()
                except Exception:
                    pass
                j['progress'] = '已取消'
                j['done'] = True
            self._json({'status': 'ok'})

        elif p.path == '/api/clean':
            cleaned = 0
            # 按修改时间排序，保留最近 5 次
            dirs = sorted(
                [d for d in OUT_BASE.iterdir() if d.is_dir() and d.name not in ('uploads', 'templates')],
                key=lambda d: d.stat().st_mtime, reverse=True
            )
            for d in dirs[5:]:
                shutil.rmtree(d, ignore_errors=True)
                cleaned += 1
            self._json({'message': f'已清理 {cleaned} 个旧渲染，保留最近 5 个', 'cleaned': cleaned})

        elif p.path == '/api/templates':
            # POST = save template
            data = json.loads(body)
            tid = uuid.uuid4().hex[:8]
            tp = TEMPLATE_DIR / f'{tid}.json'
            data['id'] = tid
            data['date'] = time.strftime('%Y-%m-%d %H:%M')
            data['count'] = len(data.get('scenes', []))
            tp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            self._json({'id': tid})

        elif p.path == '/api/export':
            # 导出工程：manifest + 所有引用的图片/视频 + BGM 打包成 zip
            import zipfile, tempfile
            data = json.loads(body)
            m = data.get('manifest', {})
            bgm = data.get('bgm')
            # 创建临时 zip
            zip_buf = io.BytesIO()
            zf = zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED)
            # 收集需要打包的文件及其新路径
            collected = {}  # abs_path -> zip_relative_path
            manifest_copy = json.loads(json.dumps(m))  # deep copy
            for i, scene in enumerate(manifest_copy.get('scenes', [])):
                img = scene.get('image', '')
                if not img:
                    continue
                img_path = Path(img)
                if not img_path.is_absolute():
                    img_path = UPLOAD_DIR / img_path
                img_path = img_path.resolve()
                if img_path.exists() and str(img_path) not in collected:
                    ext = img_path.suffix.lower()
                    zname = f'assets/scene_{i:03d}{ext}'
                    collected[str(img_path)] = zname
                if str(img_path) in collected:
                    scene['image'] = collected[str(img_path)]
            # BGM
            if bgm:
                bgm_path = Path(bgm)
                if not bgm_path.is_absolute():
                    bgm_path = UPLOAD_DIR / bgm_path
                bgm_path = bgm_path.resolve()
                if bgm_path.exists():
                    zname = f'assets/bgm{bgm_path.suffix}'
                    collected[str(bgm_path)] = zname
                    manifest_copy['bgm'] = zname
            # 写入 manifest
            zf.writestr('manifest.json', json.dumps(manifest_copy, ensure_ascii=False, indent=2))
            # 写入所有媒体文件
            for abs_path, zname in collected.items():
                zf.write(abs_path, zname)
            zf.close()
            zip_data = zip_buf.getvalue()
            # 返回 base64
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', f'attachment; filename="narravid_project.zip"')
            self.send_header('Content-Length', str(len(zip_data)))
            self.end_headers()
            self.wfile.write(zip_data)

        elif p.path == '/api/import':
            # 导入工程：上传 zip，解压到 uploads 新目录，返回修正路径后的 manifest
            import zipfile, tempfile
            data = json.loads(body)
            b64 = data.get('data', '')
            try:
                zip_bytes = base64.b64decode(b64)
            except Exception:
                self._json({'error': 'base64 解码失败'}, 400); return
            project_id = uuid.uuid4().hex[:8]
            project_dir = UPLOAD_DIR / f'project_{project_id}'
            project_dir.mkdir(parents=True, exist_ok=True)
            zip_buf = io.BytesIO(zip_bytes)
            with zipfile.ZipFile(zip_buf, 'r') as zf:
                # 安全检查：防止路径穿越和 zip bomb
                total_size = 0
                max_extract = 500 * 1024 * 1024  # 500MB 上限
                safe_members = []
                for member in zf.namelist():
                    # 检查路径穿越
                    member_path = (project_dir / member).resolve()
                    try:
                        member_path.relative_to(project_dir.resolve())
                    except ValueError:
                        self._json({'error': f'zip 包含非法路径: {member}'}, 400); return
                    # 检查解压后总大小
                    total_size += zf.getinfo(member).file_size
                    if total_size > max_extract:
                        self._json({'error': 'zip 解压后超过 500MB 限制'}, 400); return
                    safe_members.append(member)
                zf.extractall(project_dir, members=safe_members)
            # 读取 manifest 并修正路径
            mp = project_dir / 'manifest.json'
            if not mp.exists():
                self._json({'error': 'zip 中未找到 manifest.json'}, 400); return
            manifest = json.loads(mp.read_text(encoding='utf-8'))
            # 校验 manifest 基本结构
            if not isinstance(manifest, dict):
                self._json({'error': 'manifest.json 不是有效 JSON 对象'}, 400); return
            scenes = manifest.get('scenes')
            if not isinstance(scenes, list):
                self._json({'error': 'manifest.scenes 不是数组'}, 400); return
            for scene in scenes:
                img = scene.get('image', '')
                if img and not Path(img).is_absolute():
                    scene['image'] = str((project_dir / img).resolve())
            bgm_val = manifest.pop('bgm', None)
            if bgm_val and not Path(bgm_val).is_absolute():
                bgm_val = str((project_dir / bgm_val).resolve())
            self._json({'manifest': manifest, 'bgm': bgm_val})

        else:
            self._json({'error': 'not found'}, 404)

    def _handle_templates_get(self, p):
        if p.path == '/api/templates':
            # 列表
            tpls = []
            for f in sorted(TEMPLATE_DIR.glob('*.json')):
                try:
                    d = json.loads(f.read_text(encoding='utf-8'))
                    tpls.append({'id': d.get('id', f.stem), 'name': d.get('name', f.stem),
                                 'count': d.get('count', 0), 'date': d.get('date', '')})
                except Exception:
                    pass
            self._json(tpls)
        else:
            # 单个模板 GET /api/templates/<id>
            tid = p.path.split('/')[-1]
            tp = TEMPLATE_DIR / f'{tid}.json'
            if tp.exists():
                self._json(json.loads(tp.read_text(encoding='utf-8')))
            else:
                self._json({'error': 'not found'}, 404)

    def do_PUT(self):
        p = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        if p.path.startswith('/api/templates/'):
            tid = p.path.split('/')[-1]
            tp = TEMPLATE_DIR / f'{tid}.json'
            if not tp.exists():
                self._json({'error': 'not found'}, 404); return
            data = json.loads(body) if body else {}
            tpl = json.loads(tp.read_text(encoding='utf-8'))
            if 'name' in data:
                tpl['name'] = data['name']
            if 'subtitle_style' in data:
                tpl['subtitle_style'] = data['subtitle_style']
            tp.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding='utf-8')
            self._json({'status': 'ok'})
        else:
            self._json({'error': 'not found'}, 404)

    def do_DELETE(self):
        p = urllib.parse.urlparse(self.path)
        if p.path.startswith('/api/templates/'):
            tid = p.path.split('/')[-1]
            tp = TEMPLATE_DIR / f'{tid}.json'
            if tp.exists():
                tp.unlink()
                self._json({'status': 'ok'})
            else:
                self._json({'error': 'not found'}, 404)
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
    ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--host', default='127.0.0.1')
    args = ap.parse_args()
    for d in [OUT_BASE, UPLOAD_DIR, TEMPLATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    srv = HTTPServer((args.host, args.port), H)
    url = f'http://{args.host}:{args.port}'
    print(f'narravid Web UI: {url}')
    print(f'  打开浏览器访问上述地址即可')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('stopped'); srv.shutdown()


if __name__ == '__main__':
    main()
