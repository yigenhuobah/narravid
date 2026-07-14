# narravid — Agent 使用说明书

**给 AI / 自动化协作者的第一份文档。**  
人类用户请看仓库根目录 [README.md](../README.md)。维护细节分散在其它 `docs/*`，本页负责**导流、边界、命令、禁止事项**。

| 项 | 值 |
|----|-----|
| 产品 | 图片/视频场景 + JSON 解说 → 成片（TTS + 字幕 + 可选 BGM） |
| 定位 | **单用户**本机 / LAN 工具；Windows exe 为主；源码可跑 Linux/macOS/Docker |
| 当前发布 | 见 [Releases](https://github.com/yigenhuobah/narravid/releases)（SemVer + `CHANGELOG.md`） |
| 不是 | 多租户 SaaS、公网开放 API、Flask/React 重写目标 |

---

## 0. 你是 Agent 时先做这几步

1. **读本文件全文**（尤其 §2 禁止、§4 门禁、§6 债与勿重复）。  
2. 再按需打开：  
   - [ARCHITECTURE.md](ARCHITECTURE.md) — 模块与作业流  
   - [REMAINING_DEBT.md](REMAINING_DEBT.md) — 未做完 / 已关闭票  
   - [OPS.md](OPS.md) — 运行、Docker、发版  
   - [STYLE.md](STYLE.md) — 命名与 Ruff  
   - 根目录 [CLAUDE.md](../CLAUDE.md) — 仓库内嵌的 agent 约定（若存在）  
3. 改代码前：`git status`、当前分支、是否已有相关 PR。  
4. 默认工作流：**分支 → 实现 → `ruff` + `run_tests.py --fast` → PR**；用户偏好 CI 绿再合、质量/安全用 patch（1.10.x）。

---

## 1. 两分钟架构

```
CLI:   video_auto.py  → main(argv=None) / run_from_manifest_file(...)
WebUI: webui.py (HTTP) → webui_jobs.py (JOBS/路径/取消) + webui_ui.py (HTML/JS)
       渲染线程内调用 video_auto.main(main_argv)  —— 不改写全局 sys.argv
共享:  _bundled_ffmpeg.py
```

| 文件 | 职责 | Agent 注意 |
|------|------|------------|
| `video_auto.py` | 管线：TTS → 语速/hold → 字幕 → 场景 mp4 → concat → BGM | `CancelToken` **进程级**；WebUI 靠 `RENDER_LOCK` 串行 |
| `webui.py` | HTTP、`WebUIHandler`（别名 `H`） | 须捕获 `Exception` **与** `SystemExit` |
| `webui_jobs.py` | 任务表、路径沙箱、数据根 | **`ROOT`=可写数据**（frozen=exe 旁或 `NARRAVID_DATA_DIR`）；`PACKAGE_ROOT`=只读包 |
| `webui_ui.py` | 内嵌 HTML/JS 大字符串 | 改 UI 只动此文件；无独立前端工程 |
| `_bundled_ffmpeg.py` | ffmpeg/ffprobe 解析 | 永远走此模块，勿写死 `ffmpeg` 字符串当唯一路径 |

**场景停顿字段：`hold_sec`。** 历史字段 `hold` 只在边界兼容（`scene_hold_sec` / normalize / 导入）。

**可编程入口（仍经 argparse 内部）：** `video_auto.run_from_manifest_file(...)`。  
真正的 `run_manifest(dict)`（不经 argv）仍是债项 D6，未完成前不要假装已有稳定库 API。

---

## 2. 明确禁止（违反即视为错误改动）

- 无必要 **Flask / FastAPI / React 全盘重写**  
- 无鉴权把服务默认绑到公网当产品方案  
- 在 Linux 上实现完整 **System.Speech** 替代全家桶  
- 提交：`rendered/` 成片、`_test_*` / `_ux_*` 草稿、`.claude/` 私货、本地密钥  
- 为“干净”做 **CancelToken per-job 大手术**（除非用户明确要并发/嵌入，且接受高风险）  
- 把 `hold` 重新变成主路径字段，或用 `||` 合并 `hold_sec=0`  
- WebUI 渲染再去 **污染全局 `sys.argv`** 或 **`os.chdir` 到 job 目录**  
- edge-tts 传入 `rate`/`volume=None`（须为 `'+0%'` 这类字符串）  
- frozen WebUI 把 uploads/jobs 写进 **`_MEIPASS`**  
- 成功选片用 **字典序第一个 `*.mp4`**（须优先 `manifest.mp4` / `_pick_final_mp4`）  
- 让 `SystemExit` 从 `main` 冒泡成 WebUI **空成功**（无 video、无 error）

---

## 3. 常用命令

```bash
# 环境（Python 3.11+；非 exe 时系统需 ffmpeg/ffprobe）
pip install -r requirements.txt
pip install -r requirements-dev.txt   # ruff 等

# 运行
python webui.py
python webui.py --port 8080 --host 127.0.0.1
python video_auto.py examples/demo_manifest.json
python video_auto.py my.json --voice zh-CN-YunyangNeural --speed 1.5 --bgm bgm.mp3

# 门禁（无 pytest；分层 unittest）
ruff check .
python run_tests.py --fast      # unit + security + cancel
python run_tests.py             # + live（起本机 HTTP，假 main）
python run_tests.py --max       # + pipeline(ffmpeg) + legacy
python test_e2e.py              # 真 Edge TTS，发版前

# Docker
docker build -t narravid . && docker run --rm -p 5000:5000 narravid
```

环境变量速查：`NARRAVID_HOST` / `NARRAVID_PORT` / `NARRAVID_DOCKER`、`NARRAVID_FONT`、`NARRAVID_FFMPEG`、`NARRAVID_DATA_DIR`（WebUI 可写根）、`NARRAVID_PROGRESS_FILE`（渲染线程用）。

---

## 4. 改动门禁（何时跑什么）

| 改动范围 | 最低门禁 |
|----------|----------|
| 纯文档 | 目视链接即可 |
| 辅助函数 / 无 HTTP | `ruff` + `run_tests.py --fast` |
| WebUI 路由 / 取消 / 路径 | 同上 + 默认 `run_tests.py`（live） |
| 管线 / ffmpeg / 字幕 | 有环境则 `--max` 或针对性 pipeline |
| 发版 tag `v*` | CHANGELOG 收节 + 绿 CI；理想再跑 `test_e2e.py` |

发版习惯：功能/跨平台用 minor；质量安全边角用 **patch（1.10.x）**。  
Windows exe：push `v*` tag → workflow **Build & Release EXE**。

---

## 5. 契约速记（易回归）

- **WebUI 单 flight：** `RENDER_LOCK`；取消只武装**当前 active** job 的全局 `CancelToken`。  
- **Stall：** 进度文件约 **300s** 无变化判超时（`STALL_TICKS`）；排队不计 stall。  
- **终态：** 已成功的 cancel 应 `ignored`，不可抹掉 `video`；超时文案优先于“已取消”。  
- **媒体路径：** uploads / examples-assets / 输出树白名单；export 拒绝 job 内部日志。  
- **字幕：** 用户未改样式时不要强塞 `subtitle_style`；有样式则 `sanitize_subtitle_style`。  
- **BGM：** 混音降级可“成功但无/弱 BGM”，应进 `_warnings.txt` / status `warning`；CLI 坏路径仍可能偏软（债）。  
- **打包：** CLI/WebUI 均需合理 hidden-import；标题卡依赖 matplotlib collect；数据目录见 `webui_jobs._app_data_root`。

HTTP 面摘要见 [ARCHITECTURE.md](ARCHITECTURE.md) 与根 [CLAUDE.md](../CLAUDE.md)。

---

## 6. 债与优先级（勿重复已关闭项）

**仍值得做（摘要）：** 详见 [REMAINING_DEBT.md](REMAINING_DEBT.md)。

| 优先 | 项 | 说明 |
|------|----|------|
| 高耗时 | D1 真 multipart 上传 | 大视频内存 |
| 高耗时 | D6 `run_manifest(dict)` | 可嵌入 API；做 MCP 前更应先做这个 |
| 高风险 | D5 CancelToken per-job | 仅并发/多入口需要时 |
| 体验 | D11 Playwright 一条主路径 | 发版信心 |
| 安全 | D2 zip 压缩比等 | 随暴露面加强 |

**已关闭示例（不要重开）：** late-cancel 抹视频、sys.argv 污染渲染、HEAD 泄露、SystemExit 假成功、frozen `_MEIPASS` 写数据、MP3 误拷成 `.wav`、字典序选 mp4、BGM `-shortest` 截尾 等——完整列表在债文档「已关闭」节。

**明确不做：** 多租户计费、Linux 系统 TTS 全家桶、为现代感重写 Web 栈。

**关于 MCP：** 可选“Agent 遥控器”，不是产品主线。若做：本机绑定、薄封装现有能力、路径白名单；**先 D6 再 MCP**。不要为了 MCP 引入公网默认暴露。

---

## 7. 推荐工作方式

1. 小步 PR；标题说明用户可见影响。  
2. 修 bug 先查 `CHANGELOG.md` 近几节，避免回退已修行为。  
3. 测试：stdlib `unittest` + `run_tests.py`；不要引入 pytest 作为新门禁 unless 用户要求。  
4. 前端在 `webui_ui.py` 字符串内；保持现有 JS 命名风格（见 STYLE）。  
5. 安全改动优先扩 `tests/test_security_http.py` / live，而不是只改注释。  
6. 需要并行调研时可用多 agent，但**合并前在主会话跑门禁**。

---

## 8. 文档地图

| 文档 | 给谁 | 内容 |
|------|------|------|
| **本页 `AGENT_GUIDE.md`** | **AI / Agent** | 入口、禁区、命令、契约 |
| [FUTURE_AGENTS.md](FUTURE_AGENTS.md) | 协作者短交接 | 压缩版注意点 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 维护者 | 模块与生命周期 |
| [REMAINING_DEBT.md](REMAINING_DEBT.md) | 维护者 | 债与已关闭 |
| [OPS.md](OPS.md) | 运维/发版 | Docker、tag、排障 |
| [STYLE.md](STYLE.md) | 写代码时 | Ruff/命名 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 人类贡献者 | PR 简表 |
| [../README.md](../README.md) | 终端用户 | 下载与使用 |
| [../CHANGELOG.md](../CHANGELOG.md) | 全员 | 版本行为 |

---

## 9. 一句话

你是在维护一个**已能出片的本机工具**：优先修真实回归与安全边界，保持 exe/源码双入口可用；大重构与 MCP 只能在债文档优先级下、用户明确要时再动。
