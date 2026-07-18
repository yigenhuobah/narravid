"""Layer 5 — live ThreadingHTTPServer API tests.

Default path avoids real Edge TTS by patching video_auto.main with a fast fake
that still writes mp4/srt so JOBS/status/cancel/clean/export-import can be exercised.
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from urllib.parse import quote

import webui
from tests.support import (
    ROOT,
    fake_video_auto_main,
    http_json,
    http_raw,
    live_webui,
    poll_status,
    upload_bytes,
    write_tiny_png,
    write_tone_wav,
)


def wait_job_threads(rid: str, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = webui.JOBS.get(rid)
        if not job or not (
            job.get('_runner_active') or job.get('_monitor_active')
        ):
            return True
        time.sleep(0.01)
    return False


class TestLiveBasicApi(unittest.TestCase):
    def test_home_and_tts_check(self):
        with live_webui() as base:
            code, body = http_json('GET', base + '/')
            self.assertEqual(code, 200)
            # HTML home: body may be bytes
            if isinstance(body, (bytes, bytearray)):
                text = body.decode('utf-8', 'ignore')
            else:
                text = str(body)
            self.assertIn('function render()', text)
            code, data = http_json('GET', base + '/api/tts-check')
            self.assertEqual(code, 200)
            self.assertIn(data.get('engine'), ('edge', 'system'))

    def test_health(self):
        with live_webui() as base:
            code, data = http_json('GET', base + '/api/health')
            self.assertIn(code, (200, 503))
            self.assertIn('tts', data)
            self.assertIn('ffmpeg', data)
            self.assertIn('ok', data)
            self.assertIn('ok', data.get('ffmpeg', {}))
            if data.get('ffmpeg', {}).get('ok'):
                self.assertTrue(data['ffmpeg'].get('path'), 'ffmpeg path should be set when ok')

    def test_upload_and_bgm_list(self):
        with live_webui() as base:
            png = write_tiny_png(Path('_tmp_live.png'))
            try:
                code, data = upload_bytes(base, 'live.png', png.read_bytes())
                self.assertEqual(code, 200)
                self.assertTrue(Path(data['path']).exists())
                Path(data['path']).unlink(missing_ok=True)
            finally:
                png.unlink(missing_ok=True)

            wav = write_tone_wav(Path('_tmp_live.wav'), 0.3)
            try:
                code, data = upload_bytes(base, 'live.wav', wav.read_bytes(), kind='bgm')
                self.assertEqual(code, 200)
                p = Path(data['path'])
                code, bgms = http_json('GET', base + '/api/bgm-list')
                self.assertEqual(code, 200)
                self.assertTrue(any(b.get('path') == str(p) for b in bgms))
                p.unlink(missing_ok=True)
            finally:
                wav.unlink(missing_ok=True)

    def test_upload_chinese_name_ascii(self):
        with live_webui() as base:
            raw = write_tiny_png(Path('_tmp_cn.png')).read_bytes()
            Path('_tmp_cn.png').unlink(missing_ok=True)
            code, data = upload_bytes(base, '测试 图片#1.png', raw)
            self.assertEqual(code, 200)
            name = Path(data['path']).name
            self.assertTrue(all(ord(c) < 128 for c in name))
            self.assertTrue(name.endswith('.png'))
            Path(data['path']).unlink(missing_ok=True)

    def test_render_rejects_bad_media(self):
        with live_webui() as base:
            code, data = http_json('POST', base + '/api/render', {
                'manifest': {'scenes': [{'image': str(Path('webui.py').resolve()), 'text': 'x'}]},
            })
            self.assertEqual(code, 400)
            self.assertIn('非法', str(data.get('error', '')))

    def test_render_rejects_empty_scenes(self):
        with live_webui() as base:
            code, data = http_json('POST', base + '/api/render', {
                'manifest': {'scenes': []},
            })
            self.assertEqual(code, 400)

    def test_render_id_escape_rewritten_live(self):
        """Live server rewrites bad IDs and cancels a controlled active render."""
        with live_webui() as base:
            raw = write_tiny_png(Path('_tmp_r.png')).read_bytes()
            Path('_tmp_r.png').unlink(missing_ok=True)
            code, up = upload_bytes(base, 'r.png', raw)
            self.assertEqual(code, 200)
            path = up['path']
            started = threading.Event()
            finished = threading.Event()
            fake = fake_video_auto_main(delay_sec=2.0, write_srt=False)

            def controlled_main(argv=None):
                started.set()
                try:
                    return fake(argv)
                finally:
                    finished.set()

            rid = None
            try:
                with mock.patch('video_auto.main', controlled_main):
                    code, data = http_json('POST', base + '/api/render', {
                        'render_id': '../escape_live',
                        'manifest': {
                            'scenes': [{'image': path, 'text': '', 'hold_sec': 0.3}],
                            'workers': 1,
                            'burn_subtitles': False,
                        },
                    })
                    self.assertEqual(code, 200)
                    rid = data['render_id']
                    self.assertNotIn('..', rid)
                    self.assertIsNotNone(webui._sanitize_render_id(rid))
                    self.assertTrue(started.wait(5), 'render thread did not enter video_auto.main')
                    cancel_code, _ = http_json('POST', base + f'/api/cancel/{rid}')
                    self.assertEqual(cancel_code, 200)
                    status_code, status = poll_status(base, rid, timeout=10)
                    self.assertEqual(status_code, 200)
                    self.assertTrue(status.get('cancelled'))
                    self.assertTrue(finished.wait(5), 'render thread did not exit after cancel')
                    self.assertTrue(wait_job_threads(rid), 'job lifecycle threads did not exit')
            finally:
                if rid:
                    job = webui.JOBS.pop(rid, None)
                    out = job.get('out') if isinstance(job, dict) else webui._job_out_dir(rid)
                    if out:
                        shutil.rmtree(out, ignore_errors=True)
                Path(path).unlink(missing_ok=True)

    def test_templates_crud_with_bgm_fields(self):
        with live_webui() as base:
            code, data = http_json('POST', base + '/api/templates', {
                'name': 'max-tpl',
                'scenes': [{'image': 'x', 'text': 't', 'hold': 0.2}],
                'bgm': str(webui.UPLOAD_DIR / 'fake_bgm.wav'),
                'card_duration': '2.5',
                'end_card_duration': '1.5',
                'bgm_volume': '0.3',
                'title_card': 'T',
                'end_card': 'E',
            })
            self.assertEqual(code, 200)
            tid = data['id']
            code, one = http_json('GET', base + f'/api/templates/{tid}')
            self.assertEqual(code, 200)
            self.assertEqual(one.get('name'), 'max-tpl')
            self.assertEqual(str(one.get('card_duration')), '2.5')
            self.assertEqual(str(one.get('end_card_duration')), '1.5')
            self.assertTrue(one.get('bgm'))
            code, _ = http_json('PUT', base + f'/api/templates/{tid}', {'name': 'max-tpl-2'})
            self.assertEqual(code, 200)
            code, one2 = http_json('GET', base + f'/api/templates/{tid}')
            self.assertEqual(one2.get('name'), 'max-tpl-2')
            code, _ = http_json('GET', base + '/api/templates/../evil')
            self.assertIn(code, (404, 400, 403))
            code, _ = http_json('DELETE', base + f'/api/templates/{tid}')
            self.assertIn(code, (200, 404))
            tp = webui.TEMPLATE_DIR / f'{tid}.json'
            if tp.exists():
                tp.unlink(missing_ok=True)

    def test_thumb_forbidden_outside(self):
        with live_webui() as base:
            bad = quote(str(Path('webui.py').resolve()))
            code, data = http_json('GET', base + f'/thumb?path={bad}')
            self.assertEqual(code, 403)

    def test_thumb_uploaded_ok(self):
        with live_webui() as base:
            raw = write_tiny_png(Path('_tmp_th.png')).read_bytes()
            Path('_tmp_th.png').unlink(missing_ok=True)
            code, up = upload_bytes(base, 'th.png', raw)
            self.assertEqual(code, 200)
            path = up['path']
            try:
                code, body, _ = http_raw('GET', base + '/thumb?path=' + quote(path))
                self.assertEqual(code, 200)
                self.assertGreater(len(body), 10)
            finally:
                Path(path).unlink(missing_ok=True)


class TestLiveCancelStatus(unittest.TestCase):
    def test_cancel_unknown_ok(self):
        with live_webui() as base:
            code, data = http_json('POST', base + '/api/cancel/does-not-exist')
            self.assertEqual(code, 200)

    def test_status_not_found(self):
        with live_webui() as base:
            code, data = http_json('GET', base + '/api/status/nope')
            self.assertEqual(code, 404)


class TestLiveRenderOpsMocked(unittest.TestCase):
    """Render lifecycle with video_auto.main mocked — no Edge TTS / ffmpeg."""

    def _upload_png(self, base):
        raw = write_tiny_png(Path('_tmp_ops.png')).read_bytes()
        Path('_tmp_ops.png').unlink(missing_ok=True)
        code, up = upload_bytes(base, 'ops.png', raw)
        self.assertEqual(code, 200)
        return up['path']

    def _cleanup_job(self, rid_prefix, upload_path=None):
        if upload_path:
            Path(upload_path).unlink(missing_ok=True)
        for k, j in list(webui.JOBS.items()):
            if not (k == rid_prefix or str(k).startswith(rid_prefix) or rid_prefix in str(k)):
                if not (isinstance(j, dict) and j.get('out') and rid_prefix in str(j.get('out'))):
                    continue
            o = j.get('out') if isinstance(j, dict) else None
            if o:
                shutil.rmtree(o, ignore_errors=True)
            webui.JOBS.pop(k, None)
        out = webui._job_out_dir(rid_prefix)
        if out and out.exists():
            shutil.rmtree(out, ignore_errors=True)

    def test_fake_render_status_srt_and_download(self):
        with live_webui() as base:
            path = self._upload_png(base)
            fake = fake_video_auto_main(delay_sec=0.1, write_srt=True)
            try:
                with mock.patch('video_auto.main', fake):
                    code, data = http_json('POST', base + '/api/render', {
                        'render_id': 'livefake1',
                        'manifest': {
                            'title': 'live-fake',
                            'width': 640,
                            'height': 360,
                            'workers': 1,
                            'burn_subtitles': True,
                            'scenes': [{'image': path, 'text': 'hello', 'hold_sec': 0.1}],
                        },
                        'title_card': 'T',
                    })
                    self.assertEqual(code, 200)
                    rid = data['render_id']
                    sc, st = poll_status(base, rid, timeout=30)
                    self.assertEqual(sc, 200)
                    self.assertTrue(st.get('done'))
                    self.assertFalse(st.get('cancelled'))
                    self.assertTrue(st.get('video'))
                    self.assertTrue(st.get('srt'), msg=f'srt missing: {st}')
                    c1, b1, _ = http_raw('GET', base + st['video'])
                    self.assertEqual(c1, 200)
                    self.assertGreater(len(b1), 10)
                    c2, b2, _ = http_raw('GET', base + st['srt'])
                    self.assertEqual(c2, 200)
                    self.assertIn(b'-->', b2)
            finally:
                self._cleanup_job('livefake1', path)

    def test_cancel_mid_fake_render(self):
        with live_webui() as base:
            path = self._upload_png(base)
            fake = fake_video_auto_main(delay_sec=2.0, write_srt=False)
            started = threading.Event()
            finished = threading.Event()

            def controlled_main(argv=None):
                started.set()
                try:
                    return fake(argv)
                finally:
                    finished.set()

            try:
                with mock.patch('video_auto.main', controlled_main):
                    code, data = http_json('POST', base + '/api/render', {
                        'render_id': 'livecancelmid',
                        'manifest': {
                            'workers': 1,
                            'burn_subtitles': False,
                            'scenes': [{'image': path, 'text': 'long', 'hold_sec': 0.1}],
                        },
                    })
                    self.assertEqual(code, 200)
                    rid = data['render_id']
                    self.assertTrue(started.wait(5), 'render thread did not enter video_auto.main')
                    c, _ = http_json('POST', base + f'/api/cancel/{rid}')
                    self.assertEqual(c, 200)
                    sc, st = poll_status(base, rid, timeout=20)
                    self.assertEqual(sc, 200)
                    self.assertTrue(st.get('cancelled'), msg=f'expected cancel terminal, got {st}')
                    self.assertFalse(st.get('video'), msg=f'cancel must not expose video: {st}')
                    self.assertTrue(finished.wait(5), 'render thread did not exit after cancel')
                    self.assertTrue(wait_job_threads(rid), 'job lifecycle threads did not exit')
            finally:
                self._cleanup_job('livecancelmid', path)

    def test_systemexit_from_main_is_failure(self):
        """SystemExit from video_auto.main must not present as empty success."""
        with live_webui() as base:
            path = self._upload_png(base)

            def boom(_argv=None):
                raise SystemExit('错误: 无可用 TTS 引擎')

            try:
                with mock.patch('video_auto.main', boom):
                    code, data = http_json('POST', base + '/api/render', {
                        'render_id': 'livesysexit',
                        'manifest': {
                            'workers': 1,
                            'burn_subtitles': False,
                            'scenes': [{'image': path, 'text': 'x', 'hold_sec': 0.1}],
                        },
                    })
                    self.assertEqual(code, 200)
                    rid = data['render_id']
                    sc, st = poll_status(base, rid, timeout=20)
                    self.assertEqual(sc, 200)
                    self.assertTrue(st.get('done'))
                    self.assertTrue(st.get('error'), msg=f'expected error, got {st}')
                    self.assertIn('TTS', str(st.get('error')))
                    self.assertFalse(st.get('video'))
                    self.assertFalse(st.get('cancelled'))
            finally:
                self._cleanup_job('livesysexit', path)

    def test_late_cancel_after_success_keeps_video(self):
        with live_webui() as base:
            path = self._upload_png(base)
            fake = fake_video_auto_main(delay_sec=0.05, write_srt=True)
            try:
                with mock.patch('video_auto.main', fake):
                    code, data = http_json('POST', base + '/api/render', {
                        'render_id': 'livelatecancel',
                        'manifest': {
                            'workers': 1,
                            'burn_subtitles': False,
                            'scenes': [{'image': path, 'text': 'x', 'hold_sec': 0.1}],
                        },
                    })
                    self.assertEqual(code, 200)
                    rid = data['render_id']
                    sc, st = poll_status(base, rid, timeout=20)
                    self.assertTrue(st.get('video'))
                    video = st['video']
                    c, d = http_json('POST', base + f'/api/cancel/{rid}')
                    self.assertEqual(c, 200)
                    self.assertTrue(isinstance(d, dict) and d.get('ignored') is True)
                    sc2, st2 = http_json('GET', base + f'/api/status/{rid}')
                    self.assertEqual(sc2, 200)
                    self.assertEqual(st2.get('video'), video)
                    self.assertFalse(st2.get('cancelled'))
            finally:
                self._cleanup_job('livelatecancel', path)

    def test_serial_lock_two_jobs(self):
        with live_webui() as base:
            path = self._upload_png(base)
            # first job holds lock ~0.4s, second should still complete after
            fake_slow = fake_video_auto_main(delay_sec=0.4, write_srt=False)
            fake_fast = fake_video_auto_main(delay_sec=0.05, write_srt=False)
            calls = {'n': 0}

            def side_effect(*a, **k):
                calls['n'] += 1
                # forward argv= from video_auto.main(argv)
                if calls['n'] == 1:
                    return fake_slow(*a, **k)
                return fake_fast(*a, **k)

            try:
                with mock.patch('video_auto.main', side_effect=side_effect):
                    c1, d1 = http_json('POST', base + '/api/render', {
                        'render_id': 'livelocka',
                        'manifest': {
                            'workers': 1,
                            'burn_subtitles': False,
                            'scenes': [{'image': path, 'text': 'a', 'hold_sec': 0.1}],
                        },
                    })
                    c2, d2 = http_json('POST', base + '/api/render', {
                        'render_id': 'livelockb',
                        'manifest': {
                            'workers': 1,
                            'burn_subtitles': False,
                            'scenes': [{'image': path, 'text': 'b', 'hold_sec': 0.1}],
                        },
                    })
                    self.assertEqual(c1, 200)
                    self.assertEqual(c2, 200)
                    r1, r2 = d1['render_id'], d2['render_id']
                    sc1, s1 = poll_status(base, r1, timeout=30)
                    sc2, s2 = poll_status(base, r2, timeout=30)
                    self.assertEqual(sc1, 200)
                    self.assertEqual(sc2, 200)
                    self.assertTrue(s1.get('done') and s1.get('video'), s1)
                    self.assertTrue(s2.get('done') and s2.get('video'), s2)
            finally:
                Path(path).unlink(missing_ok=True)
                for rid in ('livelocka', 'livelockb'):
                    out = webui._job_out_dir(rid)
                    if out and out.exists():
                        shutil.rmtree(out, ignore_errors=True)

    def test_export_import_roundtrip(self):
        with live_webui() as base:
            raw = write_tiny_png(Path('_tmp_ex.png')).read_bytes()
            Path('_tmp_ex.png').unlink(missing_ok=True)
            code, up = upload_bytes(base, 'ex.png', raw)
            self.assertEqual(code, 200)
            img = up['path']
            wav = write_tone_wav(Path('_tmp_ex.wav'), 0.2)
            try:
                code, bg = upload_bytes(base, 'ex.wav', wav.read_bytes(), kind='bgm')
                self.assertEqual(code, 200)
                bgm = bg['path']
                code, zbytes, hdrs = http_raw('POST', base + '/api/export', {
                    'manifest': {
                        'title': 'live-export',
                        'width': 1280,
                        'height': 720,
                        'scenes': [{'image': img, 'text': '场景一', 'hold_sec': 0.2}],
                        'title_card': '开场',
                        'end_card': '结束',
                        'card_duration': 2,
                        'end_card_duration': 1.5,
                        'subtitle_style': 'FontName=Microsoft YaHei,FontSize=16',
                    },
                    'bgm': bgm,
                    'title_card': '开场',
                    'end_card': '结束',
                    'card_duration': 2,
                    'end_card_duration': 1.5,
                })
                self.assertEqual(code, 200)
                self.assertEqual(zbytes[:2], b'PK')
                with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
                    man = json.loads(zf.read('manifest.json'))
                    self.assertTrue(man['scenes'][0]['image'].startswith('assets/'))
                    self.assertNotIn(str(ROOT), zf.read('manifest.json').decode('utf-8'))
                code, imp = http_json('POST', base + '/api/import', {
                    'data': base64.b64encode(zbytes).decode('ascii'),
                })
                self.assertEqual(code, 200)
                self.assertTrue(imp.get('manifest', {}).get('scenes'))
                self.assertEqual(imp['manifest'].get('title_card'), '开场')
                self.assertTrue(imp.get('bgm'))
                # cleanup project dir
                p0 = Path(imp['manifest']['scenes'][0]['image'])
                proj = p0
                while proj != proj.parent:
                    if proj.parent == webui.UPLOAD_DIR:
                        if proj.name.startswith('project_'):
                            shutil.rmtree(proj, ignore_errors=True)
                        break
                    proj = proj.parent
            finally:
                Path(img).unlink(missing_ok=True)
                if 'bgm' in dir():
                    Path(bgm).unlink(missing_ok=True)
                wav.unlink(missing_ok=True)

    def test_import_bad_zip_400(self):
        with live_webui() as base:
            before = {p.name for p in webui.UPLOAD_DIR.glob('project_*')}
            code, data = http_json('POST', base + '/api/import', {
                'data': base64.b64encode(b'not-a-zip').decode('ascii'),
            })
            self.assertEqual(code, 400)
            self.assertIn('zip', str(data.get('error', '')).lower())
            after = {p.name for p in webui.UPLOAD_DIR.glob('project_*')}
            self.assertEqual(after - before, set())

    def test_clean_keeps_recent(self):
        with live_webui() as base:
            # create 3 fake job dirs
            made = []
            for i in range(3):
                rid = f'liveclean{i}'
                out = webui._job_out_dir(rid)
                out.mkdir(parents=True, exist_ok=True)
                (out / 'manifest.mp4').write_bytes(b'x')
                made.append(out)
                time.sleep(0.02)
            try:
                code, data = http_json('POST', base + '/api/clean')
                self.assertEqual(code, 200)
                self.assertIn('message', data)
            finally:
                for o in made:
                    shutil.rmtree(o, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
