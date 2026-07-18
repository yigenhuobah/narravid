"""Layer 4 — pipeline / ffmpeg smoke (skipped if ffmpeg missing)."""
from __future__ import annotations

import json
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import video_auto
from tests.support import has_ffmpeg, write_tone_wav


def _write_matplotlib_png(path: Path, w: int = 320, h: int = 240):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
    ax.set_facecolor('#224466')
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis('off')
    ax.text(w / 2, h / 2, 'T', color='white', ha='center', va='center', fontsize=40)
    fig.savefig(path, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def _max_audio_amplitude(media_path: Path, wav_path: Path) -> int:
    video_auto.run([
        video_auto.FFMPEG, '-y', '-i', str(media_path),
        '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '24000',
        '-c:a', 'pcm_s16le', str(wav_path),
    ], silent=True)
    with wave.open(str(wav_path), 'rb') as audio:
        frames = audio.readframes(audio.getnframes())
    samples = (abs(sample) for (sample,) in struct.iter_unpack('<h', frames))
    return max(samples, default=0)


def _read_rgb_frame(
    media_path: Path,
    at_sec: float,
    width: int,
    height: int,
    crop: str | None = None,
) -> bytes:
    """Decode one deterministic RGB frame through the real ffmpeg binary."""
    filters = []
    if crop:
        filters.append(crop)
    filters.append(f'scale={width}:{height}:flags=neighbor')
    completed = subprocess.run(
        [
            video_auto.FFMPEG,
            '-v', 'error',
            '-i', str(media_path),
            '-ss', f'{at_sec:.3f}',
            '-frames:v', '1',
            '-vf', ','.join(filters),
            '-f', 'rawvideo',
            '-pix_fmt', 'rgb24',
            'pipe:1',
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode('utf-8', errors='replace')
        raise AssertionError(f'ffmpeg frame extraction failed: {error}')
    expected_size = width * height * 3
    if len(completed.stdout) != expected_size:
        raise AssertionError(
            f'expected {expected_size} RGB bytes, got {len(completed.stdout)}'
        )
    return completed.stdout


def _changed_pixels(first: bytes, second: bytes, minimum_channel_delta: int = 24) -> int:
    """Count pixels whose strongest RGB channel differs by a visible amount."""
    if len(first) != len(second):
        raise AssertionError('RGB frames must have identical dimensions')
    changed = 0
    for offset in range(0, len(first), 3):
        if max(abs(first[offset + channel] - second[offset + channel]) for channel in range(3)) >= minimum_channel_delta:
            changed += 1
    return changed


@unittest.skipUnless(has_ffmpeg(), 'ffmpeg not available')
class TestProcessAudio(unittest.TestCase):
    def test_pad_and_speed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = write_tone_wav(td / 'raw.wav', duration_sec=1.0)
            out = td / 'out.wav'
            dur = video_auto.process_audio(raw, out, speed=1.0, pad_sec=0.25)
            self.assertTrue(out.exists())
            self.assertGreater(dur, 1.1)
            out2 = td / 'out2.wav'
            dur2 = video_auto.process_audio(raw, out2, speed=2.0, pad_sec=0.0)
            self.assertLess(dur2, 0.7)

    def test_silent(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            out = td / 'sil.wav'
            video_auto.make_silent_audio(out, 0.4)
            self.assertTrue(out.exists())
            d = video_auto.ffprobe_duration(out)
            self.assertAlmostEqual(d, 0.4, delta=0.15)


@unittest.skipUnless(has_ffmpeg(), 'ffmpeg not available')
class TestCliPipelineSmoke(unittest.TestCase):
    def test_hold_only_scene_no_tts_text(self):
        """Empty text + hold_sec produces a short video without Edge TTS."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            img = _write_matplotlib_png(td / 's.png')
            man = {
                'title': 'max-smoke',
                'width': 320,
                'height': 240,
                'fps': 10,
                # hold-only empty text: must not require system TTS (Linux CI)
                'tts_engine': 'edge',
                'workers': 1,
                'burn_subtitles': False,
                'scenes': [
                    {'image': img.name, 'text': '', 'hold_sec': 0.4},
                ],
            }
            mp = td / 'manifest.json'
            mp.write_text(json.dumps(man, ensure_ascii=False), encoding='utf-8')
            out_dir = td / 'out'
            argv = [
                'video_auto.py', str(mp),
                '--output-dir', str(out_dir),
                '--engine', 'edge',
                '--workers', '1',
                '--no-burn',
            ]
            video_auto.CancelToken.reset()
            # Guard: empty-text hold path must never call system/edge synthesizers
            with mock.patch('sys.argv', argv), \
                 mock.patch.object(video_auto, 'synthesize_system_tts', side_effect=AssertionError('system TTS should not run')), \
                 mock.patch.object(video_auto, 'synthesize_edge_tts', side_effect=AssertionError('edge TTS should not run for empty text')):
                video_auto.main()
            mp4s = list(out_dir.glob('*.mp4'))
            self.assertTrue(mp4s, 'expected final mp4')
            d = video_auto.ffprobe_duration(mp4s[0])
            self.assertGreater(d, 0.25)
            self.assertLess(d, 3.0)

    def test_hold_pad_via_process_audio_then_probe(self):
        """Second-stage hold pad length is reflected in ffprobe duration."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = write_tone_wav(td / 'n.wav', 0.5)
            mid = td / 'mid.wav'
            narr = video_auto.process_audio(raw, mid, 1.0, 0.1)
            final = td / 'final.wav'
            actual = video_auto.process_audio(mid, final, 1.0, 0.3)
            self.assertGreater(actual, narr + 0.2)

    def test_mocked_edge_narration_burns_quoted_path_before_hold_tail(self):
        """Local tone stands in for Edge output; quoted paths reach real ffmpeg."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td) / "quoted'project"
            td.mkdir()
            image = _write_matplotlib_png(td / 'slide.png')
            manifest = {
                'width': 320,
                'height': 240,
                'fps': 10,
                'tts_engine': 'edge',
                'workers': 1,
                'burn_subtitles': True,
                'speech_speed': 1.0,
                'scene_tail_silence_sec': 0.1,
                'scenes': [{
                    'image': image.name,
                    'text': 'First! Second?',
                    'hold_sec': 0.25,
                }],
            }
            manifest_path = td / 'narrated.json'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            out_dir = td / 'out'
            synth_calls = []

            def fake_synthesize(text, raw_path, engine, voice, rate=0, volume=100):
                synth_calls.append((text, raw_path, engine, voice, rate, volume))
                write_tone_wav(raw_path, duration_sec=0.35)
                return 'edge'

            video_auto.CancelToken.reset()
            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge'):
                with mock.patch.object(
                    video_auto, 'synthesize_audio_with_retry', side_effect=fake_synthesize,
                ):
                    video_auto.main([
                        str(manifest_path),
                        '--output-dir', str(out_dir),
                        '--workers', '1',
                    ])

                    control_manifest = dict(manifest)
                    control_manifest['burn_subtitles'] = False
                    control_manifest_path = td / 'narrated_control.json'
                    control_manifest_path.write_text(json.dumps(control_manifest), encoding='utf-8')
                    control_out_dir = td / 'control-out'
                    video_auto.CancelToken.reset()
                    video_auto.main([
                        str(control_manifest_path),
                        '--output-dir', str(control_out_dir),
                        '--workers', '1',
                        '--no-burn',
                    ])

            self.assertEqual(len(synth_calls), 2)
            self.assertEqual(synth_calls[0][0], 'First! Second?')
            self.assertEqual(synth_calls[0][1].suffix, '.mp3')
            self.assertEqual(synth_calls[0][2], 'edge')
            final_mp4 = out_dir / 'narrated.mp4'
            control_mp4 = control_out_dir / 'narrated_control.mp4'
            burned_subtitle_region = _read_rgb_frame(
                final_mp4,
                at_sec=0.15,
                width=320,
                height=100,
                crop='crop=320:100:0:140',
            )
            clean_subtitle_region = _read_rgb_frame(
                control_mp4,
                at_sec=0.15,
                width=320,
                height=100,
                crop='crop=320:100:0:140',
            )
            self.assertGreater(
                _changed_pixels(burned_subtitle_region, clean_subtitle_region),
                100,
                'burned output should visibly differ from the no-burn control in the subtitle region',
            )
            final_srt = out_dir / 'narrated.srt'
            duration = video_auto.ffprobe_duration(final_mp4)
            self.assertGreater(duration, 0.55)
            self.assertLess(duration, 1.5)
            srt_text = final_srt.read_text(encoding='utf-8')
            self.assertEqual(srt_text.count('-->'), 2)
            last_end = [line for line in srt_text.splitlines() if '-->' in line][-1].split(' --> ')[1]
            hours, minutes, seconds = last_end.replace(',', '.').split(':')
            subtitle_end = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            self.assertGreater(duration - subtitle_end, 0.15)
            self.assertFalse((out_dir / '_tmp').exists())

    def test_two_scene_concat_with_bgm_preserves_full_duration(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            image = _write_matplotlib_png(td / 'slide.png')
            bgm = write_tone_wav(td / 'music.wav', duration_sec=0.2)
            manifest = {
                'width': 320,
                'height': 240,
                'fps': 10,
                'tts_engine': 'edge',
                'workers': 1,
                'burn_subtitles': False,
                'bgm': bgm.name,
                'bgm_volume': 0.2,
                'scenes': [
                    {'image': image.name, 'text': '', 'hold_sec': 0.35},
                    {'image': image.name, 'text': '', 'hold_sec': 0.55},
                ],
            }
            manifest_path = td / 'with_bgm.json'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            out_dir = td / 'out'

            video_auto.CancelToken.reset()
            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge'):
                with mock.patch.object(
                    video_auto,
                    'synthesize_audio_with_retry',
                    side_effect=AssertionError('empty scenes must not use TTS'),
                ):
                    video_auto.main([
                        str(manifest_path),
                        '--output-dir', str(out_dir),
                        '--workers', '1',
                        '--no-burn',
                    ])

            final_mp4 = out_dir / 'with_bgm.mp4'
            duration = video_auto.ffprobe_duration(final_mp4)
            self.assertGreater(duration, 0.75)
            self.assertLess(duration, 2.0)
            self.assertTrue((out_dir / 'with_bgm.srt').is_file())
            self.assertFalse((out_dir / '_tmp').exists())
            amplitude = _max_audio_amplitude(final_mp4, td / 'mixed-pcm.wav')
            self.assertGreater(amplitude, 200)

    def test_video_background_branch_uses_replacement_audio_track(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            image = _write_matplotlib_png(td / 'source.png')
            source_video = td / 'source.mp4'
            video_auto.run([
                video_auto.FFMPEG, '-y',
                '-loop', '1', '-i', str(image),
                '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=24000',
                '-t', '0.3', '-r', '10',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', str(source_video),
            ], silent=True)
            manifest = {
                'width': 320,
                'height': 240,
                'fps': 10,
                'tts_engine': 'edge',
                'workers': 1,
                'burn_subtitles': False,
                'scenes': [{'image': source_video.name, 'text': '', 'hold_sec': 0.55}],
            }
            manifest_path = td / 'video_scene.json'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            out_dir = td / 'out'

            video_auto.CancelToken.reset()
            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge'):
                with mock.patch.object(
                    video_auto,
                    'synthesize_audio_with_retry',
                    side_effect=AssertionError('empty video scene must not use TTS'),
                ):
                    video_auto.main([
                        str(manifest_path),
                        '--output-dir', str(out_dir),
                        '--workers', '1',
                        '--no-burn',
                    ])

            duration = video_auto.ffprobe_duration(out_dir / 'video_scene.mp4')
            self.assertGreater(duration, 0.4)
            self.assertLess(duration, 1.5)
            amplitude = _max_audio_amplitude(out_dir / 'video_scene.mp4', td / 'replacement-pcm.wav')
            self.assertLess(amplitude, 100)

    def test_title_and_end_cards_wrap_content_scene(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            image = _write_matplotlib_png(td / 'content.png')
            manifest = {
                'width': 320,
                'height': 240,
                'fps': 10,
                'tts_engine': 'edge',
                'workers': 1,
                'burn_subtitles': False,
                'title_card': 'Opening',
                'end_card': 'Closing',
                'card_duration': 1.0,
                'end_card_duration': 1.2,
                'title_card_bg': '#112233',
                'scenes': [{'image': image.name, 'text': '', 'hold_sec': 0.3}],
            }
            manifest_path = td / 'cards.json'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            out_dir = td / 'out'

            video_auto.CancelToken.reset()
            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge'):
                with mock.patch.object(
                    video_auto,
                    'synthesize_audio_with_retry',
                    side_effect=AssertionError('empty content scene must not use TTS'),
                ):
                    video_auto.main([
                        str(manifest_path),
                        '--output-dir', str(out_dir),
                        '--workers', '1',
                        '--no-burn',
                    ])

            duration = video_auto.ffprobe_duration(out_dir / 'cards.mp4')
            self.assertGreater(duration, 2.2)
            self.assertLess(duration, 3.5)
            scene_names = sorted(path.name for path in (out_dir / 'scenes').glob('*.mp4'))
            self.assertEqual(scene_names, ['000.mp4', '001.mp4', '002_end.mp4'])
            scene_paths = [out_dir / 'scenes' / name for name in scene_names]
            scene_durations = [video_auto.ffprobe_duration(path) for path in scene_paths]
            final_mp4 = out_dir / 'cards.mp4'
            title_frame = _read_rgb_frame(
                final_mp4,
                at_sec=min(0.3, scene_durations[0] / 2),
                width=320,
                height=240,
            )
            content_frame = _read_rgb_frame(
                final_mp4,
                at_sec=scene_durations[0] + min(0.1, scene_durations[1] / 2),
                width=320,
                height=240,
            )
            end_frame = _read_rgb_frame(
                final_mp4,
                at_sec=sum(scene_durations[:2]) + min(0.3, scene_durations[2] / 2),
                width=320,
                height=240,
            )
            self.assertGreater(
                _changed_pixels(title_frame, content_frame),
                1000,
                'title card and content scene should be visually distinct',
            )
            self.assertGreater(
                _changed_pixels(content_frame, end_frame),
                1000,
                'content scene and end card should be visually distinct',
            )
            self.assertGreater(
                _changed_pixels(title_frame, end_frame),
                100,
                'different title/end text should produce visibly distinct cards',
            )
            self.assertTrue((out_dir / 'cards.srt').is_file())
            self.assertFalse((out_dir / '_tmp').exists())


if __name__ == '__main__':
    unittest.main()
