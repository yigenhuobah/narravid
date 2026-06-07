# narravid

把图片 + JSON 文案自动变成解说视频。提供 **Web UI** 和 **命令行** 两种使用方式。

## Web UI（推荐）

```bash
python webui.py
```

浏览器打开 http://localhost:5000，拖图片、写文案、选音色、点生成。零命令行。

## 命令行

```bash
# 基础
python video_auto.py my-video.json

# 换音色 + 调语速
python video_auto.py my-video.json --voice zh-CN-YunyangNeural --speed 1.5

# 加标题页 + 背景音乐
python video_auto.py my-video.json --title-card "分析报告" --bgm bgm.mp3
```

## 特性

- 🖥 Web UI + 命令行双模式
- 🎙 Edge TTS / 系统 TTS，失败自动重试降级
- 📝 按句自动字幕，可选烧录
- ⏱ 音频时长自动匹配图片，不需要手动对轴
- 🎵 可选 BGM + 自动标题页
- 🔧 语速、音色均支持一键切换

## 依赖

- Python 3.11+
- ffmpeg / ffprobe（需在 PATH 中）
- edge-tts >= 7.2.8、matplotlib

## 文档

- [QUICKSTART.md](QUICKSTART.md) — 5 分钟上手
- `python video_auto.py --help` — 全部 CLI 参数

## License

MIT
