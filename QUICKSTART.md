# narravid 快速上手

5 分钟，从零到第一条解说视频。

## 1. 安装依赖

```bash
# Python 包
python -m pip install -r narravid\requirements.txt

# ffmpeg 必须已在 PATH 中
ffmpeg -version
```

## 2. 创建你的第一个 manifest

保存为 `my-video.json`：

```json
{
  "title": "我的第一条视频",
  "scenes": [
    {
      "image": "./slide-01.png",
      "text": "这是第一个场景。narravid 会自动生成配音和字幕。"
    },
    {
      "image": "./slide-02.png",
      "text": "你可以加任意多个场景。每个场景都会有独立的音频和字幕。"
    }
  ]
}
```

## 3. 运行

```bash
python narravid\video_auto.py my-video.json
```

输出在 `rendered/my-video/` 里。

## 4. 换音色、调语速

```bash
# 查看可用音色
python -m edge_tts --list-voices

# 换音色
python narravid\video_auto.py my-video.json --voice zh-CN-YunyangNeural

# 调语速
python narravid\video_auto.py my-video.json --speed 1.5

# 一起用
python narravid\video_auto.py my-video.json --voice zh-CN-YunxiNeural --speed 1.4
```

## 5. 加标题页

```bash
python narravid\video_auto.py my-video.json --title-card "我的分析报告"
```

## 6. 加背景音乐

```bash
python narravid\video_auto.py my-video.json --bgm bgm.mp3
```

BGM 会在配音时自动降低音量。

## 常用音色

| 音色名 | 性别 | 风格 |
|--------|------|------|
| `zh-CN-XiaoxiaoNeural` | 女 | 温暖、通用 |
| `zh-CN-XiaoyiNeural` | 女 | 活泼 |
| `zh-CN-YunxiNeural` | 男 | 轻快 |
| `zh-CN-YunyangNeural` | 男 | 专业、播报感 |
| `zh-CN-YunjianNeural` | 男 | 热情、讲述感 |

## 常见问题

### "edge-tts 失败了怎么办？"
脚本会自动重试 2 次，还不行就自动切到 Windows 系统 TTS。

### "怎么关掉字幕？"
```bash
python narravid\video_auto.py my-video.json --no-burn
```

### "字幕能不烧录，只导出 srt 吗？"
可以。加 `--no-burn`，srt 文件会正常生成，只是不压进视频。
