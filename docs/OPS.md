# 运维与发布手册

## 本机开发

```bash
pip install -r requirements-dev.txt   # 含 ruff
python webui.py                       # http://127.0.0.1:5000
python video_auto.py examples/demo_manifest.json
ruff check .
python run_tests.py --fast
```

环境变量：

| 变量 | 含义 |
|------|------|
| `NARRAVID_HOST` / `NARRAVID_PORT` | 监听地址端口 |
| `NARRAVID_DOCKER=1` | 默认 host 0.0.0.0 |
| `NARRAVID_FONT` | 中文字体文件 |
| `NARRAVID_FFMPEG` / `NARRAVID_FFPROBE` | 覆盖二进制路径 |
| `NARRAVID_PROGRESS_FILE` | 进度文件（WebUI 自动设） |
| `NARRAVID_DATA_DIR` | WebUI 可写数据根（uploads/jobs/templates）；**frozen exe 默认写在 exe 同目录**，勿用 `_MEIPASS` |

## Docker（单用户）

```bash
docker build -t narravid .
docker run --rm -p 5000:5000 -v narravid-data:/app/rendered narravid
```

内网多人：**不要**裸映射 5000。用 `deploy/docker-compose.example.yml` + Caddy Basic Auth（见 `deploy/README.md`）。

健康检查：

```bash
curl -s http://127.0.0.1:5000/api/health | jq .
# ok=true 且 ffmpeg.ok / tts.engine 合理
```

## 发布 exe（Windows CI）

1. `CHANGELOG.md`：把 `[Unreleased]` 收成 `## [vX.Y.Z] - YYYY-MM-DD`  
2. 可选：`pyproject.toml` version  
3. commit → `git tag vX.Y.Z` → `git push origin main --tags`  
4. 等 workflow **Build & Release EXE**  
5. Release 页应有 `narravid.exe` + `narravid-webui.exe`  

版本习惯：功能/跨平台用 minor；质量/安全边角用 patch（1.10.x）。

## 故障排查

| 现象 | 检查 |
|------|------|
| 标题/字幕方块 | 字体：`NARRAVID_FONT` / Noto CJK / Windows 雅黑 |
| Edge TTS 失败 | 出网、edge-tts 版本；Linux **无** system 回退 |
| health ok 但渲染失败 | 看 job 目录 `_stderr.log`；progress 文件 |
| 有 BGM 设置但听不到 | status `warning` / `_warnings.txt` |
| 取消不掉 | 是否已成功终态（会 ignored）；是否在排队 |
| 导入 zip 失败 | 条目数、解压大小、路径穿越、无 manifest |
| exe 重启后 uploads/成片消失 | 旧版写进 `_MEIPASS`；升级后数据在 exe 旁 `rendered/webui/` 或 `NARRAVID_DATA_DIR` |
| 长编码被标「渲染超时」 | 默认约 300s 无进度心跳；进度文件应持续被 pipeline 更新 |

Job 目录：`rendered/webui/<render_id>/`（相对 `NARRAVID_DATA_DIR` 或源码/exe 根） 
上传：`rendered/webui/uploads/`  
模板：`rendered/webui/templates/`

## 安全基线（部署）

- 默认绑定回环；Docker 示例走反代鉴权  
- 无内置用户体系 → **能访问端口 = 能渲染/清文件**  
- 定期清理 `rendered/`（UI「清理旧文件」保留最近 5 个 job）  
