# 剩余技术债（诚实清单）

更新于 2026-07-14（v1.10.3 + PR#6 合入后）。只列**仍未做完**、且有业务/安全含义的项。

## 仍值得做

### 安全 / 资源

| ID | 项 | 风险 | 建议方向 | 预估 |
|----|----|------|----------|------|
| D1 | JSON+base64 上传仍整包进请求 body | 内存峰值 | 真 multipart 流式；或继续降 body 上限 | M–L |
| D2 | import zip 压缩比/条目仍可加压磁盘 | DoS | 更严 ratio、总文件数、超时 | M |
| D3 | 无鉴权 | 内网暴露即全权 | 保持反代；可选本机 token | 产品决策 |
| D4 | 硬链接可能绕过“路径在目录内”语义 | 本机多用户 | `os.stat` 校验 real device/inode 策略 | S–M |

### 正确性 / 体验

| ID | 项 | 风险 | 建议方向 | 预估 |
|----|----|------|----------|------|
| D5 | CancelToken 进程单例 | 同进程多入口交错 | per-job token + 传入 pipeline | L（高风险） |
| D6 | 管线仍经 argv 桥接 | 扩展成本 | `run_manifest(dict, out_dir, **opts)` 真正不经 argparse | L |
| D7 | BGM 失败可“成功无 BGM” | 假成功 | 已有 warning；可改为可配置 fail-hard | S |
| D8 | 视频/字幕字体依赖主机 | Docker 方块字 | health 暴露 font；文档强调 Noto | 已部分做 |
| D9 | 并行场景 fail-fast 后 worker 尾延迟 | 取消不够快 | 已 set_aborted；可加强任务取消传播 | M |

### 可维护性

| ID | 项 | 说明 |
|----|----|------|
| D10 | TypedDict 偏文档 | `SceneDict`/`ManifestDict` 未绑满签名 |
| D11 | 无 Playwright | 拖拽/真实点击未覆盖 |
| D12 | pre-commit 需本机安装 | 配置有了，`pre-commit install` 未强制 |
| D13 | `webui_ui.py` 仍是巨字符串 | ESLint 难；拆 JS 文件要改打包 |
| D14 | 绝对路径出现在 upload/bgm-list | 本机工具可接受；公网需脱敏 |

## 明确不做（除非产品转向）

- 多租户、计费、水平扩展  
- Linux System.Speech 替代全家桶  
- 为“现代”重写 Flask/React  

## 已关闭（勿重复开票）

- late-cancel 抹视频、hold/hold_sec 双字段主路径、sys.argv 污染渲染  
- health 裸名 ffmpeg 假阳性、HEAD 泄露、export 任意 OUT_BASE 日志  
- 模块拆分 webui_jobs/ui、Ruff CI、跨平台 Edge/字体/killpg  

## 给下一任的优先级建议

1. **D1 multipart**（若用户开始传大视频）  
2. **D6 run_manifest(dict)**（下一次动管线时一并做）  
3. **D5 CancelToken per-job**（仅当出现同进程并行入口）  
4. **D11 一条 Playwright**（发版信心）  
