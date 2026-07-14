# narravid 架构地图（给后续维护者）

**当前发布线：** post-v1.10.3 + 深度扫描 critical 修复（SystemExit / frozen ROOT / 选片等）。  
**产品定位：** Windows 桌面 exe 为主；源码/Docker 可跑；**单用户**工具，不是多租户 SaaS。

## 入口与模块

```
CLI:   video_auto.py  → main(argv=None) / run_from_manifest_file(...)
WebUI: webui.py (HTTP) → webui_jobs.py (JOBS/路径/取消) + webui_ui.py (HTML/JS)
       渲染线程: video_auto.main(main_argv)  [不改写 sys.argv]
共享:  _bundled_ffmpeg.py
```

| 文件 | 职责 | 注意 |
|------|------|------|
| `video_auto.py` | 管线：TTS → atempo/hold → 字幕 → 场景 mp4 → concat → BGM | `CancelToken` **进程级**；靠 WebUI `RENDER_LOCK` 串行；`SystemExit` 表示致命配置错误 |
| `webui.py` | `WebUIHandler`（别名 `H`）、路由、上传/渲染/模板 | 捕获 `Exception` **与** `SystemExit`；大 POST body 仍是 JSON |
| `webui_jobs.py` | `JOBS`、`RENDER_LOCK`、路径沙箱、数据根 | **`ROOT`=可写数据根**（frozen=exe 旁或 `NARRAVID_DATA_DIR`）；`PACKAGE_ROOT`=只读包/解压目录 |
| `webui_ui.py` | 前端模板字符串 | `scenes`/`byId`/`paintScenes`/`sceneHoldSec` |
| `_bundled_ffmpeg.py` | ffmpeg/ffprobe 解析 | 懒解析；POSIX 无后缀 + Windows `.exe` |

## 渲染作业生命周期（WebUI）

1. `POST /api/render`：校验 media 路径 → `normalize_manifest` → 写 `rendered/webui/<rid>/manifest.json`  
2. 线程 `run_in_thread` 获取 `RENDER_LOCK` → `CancelToken.reset()` → `main(argv)`  
3. `monitor_job`：进度文件 stall ~300s（`STALL_TICKS=150`×2s）；排队中不计 stall  
4. 成功选片：优先 `manifest.mp4`（`_pick_final_mp4`），非字典序盲扫  
5. `POST /api/cancel/<rid>`：终态成功则 `ignored`；否则 cancel_event + 可能 `CancelToken`  
6. 约 5 分钟后 `JOBS.pop`（active 时延期）

## 关键契约

- 场景停顿字段：**`hold_sec`**（历史 `hold` 在 load/import/`scene_hold_sec` 兼容）  
- 烧录字幕：未改 UI 样式时**不传** `subtitle_style` → 服务端默认字体  
- Status 可含 `warning`（如 BGM 降级）；UI toast + `#warnBar`  
- Health：`GET /api/health`（TTS + ffmpeg/ffprobe `-version` + 字体）

## 打包

- Windows exe：`.github/workflows/build-exe.yml`（`v*` tag）  
  需 hidden-import：`video_auto`、`webui_jobs`、`webui_ui`、`edge_tts`、`_bundled_ffmpeg`  
- Docker：`Dockerfile`（ffmpeg + fonts-noto-cjk）；示例鉴权见 `deploy/`

## 测试门禁

```bash
pip install -r requirements-dev.txt
ruff check .
python run_tests.py --fast    # unit+security+cancel
python run_tests.py           # + live
python run_tests.py --max     # + pipeline + legacy
python test_e2e.py            # 真 Edge TTS，发版前
```

## 刻意设计（不要“顺手推翻”）

- 单文件/少文件 WebUI 便于 PyInstaller  
- 无 Flask/DB：降低 exe 体积与依赖  
- 无内置登录：内网用反代 Basic Auth（`deploy/`）  
- System TTS 仅 Windows；Linux 仅 Edge  
