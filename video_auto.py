"""
narravid — 图片 + JSON 文案 → 解说视频，一键自动生成。

用法:
  python video_auto.py manifest.json
  python video_auto.py manifest.json --voice zh-CN-YunyangNeural --speed 1.5
  python video_auto.py manifest.json --bgm music.mp3 --output-dir ./out
  python video_auto.py manifest.json --title-card "魔神任务分析" --no-burn
  python video_auto.py manifest.json --workers 8

特性:
  - Edge TTS / 系统 TTS 自动切换
  - TTS 失败自动重试
  - 多线程并行处理场景（TTS + 渲染）
  - 可选 BGM + 自动闪避
  - 可选自动标题页
  - CLI 参数覆盖 manifest
  - exe 打包后自带 ffmpeg，无需手动安装
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── 统一使用 _bundled_ffmpeg 模块定位自带 ffmpeg ──────────────────
try:
    import _bundled_ffmpeg
    FFMPEG = _bundled_ffmpeg.get_ffmpeg()
    FFPROBE = _bundled_ffmpeg.get_ffprobe()
except ImportError:
    FFMPEG = 'ffmpeg'
    FFPROBE = 'ffprobe'

DEFAULT_W = 1920
DEFAULT_H = 1080
DEFAULT_FPS = 30
DEFAULT_TTS_ENGINE = 'edge'
DEFAULT_SYSTEM_VOICE = 'Microsoft Huihui Desktop'
DEFAULT_EDGE_VOICE = 'zh-CN-XiaoxiaoNeural'
DEFAULT_SPEECH_SPEED = 1.5
MAX_TTS_RETRIES = 2
DEFAULT_WORKERS = 4

# ── helpers ──────────────────────────────────────────────────────

def run(cmd, silent=False):
    kwargs = {}
    if silent:
        kwargs['stdout'] = subprocess.DEVNULL
        kwargs['stderr'] = subprocess.DEVNULL
    subprocess.run(cmd, check=True, **kwargs)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)
    ], text=True, encoding='utf-8').strip()
    return float(out)


def srt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def split_sentences(text: str, smart_comma: bool = True):
    """按中英文标点分句，支持 。！？；!?; 等句末标点。
    smart_comma=True 时，对逗号/顿号做智能断句：长句按逗号切分但合并短句。"""
    text = text.replace('\r', '').replace('\n', '').strip()
    if not text:
        return []
    # 句末标点集合：中文句号、感叹号、问号、分号 + 英文对应
    sentence_enders = set('。！？；!?;')
    chunks, cur = [], ''
    for ch in text:
        cur += ch
        if ch in sentence_enders:
            if cur.strip():
                chunks.append(cur.strip())
            cur = ''
    if cur.strip():
        chunks.append(cur.strip())
    # 如果只有一整句（无句末标点结尾），尝试按逗号智能断句
    if smart_comma and len(chunks) <= 1:
        raw = chunks[0] if chunks else text
        # 按逗号/顿号拆分
        comma_parts = []
        buf = ''
        for ch in raw:
            buf += ch
            if ch in '，、,':
                if buf.strip():
                    comma_parts.append(buf.strip())
                buf = ''
        if buf.strip():
            comma_parts.append(buf.strip())
        if len(comma_parts) > 1:
            # 合并短句：相邻短句总长度 < 15 字就合并
            merged = []
            i = 0
            while i < len(comma_parts):
                group = comma_parts[i]
                j = i + 1
                while j < len(comma_parts) and len(group.replace('，','').replace('、','').replace(',','')) + len(comma_parts[j].replace('，','').replace('、','').replace(',','')) < 15:
                    group += comma_parts[j]
                    j += 1
                merged.append(group)
                i = j
            return merged
    return chunks or [text]


def clean_subtitle_text(text: str) -> str:
    return text.strip().rstrip('。！？；!?;，,')


def build_sentence_segments(text: str, narration_duration: float, offset: float = 0.0, smart_comma: bool = True):
    sentences = split_sentences(text, smart_comma=smart_comma)
    if not sentences:
        return []
    weights = [max(len(s.replace(' ', '').replace('。', '')), 1) for s in sentences]
    total_weight = sum(weights) or 1
    cur = offset
    segments = []
    for i, (sentence, weight) in enumerate(zip(sentences, weights), 1):
        seg_dur = narration_duration * weight / total_weight
        end = offset + narration_duration if i == len(sentences) else cur + seg_dur
        segments.append({
            'start': cur,
            'end': end,
            'subtitle': clean_subtitle_text(sentence),
        })
        cur = end
    return segments


def subtitle_filter_arg(srt_path: Path, style_override: str = None) -> str:
    # ffmpeg subtitles filter 路径转义规则：
    #   路径用单引号包裹，内部特殊字符用 \ 转义：: \ ' [ ]
    #   但单引号在单引号字符串内无法用 \ 转义，
    #   所以路径含单引号时改用 filename 选项避免问题
    path = str(srt_path.resolve()).replace('\\', '/')
    has_apostrophe = "'" in path
    if has_apostrophe:
        # 含单引号的路径：使用 filename= 选项，用双引号包裹
        # 双引号内需要转义：\ : "
        for ch in ['\\', ':', '"']:
            path = path.replace(ch, '\\' + ch)
        if style_override:
            style = style_override
        else:
            style = (
                'FontName=Microsoft YaHei,FontSize=16,PrimaryColour=&H00FFFFFF,'
                'OutlineColour=&H64000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=30,Alignment=2'
            )
        return f'subtitles=filename="{path}":force_style=\'{style}\''
    else:
        # 常规路径：单引号包裹，转义 : [ ]
        for ch in [':', '[', ']']:
            path = path.replace(ch, '\\' + ch)
        if style_override:
            style = style_override
        else:
            style = (
                'FontName=Microsoft YaHei,FontSize=16,PrimaryColour=&H00FFFFFF,'
                'OutlineColour=&H64000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=30,Alignment=2'
            )
        return f"subtitles='{path}':force_style='{style}'"


def edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


# ── manifest ─────────────────────────────────────────────────────

def load_manifest(path: Path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if 'scenes' not in data or not data['scenes']:
        raise ValueError('manifest 缺少 scenes')
    return data

# ── TTS ──────────────────────────────────────────────────────────

def synthesize_system_tts(text: str, wav_path: Path, voice: str, rate: int = 0, volume: int = 100):
    txt_path = wav_path.with_suffix('.txt')
    ps1_path = wav_path.with_suffix('.ps1')
    txt_path.write_text(text, encoding='utf-8')
    esc_txt = str(txt_path).replace("'", "''")
    esc_wav = str(wav_path).replace("'", "''")
    esc_voice = voice.replace("'", "''")
    ps1 = f"""
Add-Type -AssemblyName System.Speech
$txt = [System.IO.File]::ReadAllText('{esc_txt}', [System.Text.Encoding]::UTF8)
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $s.GetInstalledVoices() | ForEach-Object {{ $_.VoiceInfo.Name }}
if ($voices -contains '{esc_voice}') {{
  $s.SelectVoice('{esc_voice}')
}} else {{
  $zh = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq 'zh-CN' }} | Select-Object -First 1
  if ($zh) {{ $s.SelectVoice($zh.VoiceInfo.Name) }}
}}
$s.Rate = {int(rate)}
$s.Volume = {int(volume)}
$s.SetOutputToWaveFile('{esc_wav}')
$s.Speak($txt)
$s.Dispose()
""".strip()
    ps1_path.write_text(ps1, encoding='utf-8')
    run(['powershell', '-ExecutionPolicy', 'Bypass', '-File', str(ps1_path)], silent=True)


def synthesize_edge_tts(text: str, media_path: Path, voice: str, rate: int = 0, volume: int = 100):
    """使用 edge-tts Python API 合成语音（不再起子进程，兼容 exe 打包）"""
    if not edge_tts_available():
        raise RuntimeError('edge-tts 未安装')
    import edge_tts
    import asyncio
    clean_text = text.replace('\ufffd', '').replace('�', '').strip()
    if not clean_text:
        raise RuntimeError('edge-tts: 文本为空')
    rate_str = f'{int(rate):+d}%' if rate else None
    volume_str = f'{int(volume) - 100:+d}%' if volume != 100 else None
    communicate = edge_tts.Communicate(
        text=clean_text,
        voice=voice,
        rate=rate_str,
        volume=volume_str,
    )
    asyncio.run(communicate.save(str(media_path)))
    if not media_path.exists() or media_path.stat().st_size == 0:
        raise RuntimeError('edge-tts: 合成文件为空或不存在')


def synthesize_audio_with_retry(text: str, raw_audio_path: Path, engine: str, voice: str, rate: int = 0, volume: int = 100):
    if engine == 'edge':
        for attempt in range(MAX_TTS_RETRIES + 1):
            try:
                synthesize_edge_tts(text, raw_audio_path, voice=voice, rate=rate, volume=volume)
                return 'edge'
            except Exception:
                if attempt < MAX_TTS_RETRIES:
                    time.sleep(3)
                else:
                    try:
                        synthesize_system_tts(text, raw_audio_path.with_suffix('.raw.wav'), voice=DEFAULT_SYSTEM_VOICE, rate=rate, volume=volume)
                        run([FFMPEG, '-y', '-i', str(raw_audio_path.with_suffix('.raw.wav')),
                             '-ar', '24000', '-ac', '1', str(raw_audio_path)], silent=True)
                        return 'system'
                    except Exception as fallback_err:
                        raise RuntimeError(f'edge-tts 和 system TTS 均失败: {fallback_err}') from fallback_err
    elif engine == 'system':
        synthesize_system_tts(text, raw_audio_path, voice=voice, rate=rate, volume=volume)
        return 'system'
    else:
        raise ValueError(f'不支持的 tts_engine: {engine}')
    return engine


# ── audio processing ────────────────────────────────────────────

def process_audio(raw_audio_path: Path, out_path: Path, speed: float, pad_sec: float):
    source_duration = ffprobe_duration(raw_audio_path)
    target_duration = source_duration / speed + pad_sec
    filters = []
    if abs(speed - 1.0) > 1e-6:
        filters.append(f'atempo={speed:.3f}')
    if pad_sec > 0:
        filters.append(f'apad=pad_dur={pad_sec:.3f}')
    if not filters:
        shutil.copyfile(raw_audio_path, out_path)
        return source_duration
    run([FFMPEG, '-y', '-i', str(raw_audio_path),
         '-af', ','.join(filters),
         '-ar', '24000', '-ac', '1',
         '-t', f'{target_duration:.3f}',
         str(out_path)], silent=True)
    return ffprobe_duration(out_path)


def make_silent_audio(out_path: Path, duration: float):
    run([FFMPEG, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
         '-t', f'{duration:.3f}', '-ar', '24000', '-ac', '1', str(out_path)], silent=True)


# ── subtitle ─────────────────────────────────────────────────────

def make_scene_srt(segments, srt_path: Path):
    rows = []
    for i, seg in enumerate(segments, 1):
        rows.append(f"{i}\n{srt_ts(seg['start'])} --> {srt_ts(seg['end'])}\n{seg['subtitle']}\n")
    srt_path.write_text('\n'.join(rows), encoding='utf-8')


def make_global_srt(scene_infos, out_path: Path):
    rows, idx, offset = [], 1, 0.0
    for scene in scene_infos:
        for seg in build_sentence_segments(scene['text'], scene['narration_duration'], offset):
            rows.append(f"{idx}\n{srt_ts(seg['start'])} --> {srt_ts(seg['end'])}\n{seg['subtitle']}\n")
            idx += 1
        offset += scene['scene_duration']
    out_path.write_text('\n'.join(rows), encoding='utf-8')


# ── title card ───────────────────────────────────────────────────

def _find_zh_font():
    """查找可用的中文字体路径，优先系统字体，其次打包字体"""
    # 系统字体候选
    system_fonts = [
        'C:/Windows/Fonts/msyh.ttc',    # Microsoft YaHei
        'C:/Windows/Fonts/simhei.ttf',   # SimHei
        'C:/Windows/Fonts/msyhl.ttc',    # YaHei Light
    ]
    for f in system_fonts:
        if Path(f).exists():
            return f
    # 打包字体（exe 模式下 _MEIPASS 或同级 fonts/ 目录）
    try:
        base = Path(sys._MEIPASS)
    except AttributeError:
        base = Path(__file__).resolve().parent
    bundled = base / 'fonts' / 'msyh.ttc'
    if bundled.exists():
        return str(bundled)
    return None


def generate_title_card(title: str, out_path: Path, width: int, height: int, bg_color: str = '#1a1a2e'):
    """用 matplotlib 生成标题页"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
    except ImportError:
        print('  [warn] matplotlib not available, skipping title card')
        return None

    # 加载中文字体
    zh_font_path = _find_zh_font()
    if zh_font_path:
        fm.fontManager.addfont(zh_font_path)
        font_prop = fm.FontProperties(fname=zh_font_path)
        font_name = font_prop.get_name()
    else:
        font_prop = None
        font_name = 'sans-serif'
        print('  [warn] 未找到中文字体，标题页可能显示方块')

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis('off')
    ax.text(width / 2, height / 2 + 20, title, fontsize=48, fontweight='bold',
            color='white', ha='center', va='center', fontproperties=font_prop or font_name)
    ax.text(width / 2, height / 2 - 50, 'narravid', fontsize=18,
            color='#888888', ha='center', va='center', fontproperties=font_prop or font_name)
    plt.tight_layout(pad=0)
    fig.savefig(out_path, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


# ── BGM mixing ───────────────────────────────────────────────────

def mix_bgm(voice_audio: Path, bgm_path: Path, out_path: Path, duck_ratio: float = 0.25):
    """将 BGM 与配音混音，配音时 BGM 音量降到 duck_ratio；失败则降级用原音频"""
    dur = ffprobe_duration(voice_audio)
    try:
        run([FFMPEG, '-y',
             '-i', str(voice_audio),
             '-stream_loop', '-1', '-i', str(bgm_path),
             '-filter_complex',
             f'[1:a]volume={duck_ratio:.2f}[a1];[0:a][a1]amix=inputs=2:duration=first:dropout_transition=0.5',
             '-t', f'{dur:.3f}', '-ar', '24000', '-ac', '1',
             str(out_path)], silent=True)
    except Exception as e:
        print(f'  BGM 混音失败({e})，使用原音频')
        shutil.copy2(str(voice_audio), str(out_path))


# ── 并行场景处理 ────────────────────────────────────────────────

class CancelToken:
    """全局取消令牌，供 WebUI 外部控制渲染中断"""
    _cancelled = False
    _lock = threading.Lock()

    @classmethod
    def set_cancelled(cls):
        with cls._lock:
            cls._cancelled = True

    @classmethod
    def is_cancelled(cls) -> bool:
        with cls._lock:
            return cls._cancelled

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._cancelled = False


def _check_cancel():
    """在关键步骤检查是否已取消，如已取消则抛出异常"""
    if CancelToken.is_cancelled():
        raise RuntimeError('渲染已被用户取消')


class ProgressTracker:
    """线程安全的进度追踪器"""

    def __init__(self, total: int, progress_file: str = None):
        self.total = total
        self.progress_file = progress_file
        self._completed = 0
        self._lock = threading.Lock()

    def report(self, idx: int, msg: str):
        """报告当前进度（线程安全）"""
        with self._lock:
            print(f'[{idx}/{self.total}] {msg}', flush=True)
            self._write_progress(f'[{idx}/{self.total}] {msg}')

    def complete(self, idx: int, msg: str):
        """标记完成并更新计数"""
        with self._lock:
            self._completed += 1
            print(f'[{idx}/{self.total}] {msg} ({self._completed}/{self.total} done)', flush=True)
            self._write_progress(f'[{self._completed}/{self.total}] {msg}')

    def _write_progress(self, msg: str):
        if self.progress_file:
            try:
                Path(self.progress_file).write_text(msg, encoding='utf-8')
            except Exception:
                pass


def process_single_scene(idx: int, scene: dict, project_root: Path,
                         tts_engine: str, voice: str, rate: int, volume: int,
                         speech_speed: float, pad_sec: float,
                         width: int, height: int, fps: int, burn_subtitles: bool,
                         subtitle_style: str,
                         smart_comma: bool,
                         tmp_dir: Path, audio_dir: Path, scene_dir: Path,
                         progress: ProgressTracker):
    """处理单个场景：TTS → 音频处理 → 字幕 → 渲染。供线程池调用。"""

    text = str(scene.get('text', '')).strip()
    image = Path(scene['image'])
    if not image.is_absolute():
        image = (project_root / image).resolve()
    if not image.exists():
        raise FileNotFoundError(f'scene {idx} 图片不存在: {image}')

    hold_sec = float(scene.get('hold_sec', 0.0))
    raw_audio = tmp_dir / (f'{idx:03d}.raw.mp3' if tts_engine == 'edge' else f'{idx:03d}.raw.wav')

    _check_cancel()
    wav = audio_dir / f'{idx:03d}.wav'
    srt = tmp_dir / f'{idx:03d}.srt'
    mp4 = scene_dir / f'{idx:03d}.mp4'

    # ── TTS ──
    if text:
        progress.report(idx, 'TTS ...')
        used_engine = synthesize_audio_with_retry(text, raw_audio, tts_engine, voice, rate, volume)
        narration_duration = process_audio(raw_audio, wav, speech_speed, pad_sec)
        progress.report(idx, f'TTS OK ({narration_duration:.1f}s, {used_engine})')
    else:
        narration_duration = 0.0
        progress.report(idx, 'Hold ...')
        make_silent_audio(wav, hold_sec or 2.0)
        progress.report(idx, 'Hold OK')

    # ── 字幕 + 渲染 ──
    scene_duration = narration_duration + hold_sec if narration_duration > 0 else (hold_sec or ffprobe_duration(wav))
    segments = build_sentence_segments(text, narration_duration, 0.0, smart_comma=smart_comma) if text else []
    make_scene_srt(segments, srt)

    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    if burn_subtitles and segments:
        vf += ',' + subtitle_filter_arg(srt, subtitle_style)

    _check_cancel()
    progress.report(idx, 'Render ...')
    run([FFMPEG, '-y', '-loop', '1', '-i', str(image), '-i', str(wav),
         '-vf', vf, '-r', str(fps), '-t', f'{scene_duration:.3f}', '-shortest',
         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
         str(mp4)], silent=True)
    progress.complete(idx, 'Render OK')

    return {
        'idx': idx, 'image': str(image), 'text': text,
        'narration_duration': narration_duration, 'hold_sec': hold_sec,
        'scene_duration': scene_duration, 'mp4': str(mp4), 'audio': str(wav),
    }


# ── main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='narravid — 图片 + JSON 文案 → 解说视频，一键自动生成',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python video_auto.py demo.json
  python video_auto.py demo.json --voice zh-CN-YunyangNeural --speed 1.4
  python video_auto.py demo.json --bgm bgm.mp3 --title-card "数据分析"
  python video_auto.py demo.json --output-dir ./out --no-burn
  python video_auto.py demo.json --workers 8
        ''')
    parser.add_argument('manifest', help='manifest JSON 文件路径')
    parser.add_argument('--voice', help='TTS 音色名称 (如 zh-CN-YunyangNeural)')
    parser.add_argument('--speed', type=float, help='语速倍率 (如 1.3, 1.5)')
    parser.add_argument('--output-dir', help='输出目录 (覆盖 manifest 中的 output_dir)')
    parser.add_argument('--bgm', help='背景音乐文件路径 (mp3/wav)')
    parser.add_argument('--title-card', help='自动生成标题页 (输入标题文字)')
    parser.add_argument('--title-card-file', help='从 UTF-8 文件读取标题页文字 (优先于 --title-card)')
    parser.add_argument('--end-card', help='自动生成封尾页 (输入文字，如"感谢观看")')
    parser.add_argument('--end-card-file', help='从 UTF-8 文件读取封尾页文字 (优先于 --end-card)')
    parser.add_argument('--card-duration', type=float, default=3.0,
                        help='标题页停留秒数 (默认 3.0)')
    parser.add_argument('--end-card-duration', type=float, default=0,
                        help='封尾页停留秒数 (默认与标题页相同)')
    parser.add_argument('--bgm-volume', type=float, default=0.25,
                        help='BGM 音量 (0.0~1.0, 配音时 BGM 降到该比例, 默认 0.25)')
    parser.add_argument('--subtitle-style', help='字幕 ASS 样式字符串 (覆盖默认)')
    parser.add_argument('--title-card-bg', help='标题页/封尾页背景色 (如 #1a1a2e, 默认)')
    parser.add_argument('--no-smart-comma', action='store_true', help='禁用逗号智能断句')
    parser.add_argument('--no-burn', action='store_true', help='不烧录字幕到视频')
    parser.add_argument('--engine', choices=['edge', 'system'], help='TTS 引擎: edge 或 system')
    parser.add_argument('--workers', type=int, default=0,
                        help=f'并行处理线程数 (默认 {DEFAULT_WORKERS}, 1=串行)')

    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    project_root = manifest_path.parent

    manifest = load_manifest(manifest_path)
    title = manifest.get('title', manifest_path.stem)
    width = int(manifest.get('width', DEFAULT_W))
    height = int(manifest.get('height', DEFAULT_H))
    fps = int(manifest.get('fps', DEFAULT_FPS))
    tts_engine = args.engine or manifest.get('tts_engine') or ('edge' if edge_tts_available() else 'system')
    voice = args.voice or manifest.get('voice') or (DEFAULT_EDGE_VOICE if tts_engine == 'edge' else DEFAULT_SYSTEM_VOICE)
    rate = int(manifest.get('rate', 0))
    volume = int(manifest.get('volume', 100))
    speech_speed = args.speed or float(manifest.get('speech_speed', DEFAULT_SPEECH_SPEED))
    if speech_speed < 0.5:
        print(f'  [warn] 语速 {speech_speed} 过低，已调整为 0.5')
        speech_speed = 0.5
    elif speech_speed > 3.0:
        print(f'  [warn] 语速 {speech_speed} 过高，已调整为 3.0')
        speech_speed = 3.0
    pad_sec = float(manifest.get('scene_tail_silence_sec', 0.16))
    burn_subtitles = not args.no_burn and bool(manifest.get('burn_subtitles', True))
    bgm_path = args.bgm
    bgm_volume = max(0.0, min(1.0, args.bgm_volume))
    title_card_text = None
    if args.title_card_file:
        try:
            title_card_text = Path(args.title_card_file).read_text(encoding='utf-8').strip()
        except Exception as e:
            print(f'  [warn] 无法读取标题页文件: {e}')
    if not title_card_text:
        title_card_text = args.title_card
    end_card_text = None
    if args.end_card_file:
        try:
            end_card_text = Path(args.end_card_file).read_text(encoding='utf-8').strip()
        except Exception as e:
            print(f'  [warn] 无法读取封尾页文件: {e}')
    if not end_card_text:
        end_card_text = args.end_card
    card_duration = max(1.0, args.card_duration)
    end_card_duration = max(1.0, args.end_card_duration) if args.end_card_duration > 0 else card_duration
    subtitle_style = args.subtitle_style
    card_bg = args.title_card_bg or '#1a1a2e'
    smart_comma = not args.no_smart_comma
    workers = args.workers or int(manifest.get('workers', DEFAULT_WORKERS))
    # 至少 1 个 worker
    workers = max(1, workers)

    out_dir = Path(args.output_dir) if args.output_dir else Path(manifest.get('output_dir', project_root / 'rendered' / manifest_path.stem))
    if not out_dir.is_absolute():
        if args.output_dir:
            out_dir = Path.cwd() / out_dir
        else:
            out_dir = (project_root / out_dir).resolve()
    out_dir = out_dir.resolve()
    tmp_dir = out_dir / '_tmp'
    scene_dir = out_dir / 'scenes'
    audio_dir = out_dir / 'audio'
    for d in [out_dir, tmp_dir, scene_dir, audio_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 进度文件：供 WebUI 实时读取进度
    progress_file = os.environ.get('NARRAVID_PROGRESS_FILE')

    def update_progress(msg):
        if progress_file:
            try:
                Path(progress_file).write_text(msg, encoding='utf-8')
            except Exception:
                pass

    # title card（串行，因为只有一个）
    title_card_path = None
    if title_card_text:
        print('[0] Title card: ' + title_card_text)
        update_progress('生成标题页...')
        tcp = tmp_dir / 'title_card.png'
        result = generate_title_card(title_card_text, tcp, width, height, bg_color=card_bg)
        if result and result.exists():
            title_card_path = result
        else:
            print('  [warn] 标题页生成失败，跳过')

    scene_infos = []
    total_scenes = len(manifest['scenes']) + (1 if title_card_path else 0) + (1 if end_card_text else 0)

    # ── 标题页场景（串行） ──
    if title_card_path:
        wav = audio_dir / '000.wav'
        srt = tmp_dir / '000.srt'
        mp4 = scene_dir / '000.mp4'
        make_silent_audio(wav, card_duration)
        make_scene_srt([], srt)
        run([FFMPEG, '-y', '-loop', '1', '-i', str(title_card_path), '-i', str(wav),
             '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black',
             '-r', str(fps), '-t', f'{card_duration:.1f}', '-shortest',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
             str(mp4)], silent=True)
        scene_infos.append({
            'idx': 0, 'image': str(title_card_path),
            'text': '', 'narration_duration': 0, 'hold_sec': 0,
            'scene_duration': card_duration, 'mp4': str(mp4), 'audio': str(wav),
        })
        print(f'  Title card OK ({total_scenes} scenes total, workers={workers})')

    # ── 并行处理所有场景 ──
    num_scenes = len(manifest['scenes'])
    progress = ProgressTracker(total_scenes, progress_file)

    if workers > 1 and num_scenes > 1:
        print(f'\n并行处理 {num_scenes} 个场景 (workers={workers}) ...')
        update_progress(f'并行处理 {num_scenes} 个场景...')

        # 构建 scene 任务参数（idx 从 1 开始，与标题页 0 不冲突）
        scene_tasks = []
        for sidx, scene in enumerate(manifest['scenes'], 1):
            scene_tasks.append((sidx, scene))

        # 用字典收集结果，保证按 idx 排序
        results = {}
        failed = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {}
            for sidx, scene in scene_tasks:
                future = executor.submit(
                    process_single_scene,
                    sidx, scene, project_root,
                    tts_engine, voice, rate, volume,
                    speech_speed, pad_sec,
                    width, height, fps, burn_subtitles,
                    subtitle_style, smart_comma,
                    tmp_dir, audio_dir, scene_dir,
                    progress,
                )
                future_to_idx[future] = sidx

            for future in as_completed(future_to_idx):
                sidx = future_to_idx[future]
                try:
                    info = future.result()
                    results[sidx] = info
                except Exception as e:
                    print(f'[ERROR] scene {sidx} 失败: {e}')
                    failed.append(sidx)

        if failed:
            print(f'\n警告: {len(failed)} 个场景失败: {failed}')
            if len(failed) == num_scenes:
                raise RuntimeError(f'所有场景均失败')

        # 按 idx 排序，保证 concat 顺序正确
        for sidx in sorted(results.keys()):
            scene_infos.append(results[sidx])

    else:
        # 串行模式（workers=1 或只有 1 个场景）
        failed = []
        for sidx, scene in enumerate(manifest['scenes'], 1):
            try:
                info = process_single_scene(
                    sidx, scene, project_root,
                    tts_engine, voice, rate, volume,
                    speech_speed, pad_sec,
                    width, height, fps, burn_subtitles,
                    subtitle_style, smart_comma,
                    tmp_dir, audio_dir, scene_dir,
                    progress,
                )
                scene_infos.append(info)
            except Exception as e:
                print(f'[ERROR] scene {sidx} 失败: {e}')
                failed.append(sidx)
        if failed:
            print(f'\n警告: {len(failed)} 个场景失败: {failed}')
            if not scene_infos:
                raise RuntimeError('所有场景均失败')

    # ── concat（必须等所有场景完成） ──
    # 先追加封尾页（在 concat 之前生成）
    end_card_path = None
    if end_card_text:
        update_progress('生成封尾页...')
        ecp = tmp_dir / 'end_card.png'
        result = generate_title_card(end_card_text, ecp, width, height, bg_color=card_bg)
        if result and result.exists():
            end_card_path = result
            print(f'[end] End card: {end_card_text}')
            ec_idx = len(scene_infos)
            ec_wav = audio_dir / f'{ec_idx:03d}_end.wav'
            ec_srt = tmp_dir / f'{ec_idx:03d}_end.srt'
            ec_mp4 = scene_dir / f'{ec_idx:03d}_end.mp4'
            make_silent_audio(ec_wav, end_card_duration)
            make_scene_srt([], ec_srt)
            run([FFMPEG, '-y', '-loop', '1', '-i', str(end_card_path), '-i', str(ec_wav),
                 '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black',
                 '-r', str(fps), '-t', f'{end_card_duration:.1f}', '-shortest',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
                 str(ec_mp4)], silent=True)
            scene_infos.append({
                'idx': ec_idx, 'image': str(end_card_path),
                'text': '', 'narration_duration': 0, 'hold_sec': 0,
                'scene_duration': end_card_duration, 'mp4': str(ec_mp4), 'audio': str(ec_wav),
            })
            print(f'  End card OK')
        else:
            print('  [warn] 封尾页生成失败，跳过')

    _check_cancel()
    print(f'\nConcat {len(scene_infos)} scenes ... ', end='', flush=True)
    update_progress('合并场景...')
    concat_txt = tmp_dir / 'concat.txt'
    lines = []
    for s in scene_infos:
        p = str(Path(s['mp4']).resolve()).replace("'", "'\\''")
        lines.append(f"file '{p}'")
    concat_txt.write_text('\n'.join(lines), encoding='utf-8')

    final_mp4 = out_dir / f'{manifest_path.stem}.mp4'
    run([FFMPEG, '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_txt),
         '-c', 'copy', str(final_mp4)], silent=True)
    print('OK')

    # BGM mixing
    if bgm_path and Path(bgm_path).exists():
        _check_cancel()
        print('Mix BGM ... ', end='', flush=True)
        update_progress('混入 BGM...')
        voice_total = audio_dir / '_narration_full.wav'
        run([FFMPEG, '-y', '-i', str(final_mp4), '-vn', '-ar', '24000', '-ac', '1',
             str(voice_total)], silent=True)
        mixed_audio = tmp_dir / 'mixed_audio.wav'
        mix_bgm(voice_total, Path(bgm_path).resolve(), mixed_audio, duck_ratio=bgm_volume)
        tmp_video = tmp_dir / 'video_no_audio.mp4'
        run([FFMPEG, '-y', '-i', str(final_mp4), '-i', str(mixed_audio),
             '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-map', '0:v:0', '-map', '1:a:0',
             '-shortest', str(tmp_video)], silent=True)
        shutil.move(str(tmp_video), str(final_mp4))
        print('OK')

    # global SRT
    final_srt = out_dir / f'{manifest_path.stem}.srt'
    make_global_srt(scene_infos, final_srt)

    total_dur = round(sum(s['scene_duration'] for s in scene_infos), 3)
    update_progress('完成')
    print(f'\n完成 — {len(scene_infos)} 个场景, {total_dur}s')
    print(f'  视频 : {final_mp4}')
    print(f'  字幕 : {final_srt}')
    if bgm_path:
        print(f'  BGM  : {bgm_path}')

    # 清理临时文件
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # 清理 WebUI 写入的 card 文本文件
        for f in out_dir.glob('_*_card.txt'):
            try: f.unlink()
            except Exception: pass
        print('  临时文件已清理')
    except Exception:
        pass


if __name__ == '__main__':
    main()
