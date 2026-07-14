# 给后续 Agent / 协作者

> **完整说明书请读：[AGENT_GUIDE.md](AGENT_GUIDE.md)**（README 已导流至此）。  
> 本页是压缩交接；细节与禁区以 `AGENT_GUIDE` + 债文档为准。

## 先读

1. **`docs/AGENT_GUIDE.md`** — Agent 专用（命令 / 禁止 / 契约）  
2. `docs/ARCHITECTURE.md` — 模块与作业流  
3. `docs/REMAINING_DEBT.md` — 别重复已关闭项  
4. `docs/STYLE.md` — 命名与 Ruff  
5. `docs/OPS.md` — 运行与发版  
6. `CLAUDE.md`（若本地有）— 仓库约定  

## 改代码时

- 门禁：`ruff check .` + `python run_tests.py --fast`；动 WebUI/取消再跑 default/live  
- 发版前：`test_e2e.py`（真 Edge）  
- **不要**在无必要 PR 里：全库改名、重写框架、开 CancelToken 大手术  
- WebUI 三文件：`webui.py` / `webui_jobs.py` / `webui_ui.py`；测试可 `import webui`  
- 场景字段：`hold_sec`；兼容 `hold` 只在边界  

## 高价值、高耗时任务（适合有额度时做）

| 任务 | 为何费 | 产出 |
|------|--------|------|
| multipart 上传端到端 | 前后端协议 | 大视频内存友好 |
| `run_manifest(dict)` 去掉 argparse 热路径 | 大重构+测 | 可嵌入 API |
| CancelToken per-job | 并发语义 | 同进程多入口安全 |
| Playwright 主路径 | 环境/脆弱 | 真 UI 回归 |
| 安全回归扩充 | 构造 zip/HEAD/硬链 | 防回退 |

## 最近版本线（便于 bisect）

- v1.10.0 跨平台 Edge/字体/killpg/Docker  
- v1.10.1 拆分 WebUI、Ruff、hold 契约、health  
- v1.10.2 main(argv)、health -version、BGM warning  
- v1.10.3 HEAD/allowlist/zip/chdir/字幕默认/deploy 示例  
- main 其后：`run_from_manifest_file`、分块 b64 上传、`WebUIHandler`  

## 明确禁止

- 提交 `_ux_*`、`_test_*` 草稿、`.claude/` 私货、`rendered/` 成片  
- 无鉴权把服务绑公网  
- 把 Linux 当 System TTS 平台  
