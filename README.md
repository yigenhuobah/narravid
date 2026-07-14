# narravid

把图片 + JSON 文案自动变成解说视频。Windows 可 **双击 exe**；也支持 Linux / Docker 源码运行（Edge TTS）。

## 下载（Windows 推荐）

去 [Releases](https://github.com/yigenhuobah/narravid/releases) 下载 `narravid-webui.exe`。

- **ffmpeg 已打包在内，无需手动安装**
- 双击运行 → 终端会打印本机地址（默认 `http://127.0.0.1:5000`）→ 浏览器打开 → 拖图片、写文案、点生成

## 从源码运行

```bash
pip install -r requirements.txt
# 需要系统已安装 ffmpeg/ffprobe（Windows 也可用 PATH 上的 ffmpeg）
python webui.py        # Web UI（推荐）→ http://127.0.0.1:5000
python video_auto.py my-video.json   # 命令行
```

### 平台说明

| 能力 | Windows | Linux / Docker | macOS |
|------|---------|----------------|-------|
| Edge TTS | ✅（需出网） | ✅（需出网） | ✅ |
| 系统 TTS（PowerShell） | ✅ | ❌ | ❌ |
| ffmpeg | 打包 exe 或 PATH | apt/包管理安装 | brew 等 |
| 中文标题 / 字幕 | 微软雅黑等 | 需 Noto CJK 等，或 `NARRAVID_FONT` / `fonts/` | PingFang 等 |
| 取消杀 ffmpeg 进程树 | taskkill /T | killpg | killpg |

Linux 依赖示例（Debian/Ubuntu）：

```bash
sudo apt-get install -y ffmpeg fonts-noto-cjk
pip install -r requirements.txt
python webui.py --host 127.0.0.1 --port 5000
```

可选环境变量：`NARRAVID_FONT`（字体文件）、`NARRAVID_HOST` / `NARRAVID_PORT`、`NARRAVID_DOCKER=1`（默认监听 `0.0.0.0`）、`NARRAVID_FFMPEG` / `NARRAVID_FFPROBE`。

### Docker（单用户）

```bash
docker build -t narravid .
docker run --rm -p 5000:5000 -v narravid-data:/app/rendered narravid
# 浏览器打开 http://127.0.0.1:5000
```

镜像内已装 ffmpeg + Noto CJK，TTS 仅 Edge。**局域网多人时请在反代上加鉴权**，不要裸暴露端口。

## Web UI 功能

- 📁 批量添加图片，自由拖拽排序
- 🖱 拖图片到场景卡片直接替换
- 🎙 一键切换音色、语速
- 📝 按句自动字幕（支持 `。！？；!?;` 分句）
- 🎵 可选 BGM + 自动标题页
- ⏱ 音频自动匹配图片，不需要手动对轴
- 🚀 多线程并行渲染，大幅提升生成速度
- 📊 实时进度显示

## 命令行

```bash
# 基础
python video_auto.py my-video.json

# 指定音色、语速、BGM
python video_auto.py my-video.json --voice zh-CN-YunyangNeural --speed 1.5 --bgm bgm.mp3

# 多线程渲染（默认 4 线程）
python video_auto.py my-video.json --workers 8

# 标题页
python video_auto.py my-video.json --title-card "数据分析" --no-burn
```

### CLI 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--voice` | TTS 音色名称 | `zh-CN-XiaoxiaoNeural` |
| `--speed` | 语速倍率 | 1.5 |
| `--engine` | TTS 引擎 (`edge` / `system`) | 自动检测 |
| `--workers` | 并行线程数 | 4 |
| `--bgm` | 背景音乐文件路径 | — |
| `--bgm-volume` | BGM 音量 (0.0~1.0) | 0.25 |
| `--title-card` | 标题页文字 | — |
| `--title-card-file` | 从文件读取标题页文字 | — |
| `--end-card` | 封尾页文字 | — |
| `--end-card-file` | 从文件读取封尾页文字 | — |
| `--card-duration` | 标题页停留秒数 | 3.0 |
| `--end-card-duration` | 封尾页停留秒数 | 同标题页 |
| `--subtitle-style` | 自定义字幕 ASS 样式 | 默认样式 |
| `--title-card-bg` | 标题页/封尾页背景色 | #1a1a2e |
| `--no-smart-comma` | 禁用逗号智能断句 | — |
| `--no-burn` | 不烧录字幕 | — |
| `--output-dir` | 输出目录 | manifest 中的值 |

### Manifest JSON 字段

除 CLI 参数外，manifest JSON 也支持以下字段（CLI 参数优先）：

```json
{
  "workers": 8,
  "tts_engine": "edge",
  "voice": "zh-CN-YunyangNeural",
  "speech_speed": 1.5,
  "burn_subtitles": true,
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "scenes": [...]
}
```

## 依赖

仅从源码运行时需要：
- Python 3.11+
- ffmpeg / ffprobe（也可下载 exe 版本，自带 ffmpeg）
- `pip install -r requirements.txt`

## 测试

```bash
# 端到端全功能测试（自动启动 WebUI、生成测试素材、测试所有功能）
python test_e2e.py

# 自定义参数
python test_e2e.py --port 5001 --workers 4 --keep

# 测试已有服务
python test_e2e.py --base-url http://127.0.0.1:5000
```

## License

MIT
