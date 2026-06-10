# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.5.0] - 2026-06-11

### Added

- **WebUI v6 完整重写**：模板、BGM 管理、在线预览、清理旧文件
  - 模板系统：保存/加载/删除场景配置模板
  - BGM 管理：下拉选择已上传 BGM + 独立上传按钮
  - 视频预览：渲染完成后弹窗内播放预览 + 下载按钮
  - 清理旧文件：一键保留最近 5 次渲染
  - 分辨率选择：1080p横屏/720p横屏/1080p竖屏/方形
  - 标题页/封尾页独立时长输入
  - 拖拽排序视觉反馈（虚线高亮）
  - textarea 实时保存（oninput 代替 onchange）
  - 停顿输入框加宽
  - 自动检测 edge-tts 可用性（/api/tts-check）
  - 文件大小限制（图片 20MB / BGM 50MB / 总 60MB）
  - 渲染完成自动下载

- **video_auto.py 大量增强**
  - `--end-card-duration`：封尾页时长独立于标题页
  - `--card-duration`：标题页停留秒数可配（默认 3.0）
  - `--subtitle-style`：自定义字幕 ASS 样式
  - `--title-card-bg`：标题页/封尾页背景色可配
  - `--no-smart-comma`：禁用逗号智能断句
  - 智能逗号断句：长句按逗号切分但合并短句（< 15 字）
  - 单场景失败不崩全局：`failed` 列表追踪，仅全部失败才 raise
  - BGM 混音降级：`mix_bgm` 失败时复制原音频而非崩溃
  - 标题页/封尾页生成失败时跳过（matplotlib 不可用场景）
  - 渲染后自动清理 `_tmp` 临时目录

### Fixed

- **mon() 递归死循环**：改为 while 循环，stall_count 不再因递归重置
- **stderr PIPE 死锁**：改用文件写 stderr（避免 matplotlib 字体警告撑爆管道）
- **stderr 文件句柄泄漏**：Popen stderr=open() 改为变量 + finally 关闭
- **/api/cancel/ 路径匹配**：改为 startswith 兼容有无尾斜杠
- **/api/status 竞态**：mon() 还没设 video 时状态端点直接扫目录回填
- **workers=1 不传递**：条件 `1 < wk` 改为 `1 <= wk`

## [v1.3.1] - 2026-06-09

### Changed

- **WebUI v5 暗色主题重构**：整体视觉重做
  - 深色背景 (#0f0f13) + 橙色渐变强调色 (#e85d26 → #ff8c42)
  - 设置面板改为双栏卡片布局（语音设置 / 输出设置）
  - 生成按钮突出为渐变主按钮，带投影和 hover 上浮动效
  - 场景卡片缩略图加大至 128×80，文字区更宽敞
  - 底部状态栏新增彩色进度条（解析 [N/M] 格式 → 百分比）
  - 空场景列表增加引导提示
  - 结果通知改为上滑渐入动画
  - 响应式适配：768px 以下自动切换单栏

### Improved

- 控件标签 11px → 12px，更易辨认
- 音色选项增加中文描述（如"Xiaoxiao · 女声温暖"）
- 线程选项增加说明文字（"串行（调试用）"、"推荐"）
- 停顿输入框 placeholder 从"多停秒"→"停顿秒"
- 换图按钮 hover 变橙色，更醒目
- 进度实时解析：`[2/5]` 格式自动映射到进度条百分比

## [v1.3.0] - 2026-06-09

### Added

- **多线程并行渲染**：场景级并行处理（TTS + 渲染），`ThreadPoolExecutor` 实现，默认 4 线程
  - CLI 新增 `--workers N` 参数（`1` = 串行，默认 `4`）
  - manifest JSON 支持 `"workers": N 字段
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
