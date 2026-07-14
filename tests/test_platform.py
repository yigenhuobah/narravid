"""Cross-platform helpers: fonts, TTS gates, process kill, ffmpeg names."""
from __future__ import annotations

import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _bundled_ffmpeg
import video_auto


class TestSystemTtsGate(unittest.TestCase):
    def test_system_tts_available_matches_nt(self):
        self.assertEqual(video_auto.system_tts_available(), os.name == 'nt')

    def test_resolve_engine_system_rejected_off_windows(self):
        with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
            with mock.patch.object(video_auto, 'edge_tts_available', return_value=True):
                with self.assertRaises(RuntimeError) as cm:
                    video_auto.resolve_tts_engine('system')
                self.assertIn('Windows', str(cm.exception))

    def test_resolve_engine_auto_edge(self):
        with mock.patch.object(video_auto, 'edge_tts_available', return_value=True):
            self.assertEqual(video_auto.resolve_tts_engine(None), 'edge')

    def test_resolve_engine_auto_none(self):
        with mock.patch.object(video_auto, 'edge_tts_available', return_value=False):
            with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
                with self.assertRaises(RuntimeError):
                    video_auto.resolve_tts_engine(None)

    def test_synthesize_system_tts_guard(self):
        with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
            with self.assertRaises(RuntimeError):
                video_auto.synthesize_system_tts('hi', Path('x.wav'), 'v')

    def test_edge_retry_no_system_fallback_off_windows(self):
        calls = {'n': 0}

        def boom(*_a, **_k):
            calls['n'] += 1
            raise RuntimeError('edge down')

        with mock.patch.object(video_auto, 'synthesize_edge_tts', side_effect=boom):
            with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
                with mock.patch.object(video_auto, 'MAX_TTS_RETRIES', 0):
                    with self.assertRaises(RuntimeError) as cm:
                        video_auto.synthesize_audio_with_retry(
                            'text', Path('out.mp3'), 'edge', 'zh-CN-XiaoxiaoNeural',
                        )
                    self.assertIn('无系统 TTS', str(cm.exception))
                    # must not call system path
        self.assertGreaterEqual(calls['n'], 1)


class TestFontDiscovery(unittest.TestCase):
    def setUp(self):
        video_auto.clear_font_cache_for_tests()

    def tearDown(self):
        video_auto.clear_font_cache_for_tests()

    def test_narravid_font_env(self):
        with tempfile.TemporaryDirectory() as td:
            font = Path(td) / 'CustomFont.ttf'
            font.write_bytes(b'\x00' * 16)
            with mock.patch.dict(os.environ, {'NARRAVID_FONT': str(font)}):
                video_auto.clear_font_cache_for_tests()
                found = video_auto._find_zh_font()
            self.assertEqual(Path(found).resolve(), font.resolve())

    def test_bundled_fonts_dir(self):
        with tempfile.TemporaryDirectory() as td:
            fonts = Path(td) / 'fonts'
            fonts.mkdir()
            target = fonts / 'NotoSansSC-Regular.otf'
            target.write_bytes(b'\x00' * 8)
            with mock.patch.dict(os.environ, {'NARRAVID_FONT': ''}, clear=False):
                os.environ.pop('NARRAVID_FONT', None)
                with mock.patch.object(video_auto, '_font_search_roots', return_value=[fonts]):
                    with mock.patch.object(video_auto, '_system_zh_font_candidates', return_value=[]):
                        video_auto.clear_font_cache_for_tests()
                        found = video_auto._find_zh_font()
            self.assertTrue(found)
            self.assertTrue(found.endswith('NotoSansSC-Regular.otf'))

    def test_default_subtitle_font_name_fallback(self):
        with mock.patch.object(video_auto, '_find_zh_font', return_value=None):
            video_auto.clear_font_cache_for_tests()
            name = video_auto.default_subtitle_font_name()
        self.assertTrue(isinstance(name, str) and len(name) > 0)

    def test_font_name_from_path_heuristics(self):
        self.assertEqual(video_auto._font_name_from_path('/x/msyh.ttc'), 'Microsoft YaHei')
        self.assertEqual(video_auto._font_name_from_path('/usr/share/fonts/NotoSansCJK-Regular.ttc'), 'Noto Sans CJK SC')
        self.assertEqual(video_auto._font_name_from_path('/usr/share/fonts/wqy-microhei.ttc'), 'WenQuanYi Micro Hei')

    def test_default_subtitle_style_contains_font(self):
        with mock.patch.object(video_auto, 'default_subtitle_font_name', return_value='Noto Sans CJK SC'):
            s = video_auto.default_subtitle_style()
        self.assertIn('FontName=Noto Sans CJK SC', s)

    def test_font_cache_reuses_result(self):
        with mock.patch.object(video_auto, '_system_zh_font_candidates', return_value=[]) as sys_cands:
            with mock.patch.object(video_auto, '_iter_bundled_font_files', return_value=iter([])):
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop('NARRAVID_FONT', None)
                    video_auto.clear_font_cache_for_tests()
                    a = video_auto._find_zh_font()
                    b = video_auto._find_zh_font()
                    self.assertEqual(a, b)
                    # second call should not re-scan system list
                    self.assertEqual(sys_cands.call_count, 1)


class TestKillProcess(unittest.TestCase):
    def test_windows_uses_taskkill(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4242
        with mock.patch.object(video_auto.os, 'name', 'nt'):
            with mock.patch.object(video_auto.subprocess, 'run') as run:
                video_auto._kill_process(proc)
                run.assert_called()
                args = run.call_args[0][0]
                self.assertEqual(args[0], 'taskkill')
                self.assertIn('/PID', args)
                self.assertIn('4242', args)

    def test_posix_uses_killpg(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 99
        proc.wait.return_value = 0  # after SIGTERM
        with mock.patch.object(video_auto.os, 'name', 'posix'):
            with mock.patch.object(video_auto.os, 'killpg', create=True) as killpg:
                video_auto._kill_process(proc)
                killpg.assert_called()
                self.assertEqual(killpg.call_args[0][0], 99)
                self.assertEqual(killpg.call_args[0][1], signal.SIGTERM)


class TestBundledFfmpeg(unittest.TestCase):
    def test_binary_names_nt(self):
        with mock.patch.object(_bundled_ffmpeg.os, 'name', 'nt'):
            self.assertEqual(_bundled_ffmpeg._binary_names('ffmpeg')[0], 'ffmpeg.exe')

    def test_binary_names_posix(self):
        with mock.patch.object(_bundled_ffmpeg.os, 'name', 'posix'):
            self.assertEqual(_bundled_ffmpeg._binary_names('ffmpeg')[0], 'ffmpeg')

    def test_first_existing_extensionless(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'ffmpeg').write_text('x', encoding='utf-8')
            with mock.patch.object(_bundled_ffmpeg.os, 'name', 'posix'):
                found = _bundled_ffmpeg._first_existing(d, 'ffmpeg')
            self.assertTrue(found)
            self.assertTrue(found.endswith('ffmpeg'))


class TestSubtitleFilterUsesDefault(unittest.TestCase):
    def test_no_override_uses_default_style(self):
        with tempfile.TemporaryDirectory() as td:
            srt = Path(td) / 'a.srt'
            srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nhi\n', encoding='utf-8')
            with mock.patch.object(video_auto, 'default_subtitle_style', return_value='FontName=TestFont,FontSize=16'):
                arg = video_auto.subtitle_filter_arg(srt, None)
            self.assertIn('TestFont', arg)
            self.assertIn('force_style', arg)


if __name__ == '__main__':
    unittest.main()


class TestMainArgvApi(unittest.TestCase):
    def test_main_accepts_explicit_argv(self):
        """main(argv=...) must parse without mutating process sys.argv."""
        import sys
        before = list(sys.argv)
        try:
            try:
                video_auto.main(['__no_such_manifest__.json', '--workers', '1'])
            except (SystemExit, FileNotFoundError, ValueError, Exception):
                pass
        finally:
            self.assertEqual(list(sys.argv), before)


class TestRunFromManifestFile(unittest.TestCase):
    def test_run_from_manifest_file_builds_argv(self):
        import sys
        before = list(sys.argv)
        with self.assertRaises((SystemExit, FileNotFoundError, ValueError, Exception)):
            video_auto.run_from_manifest_file('__nope__.json', output_dir='out', workers=1, no_burn=True)
        self.assertEqual(list(sys.argv), before)
