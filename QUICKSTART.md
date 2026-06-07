# narravid 快速上手

## 推荐方式：下载 exe

1. 去 [Releases](https://github.com/yigenhuobah/narravid/releases) 下载 `narravid-webui.exe`
2. 双击运行（ffmpeg 已内置，无需安装）
3. 浏览器自动打开
4. 拖图片进来 → 写文案 → 选音色 → 点生成

## 源码方式

### 1. 安装

```bash
pip install -r requirements.txt
# ffmpeg 需在 PATH 中（或下载 exe 版本）
```

### 2. 启动 Web UI

```bash
python webui.py
```

### 3. 使用

- **📁 批量添加图片**：点按钮一次选多张
- **拖拽排序**：拖动场景左边的 ⠿ 手柄调整顺序
- **拖图片替换**：从文件夹拖图片到缩略图上直接换图
- **写文案**：每张图下面填解说词，按句号自动切字幕
- **选音色**：顶部下拉选 TTS 音色
- **调语速**：拖动语速滑块
- **点生成**：底部进度条显示进度，完成后下载视频

## 命令行方式

```bash
# 基础
python video_auto.py my-video.json

# 常用参数
python video_auto.py my-video.json --voice zh-CN-YunyangNeural --speed 1.5 --bgm bgm.mp3
```

## 常用音色

| 音色 | 风格 |
|------|------|
| `zh-CN-XiaoxiaoNeural` | 女声·温暖 |
| `zh-CN-YunyangNeural` | 男声·专业播报 |
| `zh-CN-YunxiNeural` | 男声·轻快 |
| `zh-CN-YunjianNeural` | 男声·热情讲述 |
