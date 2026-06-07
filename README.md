# narravid

把图片 + JSON 文案自动变成解说视频。**双击 exe 即用，零安装。**

## 下载（推荐）

去 [Releases](https://github.com/yigenhuobah/narravid/releases) 下载 `narravid-webui.exe`。

- **ffmpeg 已打包在内，无需手动安装**
- 双击运行 → 浏览器自动打开 → 拖图片、写文案、点生成

## 从源码运行

```bash
pip install -r requirements.txt
python webui.py        # Web UI（推荐）
python video_auto.py my-video.json   # 命令行
```

## Web UI 功能

- 📁 批量添加图片，自由拖拽排序
- 🖱 拖图片到场景卡片直接替换
- 🎙 一键切换音色、语速
- 📝 按句自动字幕
- 🎵 可选 BGM + 自动标题页
- ⏱ 音频自动匹配图片，不需要手动对轴

## 命令行

```bash
python video_auto.py my-video.json --voice zh-CN-YunyangNeural --speed 1.5 --bgm bgm.mp3
```

## 依赖

仅从源码运行时需要：
- Python 3.11+
- ffmpeg / ffprobe（也可下载 exe 版本，自带 ffmpeg）
- `pip install -r requirements.txt`

## License

MIT
