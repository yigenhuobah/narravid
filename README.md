# narravid

把图片 + JSON 文案自动变成解说视频。提供 **Web UI** 和 **命令行** 两种使用方式。

## 下载（推荐）

去 [Releases](https://github.com/yigenhuobah/narravid/releases) 下载 `narravid-webui.exe`，双击运行。

## 从源码运行

### Web UI（推荐）

```bash
python webui.py
```

浏览器自动打开，拖图片、写文案、选音色、点生成。

### 命令行

```bash
python video_auto.py my-video.json --voice zh-CN-YunyangNeural --speed 1.5
```

## 特性

- 🖥 Web UI — 浏览器里操作，零命令行
- 📦 可打包为 exe — 双击运行（GitHub Actions 自动构建）
- 🎙 Edge TTS / 系统 TTS，失败自动重试降级
- 📝 按句自动字幕，可选烧录
- ⏱ 音频时长自动匹配图片
- 🎵 可选 BGM + 自动标题页

## 依赖

- Python 3.11+
- ffmpeg / ffprobe（需在 PATH 中）
- `pip install -r requirements.txt`

## License

MIT
