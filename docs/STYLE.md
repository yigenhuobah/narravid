# narravid 代码风格与命名约定

目标：可读、可维护、跨 Windows/Linux；**不**追求一次改名整库。

## 工具

| 工具 | 作用 | 命令 |
|------|------|------|
| **Ruff** | Python lint + import 排序 + 基础命名 | `ruff check .` / `ruff format .` |
| （暂无）mypy | 类型检查 | 模块边界稳定后再加 |
| （暂无）ESLint | 前端 | UI 仍内嵌在 `webui.py` 字符串里，暂不单独拆包 |

安装（开发机）：

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
```

CI：Linux workflow 会跑 `ruff check`（见 `.github/workflows/test-linux.yml`）。

## Python 命名

| 种类 | 约定 | 示例 |
|------|------|------|
| 模块/包 | `snake_case` | `video_auto.py` |
| 函数/方法 | `snake_case`，动词开头 | `resolve_tts_engine` |
| 常量 | `UPPER_SNAKE` | `MAX_IMAGE_SIZE` |
| 类 | `PascalCase` | `ProgressTracker` |
| 私有 | 前缀 `_` | `_find_zh_font` |
| 布尔 | `is_` / `has_` / `can_` | `system_tts_available` |

**避免：**

- 无语境单字母：`j`, `h`, `p`（循环下标 `i`、`e` as Exception 除外）
- 误导缩写：`pain`（应为 `paint`/`render_scenes`）、`mon`（`monitor`）
- 与内置冲突：`id`, `type`, `list` 作变量名

**历史债（已知，渐进改）：**

- `webui.py`：`H` handler 类、`mon` 监控闭包、`JOBS` 全局
- 内嵌 JS：`S` 场景数组、`E(id)` DOM 查询、`pain()` 重绘列表

新代码不要再引入同等级的短名。改旧名时：**一次只改一条符号链，并跑 `run_tests.py --fast`**。

## 内嵌 JS（`webui.py` HTML 字符串）

| 种类 | 约定 | 示例 |
|------|------|------|
| 函数 | `camelCase`，动词 | `loadTemplate`, `exportProject` |
| 状态变量 | 有意义的全词或可读缩写 | `scenes` 优于 `S`；`el` 仅限局部 DOM |
| DOM 快捷方式 | 允许薄封装但名字要可读 | `byId(id)` 优于 `E(id)` |
| 事件处理 | `on`/`handle` 前缀可选 | `handleDrop` |

**避免：** 单字母全局、`d`/`r` 满天飞（`for` 循环局部除外）。

**已完成的可读性改名（v1.10+）：** `pain`→`paintScenes`，`E`→`byId`，`S`→`scenes`，`mon`→`monitor_job`。

## 注释与文案

- 代码标识符：**英文**
- 用户可见 UI 文案：中文（产品面向中文用户）
- 注释：中英文均可，优先说明「为什么」

## 文件与结构

- WebUI 拆分：`webui.py`（HTTP handler）+ `webui_jobs.py`（任务/路径）+ `webui_ui.py`（HTML/JS 模板）。
- 场景停顿字段统一为 **`hold_sec`**（模板/导入仍可读历史 `hold`）。
- 测试：`tests/test_*.py`，入口 `run_tests.py`（无 pytest 强制）。
- 本地草稿：`_test_*.py` / `_ux_*.py` 不进仓库。

## 提交前检查清单

```bash
ruff check .
python run_tests.py --fast
```

改 WebUI 行为时再加：

```bash
python run_tests.py          # + live
# 或 python test_e2e.py
```

## 重命名策略（可选，非门禁）

后续可选：

1. handler 类 `H` → `WebUIHandler`（改动面大，单独 PR）
2. 将 HTML/JS 从 `webui.py` 字符串拆出，便于 ESLint

不要在同一 PR 里「lint 全绿 + 全库改名 + 功能修改」。
