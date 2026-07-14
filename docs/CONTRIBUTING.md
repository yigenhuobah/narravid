# 贡献简表

1. 读 `docs/FUTURE_AGENTS.md` + `docs/REMAINING_DEBT.md`
2. 分支开发，PR；CI：Ruff + `run_tests.py`
3. 本地：`pip install -r requirements-dev.txt && ruff check . && python run_tests.py --fast`
4. 不提交 `rendered/`、`_ux_*`、私货配置
5. 发版：更新 CHANGELOG 版本节 + tag `v*`

大改（multipart、CancelToken per-job、run_manifest dict）先开 issue/讨论，避免与小修复搅在一起。
