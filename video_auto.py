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
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from _console_io import configure_console_io

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
MAX_DURATION_SECONDS = 3600.0

# ── helpers ──────────────────────────────────────────────────────

# Active ffmpeg/ffprobe children — cancelled jobs kill these promptly.
_ACTIVE_PROCS = []
_ACTIVE_PROCS_LOCK = threading.Lock()


def _kill_process(proc: subprocess.Popen):
    """Best-effort kill of a child process (and its tree).

    Windows: taskkill /T. POSIX: kill process group when started with
    start_new_session=True in run().
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == 'nt':
            # /T kills the whole tree (ffmpeg often spawns helpers)
            result = subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10,
            )
            if result.returncode == 0 or proc.poll() is not None:
                return
            try:
                proc.terminate()
                proc.wait(timeout=2)
                return
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            pid = proc.pid
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=2)
                return
            except Exception:
                pass
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except Exception:
                    pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def kill_active_subprocesses():
    """Kill any in-flight run() children (used by CancelToken)."""
    with _ACTIVE_PROCS_LOCK:
        procs = list(_ACTIVE_PROCS)
    for p in procs:
        _kill_process(p)


def run(cmd, silent=False):
    """Run a subprocess; honor CancelToken by killing mid-flight ffmpeg."""
    _check_cancel()
    kwargs = {}
    if silent:
        kwargs['stdout'] = subprocess.DEVNULL
        kwargs['stderr'] = subprocess.DEVNULL
    # POSIX: new session so cancel can killpg the whole ffmpeg tree
    if os.name != 'nt':
        kwargs['start_new_session'] = True
    # Avoid shell; inherit no extra handles beyond stdio redirects.
    proc = subprocess.Popen(cmd, **kwargs)
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_PROCS.append(proc)
    try:
        deadline = time.monotonic() + 600
        while True:
            try:
                ret = proc.wait(timeout=0.4)
                break
            except subprocess.TimeoutExpired:
                if CancelToken.is_cancelled():
                    _kill_process(proc)
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    _check_cancel()  # raise user/abort error
                    raise RuntimeError('渲染已中止')
                if time.monotonic() >= deadline:
                    _kill_process(proc)
                    raise subprocess.TimeoutExpired(cmd, 600)
        if ret != 0:
            raise subprocess.CalledProcessError(ret, cmd)
    finally:
        with _ACTIVE_PROCS_LOCK:
            try:
                _ACTIVE_PROCS.remove(proc)
            except ValueError:
                pass


def run_capture_text(cmd, timeout=60) -> str:
    """Run a text-output subprocess with timeout and cooperative cancellation."""
    _check_cancel()
    kwargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.DEVNULL,
        'text': True,
        'encoding': 'utf-8',
        'errors': 'replace',
    }
    if os.name != 'nt':
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_PROCS.append(proc)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                out, _ = proc.communicate(timeout=0.4)
                break
            except subprocess.TimeoutExpired:
                if CancelToken.is_cancelled():
                    _kill_process(proc)
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    _check_cancel()
                    raise RuntimeError('渲染已中止')
                if time.monotonic() >= deadline:
                    _kill_process(proc)
                    raise subprocess.TimeoutExpired(cmd, timeout)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
        return out or ''
    finally:
        with _ACTIVE_PROCS_LOCK:
            try:
                _ACTIVE_PROCS.remove(proc)
            except ValueError:
                pass


def ffprobe_duration(path: Path) -> float:
    """Probe media duration; registered so CancelToken can kill a hung probe."""
    cmd = [
        FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(path),
    ]
    return float(run_capture_text(cmd, timeout=60).strip())


def atempo_filter_chain(speed: float) -> list:
    """Build one or more atempo filters. ffmpeg allows only 0.5–2.0 per filter."""
    s = float(speed)
    if not math.isfinite(s) or s <= 0:
        raise ValueError('speech speed must be a finite positive number')
    if abs(s - 1.0) <= 1e-6:
        return []
    filters = []
    # Speed up: peel off 2.0 factors
    while s > 2.0 + 1e-9:
        filters.append('atempo=2.000')
        s /= 2.0
    # Slow down: peel off 0.5 factors
    while s < 0.5 - 1e-9:
        filters.append('atempo=0.500')
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        filters.append(f'atempo={s:.3f}')
    return filters


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
            # 只保留有非标点内容的 chunk
            stripped = cur.strip()
            if stripped and any(c not in sentence_enders and c not in '，、, ' for c in stripped):
                chunks.append(stripped)
            cur = ''
    if cur.strip():
        stripped = cur.strip()
        if any(c not in sentence_enders and c not in '，、, ' for c in stripped):
            chunks.append(stripped)
    # 对每个 chunk 检查是否需要逗号智能断句
    if smart_comma:
        result = []
        for chunk in chunks:
            # 按逗号/顿号拆分
            comma_parts = []
            buf = ''
            for ch in chunk:
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
                result.extend(merged)
            else:
                result.append(chunk)
        return result
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
    for i, (sentence, weight) in enumerate(zip(sentences, weights, strict=True), 1):
        seg_dur = narration_duration * weight / total_weight
        end = offset + narration_duration if i == len(sentences) else cur + seg_dur
        segments.append({
            'start': cur,
            'end': end,
            'subtitle': clean_subtitle_text(sentence),
        })
        cur = end
    return segments


def default_subtitle_style() -> str:
    """ASS force_style 默认串；FontName 随平台可用中文字体变化。"""
    global _SUBTITLE_STYLE_CACHE
    if _SUBTITLE_STYLE_CACHE is not None:
        return _SUBTITLE_STYLE_CACHE
    font = default_subtitle_font_name()
    _SUBTITLE_STYLE_CACHE = (
        f'FontName={font},FontSize=16,PrimaryColour=&H00FFFFFF,'
        'OutlineColour=&H64000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=30,Alignment=2'
    )
    return _SUBTITLE_STYLE_CACHE


def sanitize_subtitle_style(style: str | None) -> str:
    """Strip characters that break ffmpeg force_style='...' quoting / filter graph."""
    if not style:
        return default_subtitle_style()
    # force_style is single-quoted; ban quote/backslash and filter separators
    cleaned = re.sub(r"[\\'\"\[\]:;|]", '', str(style))
    cleaned = cleaned.replace('\n', ' ').replace('\r', ' ').strip()
    return cleaned or default_subtitle_style()


def subtitle_filter_arg(srt_path: Path, style_override: str = None) -> str:
    # libavfilter uses single quotes for option values. A literal apostrophe
    # must close the quote, be escaped at all filter-parser levels, then reopen.
    path = str(srt_path.resolve()).replace('\\', '/')
    for ch in [':', '[', ']']:
        path = path.replace(ch, '\\' + ch)
    apostrophe_escape = "'" + ("\\" * 3) + "''"
    path = path.replace("'", apostrophe_escape)
    style = sanitize_subtitle_style(style_override)
    return f"subtitles=filename='{path}':force_style='{style}'"


def edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def system_tts_available() -> bool:
    """Windows PowerShell System.Speech only."""
    return os.name == 'nt'


def resolve_tts_engine(requested: str | None) -> str:
    """Pick a usable TTS engine; never default to system off Windows."""
    req = (requested or '').strip().lower() or None
    if req == 'system':
        if not system_tts_available():
            raise RuntimeError(
                '系统 TTS 仅支持 Windows（PowerShell System.Speech）。'
                '请改用 edge，或在 Windows 上运行。'
            )
        return 'system'
    if req == 'edge':
        if not edge_tts_available():
            if system_tts_available():
                print('  [warn] edge-tts 不可用，改用系统 TTS')
                return 'system'
            raise RuntimeError('edge-tts 未安装且当前平台无系统 TTS 可用')
        return 'edge'
    # auto
    if edge_tts_available():
        return 'edge'
    if system_tts_available():
        return 'system'
    raise RuntimeError(
        '无可用 TTS：请 pip install edge-tts（Linux/macOS/Docker 必需），'
        '或在 Windows 上使用系统语音。'
    )


# ── manifest ─────────────────────────────────────────────────────

class SceneDict(TypedDict):
    """Normalized scene entry used by the pipeline."""
    image: str
    text: NotRequired[str]
    hold_sec: NotRequired[float]


class ManifestDict(TypedDict, total=False):
    """Subset of manifest fields; scenes is required at runtime via normalize."""
    title: str
    width: int
    height: int
    fps: int
    tts_engine: str
    voice: str
    rate: int
    volume: int
    speech_speed: float
    scene_tail_silence_sec: float
    burn_subtitles: Any
    workers: int
    bgm_volume: float
    subtitle_style: str
    scenes: list


def scene_hold_sec(scene: dict) -> float:
    """UI may historically send hold; pipeline wire format is hold_sec.

    Explicit hold_sec wins when present and numeric (including 0). Empty/invalid
    hold_sec falls back to legacy hold. Non-finite values are rejected as 0.
    """
    if not isinstance(scene, dict):
        return 0.0

    def _parse(raw):
        if raw is None or raw is False:
            return None
        if isinstance(raw, str) and raw.strip() == '':
            return None
        try:
            n = float(raw)
        except (OverflowError, TypeError, ValueError):
            return None
        if n != n or n in (float('inf'), float('-inf')):  # NaN/inf
            return None
        return max(0.0, min(n, MAX_DURATION_SECONDS))  # clamp to 1h

    if 'hold_sec' in scene:
        parsed = _parse(scene.get('hold_sec'))
        if parsed is not None:
            return parsed
        # present but empty/invalid → try legacy hold
    if 'hold' in scene:
        parsed = _parse(scene.get('hold'))
        if parsed is not None:
            return parsed
    return 0.0


def normalize_scene(scene: dict) -> dict:
    """Return a shallow-copied scene with hold_sec set and legacy hold removed."""
    if not isinstance(scene, dict):
        raise ValueError('scene 必须是对象')
    out = dict(scene)
    img = out.get('image')
    if img is None or str(img).strip() == '':
        raise ValueError('scene 缺少 image')
    out['image'] = str(img)
    out['hold_sec'] = scene_hold_sec(out)
    out.pop('hold', None)
    if out.get('text') is not None:
        out['text'] = str(out['text'])
    else:
        out['text'] = ''
    return out


def normalize_manifest(data: dict) -> dict:
    """Validate/normalize manifest dict (in place-friendly copy)."""
    if not isinstance(data, dict):
        raise ValueError('manifest 必须是对象')
    out = dict(data)
    scenes = out.get('scenes')
    if not isinstance(scenes, list) or not scenes:
        raise ValueError('manifest 缺少 scenes')
    out['scenes'] = [normalize_scene(s) for s in scenes]
    return out


def _reject_json_constant(value: str):
    raise ValueError(f'non-finite JSON number: {value}')


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f'non-finite JSON number: {value}')
    return parsed


def load_manifest(path: Path) -> dict:
    data = json.loads(
        path.read_text(encoding='utf-8-sig'),
        parse_constant=_reject_json_constant,
        parse_float=_parse_finite_json_float,
    )
    return normalize_manifest(data)

# ── TTS ──────────────────────────────────────────────────────────

def synthesize_system_tts(text: str, wav_path: Path, voice: str, rate: int = 0, volume: int = 100):
    if not system_tts_available():
        raise RuntimeError('系统 TTS 仅支持 Windows（PowerShell System.Speech）')
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
    import asyncio

    import edge_tts
    clean_text = text.replace('\ufffd', '').replace('�', '').strip()
    if not clean_text:
        raise RuntimeError('edge-tts: 文本为空')
    rate_str = f'{int(rate):+d}%' if rate else '+0%'
    volume_str = f'{int(volume) - 100:+d}%' if volume != 100 else '+0%'
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
        last_err = None
        for attempt in range(MAX_TTS_RETRIES + 1):
            _check_cancel()
            try:
                synthesize_edge_tts(text, raw_audio_path, voice=voice, rate=rate, volume=volume)
                return 'edge'
            except Exception as e:
                last_err = e
                _check_cancel()
                if attempt < MAX_TTS_RETRIES:
                    # 分段 sleep，便于取消及时生效
                    for _ in range(6):
                        _check_cancel()
                        time.sleep(0.5)
                else:
                    # system_tts_available / synthesize_system_tts are the only gates
                    if not system_tts_available():
                        raise RuntimeError(
                            f'edge-tts 失败（已重试 {MAX_TTS_RETRIES} 次）: {last_err}。'
                            f'当前平台无系统 TTS 回退（仅 Windows 支持）。'
                            f'请检查网络/edge-tts，或稍后重试。'
                        ) from last_err
                    try:
                        _check_cancel()
                        synthesize_system_tts(
                            text, raw_audio_path.with_suffix('.raw.wav'),
                            voice=DEFAULT_SYSTEM_VOICE, rate=rate, volume=volume,
                        )
                        run([FFMPEG, '-y', '-i', str(raw_audio_path.with_suffix('.raw.wav')),
                             '-ar', '24000', '-ac', '1', str(raw_audio_path)], silent=True)
                        print('  [warn] Edge TTS 失败，已降级为系统 TTS（音色可能变化）')
                        return 'system'
                    except Exception as fallback_err:
                        raise RuntimeError(
                            f'edge-tts 和 system TTS 均失败: edge={last_err}; system={fallback_err}'
                        ) from fallback_err
    elif engine == 'system':
        _check_cancel()
        # platform guard lives in synthesize_system_tts
        synthesize_system_tts(text, raw_audio_path, voice=voice, rate=rate, volume=volume)
        return 'system'
    else:
        raise ValueError(f'不支持的 tts_engine: {engine}')


# ── audio processing ────────────────────────────────────────────

def process_audio(raw_audio_path: Path, out_path: Path, speed: float, pad_sec: float):
    """Normalize scene audio to 24k mono WAV (or same-container copy only when safe)."""
    source_duration = ffprobe_duration(raw_audio_path)
    filters = atempo_filter_chain(speed)
    if pad_sec > 0:
        filters.append(f'apad=pad_dur={pad_sec:.3f}')
    src_suf = Path(raw_audio_path).suffix.lower()
    dst_suf = Path(out_path).suffix.lower()
    # Same container + no filters: byte-copy is safe. Never copy MP3/etc onto .wav.
    if not filters and src_suf == dst_suf:
        shutil.copyfile(raw_audio_path, out_path)
        return source_duration
    # Always re-encode when filters apply or container would mismatch (Edge TTS → .wav)
    af = ','.join(filters) if filters else 'anull'
    run([FFMPEG, '-y', '-i', str(raw_audio_path),
         '-af', af,
         '-ar', '24000', '-ac', '1',
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


def make_global_srt(scene_infos, out_path: Path, smart_comma: bool = True):
    rows, idx, offset = [], 1, 0.0
    for scene in scene_infos:
        for seg in build_sentence_segments(
            scene['text'], scene['narration_duration'], offset, smart_comma=smart_comma
        ):
            rows.append(f"{idx}\n{srt_ts(seg['start'])} --> {srt_ts(seg['end'])}\n{seg['subtitle']}\n")
            idx += 1
        offset += scene['scene_duration']
    out_path.write_text('\n'.join(rows), encoding='utf-8')


# ── title card ───────────────────────────────────────────────────

def _font_search_roots():
    """Bundled / repo fonts directories (PyInstaller + source), unique paths."""
    roots = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        roots.append(Path(meipass) / 'fonts')
    roots.append(Path(__file__).resolve().parent / 'fonts')
    if getattr(sys, 'frozen', False):
        roots.append(Path(sys.executable).resolve().parent / 'fonts')
    # preserve order, drop duplicates (onefile often overlaps roots)
    uniq = []
    seen = set()
    for r in roots:
        try:
            key = str(r.resolve())
        except Exception:
            key = str(r)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


_BUNDLED_FONT_KEYWORDS = ('noto', 'sourcehan', 'msyh', 'simhei', 'wqy', 'pingfang')
_FONT_NAME_RULES = (
    (('msyh', 'yahei'), 'Microsoft YaHei'),
    (('simhei',), 'SimHei'),
    (('simsun',), 'SimSun'),
    (('pingfang',), 'PingFang SC'),
    (('wqy-microhei', 'microhei'), 'WenQuanYi Micro Hei'),
    (('wqy',), 'WenQuanYi Zen Hei'),
    (('noto',), 'Noto Sans CJK SC'),
    (('sourcehan', 'source-han'), 'Source Han Sans SC'),
)

# Process-local caches (font set is stable for a job lifetime)
_ZH_FONT_PATH_CACHE = None  # None=unset, False=missing, str=path
_SUBTITLE_FONT_NAME_CACHE = None
_SUBTITLE_STYLE_CACHE = None


def _iter_bundled_font_files():
    """Yield CJK-ish font files under fonts/ roots (deduped, preferred names first)."""
    preferred = (
        'NotoSansSC-Regular.otf', 'NotoSansSC-Regular.ttf',
        'NotoSansCJKsc-Regular.otf', 'NotoSansCJK-Regular.ttc',
        'SourceHanSansSC-Regular.otf', 'SourceHanSansCN-Regular.otf',
        'wqy-microhei.ttc', 'msyh.ttc', 'simhei.ttf',
    )
    seen = set()
    for root in _font_search_roots():
        if not root.is_dir():
            continue
        # fast path: known filenames first (stop after first hit for _find_zh_font consumers)
        for name in preferred:
            p = root / name
            if not p.is_file():
                continue
            try:
                key = str(p.resolve())
            except Exception:
                key = str(p)
            if key in seen:
                continue
            seen.add(key)
            yield Path(key)
        # slow path: other CJK-ish names in the directory
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file() or p.suffix.lower() not in ('.ttf', '.otf', '.ttc'):
                continue
            if not any(k in p.name.lower() for k in _BUNDLED_FONT_KEYWORDS):
                continue
            try:
                key = str(p.resolve())
            except Exception:
                key = str(p)
            if key in seen:
                continue
            seen.add(key)
            yield Path(key)


def _system_zh_font_candidates():
    """Platform font file candidates (first existing wins)."""
    if os.name == 'nt':
        return [
            'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/msyhl.ttc',
            'C:/Windows/Fonts/simhei.ttf',
            'C:/Windows/Fonts/simsun.ttc',
        ]
    linux = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf',
        '/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf',
        '/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf',
        '/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/arphic/uming.ttc',
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    ]
    mac = [
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/Supplemental/Songti.ttc',
    ]
    return (mac + linux) if sys.platform == 'darwin' else (linux + mac)


def _find_zh_font():
    """查找可用的中文字体路径：环境变量 → 打包 fonts/ → 系统路径。"""
    global _ZH_FONT_PATH_CACHE
    if _ZH_FONT_PATH_CACHE is not None:
        return _ZH_FONT_PATH_CACHE or None
    found = None
    env = (os.environ.get('NARRAVID_FONT') or '').strip()
    if env:
        p = Path(env)
        if p.is_file():
            found = str(p.resolve())
    if not found:
        for p in _iter_bundled_font_files():
            found = str(p.resolve())
            break
    if not found:
        for f in _system_zh_font_candidates():
            if Path(f).exists():
                found = f
                break
    _ZH_FONT_PATH_CACHE = found if found else False
    return found


def clear_font_cache_for_tests():
    """测试用：清空字体探测缓存。"""
    global _ZH_FONT_PATH_CACHE, _SUBTITLE_FONT_NAME_CACHE, _SUBTITLE_STYLE_CACHE
    _ZH_FONT_PATH_CACHE = None
    _SUBTITLE_FONT_NAME_CACHE = None
    _SUBTITLE_STYLE_CACHE = None


def _font_name_from_path(font_path: str | None) -> str | None:
    if not font_path:
        return None
    name = Path(font_path).name.lower()
    for keys, family in _FONT_NAME_RULES:
        if any(k in name for k in keys):
            return family
    # ASS FontName is best-effort; avoid pulling matplotlib just for a label
    return Path(font_path).stem


def default_subtitle_font_name() -> str:
    """ASS FontName for burn-in when user does not override style."""
    global _SUBTITLE_FONT_NAME_CACHE
    if _SUBTITLE_FONT_NAME_CACHE is not None:
        return _SUBTITLE_FONT_NAME_CACHE
    path = _find_zh_font()
    name = _font_name_from_path(path)
    if not name:
        if os.name == 'nt':
            name = 'Microsoft YaHei'
        elif sys.platform == 'darwin':
            name = 'PingFang SC'
        else:
            name = 'Noto Sans CJK SC'
    _SUBTITLE_FONT_NAME_CACHE = name
    return name


def generate_title_card(title: str, out_path: Path, width: int, height: int, bg_color: str = '#1a1a2e'):
    """用 matplotlib 生成标题页"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.font_manager as fm
        import matplotlib.pyplot as plt
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
        print('  [warn] 未找到中文字体，标题页可能显示方块；可设置 NARRAVID_FONT 或安装 Noto CJK / 将字体放入 fonts/')

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

def mix_bgm(voice_audio: Path, bgm_path: Path, out_path: Path, duck_ratio: float = 0.25) -> str:
    """将 BGM 与配音混音，使用侧链压缩实现人声闪避效果。

    duck_ratio 作为 BGM 压缩后的最低音量比例（如 0.25 = 压到 25%）。
    人声出现时 BGM 被侧链压缩，人声停止时 BGM 平滑恢复。
    失败则降级为固定音量 amix。

    Returns mode: 'sidechain' | 'fixed' | 'none'.
    """
    dur = ffprobe_duration(voice_audio)
    # threshold 根据 duck_ratio 反推：ratio 越小（压得越低），threshold 越灵敏
    threshold = max(0.02, duck_ratio * 0.3)
    # 压缩比：duck_ratio=0.25 → ratio≈4, duck_ratio=0.1 → ratio≈10
    ratio = max(2.0, 1.0 / max(duck_ratio, 0.05))
    try:
        run([FFMPEG, '-y',
             '-i', str(voice_audio),
             '-stream_loop', '-1', '-i', str(bgm_path),
             '-filter_complex',
             # 侧链压缩：人声[0:a]作为sidechain控制BGM[1:a]的压缩
             # makeup=1.0 不放大，静音时 BGM 保持原始音量；人声时压缩到 1/ratio
             # 再用 volume 滤镜将 BGM 整体限制在 duck_ratio 水平，避免静音段爆音
             f'[1:a][0:a]sidechaincompress=threshold={threshold:.3f}:ratio={ratio:.1f}:attack=200:release=800:makeup=1.0[ducked];'
             f'[ducked]volume={duck_ratio:.2f}[bgm_low];'
             f'[0:a][bgm_low]amix=inputs=2:duration=first:dropout_transition=0.5',
             '-t', f'{dur:.3f}', '-ar', '24000', '-ac', '1',
             str(out_path)], silent=True)
        return 'sidechain'
    except Exception as e:
        print(f'  侧链压缩失败({e})，降级为固定音量混音')
        try:
            run([FFMPEG, '-y',
                 '-i', str(voice_audio),
                 '-stream_loop', '-1', '-i', str(bgm_path),
                 '-filter_complex',
                 f'[1:a]volume={duck_ratio:.2f}[a1];[0:a][a1]amix=inputs=2:duration=first:dropout_transition=0.5',
                 '-t', f'{dur:.3f}', '-ar', '24000', '-ac', '1',
                 str(out_path)], silent=True)
            return 'fixed'
        except Exception as e2:
            print(f'  BGM 混音完全失败({e2})，使用原音频')
            shutil.copy2(str(voice_audio), str(out_path))
            return 'none'


# ── 并行场景处理 ────────────────────────────────────────────────

class CancelToken:
    """进程内取消/中止令牌（WebUI 与 fail-fast 共用；同一时刻仅一个 main）。
    非 per-job 令牌：并发安全依赖 WebUI RENDER_LOCK 串行 main()。

    - set_cancelled(): 用户取消（文案含「用户取消」）
    - set_aborted(): 内部中止（场景失败 fail-fast 等，不伪装成用户取消）
    """
    _cancelled = False
    _user = False
    _lock = threading.Lock()

    @classmethod
    def set_cancelled(cls):
        """User-initiated cancel."""
        with cls._lock:
            cls._cancelled = True
            cls._user = True
        kill_active_subprocesses()

    @classmethod
    def set_aborted(cls):
        """Internal abort (e.g. fail-fast). Does not mark as user cancel."""
        with cls._lock:
            cls._cancelled = True
            # keep _user True if user already cancelled
            if not cls._user:
                cls._user = False
        kill_active_subprocesses()

    @classmethod
    def is_cancelled(cls) -> bool:
        with cls._lock:
            return cls._cancelled

    @classmethod
    def is_user_cancel(cls) -> bool:
        with cls._lock:
            return cls._cancelled and cls._user

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._cancelled = False
            cls._user = False


def _check_cancel():
    """在关键步骤检查是否已取消/中止，如是则抛出异常"""
    if CancelToken.is_cancelled():
        if CancelToken.is_user_cancel():
            raise RuntimeError('渲染已被用户取消')
        raise RuntimeError('渲染已中止')


def parse_boolish(val, default=True):
    """Manifest/CLI 友好的布尔解析。"""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ('0', 'false', 'no', 'off', 'n', 'disabled', 'null', 'none', ''):
            return False
        if s in ('1', 'true', 'yes', 'on', 'y', 'enabled'):
            return True
        # 未知字符串：保守沿用 default，避免 typo 静默当 True
        return default
    return bool(val)


def resolve_positive_duration(val, fallback: float, name: str = 'duration') -> float:
    """Resolve a finite 1..3600 second duration, falling back when invalid."""
    try:
        fallback_value = float(fallback)
    except (OverflowError, TypeError, ValueError):
        fallback_value = 1.0
    if not math.isfinite(fallback_value):
        fallback_value = 1.0
    fallback_value = max(1.0, min(fallback_value, MAX_DURATION_SECONDS))
    if val is None:
        return fallback_value
    try:
        parsed = float(val)
    except (OverflowError, TypeError, ValueError):
        print(f'  [warn] 字段 {name} 值无效 ({val!r})，使用默认值 {fallback_value}')
        return fallback_value
    if not math.isfinite(parsed) or parsed <= 0:
        return fallback_value
    return max(1.0, min(parsed, MAX_DURATION_SECONDS))


def is_cancel_error(err) -> bool:
    """True only for user-cancel errors (not internal abort / plain failures)."""
    if not isinstance(err, BaseException):
        return False
    msg = str(err)
    return '用户取消' in msg or msg.strip() == '渲染已被用户取消'


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
        raise FileNotFoundError(f'scene {idx} 媒体文件不存在: {image}')

    # 判断是图片还是视频
    VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.flv'}
    is_video = image.suffix.lower() in VIDEO_EXTS

    hold_sec = scene_hold_sec(scene)
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
    # hold_sec：在音频尾部补静音，使音轨与 scene_duration 对齐；渲染不要用 -shortest
    # 复用 process_audio（speed=1）统一采样率/apad，避免第二套 ffmpeg 滤镜分叉
    # pad_sec(scene_tail_silence) 已含在 narration_duration 内；hold 再叠一层尾静音（有意）
    if hold_sec > 0 and narration_duration > 0:
        padded_wav = tmp_dir / f'{idx:03d}.hold.wav'
        actual = process_audio(wav, padded_wav, 1.0, hold_sec)
        wav = padded_wav
        # 以实际 ffprobe 时长为准，避免 apad/采样取整与算术不一致
        if actual and actual > 0:
            scene_duration = actual
    segments = build_sentence_segments(text, narration_duration, 0.0, smart_comma=smart_comma) if text else []
    make_scene_srt(segments, srt)

    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    if burn_subtitles and segments:
        vf += ',' + subtitle_filter_arg(srt, subtitle_style)

    _check_cancel()
    progress.report(idx, 'Render ...')
    if is_video:
        # 视频背景：丢弃视频原始音轨，用 TTS 音频；-t 控制总时长（已含 hold）
        # 先确认有视频流，避免 -map 0:v:0 晦涩失败
        try:
            vprobe = run_capture_text([
                FFPROBE, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(image),
            ], timeout=60).strip()
            if not vprobe:
                raise RuntimeError(f'scene {idx} 媒体无视频流: {image.name}')
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f'scene {idx} 无法探测视频流: {image.name}') from e
        run([FFMPEG, '-y',
             '-stream_loop', '-1', '-i', str(image),
             '-i', str(wav),
             '-map', '0:v:0', '-map', '1:a:0',
             '-vf', vf, '-r', str(fps), '-t', f'{scene_duration:.3f}',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
             str(mp4)], silent=True)
    else:
        # 图片背景：音频已含 hold 静音，用 -t 对齐；勿加 -shortest（会按较短流截断）
        run([FFMPEG, '-y', '-loop', '1', '-i', str(image), '-i', str(wav),
             '-vf', vf, '-r', str(fps), '-t', f'{scene_duration:.3f}',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
             str(mp4)], silent=True)
    progress.complete(idx, 'Render OK')

    return {
        'idx': idx, 'image': str(image), 'text': text,
        'narration_duration': narration_duration, 'hold_sec': hold_sec,
        'scene_duration': scene_duration, 'mp4': str(mp4), 'audio': str(wav),
    }


# ── main ─────────────────────────────────────────────────────────

def main(argv=None):
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
    parser.add_argument('--card-duration', type=float, default=None,
                        help='标题页停留秒数 (默认 3.0)')
    parser.add_argument('--end-card-duration', type=float, default=None,
                        help='封尾页停留秒数 (默认与标题页相同)')
    parser.add_argument('--bgm-volume', type=float, default=None,
                        help='BGM 音量 (0.0~1.0, 配音时 BGM 降到该比例, 默认 0.25)')
    parser.add_argument('--subtitle-style', help='字幕 ASS 样式字符串 (覆盖默认)')
    parser.add_argument('--title-card-bg', help='标题页/封尾页背景色 (如 #1a1a2e, 默认)')
    parser.add_argument('--no-smart-comma', action='store_true', help='禁用逗号智能断句')
    parser.add_argument('--no-burn', action='store_true', help='不烧录字幕到视频')
    parser.add_argument('--engine', choices=['edge', 'system'], help='TTS 引擎: edge 或 system')
    parser.add_argument('--workers', type=int, default=0,
                        help=f'并行处理线程数 (默认 {DEFAULT_WORKERS}, 1=串行)')

    # argv=None → sys.argv[1:]; WebUI 传入显式列表，避免改写进程全局 sys.argv
    args = parser.parse_args(None if argv is None else argv)

    manifest_path = Path(args.manifest).resolve()
    project_root = manifest_path.parent

    manifest = load_manifest(manifest_path)
    def _safe_int(val, default, name):
        try:
            return int(val)
        except (OverflowError, TypeError, ValueError):
            print(f'  [warn] manifest 字段 {name} 值无效 ({val!r})，使用默认值 {default}')
            return default
    def _safe_float(val, default, name):
        try:
            parsed = float(val)
            if not math.isfinite(parsed):
                raise ValueError('non-finite value')
            return parsed
        except (OverflowError, TypeError, ValueError):
            print(f'  [warn] manifest 字段 {name} 值无效 ({val!r})，使用默认值 {default}')
            return default

    width = _safe_int(manifest.get('width', DEFAULT_W), DEFAULT_W, 'width')
    height = _safe_int(manifest.get('height', DEFAULT_H), DEFAULT_H, 'height')
    fps = _safe_int(manifest.get('fps', DEFAULT_FPS), DEFAULT_FPS, 'fps')
    try:
        tts_engine = resolve_tts_engine(args.engine or manifest.get('tts_engine'))
    except RuntimeError as e:
        raise SystemExit(f'错误: {e}') from e
    voice = args.voice or manifest.get('voice') or (DEFAULT_EDGE_VOICE if tts_engine == 'edge' else DEFAULT_SYSTEM_VOICE)
    rate = _safe_int(manifest.get('rate', 0), 0, 'rate')
    volume = _safe_int(manifest.get('volume', 100), 100, 'volume')
    if args.speed is not None:
        speech_speed = float(args.speed)
    else:
        speech_speed = _safe_float(
            manifest.get('speech_speed', DEFAULT_SPEECH_SPEED),
            DEFAULT_SPEECH_SPEED,
            'speech_speed',
        )
    if not math.isfinite(speech_speed):
        print(f'  [warn] invalid speech speed {speech_speed!r}, using {DEFAULT_SPEECH_SPEED}')
        speech_speed = DEFAULT_SPEECH_SPEED
    if speech_speed < 0.5:
        print(f'  [warn] 语速 {speech_speed} 过低，已调整为 0.5')
        speech_speed = 0.5
    elif speech_speed > 3.0:
        print(f'  [warn] 语速 {speech_speed} 过高，已调整为 3.0')
        speech_speed = 3.0
    pad_sec = _safe_float(manifest.get('scene_tail_silence_sec', 0.16), 0.16, 'scene_tail_silence_sec')
    # parse_boolish：避免 manifest 里 "false"/"0" 被 bool() 当成 True
    burn_subtitles = not args.no_burn and parse_boolish(
        manifest.get('burn_subtitles', True), default=True)
    bgm_path = args.bgm
    if args.bgm_volume is not None:
        bgm_volume = max(0.0, min(1.0, args.bgm_volume))
    else:
        bgm_volume = max(0.0, min(1.0, _safe_float(
            manifest.get('bgm_volume', 0.25), 0.25, 'bgm_volume')))
    # 若仅有 manifest.bgm 且未传 --bgm；相对路径相对 manifest 目录（与 scene.image 一致）
    if not bgm_path and manifest.get('bgm'):
        bgm_path = str(manifest.get('bgm'))
    if bgm_path:
        bp = Path(bgm_path)
        if not bp.is_absolute():
            # CLI --bgm 相对 cwd；manifest.bgm 相对 project_root
            if args.bgm:
                bp = (Path.cwd() / bp).resolve()
            else:
                bp = (project_root / bp).resolve()
        else:
            bp = bp.resolve()
        bgm_path = str(bp)
    title_card_text = None
    if args.title_card_file:
        try:
            title_card_text = Path(args.title_card_file).read_text(encoding='utf-8').strip()
        except Exception as e:
            print(f'  [warn] 无法读取标题页文件: {e}')
    if not title_card_text:
        title_card_text = args.title_card or manifest.get('title_card')
    end_card_text = None
    if args.end_card_file:
        try:
            end_card_text = Path(args.end_card_file).read_text(encoding='utf-8').strip()
        except Exception as e:
            print(f'  [warn] 无法读取封尾页文件: {e}')
    if not end_card_text:
        end_card_text = args.end_card or manifest.get('end_card')
    if args.card_duration is not None:
        card_duration = resolve_positive_duration(args.card_duration, 1.0, 'card_duration')
    else:
        card_duration = min(MAX_DURATION_SECONDS, max(1.0, _safe_float(
            manifest.get('card_duration', 3.0), 3.0, 'card_duration')))
    if args.end_card_duration is not None:
        # 0 / 负数：与旧版一致，表示“与标题页时长相同”
        end_card_duration = resolve_positive_duration(args.end_card_duration, card_duration, 'end_card_duration')
    else:
        end_card_duration = resolve_positive_duration(
            manifest.get('end_card_duration', None), card_duration, 'end_card_duration')
    # CLI 优先；否则读 manifest.subtitle_style（WebUI 也会写入 manifest）
    subtitle_style = args.subtitle_style or manifest.get('subtitle_style') or None
    if subtitle_style is not None and not isinstance(subtitle_style, str):
        subtitle_style = None
    if subtitle_style:
        subtitle_style = sanitize_subtitle_style(subtitle_style)
    card_bg = args.title_card_bg or manifest.get('title_card_bg') or '#1a1a2e'
    smart_comma = not args.no_smart_comma
    if 'smart_comma' in manifest and not args.no_smart_comma:
        smart_comma = parse_boolish(manifest.get('smart_comma'), default=True)
    workers = args.workers or _safe_int(manifest.get('workers', DEFAULT_WORKERS), DEFAULT_WORKERS, 'workers')
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

            first_err = None
            user_cancelled = False
            for future in as_completed(future_to_idx):
                sidx = future_to_idx[future]
                try:
                    info = future.result()
                    results[sidx] = info
                except Exception as e:
                    print(f'[ERROR] scene {sidx} 失败: {e}')
                    failed.append(sidx)
                    # 优先保留“真实根因”，不要被兄弟 worker 的中止文案抢成 first_err
                    if is_cancel_error(e):
                        user_cancelled = True
                        if first_err is None:
                            first_err = e
                    else:
                        if first_err is None or is_cancel_error(first_err) or str(first_err) == '渲染已中止':
                            first_err = e
                    # fail-fast：内部中止（非用户取消语义），缩短尾延迟
                    if not CancelToken.is_user_cancel():
                        CancelToken.set_aborted()
                    else:
                        CancelToken.set_cancelled()

        if failed:
            print(f'\n错误: {len(failed)} 个场景失败: {failed}')
            # 任一正文场景失败即中止，避免静默缺镜成片
            # 取消令牌可能已被 fail-fast 置位；重置以免污染同进程后续任务
            was_user = CancelToken.is_user_cancel() or user_cancelled
            try:
                CancelToken.reset()
            except Exception:
                pass
            if was_user or is_cancel_error(first_err):
                raise RuntimeError('渲染已被用户取消') from first_err
            raise RuntimeError(f'{len(failed)} 个场景失败: {failed}') from first_err

        # 按 idx 排序，保证 concat 顺序正确
        for sidx in sorted(results.keys()):
            scene_infos.append(results[sidx])

    else:
        # 串行模式（workers=1 或只有 1 个场景）
        failed = []
        first_err = None
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
                first_err = e
                break  # fail-fast：不再继续后续场景
        if failed:
            print(f'\n错误: {len(failed)} 个场景失败: {failed}')
            if is_cancel_error(first_err) or CancelToken.is_user_cancel():
                try:
                    CancelToken.reset()
                except Exception:
                    pass
                raise RuntimeError('渲染已被用户取消') from first_err
            raise RuntimeError(f'{len(failed)} 个场景失败: {failed}') from first_err

    # ── concat（必须等所有场景完成） ──
    _check_cancel()
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
            print('  End card OK')
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
        bgm_mode = mix_bgm(voice_total, Path(bgm_path).resolve(), mixed_audio, duck_ratio=bgm_volume)
        if bgm_mode != 'sidechain':
            warn = ('BGM 已降级为固定音量混音' if bgm_mode == 'fixed'
                    else 'BGM 混音失败，成片可能无背景音乐')
            print(f'  [warn] {warn}')
            try:
                (out_dir / '_warnings.txt').write_text(warn + '\n', encoding='utf-8')
            except Exception:
                pass
        tmp_video = tmp_dir / 'video_no_audio.mp4'
        # Do not use -shortest: mixed audio slightly shorter than video would
        # truncate hold/tail. Pad audio to video length instead.
        run([FFMPEG, '-y', '-i', str(final_mp4), '-i', str(mixed_audio),
             '-filter_complex', '[1:a]apad[a]',
             '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
             '-map', '0:v:0', '-map', '[a]',
             '-t', str(ffprobe_duration(final_mp4)),
             str(tmp_video)], silent=True)
        shutil.move(str(tmp_video), str(final_mp4))
        print('OK')

    # global SRT（与烧录字幕共用 smart_comma 设置）
    final_srt = out_dir / f'{manifest_path.stem}.srt'
    make_global_srt(scene_infos, final_srt, smart_comma=smart_comma)

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
        # 清理系统 TTS 残留的 ps1/txt
        for f in audio_dir.glob('*.ps1'):
            try: f.unlink()
            except Exception: pass
        for f in audio_dir.glob('*.txt'):
            try: f.unlink()
            except Exception: pass
        for f in audio_dir.glob('*.raw.wav'):
            try: f.unlink()
            except Exception: pass
        print('  临时文件已清理')
    except Exception:
        pass



def run_from_manifest_file(manifest_path, output_dir=None, **opts):
    """Programmatic entry: build argv and call main(argv=...) without touching sys.argv.

    opts keys map to CLI flags (snake_case): voice, speed, bgm, bgm_volume, title_card,
    title_card_file, end_card, end_card_file, card_duration, end_card_duration,
    subtitle_style, title_card_bg, no_smart_comma, no_burn, engine, workers.
    """
    argv = [str(manifest_path)]
    if output_dir is not None:
        argv += ['--output-dir', str(output_dir)]
    flag_map = {
        'voice': '--voice',
        'speed': '--speed',
        'bgm': '--bgm',
        'bgm_volume': '--bgm-volume',
        'title_card': '--title-card',
        'title_card_file': '--title-card-file',
        'end_card': '--end-card',
        'end_card_file': '--end-card-file',
        'card_duration': '--card-duration',
        'end_card_duration': '--end-card-duration',
        'subtitle_style': '--subtitle-style',
        'title_card_bg': '--title-card-bg',
        'engine': '--engine',
        'workers': '--workers',
    }
    for k, flag in flag_map.items():
        if k in opts and opts[k] is not None:
            argv += [flag, str(opts[k])]
    if opts.get('no_smart_comma'):
        argv.append('--no-smart-comma')
    if opts.get('no_burn'):
        argv.append('--no-burn')
    return main(argv)



if __name__ == '__main__':
    configure_console_io()
    main()
