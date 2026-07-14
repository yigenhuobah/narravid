# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added / Fixed — 中期高价值项

- **`video_auto.run_from_manifest_file`**：可编程入口，不碰 `sys.argv`
- **上传 base64 分块解码写盘** + 提前体积拒绝，降低峰值内存
- **`WebUIHandler` 类名**（保留 `H` 别名兼容测试）
- **完成页 warning 条**（BGM 降级等）
- **CancelToken 文档**：标明进程级、依赖 RENDER_LOCK 串行
- **维护文档**：`docs/ARCHITECTURE.md`、`REMAINING_DEBT.md`、`OPS.md`、`FUTURE_AGENTS.md`

## [v1.10.3] - 2026-07-14

### Fixed / Added — 安全与体验收口

- **`do_HEAD` 与 GET 同策略**，避免 SimpleHTTPRequestHandler 泄露源码元数据
- **模板 PUT 体积上限**；export/render 媒体扩展名白名单，拒绝 job 内部日志
- **zip 导入**：条目数上限 + 失败清理工程目录
- **WebUI 不再 `os.chdir`**；视频场景探测视频流
- **未改字幕样式时不强制下发 subtitle_style**（用服务端默认字体）
- **渲染 warning toast**；pre-commit / deploy 示例

## [v1.10.2] - 2026-07-14

### Fixed — 深度审计跟进

- **`video_auto.main(argv=...)`**：WebUI 不再改写全局 `sys.argv` 驱动渲染
- **`/api/health` ffmpeg 探测**：以 `-version` 为准，去掉裸名假阳性
- **BGM 降级可观测**：混音降级/失败写入 `_warnings.txt` 并出现在 status `warning`

## [v1.10.1] - 2026-07-14

### Added — 质量与可维护性（补丁）

- **WebUI 模块拆分**：`webui_jobs.py`（任务/路径/取消）、`webui_ui.py`（HTML/JS）；`webui.py` 保留 HTTP 入口并 re-export 以兼容测试
- **`hold_sec` 统一**：UI 状态与模板保存使用 `hold_sec`；`video_auto.scene_hold_sec` / `normalize_manifest` 兼容历史 `hold`；`SceneDict`/`ManifestDict` TypedDict
- **Ruff**：`pyproject.toml` 配置 + `requirements-dev.txt`；Linux CI 增加 `ruff check .`
- **命名/风格约定**：`docs/STYLE.md`（Python / 内嵌 JS、渐进重命名策略）
- **可读性改名**：内嵌 JS `pain`→`paintScenes`、`E`→`byId`、`S`→`scenes`；Python `mon`→`monitor_job`
- **`GET /api/health`**：TTS / ffmpeg / 字体 / 活跃任务就绪信息

### Fixed

- **模板/导入 `hold_sec=0` 被历史 `hold` 覆盖**：`sceneHoldSec` 不用 `||` 假值合并
- **`/api/render` 写盘前 normalize**：统一 hold 字段并校验 scene image
- **去掉陈旧 `ACTIVE_RENDER_ID` 再导出**；活跃任务以 `_get_active_render()` 为准
- **`scene_hold_sec`**：空值回退 legacy hold；拒绝 NaN/inf；上限 3600s

## [v1.10.0] - 2026-07-14

### Added / Fixed — 跨平台（Linux / Docker）

- **系统 TTS 门控**：非 Windows 禁用 PowerShell system TTS；Edge 失败不再误走 system fallback
- **进程树取消（POSIX）**：`run()` 使用 `start_new_session`；`_kill_process` 使用 `killpg` SIGTERM→SIGKILL
- **中文字体发现**：`NARRAVID_FONT`、`fonts/`、Windows / Linux Noto·WQY / macOS PingFang 候选
- **字幕默认 FontName**：随可用字体（`default_subtitle_font_name`），非写死微软雅黑
- **`_bundled_ffmpeg`**：同时识别无后缀与 `.exe`；支持 `NARRAVID_FFMPEG` / `FFMPEG` 环境变量
- **WebUI TTS 检测**：不再在 Linux 上谎称「系统 TTS」；字幕字体按平台默认；`NARRAVID_HOST`/`NARRAVID_DOCKER`
- **`Dockerfile` + `.dockerignore`**：slim + ffmpeg + fonts-noto-cjk
- **CI**：`.github/workflows/test-linux.yml`（`--fast` / default / pipeline）
- **`tests/test_platform.py`**：字体 / TTS 门控 / kill / ffmpeg 名

### Added — 测试覆盖扩展

- **`tests/support.py`**：`fake_video_auto_main` / `poll_status` / `http_raw`，供 live 层无 TTS 测渲染生命周期
- **`tests/test_security_http.py`**：空 scenes、缺 image、中文文件名、坏 zip 400、export 含 BGM/标题、late-cancel 保留 video、status 回填 srt、`.srt` 下载
- **`tests/test_live_api.py`**：模板 BGM/时长、fake 渲染+srt、中途取消、完成后 cancel、双任务锁、导出导入往返、clean
- **`tests/test_cancel_concurrency.py`**：前端 UX 标记（模板 BGM、import 40MB、thumb 占位、语速 3.0、clean confirm）
- **`test_e2e.py`**：模板 CRUD、导出/导入、完成后 cancel、clean（真 TTS 路径）

### Fixed — WebUI 真实用户操作问题

- **完成后迟到 cancel 抹掉成片 URL**：`_mark_job_cancelled` / `/api/cancel` 对已成功或已失败终态直接忽略，保留 `video` 与超时/失败诊断
- **模板不记住 BGM / 片头片尾时长**：`saveTemplate`/`loadTemplate` 持久化并恢复 `bgm`、`card_duration`、`end_card_duration`
- **导入工程前后端体积不一致**：前端 zip 上限改为约 40MB（匹配 60MB body + base64）
- **坏 zip 返回 500**：`BadZipFile` 改为 400「不是有效的 zip 工程文件」，并清理空工程目录
- **空场景缩略图假 loading**：未上传时显示 `+` 占位并可点击换图
- **无图场景静默丢弃**：生成时 toast 提示跳过数量
- **状态 `srt` 恒为空**：渲染成功后回填 `.srt` 下载路径
- **上传中文文件名未 ASCII 化**：`_sanitize_upload_name` 仅保留 `A-Za-z0-9._-`
- **语速滑条上限 2.2**：改为 0.5–3.0，与后端 `atempo` 链一致
- **清理旧文件无确认**：`cleanOld` 增加 `confirm`

## [v1.9.0] - 2026-07-13

### Fixed — 路径安全 / 取消语义 / 失败诊断

- **`render_id` 路径穿越**：客户端 `render_id` 仅允许简单 token，输出目录强制落在 `rendered/webui/` 下
- **`/api/render` 任意本地媒体读入**：scene / BGM 路径白名单（uploads、examples-assets、输出树）
- **`/rendered` 过宽暴露**：仅服务 job 目录下 `.mp4` / `.srt`，禁止 uploads、templates、日志与源码穿越
- **工程导出泄漏本机绝对路径**：非白名单媒体直接 400，成功导出的 manifest 仅含 zip 内相对路径
- **zip 导入炸弹 / 路径穿越**：流式解压并按实际写入字节限制 500MB；成员路径严格限制在工程目录
- **取消后误报成功**：前端 `userCancelled` 硬闸；status 终态不被 progress 文件覆盖
- **超时诊断被取消文案盖掉**：`渲染超时…` 优先于「已取消」（后端 success/except 与前端 poll）
- **并行场景失败伪装成用户取消**：fail-fast 使用 `CancelToken.set_aborted()`，与用户取消区分
- **取消无法打断 ffmpeg**：`run()` 改为可注册的 Popen，取消时 `taskkill /T`（Windows）结束子进程树
- **排队任务误触发全局取消 / 超时**：`ACTIVE_RENDER_ID` 仅取消真正在跑的任务；排队不计 stall
- **`burn_subtitles: "false"` 仍烧录**：CLI / WebUI 统一 `parse_boolish`
- **`hold_sec` 滤镜分叉**：复用 `process_audio`，并以实际时长对齐 `scene_duration`
- **模板 ID / 上传文件名路径问题**：模板 ID 消毒；上传仅 basename 且限制在 uploads 内

### Added

- **分层 max 测试门禁**（stdlib，无 pytest）：`run_tests.py` + `tests/`（unit / security / cancel / live / pipeline）
- **`test_regressions.py`**：本轮安全与取消回归用例

### Changed

- `end_card_duration` ≤0 明确回退为与标题页同长（`resolve_positive_duration`）
- `smart_comma` 支持更多假值字符串（`n` / `disabled` 等）

## [v1.8.0] - 2026-07-12

### Fixed — 全量代码审议修复

- **CI Release 正文丢失**：changelog 提取步骤用 Python 打开字面路径 `"$GITHUB_ENV"`，改为 `os.environ["GITHUB_ENV"]`，Release 更新内容可正常注入
- **图片场景 hold_sec 被吃掉**：渲染去掉 `-shortest`，并以 `apad=whole_dur` 将音轨垫满 `scene_duration`，停顿秒数生效
- **取消渲染显示成功**：`/api/cancel` 与 status 增加 `cancelled`/`error=已取消`；前端 poll/cancel 明确展示取消态
- **部分场景失败仍出片**：任一正文场景失败即 raise，避免静默缺镜；串行+标题页也不再只产出封面
- **语速 >2.0 失败**：`atempo` 改为可链式（单段 0.5–2.0），支持至 3.0 语速
- **ASS 字幕颜色 R/B 颠倒**：UI 拾色器 RRGGBB 正确转换为 ASS `&HAABBGGRR`
- **工程导出丢标题/封尾**：export 写入 `title_card`/`end_card` 与时长；import 回填 UI
- **导入 BGM 挂不上**：`/api/bgm-list` 递归扫描；import 时为 BGM 补 option
- **全局 SRT 忽略 smart_comma**：`make_global_srt` 与烧录字幕共用设置
- **CLI 忽略 manifest 字段**：`subtitle_style`/`bgm_volume`/`title_card` 等可从 manifest 读取（CLI 优先）
- **图片 20MB 限制未执行**：服务端按扩展名区分图片/视频/BGM 大小限制
- **未知路径泄露源码**：取消 `super().do_GET()` 目录回落，未知路径 404
- **ffprobe 无超时**：`ffprobe_duration` 增加 60s timeout
- **弱网误判卡死**：stall 判定由 60s 放宽到约 180s
- **系统 TTS 残留文件**：清理 audio 目录下 `.ps1`/`.txt`/`.raw.wav`

### Changed

- WebUI 改用 `ThreadingHTTPServer`（渲染仍由 `RENDER_LOCK` 串行）
- 缩略图/预览改为 `Content-Disposition: inline`
- TTS 重试等待期间检查 `CancelToken`，取消更及时

## [v1.7.0] - 2026-06-22

### Fixed — 深层代码审计修复（9 项）

- **BGM 侧链压缩静音段爆音**：`sidechaincompress` 的 `makeup` 从 `1/duck_ratio`（如 4.0）改为 `1.0`，后接 `volume` 滤镜控制整体音量，消除人声停止时 BGM 被放大 4 倍导致的削波失真
- **导入工程后 BGM 列表不刷新**：`importProject()` 调用了不存在的 `loadBGM()`，修正为 `loadBGMList()`
- **视频缩略图 Content-Type 错误**：`/thumb` 端点对所有文件统一返回 `image/png`，改为按扩展名判断（视频返回 `video/mp4` 等），修复前端 `<video>` 标签加载失败
- **zip 导入路径穿越漏洞**：`/api/import` 的 `extractall()` 无路径检查，添加逐条 `relative_to()` 校验 + 500MB 解压上限
- **图片替换按钮不支持视频**：`chImg()` 的 `accept` 从 `image/*` 改为 `image/*,video/*`，与批量上传和拖拽保持一致
- **render_id 碰撞导致孤儿线程**：客户端传入已存在的 `render_id` 会覆盖 `JOBS` 字典，改为检测到碰撞时服务端重新生成
- **manifest 结构未校验**：`/api/import` 添加 `isinstance` 校验，`manifest` 必须是 dict、`scenes` 必须是 list
- **`process_audio` 死变量**：移除未使用的 `target_duration` 变量
- **纯标点文本产生空字幕**：`split_sentences` 过滤只含标点的 chunk，避免 SRT 中出现空文本条目

### Changed

- CI Release 描述改为从 CHANGELOG 自动提取，不再写死文案

## [v1.6.2] - 2026-06-21

### Fixed

- **edge_tts 7.2.7 兼容**：`rate` 和 `volume` 参数传 `None` 会抛 `TypeError: rate must be str`，改为默认 `'+0%'`

## [v1.6.0] - 2026-06-20

### Added

- **字幕样式可视化编辑器**：设置面板新增字幕样式卡片
  - 字体选择（微软雅黑/黑体/宋体/楷体/思源黑体/苹方）
  - 字号、描边粗细、底部边距数值调节
  - 文字颜色、描边颜色拾色器 + HEX 输入联动
  - 粗体开关、对齐方式选择（底部居中/左/右、顶部居中、居中）
  - 实时预览框：所见即所得展示字幕效果（字体、颜色、描边、位置）
  - 一键重置默认样式
  - 生成 ASS force_style 字符串，通过 `--subtitle-style` 传递给 video_auto

- **模板管理增强**：
  - 模板保存/加载包含字幕样式配置
  - 模板重命名：对话框内点击 ✎ 直接编辑名称（Enter 确认 / Esc 取消）
  - 模板对话框 UI 优化：操作按钮分区（重命名 / 删除）

### Changed

- 字幕样式编辑器响应式适配：768px 以下单列布局
- 模板列表项布局调整为 info + actions 两栏

## [v1.5.1] - 2026-06-19

### Fixed — exe 打包兼容性修复

- **`_bundled_ffmpeg.py`**: `get_ffmpeg()` / `get_ffprobe()` 返回绝对路径，避免 exe 环境下子进程找不到 ffmpeg
- **`video_auto.py`**: `synthesize_edge_tts` 从子进程 `python -m edge_tts` 改为直接使用 `edge_tts.Communicate` Python API
- **`video_auto.py`**: 所有 `ffmpeg` / `ffprobe` 硬编码命令替换为通过 `_bundled_ffmpeg` 获取的绝对路径
- **`video_auto.py`**: `edge_tts_available()` 从 `find_spec` 改为 `try import`（exe 中更可靠）
- **`video_auto.py`**: `synthesize_audio_with_retry` 异常捕获从 `CalledProcessError` 改为通用 `Exception`
- **`webui.py`**: `/api/render` 从 `subprocess.Popen([sys.executable, ...])` 改为子线程直接调用 `video_auto.main()`（exe 中 `sys.executable` 非 python）
- **`webui.py`**: `/api/status` 和 `/api/cancel` 适配新的线程模式
- **CI**: 添加 `--hidden-import edge_tts`、`--collect-all edge_tts`、`--collect-all matplotlib`

### Added

- **渲染取消机制**: `video_auto.py` 新增 `CancelToken` 全局取消令牌，`webui.py` `/api/cancel` 可真正中断渲染
- **并发安全**: `webui.py` 新增 `RENDER_LOCK` 全局渲染锁，防止多渲染任务并发导致全局状态污染
- **中文字体加载**: `generate_title_card` 增加打包字体查找逻辑，提升 exe 环境下标题页中文显示可靠性
- `requirements.txt` 显式声明 `aiohttp` 依赖
- README CLI 参数表补全所有参数

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
