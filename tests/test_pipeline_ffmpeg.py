"""Layer 4 — pipeline / ffmpeg smoke (skipped if ffmpeg missing)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import has_ffmpeg, write_silence_wav, write_tone_wav
import video_auto


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
                'tts_engine': 'system',
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
                '--engine', 'system',
                '--workers', '1',
                '--no-burn',
            ]
            video_auto.CancelToken.reset()
            with mock.patch('sys.argv', argv):
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


if __name__ == '__main__':
    unittest.main()
