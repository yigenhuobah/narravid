"""
narravid — 图片 + JSON 文案 → 解说视频，一键自动生成。

用法:
  python video_auto.py manifest.json
  python video_auto.py manifest.json --voice zh-CN-YunyangNeural --speed 1.5
  python video_auto.py manifest.json --bgm music.mp3 --output-dir ./out
  python video_auto.py manifest.json --title-card "魔神任务分析" --no-burn

特性:
  - Edge TTS / 系统 TTS 自动切换
  - TTS 失败自动重试
  - 可选 BGM + 自动闪避
  - 可选自动标题页
  - CLI 参数覆盖 manifest
"""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_W = 1920
DEFAULT_H = 1080
DEFAULT_FPS = 30
DEFAULT_TTS_ENGINE = 'edge'
DEFAULT_SYSTEM_VOICE = 'Microsoft Huihui Desktop'
DEFAULT_EDGE_VOICE = 'zh-CN-XiaoxiaoNeural'
DEFAULT_SPEECH_SPEED = 1.5
MAX_TTS_RETRIES = 2

# ── helpers ──────────────────────────────────────────────────────

def run(cmd, silent=False):
    kwargs = {}
    if silent:
        kwargs['stdout'] = subprocess.DEVNULL
        kwargs['stderr'] = subprocess.DEVNULL
    subprocess.run(cmd, check=True, **kwargs)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)
    ], text=True, encoding='utf-8').strip()
    return float(out)


def srt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def split_sentences(text: str):
    text = text.replace('\r', '').replace('\n', '').strip()
    if not text:
        return []
    chunks, cur = [], ''
    for ch in text:
        cur += ch
        if ch == '。':
            if cur.strip():
                chunks.append(cur.strip())
            cur = ''
    if cur.strip():
        chunks.append(cur.strip())
    return chunks or [text]


def clean_subtitle_text(text: str) -> str:
    return text.strip().rstrip('。！？；!?;，,')


def build_sentence_segments(text: str, narration_duration: float, offset: float = 0.0):
    sentences = split_sentences(text)
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


def subtitle_filter_arg(srt_path: Path) -> str:
    path = str(srt_path.resolve()).replace('\\', '/')
    path = path.replace(':', '\\:').replace("'", r"\'")
    style = (
        'FontName=Microsoft YaHei,FontSize=16,PrimaryColour=&H00FFFFFF,'
        'OutlineColour=&H64000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=30,Alignment=2'
    )
    return f"subtitles='{path}':force_style='{style}'"


def edge_tts_available() -> bool:
    return importlib.util.find_spec('edge_tts') is not None


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
    if not edge_tts_available():
        raise RuntimeError('edge-tts 未安装')
    clean_text = text.replace('\ufffd', '').replace('�', '').strip()
    txt_path = media_path.with_suffix('.txt')
    txt_path.write_text(clean_text, encoding='utf-8')
    cmd = [
        sys.executable, '-m', 'edge_tts',
        '--voice', voice,
        '--file', str(txt_path),
        '--write-media', str(media_path),
    ]
    if rate:
        cmd += [f'--rate={int(rate):+d}%']
    if volume != 100:
        cmd += [f'--volume={int(volume) - 100:+d}%']
    run(cmd, silent=True)


def synthesize_audio_with_retry(text: str, raw_audio_path: Path, engine: str, voice: str, rate: int = 0, volume: int = 100):
    if engine == 'edge':
        for attempt in range(MAX_TTS_RETRIES + 1):
            try:
                synthesize_edge_tts(text, raw_audio_path, voice=voice, rate=rate, volume=volume)
                return 'edge'
            except subprocess.CalledProcessError:
                if attempt < MAX_TTS_RETRIES:
                    print(f'     retry {attempt+1}/{MAX_TTS_RETRIES} ...')
                    time.sleep(3)
                else:
                    print('     edge-tts failed, falling back to system TTS')
                    synthesize_system_tts(text, raw_audio_path.with_suffix('.raw.wav'), voice=DEFAULT_SYSTEM_VOICE, rate=rate, volume=volume)
                    # convert to same format
                    run(['ffmpeg', '-y', '-i', str(raw_audio_path.with_suffix('.raw.wav')),
                         '-ar', '24000', '-ac', '1', str(raw_audio_path)], silent=True)
                    return 'system'
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
    run(['ffmpeg', '-y', '-i', str(raw_audio_path),
         '-af', ','.join(filters),
         '-ar', '24000', '-ac', '1',
         '-t', f'{target_duration:.3f}',
         str(out_path)], silent=True)
    return ffprobe_duration(out_path)


def make_silent_audio(out_path: Path, duration: float):
    run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
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

def generate_title_card(title: str, out_path: Path, width: int, height: int):
    """用 matplotlib 生成标题页"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print('  [warn] matplotlib not available, skipping title card')
        return None

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis('off')
    ax.text(width / 2, height / 2 + 20, title, fontsize=48, fontweight='bold',
            color='white', ha='center', va='center', fontfamily='sans-serif')
    ax.text(width / 2, height / 2 - 50, 'narravid', fontsize=18,
            color='#888888', ha='center', va='center', fontfamily='sans-serif')
    plt.tight_layout(pad=0)
    fig.savefig(out_path, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


# ── BGM mixing ───────────────────────────────────────────────────

def mix_bgm(voice_audio: Path, bgm_path: Path, out_path: Path, duck_ratio: float = 0.25):
    """将 BGM 与配音混音，配音时 BGM 音量降到 duck_ratio"""
    dur = ffprobe_duration(voice_audio)
    run(['ffmpeg', '-y',
         '-i', str(voice_audio),
         '-stream_loop', '-1', '-i', str(bgm_path),
         '-filter_complex',
         f'[1:a]volume=0.15[a1];[0:a][a1]amix=inputs=2:duration=first:dropout_transition=0.5',
         '-t', f'{dur:.3f}', '-ar', '24000', '-ac', '1',
         str(out_path)], silent=True)


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
        ''')
    parser.add_argument('manifest', help='manifest JSON 文件路径')
    parser.add_argument('--voice', help='TTS 音色名称 (如 zh-CN-YunyangNeural)')
    parser.add_argument('--speed', type=float, help='语速倍率 (如 1.3, 1.5)')
    parser.add_argument('--output-dir', help='输出目录 (覆盖 manifest 中的 output_dir)')
    parser.add_argument('--bgm', help='背景音乐文件路径 (mp3/wav)')
    parser.add_argument('--title-card', help='自动生成标题页 (输入标题文字)')
    parser.add_argument('--no-burn', action='store_true', help='不烧录字幕到视频')
    parser.add_argument('--engine', choices=['edge', 'system'], help='TTS 引擎: edge 或 system')

    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    project_root = manifest_path.parent

    manifest = load_manifest(manifest_path)
    title = manifest.get('title', manifest_path.stem)
    width = int(manifest.get('width', DEFAULT_W))
    height = int(manifest.get('height', DEFAULT_H))
    fps = int(manifest.get('fps', DEFAULT_FPS))
    tts_engine = args.engine or ('edge' if edge_tts_available() else 'system')
    voice = args.voice or (DEFAULT_EDGE_VOICE if tts_engine == 'edge' else DEFAULT_SYSTEM_VOICE)
    rate = int(manifest.get('rate', 0))
    volume = int(manifest.get('volume', 100))
    speech_speed = args.speed or float(manifest.get('speech_speed', DEFAULT_SPEECH_SPEED))
    pad_sec = float(manifest.get('scene_tail_silence_sec', 0.16))
    burn_subtitles = not args.no_burn and bool(manifest.get('burn_subtitles', True))
    bgm_path = args.bgm
    title_card_text = args.title_card

    out_dir = Path(args.output_dir) if args.output_dir else Path(manifest.get('output_dir', project_root / 'rendered' / manifest_path.stem))
    if not out_dir.is_absolute():
        if args.output_dir:
            out_dir = Path.cwd() / out_dir  # CLI arg relative to CWD
        else:
            out_dir = (project_root / out_dir).resolve()  # manifest relative to manifest dir
    out_dir = out_dir.resolve()
    tmp_dir = out_dir / '_tmp'
    scene_dir = out_dir / 'scenes'
    audio_dir = out_dir / 'audio'
    for d in [out_dir, tmp_dir, scene_dir, audio_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # title card
    title_card_path = None
    if title_card_text:
        title_card_path = tmp_dir / 'title_card.png'
        print('[0] Title card: ' + title_card_text)
        generate_title_card(title_card_text, title_card_path, width, height)

    scene_infos = []
    total_scenes = len(manifest['scenes']) + (1 if title_card_path else 0)
    idx = 0

    if title_card_path:
        idx += 1
        wav = audio_dir / '000.wav'
        srt = tmp_dir / '000.srt'
        mp4 = scene_dir / '000.mp4'
        make_silent_audio(wav, 3.0)
        make_scene_srt([], srt)
        run(['ffmpeg', '-y', '-loop', '1', '-i', str(title_card_path), '-i', str(wav),
             '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black',
             '-r', str(fps), '-t', '3.0', '-shortest',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
             str(mp4)], silent=True)
        scene_infos.append({
            'idx': 0, 'image': str(title_card_path),
            'text': '', 'narration_duration': 0, 'hold_sec': 0,
            'scene_duration': 3.0, 'mp4': str(mp4), 'audio': str(wav),
        })
        print(f'  Title card OK ({total_scenes} scenes total)')

    for sidx, scene in enumerate(manifest['scenes'], 1):
        idx += 1
        text = str(scene.get('text', '')).strip()
        image = Path(scene['image'])
        if not image.is_absolute():
            image = (project_root / image).resolve()
        if not image.exists():
            raise FileNotFoundError(f'scene {sidx} 图片不存在: {image}')

        hold_sec = float(scene.get('hold_sec', 0.0))
        raw_audio = tmp_dir / (f'{idx:03d}.raw.mp3' if tts_engine == 'edge' else f'{idx:03d}.raw.wav')
        wav = audio_dir / f'{idx:03d}.wav'
        srt = tmp_dir / f'{idx:03d}.srt'
        mp4 = scene_dir / f'{idx:03d}.mp4'

        if text:
            print(f'[{idx}/{total_scenes}] TTS ... ', end='', flush=True)
            used_engine = synthesize_audio_with_retry(text, raw_audio, tts_engine, voice, rate, volume)
            narration_duration = process_audio(raw_audio, wav, speech_speed, pad_sec)
            print(f'OK ({narration_duration:.1f}s, {used_engine})')
        else:
            narration_duration = 0.0
            print(f'[{idx}/{total_scenes}] Hold ... ', end='', flush=True)
            make_silent_audio(wav, hold_sec or 2.0)
            print('OK')

        scene_duration = narration_duration + hold_sec if narration_duration > 0 else (hold_sec or ffprobe_duration(wav))
        segments = build_sentence_segments(text, narration_duration, 0.0) if text else []
        make_scene_srt(segments, srt)

        vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
        if burn_subtitles and segments:
            vf += ',' + subtitle_filter_arg(srt)

        print(f'[{idx}/{total_scenes}] Render ... ', end='', flush=True)
        run(['ffmpeg', '-y', '-loop', '1', '-i', str(image), '-i', str(wav),
             '-vf', vf, '-r', str(fps), '-t', f'{scene_duration:.3f}', '-shortest',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
             str(mp4)], silent=True)
        print('OK')

        scene_infos.append({
            'idx': idx, 'image': str(image), 'text': text,
            'narration_duration': narration_duration, 'hold_sec': hold_sec,
            'scene_duration': scene_duration, 'mp4': str(mp4), 'audio': str(wav),
        })

    # concat
    print(f'\nConcat {len(scene_infos)} scenes ... ', end='', flush=True)
    concat_txt = tmp_dir / 'concat.txt'
    lines = []
    for s in scene_infos:
        p = str(Path(s['mp4']).resolve()).replace("'", r"'\\''")
        lines.append(f"file '{p}'")
    concat_txt.write_text('\n'.join(lines), encoding='utf-8')

    final_mp4 = out_dir / f'{manifest_path.stem}.mp4'
    run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_txt),
         '-c', 'copy', str(final_mp4)], silent=True)
    print('OK')

    # BGM mixing
    if bgm_path and Path(bgm_path).exists():
        print('Mix BGM ... ', end='', flush=True)
        voice_total = audio_dir / '_narration_full.wav'
        # extract audio from final video
        run(['ffmpeg', '-y', '-i', str(final_mp4), '-vn', '-ar', '24000', '-ac', '1',
             str(voice_total)], silent=True)
        mixed_audio = tmp_dir / 'mixed_audio.wav'
        mix_bgm(voice_total, Path(bgm_path).resolve(), mixed_audio)
        tmp_video = tmp_dir / 'video_no_audio.mp4'
        run(['ffmpeg', '-y', '-i', str(final_mp4), '-i', str(mixed_audio),
             '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-map', '0:v:0', '-map', '1:a:0',
             '-shortest', str(tmp_video)], silent=True)
        shutil.move(str(tmp_video), str(final_mp4))
        print('OK')

    # global SRT
    final_srt = out_dir / f'{manifest_path.stem}.srt'
    make_global_srt(scene_infos, final_srt)

    total_dur = round(sum(s['scene_duration'] for s in scene_infos), 3)
    print(f'\n完成 — {len(scene_infos)} 个场景, {total_dur}s')
    print(f'  视频 : {final_mp4}')
    print(f'  字幕 : {final_srt}')
    if bgm_path:
        print(f'  BGM  : {bgm_path}')


if __name__ == '__main__':
    main()
