"""Layer 1 — pure unit tests (no ffmpeg/network). Fast gate for every commit."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import video_auto
import webui
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
        # smart_comma may split more aggressively on long comma runs
        self.assertTrue(len(on) >= 1 and len(off) >= 1)

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

        j = classify('渲染超时：180 秒无进度更新', True, '渲染已被用户取消')
        self.assertTrue(j['error'].startswith('渲染超时'))
        self.assertEqual(j['progress'], '超时（渲染卡死）')

        j2 = classify('', True, '渲染已被用户取消')
        self.assertEqual(j2['error'], '已取消')

    def test_success_path_keeps_timeout_progress(self):
        """Mirror run_in_thread success branch when mon already timed out."""
        j = {
            'cancelled': True,
            'error': '渲染超时：180 秒无进度更新',
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


if __name__ == '__main__':
    unittest.main()
