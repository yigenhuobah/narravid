"""
narravid Web UI v6 — 图片上传、缩略图预览、BGM 管理、在线预览、模板、一键生成。

用法:
  python webui.py
  python webui.py --port 8080
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
      if(idx<0){scenes.push({image:'',text:'',hold:0,_loading:true})}
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
    if(idx<0){scenes.push({image:'',text:'',hold:0,_loading:true})}
    scenes[sidx]._loading=true;
    next=(idx>=0?idx:sidx)+1;
    uploading++;updateStats();paintScenes();
    uploadFile(f).then(path=>{scenes[sidx].image=path;scenes[sidx]._name=f.name;scenes[sidx]._loading=false})
    .catch(e=>{console.error('upload',e);toast('上传失败: '+e);scenes[sidx]._loading=false;scenes[sidx]._error=true})
    .finally(()=>{uploading--;updateStats();paintScenes()});
  }
}

function add(img,txt,hold){scenes.push({image:img||'',text:txt||'',hold:hold||0});paintScenes()}
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
          +'<input class="hold-input" type="number" placeholder="停顿秒" value="'+(s.hold||'')+'" oninput="scenes['+i+'].hold=parseFloat(this.value)||0" title="场景末尾额外停留秒数">'
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
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold||0}))};
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
  let data={name,scenes:scenes.filter(s=>s.image).map(s=>({text:s.text,image:s.image,hold:s.hold})),
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
  if(t.scenes){scenes=t.scenes.map(s=>({image:s.image||'',text:s.text||'',hold:s.hold||0}));paintScenes()}
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
    scenes:valid.map(s=>({image:s.image,text:s.text.trim(),hold_sec:s.hold||0}))};
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
      scenes=m.scenes.map(s=>({image:s.image,text:s.text||'',hold:s.hold_sec||s.hold||0}));
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

JOBS = {}
RENDER_LOCK = threading.Lock()  # 全局渲染锁：同时只允许一个渲染任务执行
ACTIVE_RENDER_ID = None  # 当前持有 RENDER_LOCK 并执行 main() 的 job id
_ACTIVE_RENDER_LOCK = threading.Lock()
# 渲染媒体允许目录：uploads / examples-assets / 输出树
MEDIA_ALLOWED_DIRS = [
    UPLOAD_DIR.resolve(),
    (ROOT / 'examples-assets').resolve(),
    OUT_BASE.resolve(),
]


def _set_active_render(rid):
    global ACTIVE_RENDER_ID
    with _ACTIVE_RENDER_LOCK:
        ACTIVE_RENDER_ID = rid


def _get_active_render():
    with _ACTIVE_RENDER_LOCK:
        return ACTIVE_RENDER_ID


def _is_under(path: Path, root: Path) -> bool:
    """True if resolved path is inside root (or is root)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_under_any(path: Path, roots) -> bool:
    for root in roots:
        if _is_under(path, root):
            return True
    return False


def _sanitize_upload_name(name: str) -> str:
    """Basename only; strip path separators / traversal; ASCII-only safe chars."""
    base = Path(str(name or '')).name or 'file.bin'
    stem = Path(base).stem
    suffix = Path(base).suffix.lower()
    # 扩展名仅保留 . + ASCII 字母数字
    if suffix:
        suffix = '.' + re.sub(r'[^A-Za-z0-9]+', '', suffix.lstrip('.'))[:12]
        if suffix == '.':
            suffix = ''
    # 仅保留 ASCII 字母数字与 _-，中文/空格/符号一律替换
    safe_stem = re.sub(r'[^A-Za-z0-9_-]+', '_', stem).strip('._-') or 'file'
    safe = safe_stem + (suffix or '')
    return safe or 'file.bin'


def _sanitize_render_id(rid) -> str | None:
    """Client render_id must be a simple token; reject path traversal/absolute."""
    rid = (str(rid) if rid is not None else '').strip()
    if not rid:
        return None
    if not re.fullmatch(r'[\w.-]{1,64}', rid):
        return None
    if rid in ('.', '..') or '..' in rid:
        return None
    return rid


def _job_out_dir(rid: str) -> Path | None:
    """Resolve job output dir strictly under OUT_BASE."""
    safe = _sanitize_render_id(rid)
    if not safe:
        return None
    out = (OUT_BASE / safe).resolve()
    if not _is_under(out, OUT_BASE):
        return None
    return out


def _resolve_media_path(raw, base_dir: Path = None) -> Path | None:
    """Resolve scene/BGM path; must exist as file under MEDIA_ALLOWED_DIRS."""
    if not raw:
        return None
    p = Path(str(raw))
    if not p.is_absolute():
        base = base_dir or UPLOAD_DIR
        p = (base / p).resolve()
    else:
        p = p.resolve()
    if not (p.exists() and p.is_file() and _is_under_any(p, MEDIA_ALLOWED_DIRS)):
        return None
    return p


def _is_waiting_for_lock(rid, job: dict) -> bool:
    """Job has not yet become the active renderer (still queued)."""
    active = _get_active_render()
    if active == rid:
        return False
    if active is not None:
        return True
    return not job.get('_started')


def _looks_like_cancel(msg) -> bool:
    """User-cancel only — not internal '渲染已中止'."""
    if not isinstance(msg, str):
        return False
    return '用户取消' in msg or msg.strip() in ('已取消', '渲染已被用户取消')


def _mark_job_cancelled(job: dict, error: str = '已取消') -> bool:
    """Mark a job as cancelled/done.

    Returns False if the job is already in a non-cancel terminal state
    (success with video, or failure/timeout diagnostics). Late cancel must
    not wipe a finished video URL or rewrite timeout/fail errors.
    """
    if job.get('done') and not job.get('cancelled'):
        return False
    if job.get('cancelled') and job.get('done'):
        return True
    job['cancelled'] = True
    job['progress'] = '已取消'
    job['error'] = job.get('error') or error
    job['done'] = True
    return True


def _signal_cancel_token_if_active(rid):
    """仅当 rid 是当前正在执行的渲染时，才设置全局 CancelToken。"""
    if rid and rid == _get_active_render():
        try:
            import video_auto as _va
            _va.CancelToken.set_cancelled()
        except Exception:
            pass


def _check_edge_tts():
    """检测可用 TTS，返回 (engine, label)。

    委托 video_auto 的探测逻辑；Linux/macOS 不会谎称系统 TTS 可用。
    """
    try:
        import video_auto as _va
        if _va.edge_tts_available():
            return 'edge', 'Edge TTS'
        if _va.system_tts_available():
            return 'system', '系统 TTS'
    except Exception:
        pass
    return 'none', '无可用 TTS（请安装 edge-tts）'


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
            cancelled = bool(j.get('cancelled'))
            # 终态（取消/超时/失败）以 job 字段为准，勿被仍在写的 progress_file 盖掉
            if not (done or cancelled or j.get('error')):
                pf = j.get('progress_file')
                if pf and Path(pf).exists():
                    try:
                        progress = Path(pf).read_text(encoding='utf-8').strip() or progress
                    except Exception:
                        pass
            if not cancelled:
                cancelled = _looks_like_cancel(progress) or _looks_like_cancel(j.get('error'))
            resp = {
                'done': done,
                'progress': progress,
                'video': j.get('video') if not cancelled else '',
                'srt': j.get('srt'),
                'cancelled': cancelled,
            }
            if done:
                if j.get('error'):
                    resp['error'] = j['error'][-300:]
                elif cancelled:
                    # 明确标记取消，避免前端当成成功
                    resp['cancelled'] = True
                    if not resp.get('error'):
                        resp['error'] = '已取消'
                else:
                    video = j.get('video', '')
                    # 回退：如果还没设置 video，直接扫目录（仅 job 自身 out）
                    if not video:
                        out_dir = j.get('out')
                        if out_dir:
                            try:
                                od = Path(out_dir).resolve()
                                if _is_under(od, OUT_BASE):
                                    mp4s = sorted(od.glob('*.mp4'))
                                    if mp4s:
                                        video = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\', '/')
                                        j['video'] = video
                                        if not j.get('srt'):
                                            srt_p = mp4s[0].with_suffix('.srt')
                                            if srt_p.is_file():
                                                j['srt'] = '/' + str(srt_p.relative_to(ROOT)).replace('\\', '/')
                            except Exception:
                                pass
                    resp['video'] = video
                    if j.get('srt'):
                        resp['srt'] = j.get('srt')
                    j['progress'] = j.get('progress') or '完成'
            self._json(resp)
        elif p.path == '/api/bgm-list':
            bgms = []
            # 递归：含导入工程 project_*/assets 下的 BGM
            seen = set()
            for pattern in ('**/*.mp3', '**/*.wav'):
                for f in sorted(UPLOAD_DIR.glob(pattern)):
                    if not f.is_file():
                        continue
                    key = str(f.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    bgms.append({'name': f.name, 'path': key})
            self._json(bgms)
        elif p.path == '/api/tts-check':
            engine, label = _check_edge_tts()
            self._json({'engine': engine, 'label': label})
        elif p.path == '/api/health':
            # Lightweight readiness for operators / reverse proxies
            engine, label = _check_edge_tts()
            ffmpeg_ok = False
            ffprobe_ok = False
            ffmpeg_path = ''
            ffprobe_path = ''
            try:
                import shutil

                import _bundled_ffmpeg as _bf
                ffmpeg_path = _bf.get_ffmpeg()
                ffprobe_path = _bf.get_ffprobe()
                ffmpeg_ok = bool(shutil.which(ffmpeg_path) or Path(ffmpeg_path).is_file() or ffmpeg_path == 'ffmpeg')
                ffprobe_ok = bool(shutil.which(ffprobe_path) or Path(ffprobe_path).is_file() or ffprobe_path == 'ffprobe')
                # Prefer real existence when absolute
                if Path(ffmpeg_path).is_file():
                    ffmpeg_ok = True
                if Path(ffprobe_path).is_file():
                    ffprobe_ok = True
            except Exception:
                pass
            font_path = None
            try:
                import video_auto as _va
                font_path = _va._find_zh_font()
            except Exception:
                pass
            ok = engine in ('edge', 'system') and ffmpeg_ok
            self._json({
                'ok': ok,
                'tts': {'engine': engine, 'label': label},
                'ffmpeg': {'ok': ffmpeg_ok, 'path': ffmpeg_path},
                'ffprobe': {'ok': ffprobe_ok, 'path': ffprobe_path},
                'font': {'ok': bool(font_path), 'path': font_path or ''},
                'active_render': _get_active_render(),
                'jobs': len(JOBS),
            }, 200 if ok else 503)
        elif p.path.startswith('/api/templates'):
            self._handle_templates_get(p)
        elif p.path.startswith('/rendered/'):
            fp = (ROOT / p.path.lstrip('/')).resolve()
            # 仅允许成品输出：rendered/webui/<job>/ 下的视频与字幕
            # 禁止：源码穿越、uploads/templates 媒体与 JSON、任意日志
            if not _is_under(fp, OUT_BASE):
                self._json({'error': 'forbidden'}, 403); return
            # 排除 uploads / templates
            try:
                rel = fp.relative_to(OUT_BASE.resolve())
            except ValueError:
                self._json({'error': 'forbidden'}, 403); return
            parts = rel.parts
            if not parts or parts[0] in ('uploads', 'templates'):
                self._json({'error': 'forbidden'}, 403); return
            if fp.exists() and fp.is_file():
                ext = fp.suffix.lower()
                if ext == '.mp4':
                    ct = 'video/mp4'
                elif ext == '.srt':
                    ct = 'text/plain; charset=utf-8'
                else:
                    # 不暴露 _stderr.log / manifest.json 等内部文件
                    self._json({'error': 'forbidden'}, 403); return
                self._file(fp, ct)
            else:
                self._json({'error': 'not found'}, 404)
        else:
            # 不暴露工作目录静态文件，避免源码被直接拉取
            self._json({'error': 'not found'}, 404)

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
            # 大小校验：按类型区分图片 / 视频 / BGM
            ext = Path(name).suffix.lower()
            video_exts = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.flv'}
            is_video = kind == 'video' or ext in video_exts
            if kind == 'bgm' or ext in {'.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg'}:
                if len(raw) > MAX_BGM_SIZE:
                    self._json({'error': f'BGM 文件超过 {MAX_BGM_SIZE // 1024 // 1024}MB 限制'}, 413); return
            elif is_video:
                if len(raw) > MAX_VIDEO_SIZE:
                    self._json({'error': f'视频超过 {MAX_VIDEO_SIZE // 1024 // 1024}MB 限制'}, 413); return
            else:
                if len(raw) > MAX_IMAGE_SIZE:
                    self._json({'error': f'图片超过 {MAX_IMAGE_SIZE // 1024 // 1024}MB 限制'}, 413); return
            # sanitize filename: 仅保留 basename，去掉路径分隔与穿越
            safe_name = _sanitize_upload_name(name)
            fp = (UPLOAD_DIR / f'{uuid.uuid4().hex}_{safe_name}').resolve()
            if not _is_under(fp, UPLOAD_DIR):
                self._json({'error': '非法文件名'}, 400); return
            fp.write_bytes(raw)
            self._json({'path': str(fp)})

        elif p.path == '/api/render':
            data = json.loads(body)
            m = data.get('manifest', {})
            if not isinstance(m, dict):
                self._json({'error': 'manifest 必须是对象'}, 400); return
            scenes = m.get('scenes')
            if not isinstance(scenes, list) or not scenes:
                self._json({'error': 'manifest.scenes 不能为空'}, 400); return
            # 场景媒体必须在白名单目录内（防任意本地文件读入成片）
            for i, scene in enumerate(scenes):
                if not isinstance(scene, dict):
                    self._json({'error': f'scenes[{i}] 必须是对象'}, 400); return
                img = scene.get('image', '')
                if not img:
                    self._json({'error': f'scenes[{i}] 缺少 image'}, 400); return
                resolved = _resolve_media_path(img)
                if not resolved:
                    self._json({'error': f'非法媒体路径: {img}'}, 400); return
                scene['image'] = str(resolved)
            bgm = data.get('bgm')
            if bgm:
                bp = _resolve_media_path(bgm)
                if not bp:
                    self._json({'error': f'非法 BGM 路径: {bgm}'}, 400); return
                bgm = str(bp)
            tc = data.get('title_card')
            ec = data.get('end_card')
            rid = _sanitize_render_id(data.get('render_id'))
            # 防止客户端 render_id 碰撞 / 非法：重生 UUID
            if not rid or rid in JOBS:
                rid = uuid.uuid4().hex
            out = _job_out_dir(rid)
            if out is None:
                self._json({'error': '非法 render_id'}, 400); return
            out.mkdir(parents=True, exist_ok=True)
            mp = out / 'manifest.json'
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
            # 构建命令行参数列表（统一方式，兼容源码和 exe 模式）
            cmd = [str(SCRIPT), str(mp), '--output-dir', str(out)]
            if bgm:
                cmd += ['--bgm', bgm]
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
            # 与 video_auto.parse_boolish 对齐：字符串 "false"/"0" 应关闭烧录
            try:
                import video_auto as _va_bs
                _burn = _va_bs.parse_boolish(m.get('burn_subtitles', True), default=True)
            except Exception:
                _bs = m.get('burn_subtitles', True)
                if isinstance(_bs, str):
                    _burn = _bs.strip().lower() not in ('0', 'false', 'no', 'off', 'n', '')
                else:
                    _burn = bool(_bs) if _bs is not None else True
            if not _burn:
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
                         'cancel_event': cancel_event, 'done': False, 'error': '',
                         'cancelled': False}

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
                    if j.get('done') or j.get('cancelled'):
                        return  # 已被取消 / 超时
                    # 在获取锁之后才重置取消令牌，避免排队期间被前一个任务的取消污染
                    import video_auto as _va
                    _va.CancelToken.reset()
                    # 再检一次：reset 与 main 之间的 cancel 窗口
                    if j.get('done') or j.get('cancelled') or (
                        j.get('cancel_event') and j['cancel_event'].is_set()
                    ):
                        _mark_job_cancelled(j)
                        return
                    j['_started'] = True
                    _set_active_render(rid)
                    # 若在 set active 瞬间被取消，立刻武装 token
                    if j.get('cancelled') or (j.get('cancel_event') and j['cancel_event'].is_set()):
                        _va.CancelToken.set_cancelled()
                    try:
                        os.chdir(str(ROOT))
                        sys.argv = cmd
                        # 只设 progress_file 环境变量，不污染全局
                        os.environ['NARRAVID_PROGRESS_FILE'] = progress_env_val
                        _va.main()
                        # 若取消/超时已抢先标记，不要把状态覆盖成“完成”
                        if j.get('cancelled') or j.get('error'):
                            prior = (j.get('error') or '').strip()
                            if prior.startswith('渲染超时'):
                                # 超时诊断优先于取消文案
                                j['progress'] = j.get('progress') or '超时（渲染卡死）'
                            elif j.get('cancelled') and not prior:
                                j['error'] = '已取消'
                                j['progress'] = '已取消'
                            elif j.get('cancelled'):
                                # 有其它 prior error 时保留 error，进度标取消
                                j['progress'] = j.get('progress') or '已取消'
                        else:
                            mp4s = sorted(out.glob('*.mp4'))
                            if mp4s:
                                j['video'] = '/' + str(mp4s[0].relative_to(ROOT)).replace('\\', '/')
                                srt_p = mp4s[0].with_suffix('.srt')
                                if srt_p.is_file():
                                    j['srt'] = '/' + str(srt_p.relative_to(ROOT)).replace('\\', '/')
                            j['progress'] = '完成'
                    except Exception as e:
                        import traceback
                        tb = traceback.format_exc()
                        err_file = out / '_stderr.log'
                        try:
                            out.mkdir(parents=True, exist_ok=True)
                            err_file.write_text(tb, encoding='utf-8', errors='ignore')
                        except Exception:
                            pass
                        msg = str(e)
                        prior = (j.get('error') or '').strip()
                        # 超时诊断优先：monitor 已写「渲染超时」时，即使随后用户点取消也不要盖成「已取消」
                        if prior.startswith('渲染超时'):
                            j['progress'] = j.get('progress') or '超时（渲染卡死）'
                            # 保留 prior error；cancelled 标志可并存，供 UI 区分
                        elif j.get('cancelled') or _looks_like_cancel(msg):
                            j['cancelled'] = True
                            # 保留已有非空 error（如其它 mon 诊断），否则记已取消
                            j['error'] = prior or '已取消'
                            j['progress'] = '已取消'
                        elif prior:
                            # 已有 error 且非取消：勿用 CancelToken 文案覆盖
                            j['progress'] = j.get('progress') or f'失败: {e}'[:200]
                        else:
                            j['error'] = msg[-500:]
                            j['progress'] = f'失败: {e}'[:200]
                    finally:
                        # 恢复原始状态
                        if _get_active_render() == rid:
                            _set_active_render(None)
                        try:
                            _va.CancelToken.reset()
                        except Exception:
                            pass
                        sys.argv = orig_argv
                        os.chdir(orig_cwd)
                        # 恢复 progress_file 环境变量
                        if 'NARRAVID_PROGRESS_FILE' in os.environ:
                            del os.environ['NARRAVID_PROGRESS_FILE']
                        j['done'] = True

            def monitor_job():
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
                    # 仍在排队（未持有 RENDER_LOCK）时不计超时，避免“排队 3 分钟被误判卡死”
                    if _is_waiting_for_lock(rid, j):
                        stall_count = 0
                        last_progress = ''
                        continue
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
                    # 连续 90 次（约 180 秒）无进度更新则判定卡死（弱网 Edge TTS 需要更长时间）
                    if stall_count >= 90:
                        j['error'] = '渲染超时：180 秒无进度更新'
                        j['progress'] = '超时（渲染卡死）'
                        j['done'] = True
                        # 仅打断当前真正在跑的任务；排队中的 job 超时不应误杀持锁渲染
                        _signal_cancel_token_if_active(rid)
                        if j.get('cancel_event'):
                            j['cancel_event'].set()
                        return
                    if j.get('cancel_event') and j['cancel_event'].is_set():
                        _mark_job_cancelled(j)
                        return

            # 启动渲染线程和监控线程
            threading.Thread(target=run_in_thread, daemon=True).start()
            threading.Thread(target=monitor_job, daemon=True).start()
            # 延迟清理 JOBS（5 分钟后），避免内存泄漏
            def cleanup_job():
                time.sleep(300)
                j = JOBS.get(rid)
                # done 可能被 cancel/stall 提前置位，但线程仍可能在跑；active 时不清理
                if j and (not j.get('done') or _get_active_render() == rid):
                    threading.Thread(target=cleanup_job, daemon=True).start()
                    return
                JOBS.pop(rid, None)
            threading.Thread(target=cleanup_job, daemon=True).start()
            self._json({'render_id': rid})

        elif p.path.startswith('/api/cancel'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if j:
                # 已成功/失败终态：忽略迟到 cancel，避免抹掉 video 或诊断文案
                if j.get('done') and not j.get('cancelled'):
                    self._json({'status': 'ok', 'ignored': True}); return
                # 先设置取消信号，再标记 done，避免 monitor_job() 提前退出错过取消
                if j.get('cancel_event'):
                    j['cancel_event'].set()
                # 只取消“当前正在执行”的 job 的全局 token；排队中的 job 仅靠 done 跳过
                _signal_cancel_token_if_active(rid)
                _mark_job_cancelled(j)
            self._json({'status': 'ok'})

        elif p.path == '/api/clean':
            cleaned = 0
            # 进行中 / 排队中的任务目录不可删
            protected = set()
            for j in list(JOBS.values()):
                outp = j.get('out') if isinstance(j, dict) else None
                if outp:
                    try:
                        protected.add(str(Path(outp).resolve()))
                    except Exception:
                        pass
            # 按修改时间排序，保留最近 5 次
            dirs = sorted(
                [d for d in OUT_BASE.iterdir() if d.is_dir() and d.name not in ('uploads', 'templates')],
                key=lambda d: d.stat().st_mtime, reverse=True
            )
            keep = set()
            for d in dirs[:5]:
                try:
                    keep.add(str(d.resolve()))
                except Exception:
                    pass
            for d in dirs:
                try:
                    key = str(d.resolve())
                except Exception:
                    continue
                if key in keep or key in protected:
                    continue
                shutil.rmtree(d, ignore_errors=True)
                cleaned += 1
            self._json({'message': f'已清理 {cleaned} 个旧渲染，保留最近 5 个及进行中任务', 'cleaned': cleaned})

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
            import tempfile
            import zipfile
            data = json.loads(body)
            m = data.get('manifest', {})
            bgm = data.get('bgm')
            # 创建临时 zip
            zip_buf = io.BytesIO()
            zf = zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED)
            # 收集需要打包的文件及其新路径
            collected = {}  # abs_path -> zip_relative_path
            manifest_copy = json.loads(json.dumps(m))  # deep copy
            # 确保标题页/封尾页写入 manifest（兼容 body 顶层字段）
            if data.get('title_card') and not manifest_copy.get('title_card'):
                manifest_copy['title_card'] = data.get('title_card')
            if data.get('end_card') and not manifest_copy.get('end_card'):
                manifest_copy['end_card'] = data.get('end_card')
            if data.get('card_duration') is not None and 'card_duration' not in manifest_copy:
                manifest_copy['card_duration'] = data.get('card_duration')
            if data.get('end_card_duration') is not None and 'end_card_duration' not in manifest_copy:
                manifest_copy['end_card_duration'] = data.get('end_card_duration')
            export_roots = [UPLOAD_DIR.resolve(), (ROOT / 'examples-assets').resolve(), OUT_BASE.resolve()]

            def _exportable(path: Path) -> bool:
                try:
                    rp = path.resolve()
                except Exception:
                    return False
                return rp.exists() and rp.is_file() and _is_under_any(rp, export_roots)

            for i, scene in enumerate(manifest_copy.get('scenes', [])):
                if not isinstance(scene, dict):
                    self._json({'error': f'scenes[{i}] 必须是对象'}, 400); return
                img = scene.get('image', '')
                if not img:
                    self._json({'error': f'scenes[{i}] 缺少 image，无法导出'}, 400); return
                img_path = Path(img)
                if not img_path.is_absolute():
                    img_path = UPLOAD_DIR / img_path
                try:
                    img_path = img_path.resolve()
                except Exception:
                    self._json({'error': f'无法解析媒体路径: {img}'}, 400); return
                if not _exportable(img_path):
                    # 禁止把本机绝对路径写进 zip manifest（路径泄漏 + 坏导入）
                    self._json({
                        'error': f'无法导出：场景 {i} 媒体不在允许目录（uploads/examples-assets/输出）: {Path(img).name}'
                    }, 400); return
                if str(img_path) not in collected:
                    ext = img_path.suffix.lower()
                    zname = f'assets/scene_{i:03d}{ext}'
                    collected[str(img_path)] = zname
                scene['image'] = collected[str(img_path)]
            # BGM
            if bgm:
                bgm_path = Path(bgm)
                if not bgm_path.is_absolute():
                    bgm_path = UPLOAD_DIR / bgm_path
                try:
                    bgm_path = bgm_path.resolve()
                except Exception:
                    self._json({'error': f'无法解析 BGM 路径: {bgm}'}, 400); return
                if not _exportable(bgm_path):
                    self._json({
                        'error': f'无法导出：BGM 不在允许目录: {Path(bgm).name}'
                    }, 400); return
                zname = f'assets/bgm{bgm_path.suffix}'
                collected[str(bgm_path)] = zname
                manifest_copy['bgm'] = zname
            # 写入 manifest（仅含 zip 内相对路径，无宿主绝对路径）
            zf.writestr('manifest.json', json.dumps(manifest_copy, ensure_ascii=False, indent=2))
            # 写入所有媒体文件
            for abs_path, zname in collected.items():
                zf.write(abs_path, zname)
            zf.close()
            zip_data = zip_buf.getvalue()
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename="narravid_project.zip"')
            self.send_header('Content-Length', str(len(zip_data)))
            self.end_headers()
            self.wfile.write(zip_data)

        elif p.path == '/api/import':
            # 导入工程：上传 zip，解压到 uploads 新目录，返回修正路径后的 manifest
            import tempfile
            import zipfile
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
            try:
                zf_ctx = zipfile.ZipFile(zip_buf, 'r')
            except zipfile.BadZipFile:
                shutil.rmtree(project_dir, ignore_errors=True)
                self._json({'error': '不是有效的 zip 工程文件'}, 400); return
            with zf_ctx as zf:
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
                    # 检查解压后总大小（header 声明 + 实际写出字节双保险）
                    total_size += zf.getinfo(member).file_size
                    if total_size > max_extract:
                        self._json({'error': 'zip 解压后超过 500MB 限制'}, 400); return
                    safe_members.append(member)
                # 流式解压并累计实际写入字节，防止 header 低报
                written = 0
                for member in safe_members:
                    info = zf.getinfo(member)
                    # 目录项
                    if member.endswith('/') or info.is_dir():
                        (project_dir / member).mkdir(parents=True, exist_ok=True)
                        continue
                    target = (project_dir / member).resolve()
                    if not _is_under(target, project_dir):
                        self._json({'error': f'zip 包含非法路径: {member}'}, 400); return
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, 'r') as src, open(target, 'wb') as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > max_extract:
                                try:
                                    dst.close()
                                    target.unlink(missing_ok=True)
                                except Exception:
                                    pass
                                self._json({'error': 'zip 解压后超过 500MB 限制'}, 400); return
                            dst.write(chunk)
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
            proj_root = project_dir.resolve()
            for scene in scenes:
                if not isinstance(scene, dict):
                    self._json({'error': 'manifest.scenes 项必须是对象'}, 400); return
                img = scene.get('image', '')
                if not img:
                    continue
                img_path = Path(img)
                if not img_path.is_absolute():
                    img_path = (project_dir / img_path).resolve()
                else:
                    img_path = img_path.resolve()
                if not _is_under(img_path, proj_root):
                    self._json({'error': f'非法媒体路径: {img}'}, 400); return
                scene['image'] = str(img_path)
            bgm_val = manifest.pop('bgm', None)
            if bgm_val:
                bgm_path = Path(bgm_val)
                if not bgm_path.is_absolute():
                    bgm_path = (project_dir / bgm_path).resolve()
                else:
                    bgm_path = bgm_path.resolve()
                if not _is_under(bgm_path, proj_root):
                    self._json({'error': f'非法 BGM 路径: {bgm_val}'}, 400); return
                bgm_val = str(bgm_path)
            self._json({'manifest': manifest, 'bgm': bgm_val})

        else:
            self._json({'error': 'not found'}, 404)

    def _template_path(self, tid):
        """Resolve template id to a path strictly under TEMPLATE_DIR."""
        tid = (tid or '').strip()
        if not tid or '/' in tid or '\\' in tid or tid in ('.', '..') or '..' in tid:
            return None
        # 仅允许简单文件名，避免模板 ID 路径穿越
        if not re.fullmatch(r'[\w.-]{1,64}', tid):
            return None
        tp = (TEMPLATE_DIR / f'{tid}.json').resolve()
        if not _is_under(tp, TEMPLATE_DIR):
            return None
        return tp

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
            tp = self._template_path(tid)
            if tp and tp.exists():
                self._json(json.loads(tp.read_text(encoding='utf-8')))
            else:
                self._json({'error': 'not found'}, 404)

    def do_PUT(self):
        p = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        if p.path.startswith('/api/templates/'):
            tid = p.path.split('/')[-1]
            tp = self._template_path(tid)
            if not tp or not tp.exists():
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
            tp = self._template_path(tid)
            if tp and tp.exists():
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

    def _file(self, fp, ct, as_attachment=False):
        self.send_response(200); self.send_header('Content-Type', ct)
        # 缩略图/预览用 inline，下载类资源才 attachment
        if as_attachment:
            self.send_header('Content-Disposition', f'attachment; filename="{fp.name}"')
        else:
            self.send_header('Content-Disposition', f'inline; filename="{fp.name}"')
        self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers(); self.wfile.write(fp.read_bytes())

    def log_message(self, fmt, *args): pass


def main():
    ap = argparse.ArgumentParser(description='narravid Web UI')
    ap.add_argument('--port', type=int, default=int(os.environ.get('NARRAVID_PORT', '5000') or 5000))
    # Docker 可设 NARRAVID_HOST=0.0.0.0；本机默认仅回环
    default_host = os.environ.get('NARRAVID_HOST') or (
        '0.0.0.0' if os.environ.get('NARRAVID_DOCKER') else '127.0.0.1'
    )
    ap.add_argument('--host', default=default_host)
    args = ap.parse_args()
    for d in [OUT_BASE, UPLOAD_DIR, TEMPLATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    # ThreadingHTTPServer：上传/状态轮询/导出互不阻塞；渲染仍由 RENDER_LOCK 串行
    srv = ThreadingHTTPServer((args.host, args.port), H)
    display_host = '127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host
    url = f'http://{display_host}:{args.port}'
    print(f'narravid Web UI: {url}')
    if args.host in ('0.0.0.0', '::'):
        print(f'  监听 {args.host}:{args.port}（局域网/容器可访问；内网请加反代鉴权）')
    print('  在浏览器打开上述地址即可')
    # 环境探测放到后台，避免阻塞首包/accept
    def _env_probe():
        try:
            import video_auto as _va
            eng = _va.resolve_tts_engine(None)
            print(f'  TTS: {eng}' + ('' if eng != 'edge' else ' (edge-tts)'))
            if not _va._find_zh_font():
                print('  [warn] 未找到中文字体：标题页/字幕可能方块。设置 NARRAVID_FONT 或安装 Noto CJK / 放入 fonts/')
        except Exception as e:
            print(f'  [warn] 环境检测: {e}')
    threading.Thread(target=_env_probe, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('stopped'); srv.shutdown()


if __name__ == '__main__':
    main()
