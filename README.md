# narravid

把图片 + JSON 文案自动变成解说视频。适合图表解说、报告转视频、快速出片原型。

## 快速开始

```bash
# 安装
python -m pip install -r requirements.txt

# 确认 ffmpeg 可用
ffmpeg -version

# 跑 demo
python video_auto.py examples/demo_manifest.json
```

## 用法

```bash
# 基础
python video_auto.py my-video.json

# 换音色 + 调语速
python video_auto.py my-video.json --voice zh-CN-YunyangNeural --speed 1.5

# 加标题页 + 背景音乐
python video_auto.py my-video.json --title-card "分析报告" --bgm bgm.mp3
```

## 特性

- Edge TTS / 系统 TTS 自动切换，失败自动重试
- 音频时长自动匹配图片，不需要手动对轴
- 按句自动生成字幕，可选烧录到视频
- 支持纯停留画面（只看图不出声）
- 可选 BGM 背景音乐 + 自动标题页
- 语速、音色均支持 CLI 覆盖

## 依赖

- Python 3.11+
- ffmpeg / ffprobe（需在 PATH 中）
- edge-tts >= 7.2.8

## 文档

- [QUICKSTART.md](QUICKSTART.md) — 5 分钟上手
- `python video_auto.py --help` — 全部 CLI 参数

## Manifest 格式

```json
{
  "title": "视频标题",
  "scenes": [
    {
      "image": "./chart-01.png",
      "text": "这段文案会被自动配音，并按音频时长停留。"
    },
    {
      "image": "./chart-02.png",
      "text": "字幕会按句号自动切分。"
    },
    {
      "image": "./chart-03.png",
      "hold_sec": 3
    }
  ]
}
```

如果 `text` 为空且提供了 `hold_sec`，该场景作为纯停留画面。

## License

MIT
