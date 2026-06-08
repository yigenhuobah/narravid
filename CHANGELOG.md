# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.3.0] - 2026-06-09

### Added

- **多线程并行渲染**：场景级并行处理（TTS + 渲染），`ThreadPoolExecutor` 实现，默认 4 线程
  - CLI 新增 `--workers N` 参数（`1` = 串行，默认 `4`）
  - manifest JSON 支持 `"workers": N` 字段
  - WebUI 工具栏新增「线程」下拉框（1/2/4/8/16）
- **实时进度追踪**：`ProgressTracker` 线程安全计数器 + 进度文件
  - `video_auto.py` 通过 `NARRAVID_PROGRESS_FILE` 环境变量写入进度
  - `webui.py` `/api/status` 端点读取进度文件，前端实时显示 `[3/5] TTS 生成中...`
- **统一 ffmpeg 定位模块**：新增 `_bundled_ffmpeg.py`，`video_auto.py` 和 `webui.py` 均改为 `import _bundled_ffmpeg`
- **端到端测试脚本**：新增 `test_e2e.py`，10 大测试项 24 个断言，覆盖全流程

### Fixed

- **BGM 上传假功能**：前端 BGM 选项现在真正上传文件到服务器，复用 `/api/upload` 通道
- **WebUI render 子进程 stdout 死锁**：`stdout=subprocess.PIPE` → `subprocess.DEVNULL`
- **`/thumb` 路径遍历漏洞**：新增 `THUMB_ALLOWED_DIRS` 白名单，限制只能访问 uploads 和 examples-assets
- **concat.txt 路径转义双转义**：`replace("'", r"'\\''")` → `replace("'", "'\\''")`，修复 ffmpeg concat 解析错误
- **`mix_bgm` 的 `duck_ratio` 参数未使用**：硬编码 `volume=0.15` → `volume={duck_ratio:.2f}`，参数真正生效
- **`mon()` 守护线程不检查 returncode**：失败时仍标记"完成"并可能返回残留 .mp4；现在检查 `returncode == 0`，失败时设置错误信息
- **WebUI 不传音色/语速/TTS引擎给 CLI**：新增 `--engine`、`--voice`、`--speed` 传递
- **`video_auto.py` 不从 manifest 读 `tts_engine`/`voice`**：优先级改为 CLI 参数 → manifest 字段 → 默认值
- **`split_sentences` 只认中文句号**：扩展为支持 `。！？；!?;` 六种句末标点
- **标题页中文方块**：`generate_title_card` 显式指定中文字体列表
- **TTS fallback 无保护**：system TTS fallback 包了 try-except，失败时抛出包含两个引擎错误信息的 RuntimeError
- **`requirements.txt` 含 BOM**：去掉 UTF-8 BOM
- **`.gitignore` 缺 log 排除**：新增 `*.log`

## [v1.2.0] - 2025-06-08

### Added

- WebUI v4：文件上传机制，彻底解决图片路径问题

### Fixed

- WebUI POST 崩溃保护 + 路径自动转绝对
- CI: 改用 choco 安装 ffmpeg，避免 curl 下载失败

## [v1.0.0] - 2025-06-07

### Added

- 初始发布
- 图片 + JSON 文案 → 解说视频一键生成
- Edge TTS / 系统 TTS 自动切换
- 可选 BGM + 自动闪避
- 可选自动标题页
- Web UI 界面
- exe 打包自带 ffmpeg
