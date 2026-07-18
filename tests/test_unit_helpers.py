"""Layer 1 — pure unit tests (no ffmpeg/network). Fast gate for every commit."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import video_auto
import webui
import webui_jobs
from tests.support import ROOT, write_tiny_png


class TestAtempo(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(video_auto.atempo_filter_chain(1.0), [])

    def test_single(self):
        self.assertEqual(video_auto.atempo_filter_chain(1.5), ['atempo=1.500'])
        self.assertEqual(video_auto.atempo_filter_chain(2.0), ['atempo=2.000'])

    def test_chain_fast(self):
        self.assertEqual(video_auto.atempo_filter_chain(3.0), ['atempo=2.000', 'atempo=1.500'])

    def test_chain_slow(self):
        self.assertEqual(video_auto.atempo_filter_chain(0.25), ['atempo=0.500', 'atempo=0.500'])
        for invalid in (0, -1, float('nan'), float('inf')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                video_auto.atempo_filter_chain(invalid)


class TestSrtAndSentences(unittest.TestCase):
    def test_srt_ts(self):
        self.assertEqual(video_auto.srt_ts(0), '00:00:00,000')
        self.assertEqual(video_auto.srt_ts(3661.5), '01:01:01,500')

    def test_split_basic(self):
        parts = video_auto.split_sentences('你好。世界！继续？')
        self.assertGreaterEqual(len(parts), 2)

    def test_smart_comma_off(self):
        text = '这是第一段，这是第二段，这是第三段。'
        on = video_auto.split_sentences(text, smart_comma=True)
        off = video_auto.split_sentences(text, smart_comma=False)
        self.assertEqual(len(on), 2)
        self.assertEqual(off, [text])

    def test_punctuation_only_text_produces_no_segments(self):
        self.assertEqual(video_auto.split_sentences('\uff0c\u3002\uff01\uff1f;'), [])
        self.assertEqual(video_auto.build_sentence_segments('\uff0c\u3002\uff01', 2.0), [])

    def test_build_segments_cover_duration(self):
        segs = video_auto.build_sentence_segments('你好。世界。', 2.0, 0.0, smart_comma=True)
        self.assertTrue(segs)
        self.assertAlmostEqual(segs[0]['start'], 0.0)
        self.assertAlmostEqual(segs[-1]['end'], 2.0, places=3)

    def test_make_global_srt(self):
        infos = [{
            'text': '你好，世界。继续测试',
            'narration_duration': 2.0,
            'scene_duration': 2.5,
        }]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'g.srt'
            video_auto.make_global_srt(infos, out, smart_comma=True)
            text = out.read_text(encoding='utf-8')
            self.assertIn('-->', text)
            self.assertTrue(len(text.strip()) > 0)

    def test_global_srt_uses_scene_duration_for_next_scene_offset(self):
        infos = [
            {
                'text': '\u7b2c\u4e00\u53e5\u3002',
                'narration_duration': 1.0,
                'scene_duration': 2.5,
            },
            {
                'text': '\u7b2c\u4e8c\u53e5\u3002',
                'narration_duration': 0.5,
                'scene_duration': 0.75,
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'global.srt'
            video_auto.make_global_srt(infos, out)
            text = out.read_text(encoding='utf-8')
        self.assertIn('00:00:00,000 --> 00:00:01,000', text)
        self.assertIn('00:00:02,500 --> 00:00:03,000', text)


class TestParseBoolishDuration(unittest.TestCase):
    def test_false_strings(self):
        for v in ('0', 'false', 'FALSE', 'no', 'off', 'n', 'disabled', ''):
            self.assertIs(video_auto.parse_boolish(v), False, v)

    def test_true_strings(self):
        for v in ('1', 'true', 'yes', 'on', 'y', 'enabled'):
            self.assertIs(video_auto.parse_boolish(v), True, v)

    def test_unknown_default(self):
        self.assertIs(video_auto.parse_boolish('maybe', default=True), True)
        self.assertIs(video_auto.parse_boolish('maybe', default=False), False)

    def test_duration_fallback(self):
        self.assertEqual(video_auto.resolve_positive_duration(0, 3.0), 3.0)
        self.assertEqual(video_auto.resolve_positive_duration(-1, 2.5), 2.5)
        self.assertEqual(video_auto.resolve_positive_duration(None, 4.0), 4.0)
        self.assertEqual(video_auto.resolve_positive_duration(5, 3.0), 5.0)
        self.assertEqual(video_auto.resolve_positive_duration('x', 3.0), 3.0)
        self.assertEqual(video_auto.resolve_positive_duration(float('inf'), 3.0), 3.0)
        self.assertEqual(video_auto.resolve_positive_duration(9999, 3.0), 3600.0)
        self.assertEqual(video_auto.resolve_positive_duration(None, float('inf')), 1.0)


class TestCancelTokenSemantics(unittest.TestCase):
    def setUp(self):
        video_auto.CancelToken.reset()

    def tearDown(self):
        video_auto.CancelToken.reset()

    def test_user_cancel(self):
        video_auto.CancelToken.set_cancelled()
        self.assertTrue(video_auto.CancelToken.is_cancelled())
        self.assertTrue(video_auto.CancelToken.is_user_cancel())
        with self.assertRaises(RuntimeError) as cm:
            video_auto._check_cancel()
        self.assertIn('用户取消', str(cm.exception))

    def test_abort_not_user(self):
        video_auto.CancelToken.set_aborted()
        self.assertTrue(video_auto.CancelToken.is_cancelled())
        self.assertFalse(video_auto.CancelToken.is_user_cancel())
        with self.assertRaises(RuntimeError) as cm:
            video_auto._check_cancel()
        self.assertIn('中止', str(cm.exception))
        self.assertNotIn('用户', str(cm.exception))

    def test_is_cancel_error(self):
        self.assertTrue(video_auto.is_cancel_error(RuntimeError('渲染已被用户取消')))
        self.assertFalse(video_auto.is_cancel_error(RuntimeError('渲染已中止')))
        self.assertFalse(video_auto.is_cancel_error(RuntimeError('boom')))


class TestWebuiPathHelpers(unittest.TestCase):
    def test_is_under(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            child = root / 'a' / 'b.txt'
            child.parent.mkdir(parents=True)
            child.write_text('x', encoding='utf-8')
            self.assertTrue(webui._is_under(child, root))
            self.assertFalse(webui._is_under(root.parent / 'x', root))

    def test_sanitize_upload(self):
        self.assertEqual(webui._sanitize_upload_name('../../evil.png'), 'evil.png')
        # 中文与特殊字符净化为 ASCII 安全名；保留扩展名
        self.assertEqual(webui._sanitize_upload_name('测试 图片#1.png'), '1.png')
        self.assertEqual(webui._sanitize_upload_name('my clip 2.mp3'), 'my_clip_2.mp3')
        cn = webui._sanitize_upload_name('封面图.png')
        self.assertEqual(cn, 'file.png')
        self.assertTrue(all(ord(c) < 128 for c in cn))

    def test_sanitize_render_id(self):
        self.assertEqual(webui._sanitize_render_id('r_abc-12'), 'r_abc-12')
        for bad in ('../pwn', '..\\x', 'a/b', 'C:\\Temp\\x', '', '..', 'a' * 80):
            self.assertIsNone(webui._sanitize_render_id(bad), bad)

    def test_job_out_dir(self):
        self.assertIsNone(webui._job_out_dir('../pwn'))
        out = webui._job_out_dir('normal_id')
        self.assertIsNotNone(out)
        self.assertTrue(webui._is_under(out, webui.OUT_BASE))

    def test_resolve_media(self):
        p = write_tiny_png(webui.UPLOAD_DIR / '_ut_media.png')
        try:
            self.assertIsNotNone(webui._resolve_media_path(str(p)))
            self.assertIsNone(webui._resolve_media_path(str(ROOT / 'webui.py')))
            self.assertIsNone(webui._resolve_media_path('../../webui.py'))
        finally:
            p.unlink(missing_ok=True)

    def test_looks_like_cancel(self):
        self.assertTrue(webui._looks_like_cancel('已取消'))
        self.assertTrue(webui._looks_like_cancel('渲染已被用户取消'))
        self.assertFalse(webui._looks_like_cancel('渲染已中止'))
        self.assertFalse(webui._looks_like_cancel('完成'))

    def test_active_render_signal(self):
        video_auto.CancelToken.reset()
        webui._set_active_render('A')
        webui._signal_cancel_token_if_active('B')
        self.assertFalse(video_auto.CancelToken.is_cancelled())
        webui._signal_cancel_token_if_active('A')
        self.assertTrue(video_auto.CancelToken.is_user_cancel())
        webui._set_active_render(None)
        video_auto.CancelToken.reset()

    def test_template_path(self):
        h = webui.H.__new__(webui.H)
        self.assertIsNone(h._template_path('../x'))
        self.assertIsNone(h._template_path('..\\x'))
        tp = h._template_path('abc12-34')
        self.assertIsNotNone(tp)
        self.assertTrue(webui._is_under(tp, webui.TEMPLATE_DIR))


class TestBurnSubtitlesParse(unittest.TestCase):
    def test_false_strings(self):
        for v in ('false', '0', 'no', 'off', False):
            self.assertIs(video_auto.parse_boolish(v, default=True), False, v)

    def test_true_default(self):
        self.assertIs(video_auto.parse_boolish(True, default=True), True)
        self.assertIs(video_auto.parse_boolish(None, default=True), True)


class TestTimeoutCancelErrorPriority(unittest.TestCase):
    """Timeout diagnosis must survive a later user cancel in except handling."""

    def test_timeout_prior_not_clobbered_logic(self):
        # Mirror the fixed branch priorities without spinning threads
        def classify(prior_error, cancelled, msg):
            j = {'error': prior_error, 'cancelled': cancelled, 'progress': ''}
            prior = (j.get('error') or '').strip()
            if prior.startswith('渲染超时'):
                j['progress'] = j.get('progress') or '超时（渲染卡死）'
            elif j.get('cancelled') or webui._looks_like_cancel(msg):
                j['cancelled'] = True
                j['error'] = prior or '已取消'
                j['progress'] = '已取消'
            elif prior:
                j['progress'] = j.get('progress') or f'失败: {msg}'[:200]
            else:
                j['error'] = msg[-500:]
                j['progress'] = f'失败: {msg}'[:200]
            return j

        j = classify(f'渲染超时：{webui.STALL_SECONDS} 秒无进度更新', True, '渲染已被用户取消')
        self.assertTrue(j['error'].startswith('渲染超时'))
        self.assertEqual(j['progress'], '超时（渲染卡死）')

        j2 = classify('', True, '渲染已被用户取消')
        self.assertEqual(j2['error'], '已取消')

    def test_success_path_keeps_timeout_progress(self):
        """Mirror run_in_thread success branch when mon already timed out."""
        j = {
            'cancelled': True,
            'error': f'渲染超时：{webui.STALL_SECONDS} 秒无进度更新',
            'progress': '超时（渲染卡死）',
        }
        if j.get('cancelled') or j.get('error'):
            prior = (j.get('error') or '').strip()
            if prior.startswith('渲染超时'):
                j['progress'] = j.get('progress') or '超时（渲染卡死）'
            elif j.get('cancelled') and not prior:
                j['error'] = '已取消'
                j['progress'] = '已取消'
            elif j.get('cancelled'):
                j['progress'] = j.get('progress') or '已取消'
        self.assertTrue(j['error'].startswith('渲染超时'))
        self.assertIn('超时', j['progress'])


class TestAssColorLogic(unittest.TestCase):
    """UI hex → ASS BGR conversion invariant (mirrored in webui JS)."""

    @staticmethod
    def hex_to_ass(h, alpha='00'):
        h = ''.join(c for c in (h or 'FFFFFF') if c in '0123456789abcdefABCDEF').upper().zfill(6)[:6]
        rr, gg, bb = h[0:2], h[2:4], h[4:6]
        return f'&H{alpha}{bb}{gg}{rr}'

    def test_colors(self):
        self.assertEqual(self.hex_to_ass('FF0000'), '&H000000FF')
        self.assertEqual(self.hex_to_ass('00FF00'), '&H0000FF00')
        self.assertEqual(self.hex_to_ass('0000FF'), '&H00FF0000')
        self.assertEqual(self.hex_to_ass('FFFFFF'), '&H00FFFFFF')


class TestHoldSecNormalize(unittest.TestCase):
    def test_scene_hold_sec_aliases(self):
        self.assertEqual(video_auto.scene_hold_sec({'hold_sec': 1.5}), 1.5)
        self.assertEqual(video_auto.scene_hold_sec({'hold': 2}), 2.0)
        self.assertEqual(video_auto.scene_hold_sec({'hold_sec': 1, 'hold': 9}), 1.0)
        self.assertEqual(video_auto.scene_hold_sec({}), 0.0)
        self.assertEqual(video_auto.scene_hold_sec({'hold': 'x'}), 0.0)
        self.assertEqual(video_auto.scene_hold_sec({'hold_sec': '', 'hold': 2.5}), 2.5)
        self.assertEqual(video_auto.scene_hold_sec({'hold_sec': None, 'hold': 2}), 2.0)
        self.assertEqual(video_auto.scene_hold_sec({'hold_sec': 0, 'hold': 9}), 0.0)
        self.assertEqual(video_auto.scene_hold_sec({'hold_sec': float('inf')}), 0.0)
        self.assertEqual(video_auto.scene_hold_sec({'hold_sec': 10 ** 1000}), 0.0)

    def test_normalize_manifest_rewrites_hold(self):
        m = video_auto.normalize_manifest({
            'scenes': [{'image': 'a.png', 'text': 't', 'hold': 1.25}],
        })
        self.assertEqual(m['scenes'][0]['hold_sec'], 1.25)
        self.assertNotIn('hold', m['scenes'][0])

    def test_normalize_requires_image(self):
        with self.assertRaises(ValueError):
            video_auto.normalize_manifest({'scenes': [{'text': 'x', 'hold': 1}]})


class TestSubtitleStyleSanitize(unittest.TestCase):
    def test_strips_filter_injection_chars(self):
        dirty = "FontName=Arial,FontSize=16';force_style='evil':[x]"
        clean = video_auto.sanitize_subtitle_style(dirty)
        for ch in "\\'\"[]:;|":
            self.assertNotIn(ch, clean)
        self.assertIn('FontName=Arial', clean)
        filt = video_auto.subtitle_filter_arg(Path('x.srt'), dirty)
        self.assertIn("force_style='", filt)
        # no nested single quotes from injection
        self.assertEqual(filt.count("force_style='"), 1)

    def test_empty_falls_back_to_default(self):
        d = video_auto.default_subtitle_style()
        self.assertEqual(video_auto.sanitize_subtitle_style(''), d)
        self.assertEqual(video_auto.sanitize_subtitle_style(None), d)


class TestPickFinalMp4AndSystemExit(unittest.TestCase):
    def test_pick_prefers_manifest_mp4(self):
        with tempfile.TemporaryDirectory() as td:
            od = Path(td)
            (od / 'aaa.mp4').write_bytes(b'a')
            (od / 'manifest.mp4').write_bytes(b'm')
            (od / '_tmp.mp4').write_bytes(b't')
            picked = webui._pick_final_mp4(od)
            self.assertEqual(picked.name, 'manifest.mp4')

    def test_pick_skips_underscore_and_uses_newest(self):
        with tempfile.TemporaryDirectory() as td:
            od = Path(td)
            older = od / 'older.mp4'
            newer = od / 'newer.mp4'
            older.write_bytes(b'o')
            time.sleep(0.02)
            newer.write_bytes(b'n')
            (od / '_partial.mp4').write_bytes(b'p')
            picked = webui._pick_final_mp4(od)
            self.assertEqual(picked.name, 'newer.mp4')

    def test_systemexit_message(self):
        self.assertIn('错误', webui._systemexit_message(SystemExit('错误: no tts')))
        self.assertIn('exit 2', webui._systemexit_message(SystemExit(2)))
        self.assertEqual(webui._systemexit_message(SystemExit(None)), '渲染异常退出')


class TestProcessAudioNoMislabelCopy(unittest.TestCase):
    def test_mismatched_suffix_does_not_byte_copy(self):
        """Edge MP3 → .wav must re-encode, not shutil.copyfile."""
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / 'raw.mp3'
            out = Path(td) / '001.wav'
            raw.write_bytes(b'ID3fake-mp3-payload-not-wav')
            calls = []

            def fake_run(cmd, silent=False):
                calls.append(list(cmd))
                # write a tiny wav-like placeholder so duration probe can run
                Path(cmd[-1]).write_bytes(b'RIFF....WAVEfmt ')

            with mock.patch.object(video_auto, 'ffprobe_duration', return_value=1.0):
                with mock.patch.object(video_auto, 'run', side_effect=fake_run):
                    with mock.patch.object(video_auto, 'shutil') as sh:
                        video_auto.process_audio(raw, out, speed=1.0, pad_sec=0.0)
                        sh.copyfile.assert_not_called()
            self.assertTrue(calls)
            self.assertEqual(str(calls[0][-1]), str(out))

    def test_same_suffix_no_filter_byte_copies(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / 'a.wav'
            out = Path(td) / 'b.wav'
            raw.write_bytes(b'RIFFWAVDATA')
            with mock.patch.object(video_auto, 'ffprobe_duration', return_value=0.5):
                with mock.patch.object(video_auto, 'run') as run_mock:
                    dur = video_auto.process_audio(raw, out, speed=1.0, pad_sec=0.0)
                    run_mock.assert_not_called()
            self.assertEqual(dur, 0.5)
            self.assertEqual(out.read_bytes(), b'RIFFWAVDATA')


class TestManifestContracts(unittest.TestCase):
    def test_normalize_is_non_mutating_and_clamps_hold(self):
        source = {
            'title': 'demo',
            'scenes': [{'image': 7, 'text': None, 'hold': 4001}],
        }
        normalized = video_auto.normalize_manifest(source)
        self.assertEqual(source['scenes'][0], {'image': 7, 'text': None, 'hold': 4001})
        self.assertEqual(normalized['scenes'][0], {
            'image': '7',
            'text': '',
            'hold_sec': 3600.0,
        })

    def test_load_manifest_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / 'bom.json'
            payload = {'scenes': [{'image': 'slide.png', 'text': 42}]}
            manifest_path.write_text('\ufeff' + json.dumps(payload), encoding='utf-8')
            loaded = video_auto.load_manifest(manifest_path)
        self.assertEqual(loaded['scenes'][0]['text'], '42')
        self.assertEqual(loaded['scenes'][0]['hold_sec'], 0.0)

    def test_load_manifest_rejects_non_finite_json_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / 'non-finite.json'
            for number in ('Infinity', '1e400'):
                with self.subTest(number=number):
                    manifest_path.write_text(
                        f'{{"width": {number}, "scenes": [{{"image": "slide.png"}}]}}',
                        encoding='utf-8',
                    )
                    with self.assertRaisesRegex(ValueError, 'non-finite'):
                        video_auto.load_manifest(manifest_path)


class TestEdgeTtsContract(unittest.TestCase):
    @staticmethod
    def _edge_module(calls):
        module = types.ModuleType('edge_tts')

        class FakeCommunicate:
            def __init__(self, **kwargs):
                calls.append(kwargs)

            async def save(self, target):
                Path(target).write_bytes(b'fake-edge-audio')

        module.Communicate = FakeCommunicate
        return module

    def test_rate_and_volume_are_always_edge_tts_strings(self):
        calls = []
        fake_edge = self._edge_module(calls)
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / 'first.mp3'
            second = Path(td) / 'second.mp3'
            with mock.patch.dict(sys.modules, {'edge_tts': fake_edge}):
                with mock.patch.object(video_auto, 'edge_tts_available', return_value=True):
                    video_auto.synthesize_edge_tts(
                        ' \ufffdhello ', first, 'voice-default', rate=0, volume=100,
                    )
                    video_auto.synthesize_edge_tts(
                        'world', second, 'voice-custom', rate=-12, volume=80,
                    )
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
        self.assertEqual(calls, [
            {
                'text': 'hello',
                'voice': 'voice-default',
                'rate': '+0%',
                'volume': '+0%',
            },
            {
                'text': 'world',
                'voice': 'voice-custom',
                'rate': '-12%',
                'volume': '-20%',
            },
        ])

class TestSystemTtsContract(unittest.TestCase):
    def test_powershell_script_preserves_text_and_escapes_parameters(self):
        with tempfile.TemporaryDirectory() as td:
            quoted_dir = Path(td) / "quoted'path"
            quoted_dir.mkdir()
            wav_path = quoted_dir / 'speech.wav'
            with mock.patch.object(video_auto, 'system_tts_available', return_value=True):
                with mock.patch.object(video_auto, 'run') as run:
                    video_auto.synthesize_system_tts(
                        "hello ' world", wav_path, "Voice'Name", rate=-2, volume=73,
                    )

            self.assertEqual(wav_path.with_suffix('.txt').read_text(encoding='utf-8'), "hello ' world")
            script = wav_path.with_suffix('.ps1').read_text(encoding='utf-8')
            self.assertIn("Voice''Name", script)
            self.assertIn("quoted''path", script)
            self.assertIn('$s.Rate = -2', script)
            self.assertIn('$s.Volume = 73', script)
            command = run.call_args.args[0]
            self.assertEqual(command[:4], ['powershell', '-ExecutionPolicy', 'Bypass', '-File'])
            self.assertEqual(Path(command[-1]), wav_path.with_suffix('.ps1'))


class TestTtsRetryContract(unittest.TestCase):
    def setUp(self):
        video_auto.CancelToken.reset()

    def tearDown(self):
        video_auto.CancelToken.reset()

    def test_transient_edge_failure_retries_then_succeeds(self):
        with mock.patch.object(
            video_auto,
            'synthesize_edge_tts',
            side_effect=[RuntimeError('temporary'), None],
        ) as synthesize:
            with mock.patch.object(video_auto.time, 'sleep') as sleep:
                with mock.patch.object(video_auto, 'MAX_TTS_RETRIES', 2):
                    used = video_auto.synthesize_audio_with_retry(
                        'hello', Path('out.mp3'), 'edge', 'voice', rate=3, volume=90,
                    )
        self.assertEqual(used, 'edge')
        self.assertEqual(synthesize.call_count, 2)
        self.assertEqual(sleep.call_count, 6)

    def test_edge_exhaustion_falls_back_to_system_and_converts(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / '001.raw.mp3'
            with mock.patch.object(video_auto, 'MAX_TTS_RETRIES', 0):
                with mock.patch.object(video_auto, 'synthesize_edge_tts', side_effect=RuntimeError('offline')):
                    with mock.patch.object(video_auto, 'system_tts_available', return_value=True):
                        with mock.patch.object(video_auto, 'synthesize_system_tts') as system_tts:
                            with mock.patch.object(video_auto, 'run') as run:
                                used = video_auto.synthesize_audio_with_retry(
                                    'hello', raw, 'edge', 'ignored-edge-voice', rate=2, volume=88,
                                )
        self.assertEqual(used, 'system')
        system_tts.assert_called_once_with(
            'hello', raw.with_suffix('.raw.wav'),
            voice=video_auto.DEFAULT_SYSTEM_VOICE, rate=2, volume=88,
        )
        convert_cmd = run.call_args.args[0]
        self.assertEqual(convert_cmd[0], video_auto.FFMPEG)
        self.assertEqual(Path(convert_cmd[-1]), raw)

    def test_user_cancel_during_edge_failure_stops_retry_and_fallback(self):
        def cancel_then_fail(*_args, **_kwargs):
            video_auto.CancelToken.set_cancelled()
            raise RuntimeError('network failed after cancel')

        with mock.patch.object(video_auto, 'synthesize_edge_tts', side_effect=cancel_then_fail):
            with mock.patch.object(video_auto.time, 'sleep') as sleep:
                with mock.patch.object(video_auto, 'synthesize_system_tts') as system_tts:
                    with self.assertRaisesRegex(RuntimeError, '\u7528\u6237\u53d6\u6d88'):
                        video_auto.synthesize_audio_with_retry(
                            'hello', Path('out.mp3'), 'edge', 'voice',
                        )
        sleep.assert_not_called()
        system_tts.assert_not_called()


class TestProcessSingleSceneContract(unittest.TestCase):
    def setUp(self):
        video_auto.CancelToken.reset()

    def tearDown(self):
        video_auto.CancelToken.reset()

    @staticmethod
    def _dirs(root):
        tmp_dir = root / 'tmp'
        audio_dir = root / 'audio'
        scene_dir = root / 'scenes'
        for directory in (tmp_dir, audio_dir, scene_dir):
            directory.mkdir()
        return tmp_dir, audio_dir, scene_dir

    def test_narrated_image_applies_tail_then_hold_and_burns_subtitles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            image = root / 'slide.png'
            image.write_bytes(b'image')
            tmp_dir, audio_dir, scene_dir = self._dirs(root)
            progress = mock.Mock()
            with mock.patch.object(
                video_auto, 'synthesize_audio_with_retry', return_value='edge',
            ) as synthesize:
                with mock.patch.object(
                    video_auto, 'process_audio', side_effect=[1.25, 1.75],
                ) as process_audio:
                    with mock.patch.object(
                        video_auto, 'subtitle_filter_arg', return_value='subtitles=test.srt',
                    ):
                        with mock.patch.object(video_auto, 'run') as run:
                            info = video_auto.process_single_scene(
                                1,
                                {'image': image.name, 'text': 'First! Second?', 'hold_sec': 0.5},
                                root,
                                'edge', 'edge-voice', 4, 82,
                                1.5, 0.2,
                                640, 360, 24, True,
                                'FontName=Test', True,
                                tmp_dir, audio_dir, scene_dir,
                                progress,
                            )

            raw_audio = tmp_dir / '001.raw.mp3'
            wav = audio_dir / '001.wav'
            synthesize.assert_called_once_with(
                'First! Second?', raw_audio, 'edge', 'edge-voice', 4, 82,
            )
            self.assertEqual(process_audio.call_args_list[0].args, (raw_audio, wav, 1.5, 0.2))
            self.assertEqual(
                process_audio.call_args_list[1].args,
                (wav, tmp_dir / '001.hold.wav', 1.0, 0.5),
            )
            render_cmd = run.call_args.args[0]
            self.assertIn('-loop', render_cmd)
            self.assertNotIn('-shortest', render_cmd)
            self.assertEqual(render_cmd[render_cmd.index('-t') + 1], '1.750')
            self.assertIn('subtitles=test.srt', render_cmd[render_cmd.index('-vf') + 1])
            self.assertEqual(info['narration_duration'], 1.25)
            self.assertEqual(info['scene_duration'], 1.75)
            self.assertEqual(info['audio'], str(tmp_dir / '001.hold.wav'))
            self.assertEqual((tmp_dir / '001.srt').read_text(encoding='utf-8').count('-->'), 2)
            progress.complete.assert_called_once_with(1, 'Render OK')

    def test_video_background_discards_original_audio_and_uses_scene_duration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / 'clip.mp4'
            video.write_bytes(b'video')
            tmp_dir, audio_dir, scene_dir = self._dirs(root)
            progress = mock.Mock()
            with mock.patch.object(video_auto, 'make_silent_audio') as silent:
                with mock.patch.object(video_auto, 'synthesize_audio_with_retry') as synthesize:
                    with mock.patch.object(
                        video_auto, 'run_capture_text', return_value='video\n',
                    ) as probe:
                        with mock.patch.object(video_auto, 'run') as run:
                            info = video_auto.process_single_scene(
                                2,
                                {'image': video.name, 'text': '', 'hold_sec': 0.75},
                                root,
                                'edge', 'voice', 0, 100,
                                1.0, 0.0,
                                320, 240, 10, True,
                                None, True,
                                tmp_dir, audio_dir, scene_dir,
                                progress,
                            )

        synthesize.assert_not_called()
        silent.assert_called_once_with(audio_dir / '002.wav', 0.75)
        probe.assert_called_once()
        render_cmd = run.call_args.args[0]
        self.assertIn('-stream_loop', render_cmd)
        self.assertEqual(render_cmd[render_cmd.index('-map') + 1], '0:v:0')
        second_map = render_cmd.index('-map', render_cmd.index('-map') + 1)
        self.assertEqual(render_cmd[second_map + 1], '1:a:0')
        self.assertNotIn('-shortest', render_cmd)
        self.assertEqual(render_cmd[render_cmd.index('-t') + 1], '0.750')
        self.assertEqual(info['scene_duration'], 0.75)

class TestMixBgmContract(unittest.TestCase):
    def test_sidechain_command_uses_duck_ratio_and_voice_duration(self):
        with mock.patch.object(video_auto, 'ffprobe_duration', return_value=4.25):
            with mock.patch.object(video_auto, 'run') as run:
                mode = video_auto.mix_bgm(
                    Path('voice.wav'), Path('music.wav'), Path('mixed.wav'), duck_ratio=0.3,
                )
        self.assertEqual(mode, 'sidechain')
        cmd = run.call_args.args[0]
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('sidechaincompress=', graph)
        self.assertIn('volume=0.30', graph)
        self.assertIn('duration=first', graph)
        self.assertEqual(cmd[cmd.index('-t') + 1], '4.250')
        self.assertNotIn('-shortest', cmd)

    def test_sidechain_failure_uses_fixed_volume_mix(self):
        with mock.patch.object(video_auto, 'ffprobe_duration', return_value=2.0):
            with mock.patch.object(
                video_auto, 'run', side_effect=[RuntimeError('sidechain'), None],
            ) as run:
                mode = video_auto.mix_bgm(
                    Path('voice.wav'), Path('music.wav'), Path('mixed.wav'), duck_ratio=0.2,
                )
        self.assertEqual(mode, 'fixed')
        self.assertEqual(run.call_count, 2)
        fallback = run.call_args.args[0]
        graph = fallback[fallback.index('-filter_complex') + 1]
        self.assertNotIn('sidechaincompress', graph)
        self.assertIn('volume=0.20', graph)
        self.assertIn('duration=first', graph)

    def test_total_mix_failure_copies_narration(self):
        with tempfile.TemporaryDirectory() as td:
            voice = Path(td) / 'voice.wav'
            output = Path(td) / 'mixed.wav'
            voice.write_bytes(b'narration')
            with mock.patch.object(video_auto, 'ffprobe_duration', return_value=1.0):
                with mock.patch.object(video_auto, 'run', side_effect=RuntimeError('ffmpeg failed')):
                    mode = video_auto.mix_bgm(
                        voice, Path(td) / 'music.wav', output, duck_ratio=0.25,
                    )
            self.assertEqual(mode, 'none')
            self.assertEqual(output.read_bytes(), b'narration')


class TestRunFromManifestFileContract(unittest.TestCase):
    def test_all_options_map_to_explicit_main_argv(self):
        sentinel = object()
        with mock.patch.object(video_auto, 'main', return_value=sentinel) as main:
            result = video_auto.run_from_manifest_file(
                'manifest.json',
                output_dir='out',
                voice='voice',
                speed=1.25,
                bgm='music.wav',
                bgm_volume=0.2,
                title_card='title',
                title_card_file='title.txt',
                end_card='end',
                end_card_file='end.txt',
                card_duration=2,
                end_card_duration=3,
                subtitle_style='FontName=Test',
                title_card_bg='#000000',
                engine='edge',
                workers=2,
                no_smart_comma=True,
                no_burn=True,
                ignored='value',
            )
        self.assertIs(result, sentinel)
        main.assert_called_once_with([
            'manifest.json',
            '--output-dir', 'out',
            '--voice', 'voice',
            '--speed', '1.25',
            '--bgm', 'music.wav',
            '--bgm-volume', '0.2',
            '--title-card', 'title',
            '--title-card-file', 'title.txt',
            '--end-card', 'end',
            '--end-card-file', 'end.txt',
            '--card-duration', '2',
            '--end-card-duration', '3',
            '--subtitle-style', 'FontName=Test',
            '--title-card-bg', '#000000',
            '--engine', 'edge',
            '--workers', '2',
            '--no-smart-comma',
            '--no-burn',
        ])


class TestMainOrchestration(unittest.TestCase):
    def setUp(self):
        video_auto.CancelToken.reset()

    def tearDown(self):
        video_auto.CancelToken.reset()

    @staticmethod
    def _write_manifest(root, payload, name='manifest.json'):
        path = root / name
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path

    @staticmethod
    def _fake_run(cmd, silent=False):
        del silent
        target = Path(cmd[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'fake-media')

    @staticmethod
    def _fake_scene(*args):
        idx = args[0]
        scene = args[1]
        audio_dir = Path(args[16])
        scene_dir = Path(args[17])
        audio = audio_dir / f'{idx:03d}.wav'
        mp4 = scene_dir / f'{idx:03d}.mp4'
        audio.write_bytes(b'audio')
        mp4.write_bytes(b'video')
        hold = video_auto.scene_hold_sec(scene)
        return {
            'idx': idx,
            'image': str(scene['image']),
            'text': str(scene.get('text', '')),
            'narration_duration': 1.0,
            'hold_sec': hold,
            'scene_duration': 1.0 + hold,
            'mp4': str(mp4),
            'audio': str(audio),
        }

    def test_cli_options_override_manifest_while_unexposed_fields_survive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(root, {
                'width': 640,
                'height': 360,
                'fps': 12,
                'tts_engine': 'system',
                'voice': 'manifest-voice',
                'rate': 4,
                'volume': 72,
                'speech_speed': 0.8,
                'scene_tail_silence_sec': 0.33,
                'burn_subtitles': True,
                'subtitle_style': 'FontName=Manifest',
                'smart_comma': True,
                'workers': 8,
                'output_dir': 'manifest-out',
                'scenes': [{'image': 'slide.png', 'text': 'hello', 'hold_sec': 0.25}],
            })
            cli_out = root / 'cli-out'
            captured = []

            def capture_scene(*args):
                captured.append(args)
                return self._fake_scene(*args)

            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge') as resolve:
                with mock.patch.object(video_auto, 'process_single_scene', side_effect=capture_scene):
                    with mock.patch.object(video_auto, 'run', side_effect=self._fake_run):
                        video_auto.main([
                            str(manifest_path),
                            '--output-dir', str(cli_out),
                            '--engine', 'edge',
                            '--voice', 'cli-voice',
                            '--speed', '2.5',
                            '--workers', '1',
                            '--subtitle-style', 'FontName=CLI',
                            '--no-smart-comma',
                            '--no-burn',
                        ])

            resolve.assert_called_once_with('edge')
            self.assertEqual(len(captured), 1)
            scene_args = captured[0]
            self.assertEqual(scene_args[3:9], ('edge', 'cli-voice', 4, 72, 2.5, 0.33))
            self.assertEqual(scene_args[9:13], (640, 360, 12, False))
            self.assertEqual(scene_args[13], 'FontName=CLI')
            self.assertIs(scene_args[14], False)
            self.assertEqual(scene_args[1]['hold_sec'], 0.25)
            self.assertTrue((cli_out / 'manifest.mp4').is_file())
            self.assertFalse((root / 'manifest-out' / 'manifest.mp4').exists())

    def test_manifest_values_and_relative_output_are_used_without_cli_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(root, {
                'width': 800,
                'height': 450,
                'fps': 15,
                'tts_engine': 'edge',
                'voice': 'manifest-voice',
                'rate': -3,
                'volume': 65,
                'speech_speed': 1.2,
                'scene_tail_silence_sec': 0.4,
                'burn_subtitles': 'false',
                'subtitle_style': 'FontName=Manifest',
                'smart_comma': 'false',
                'workers': 1,
                'output_dir': 'relative-out',
                'scenes': [{'image': 'slide.png', 'text': 'hello'}],
            })
            captured = []

            def capture_scene(*args):
                captured.append(args)
                return self._fake_scene(*args)

            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge') as resolve:
                with mock.patch.object(video_auto, 'process_single_scene', side_effect=capture_scene):
                    with mock.patch.object(video_auto, 'run', side_effect=self._fake_run):
                        video_auto.main([str(manifest_path)])

            resolve.assert_called_once_with('edge')
            scene_args = captured[0]
            self.assertEqual(scene_args[3:9], ('edge', 'manifest-voice', -3, 65, 1.2, 0.4))
            self.assertEqual(scene_args[9:13], (800, 450, 15, False))
            self.assertEqual(scene_args[13], 'FontName=Manifest')
            self.assertIs(scene_args[14], False)
            self.assertTrue((root / 'relative-out' / 'manifest.mp4').is_file())

    def test_manifest_bgm_is_project_relative_and_remux_pads_to_video_duration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bgm = root / 'music.wav'
            bgm.write_bytes(b'music')
            manifest_path = self._write_manifest(root, {
                'tts_engine': 'edge',
                'workers': 1,
                'output_dir': 'out',
                'bgm': bgm.name,
                'bgm_volume': 0.37,
                'scenes': [{'image': 'slide.png', 'text': 'hello'}],
            })
            run_calls = []
            mix_calls = []

            def fake_run(cmd, silent=False):
                run_calls.append(list(cmd))
                self._fake_run(cmd, silent=silent)

            def fake_mix(voice_audio, bgm_path, out_path, duck_ratio):
                mix_calls.append((voice_audio, bgm_path, out_path, duck_ratio))
                out_path.write_bytes(b'mixed')
                return 'sidechain'

            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge'):
                with mock.patch.object(video_auto, 'process_single_scene', side_effect=self._fake_scene):
                    with mock.patch.object(video_auto, 'run', side_effect=fake_run):
                        with mock.patch.object(video_auto, 'mix_bgm', side_effect=fake_mix):
                            with mock.patch.object(video_auto, 'ffprobe_duration', return_value=3.25):
                                video_auto.main([str(manifest_path)])

            self.assertEqual(len(mix_calls), 1)
            self.assertEqual(mix_calls[0][1], bgm.resolve())
            self.assertEqual(mix_calls[0][3], 0.37)
            remux = next(cmd for cmd in run_calls if Path(cmd[-1]).name == 'video_no_audio.mp4')
            self.assertEqual(remux[remux.index('-filter_complex') + 1], '[1:a]apad[a]')
            self.assertEqual(remux[remux.index('-t') + 1], '3.25')
            self.assertNotIn('-shortest', remux)
            self.assertTrue((root / 'out' / 'manifest.mp4').is_file())
            self.assertFalse((root / 'out' / '_warnings.txt').exists())

    def test_serial_scene_failure_stops_before_concat_and_preserves_cause(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(root, {
                'tts_engine': 'edge',
                'workers': 1,
                'output_dir': 'out',
                'scenes': [
                    {'image': 'one.png', 'text': 'one'},
                    {'image': 'two.png', 'text': 'two'},
                ],
            })
            root_error = RuntimeError('scene-root-cause')
            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge'):
                with mock.patch.object(
                    video_auto, 'process_single_scene', side_effect=root_error,
                ) as process_scene:
                    with mock.patch.object(video_auto, 'run') as run:
                        with self.assertRaises(RuntimeError) as raised:
                            video_auto.main([str(manifest_path)])

        self.assertIn('1 ', str(raised.exception))
        self.assertIs(raised.exception.__cause__, root_error)
        self.assertEqual(process_scene.call_count, 1)
        run.assert_not_called()

    def test_parallel_failure_keeps_real_root_cause_and_resets_abort_token(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(root, {
                'tts_engine': 'edge',
                'workers': 2,
                'output_dir': 'out',
                'scenes': [
                    {'image': 'one.png', 'text': 'one'},
                    {'image': 'two.png', 'text': 'two'},
                ],
            })
            sibling_started = threading.Event()
            root_error = ValueError('real-scene-root')

            def fail_scenes(idx, *_args):
                if idx == 1:
                    if not sibling_started.wait(timeout=2):
                        raise AssertionError('sibling worker did not start')
                    raise root_error
                sibling_started.set()
                while not video_auto.CancelToken.is_cancelled():
                    time.sleep(0.001)
                raise RuntimeError('render aborted')

            with mock.patch.object(video_auto, 'resolve_tts_engine', return_value='edge'):
                with mock.patch.object(video_auto, 'process_single_scene', side_effect=fail_scenes):
                    with mock.patch.object(video_auto, 'run') as run:
                        with self.assertRaises(RuntimeError) as raised:
                            video_auto.main([str(manifest_path)])

        self.assertIn('2 ', str(raised.exception))
        self.assertNotIn('\u7528\u6237\u53d6\u6d88', str(raised.exception))
        self.assertIs(raised.exception.__cause__, root_error)
        self.assertFalse(video_auto.CancelToken.is_cancelled())
        run.assert_not_called()


class TestFrozenDataRoot(unittest.TestCase):
    def test_app_data_root_uses_exe_dir_when_frozen(self):
        fake_exe = Path(tempfile.gettempdir()) / 'narravid-webui-fake.exe'
        with mock.patch.object(webui_jobs.sys, 'frozen', True, create=True):
            with mock.patch.object(webui_jobs.sys, 'executable', str(fake_exe)):
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop('NARRAVID_DATA_DIR', None)
                    root = webui_jobs._app_data_root()
        self.assertEqual(root, fake_exe.parent.resolve())

    def test_app_data_root_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {'NARRAVID_DATA_DIR': td}):
                root = webui_jobs._app_data_root()
            self.assertEqual(root, Path(td).resolve())


if __name__ == '__main__':
    unittest.main()



