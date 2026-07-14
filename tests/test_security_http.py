"""Layer 2 — HTTP security / path confinement (handler-level, no live server)."""
from __future__ import annotations

import base64
import io
import json
import shutil
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import webui
from tests.support import ROOT, make_handler, read_response, write_tiny_png


class FakeThread:
    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self.target = target

    def start(self):
        # Do not run render threads in security tests
        return


class TestRenderedServing(unittest.TestCase):
    def test_traversal_forbidden(self):
        secret = ROOT / '_max_secret.txt'
        secret.write_text('SECRET', encoding='utf-8')
        try:
            h = make_handler('/rendered/../_max_secret.txt')
            webui.H.do_GET(h)
            code, data = read_response(h)
            self.assertEqual(code, 403)
        finally:
            secret.unlink(missing_ok=True)

    def test_uploads_not_served(self):
        up = write_tiny_png(webui.UPLOAD_DIR / '_max_block.png')
        try:
            rel = '/' + up.resolve().relative_to(ROOT.resolve()).as_posix()
            h = make_handler(rel)
            webui.H.do_GET(h)
            code, _ = read_response(h)
            self.assertEqual(code, 403)
        finally:
            up.unlink(missing_ok=True)

    def test_job_mp4_allowed_shape(self):
        # create fake job output
        rid = 'maxtest_job_mp4_ok'
        out = webui._job_out_dir(rid)
        self.assertIsNotNone(out)
        out.mkdir(parents=True, exist_ok=True)
        mp4 = out / 'final.mp4'
        mp4.write_bytes(b'fake-mp4')
        try:
            url = '/' + mp4.resolve().relative_to(ROOT.resolve()).as_posix()
            h = make_handler(url)
            webui.H.do_GET(h)
            code, body = read_response(h)
            self.assertEqual(code, 200)
            self.assertEqual(body, b'fake-mp4')
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_job_manifest_forbidden(self):
        rid = 'maxtest_job_manifest'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        man = out / 'manifest.json'
        man.write_text('{}', encoding='utf-8')
        try:
            url = '/' + man.resolve().relative_to(ROOT.resolve()).as_posix()
            h = make_handler(url)
            webui.H.do_GET(h)
            code, _ = read_response(h)
            self.assertEqual(code, 403)
        finally:
            shutil.rmtree(out, ignore_errors=True)


class TestUploadSanitize(unittest.TestCase):
    def test_traversal_name(self):
        raw = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8
        body = json.dumps({
            'name': '../../evil.png',
            'data': base64.b64encode(raw).decode('ascii'),
            'kind': 'image',
        }).encode('utf-8')
        h = make_handler('/api/upload', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 200)
        p = Path(data['path'])
        self.assertTrue(webui._is_under(p, webui.UPLOAD_DIR))
        self.assertTrue(p.name.endswith('evil.png'))
        p.unlink(missing_ok=True)

    def test_chinese_name_ascii_only(self):
        raw = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8
        body = json.dumps({
            'name': '测试 图片#1.png',
            'data': base64.b64encode(raw).decode('ascii'),
            'kind': 'image',
        }).encode('utf-8')
        h = make_handler('/api/upload', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 200)
        p = Path(data['path'])
        self.assertTrue(webui._is_under(p, webui.UPLOAD_DIR))
        self.assertTrue(all(ord(c) < 128 for c in p.name))
        self.assertTrue(p.name.endswith('.png'))
        p.unlink(missing_ok=True)

    def test_image_oversize_413(self):
        # body itself must stay under MAX_UPLOAD_SIZE; craft slightly over IMAGE limit
        # Use small payload with mocked size check path: raw after b64 decode
        big = b'x' * (webui.MAX_IMAGE_SIZE + 10)
        body = json.dumps({
            'name': 'big.png',
            'data': base64.b64encode(big).decode('ascii'),
            'kind': 'image',
        }).encode('utf-8')
        if len(body) > webui.MAX_UPLOAD_SIZE:
            self.skipTest('base64 body exceeds MAX_UPLOAD_SIZE; image limit enforced earlier')
        h = make_handler('/api/upload', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 413)
        self.assertIn('图片', str(data.get('error', '')))


class TestRenderIdAndMedia(unittest.TestCase):
    def test_render_id_rewritten(self):
        media = write_tiny_png(webui.UPLOAD_DIR / '_max_scene.png')
        try:
            body = json.dumps({
                'render_id': '../pwn_escape',
                'manifest': {'scenes': [{'image': str(media), 'text': 'hi'}], 'workers': 1},
            }).encode('utf-8')
            h = make_handler('/api/render', 'POST', body)
            with mock.patch('webui.threading.Thread', FakeThread):
                webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            rid = data['render_id']
            self.assertEqual(webui._sanitize_render_id(rid), rid)
            self.assertNotIn('..', rid)
            out = webui._job_out_dir(rid)
            self.assertTrue(webui._is_under(out, webui.OUT_BASE))
            if out and out.exists():
                shutil.rmtree(out, ignore_errors=True)
        finally:
            media.unlink(missing_ok=True)

    def test_outside_media_rejected(self):
        body = json.dumps({
            'manifest': {'scenes': [{'image': str(ROOT / 'webui.py'), 'text': 'x'}]},
        }).encode('utf-8')
        h = make_handler('/api/render', 'POST', body)
        with mock.patch('webui.threading.Thread', FakeThread):
            webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 400)
        self.assertIn('非法', str(data.get('error', '')))

    def test_empty_scenes_rejected(self):
        body = json.dumps({'manifest': {'scenes': []}}).encode('utf-8')
        h = make_handler('/api/render', 'POST', body)
        with mock.patch('webui.threading.Thread', FakeThread):
            webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 400)
        self.assertIn('scenes', str(data.get('error', '')).lower())

    def test_missing_image_rejected(self):
        body = json.dumps({
            'manifest': {'scenes': [{'text': 'no image'}]},
        }).encode('utf-8')
        h = make_handler('/api/render', 'POST', body)
        with mock.patch('webui.threading.Thread', FakeThread):
            webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 400)
        self.assertIn('image', str(data.get('error', '')).lower())


class TestExportImport(unittest.TestCase):
    def test_export_allowlist_rejects_outside(self):
        """Non-allowlisted absolute paths must 400 — never leak host paths into zip."""
        outside = ROOT / '_max_out.bin'
        outside.write_bytes(b'OUT')
        inside = write_tiny_png(webui.UPLOAD_DIR / '_max_in.png')
        try:
            body = json.dumps({
                'manifest': {
                    'scenes': [
                        {'image': str(outside), 'text': 'a'},
                        {'image': str(inside), 'text': 'b'},
                    ]
                }
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 400)
            self.assertIn('无法导出', str(data.get('error', '')))
        finally:
            outside.unlink(missing_ok=True)
            inside.unlink(missing_ok=True)

    def test_export_ok_rewrites_paths(self):
        inside = write_tiny_png(webui.UPLOAD_DIR / '_max_in2.png')
        try:
            body = json.dumps({
                'manifest': {
                    'scenes': [
                        {'image': str(inside), 'text': 'a'},
                    ]
                }
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            zf = zipfile.ZipFile(io.BytesIO(data))
            man = json.loads(zf.read('manifest.json'))
            self.assertTrue(man['scenes'][0]['image'].startswith('assets/'))
            # no absolute host path leakage
            raw_man = zf.read('manifest.json').decode('utf-8')
            self.assertNotIn(str(ROOT), raw_man)
            self.assertNotIn(str(inside), raw_man)
        finally:
            inside.unlink(missing_ok=True)

    def test_import_blocks_absolute_escape(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('assets/ok.png', b'\x89PNG')
            zf.writestr('manifest.json', json.dumps({
                'scenes': [
                    {'image': 'assets/ok.png', 'text': 'ok'},
                    {'image': str(ROOT / 'webui.py'), 'text': 'bad'},
                ]
            }))
        body = json.dumps({'data': base64.b64encode(buf.getvalue()).decode('ascii')}).encode('utf-8')
        h = make_handler('/api/import', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 400)
        self.assertIn('非法', str(data.get('error', '')))

    def test_import_zip_slip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('../escape_slip.txt', b'pwn')
            zf.writestr('manifest.json', json.dumps({'scenes': [{'image': 'a.png', 'text': 'x'}]}))
        body = json.dumps({'data': base64.b64encode(buf.getvalue()).decode('ascii')}).encode('utf-8')
        h = make_handler('/api/import', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 400)
        self.assertFalse((webui.UPLOAD_DIR.parent / 'escape_slip.txt').exists())

    def test_import_good(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('assets/ok.png', b'\x89PNG')
            zf.writestr('manifest.json', json.dumps({
                'scenes': [{'image': 'assets/ok.png', 'text': 'ok'}],
                'bgm': 'assets/ok.png',
            }))
        body = json.dumps({'data': base64.b64encode(buf.getvalue()).decode('ascii')}).encode('utf-8')
        h = make_handler('/api/import', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 200)
        img = Path(data['manifest']['scenes'][0]['image'])
        self.assertTrue(webui._is_under(img, webui.UPLOAD_DIR))
        # cleanup project dir
        proj = img
        while proj.parent != webui.UPLOAD_DIR and proj != proj.parent:
            if proj.name.startswith('project_'):
                shutil.rmtree(proj, ignore_errors=True)
                break
            proj = proj.parent

    def test_import_bad_zip_400(self):
        body = json.dumps({
            'data': base64.b64encode(b'not-a-zip-file').decode('ascii'),
        }).encode('utf-8')
        before = {p.name for p in webui.UPLOAD_DIR.glob('project_*')}
        h = make_handler('/api/import', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 400)
        self.assertIn('zip', str(data.get('error', '')).lower())
        after = {p.name for p in webui.UPLOAD_DIR.glob('project_*')}
        # no orphan project dirs left from failed import
        self.assertEqual(after - before, set())

    def test_export_includes_title_and_bgm_relative(self):
        inside = write_tiny_png(webui.UPLOAD_DIR / '_max_export_bgm_scene.png')
        bgm = webui.UPLOAD_DIR / '_max_export_bgm.wav'
        bgm.write_bytes(b'RIFF' + b'\x00' * 12)
        try:
            body = json.dumps({
                'manifest': {
                    'scenes': [{'image': str(inside), 'text': 'a'}],
                    'title_card': '开场',
                    'end_card': '完',
                },
                'bgm': str(bgm),
                'title_card': '开场',
                'end_card': '完',
                'card_duration': 2,
                'end_card_duration': 1.5,
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            zf = zipfile.ZipFile(io.BytesIO(data))
            man = json.loads(zf.read('manifest.json'))
            self.assertEqual(man.get('title_card'), '开场')
            self.assertEqual(man.get('end_card'), '完')
            self.assertTrue(str(man.get('bgm', '')).startswith('assets/'))
            self.assertTrue(any(n.startswith('assets/bgm') for n in zf.namelist()))
        finally:
            inside.unlink(missing_ok=True)
            bgm.unlink(missing_ok=True)


class TestTemplateCrud(unittest.TestCase):
    def test_reject_bad_id(self):
        h = make_handler('/api/templates/../evil')
        webui.H.do_GET(h)
        code, _ = read_response(h)
        self.assertIn(code, (404, 403))


class TestCancelLateAndSrtStatus(unittest.TestCase):
    def test_cancel_finished_job_ignored_keeps_video(self):
        rid = 'maxtest_late_cancel'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        mp4 = out / 'manifest.mp4'
        mp4.write_bytes(b'fake')
        srt = out / 'manifest.srt'
        srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nhi\n', encoding='utf-8')
        video_url = '/' + mp4.resolve().relative_to(ROOT.resolve()).as_posix()
        srt_url = '/' + srt.resolve().relative_to(ROOT.resolve()).as_posix()
        webui.JOBS[rid] = {
            'done': True,
            'cancelled': False,
            'video': video_url,
            'srt': srt_url,
            'progress': '完成',
            'error': '',
            'out': out,
        }
        try:
            h = make_handler(f'/api/cancel/{rid}', 'POST', b'')
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            self.assertTrue(data.get('ignored'))
            h2 = make_handler(f'/api/status/{rid}')
            webui.H.do_GET(h2)
            code2, st = read_response(h2)
            self.assertEqual(code2, 200)
            self.assertEqual(st.get('video'), video_url)
            self.assertFalse(st.get('cancelled'))
            self.assertEqual(st.get('srt'), srt_url)
        finally:
            webui.JOBS.pop(rid, None)
            shutil.rmtree(out, ignore_errors=True)

    def test_status_backfills_srt_from_out_dir(self):
        rid = 'maxtest_srt_backfill'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        mp4 = out / 'manifest.mp4'
        mp4.write_bytes(b'fake')
        (out / 'manifest.srt').write_text('1\n00:00:00,000 --> 00:00:00,500\nx\n', encoding='utf-8')
        webui.JOBS[rid] = {
            'done': True,
            'cancelled': False,
            'video': '',
            'srt': '',
            'progress': '完成',
            'error': '',
            'out': out,
        }
        try:
            h = make_handler(f'/api/status/{rid}')
            webui.H.do_GET(h)
            code, st = read_response(h)
            self.assertEqual(code, 200)
            self.assertTrue(st.get('video', '').endswith('.mp4'))
            self.assertTrue(st.get('srt', '').endswith('.srt'))
        finally:
            webui.JOBS.pop(rid, None)
            shutil.rmtree(out, ignore_errors=True)


class TestJobSrtServing(unittest.TestCase):
    def test_job_srt_allowed(self):
        rid = 'maxtest_job_srt_ok'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        srt = out / 'final.srt'
        srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nok\n', encoding='utf-8')
        try:
            url = '/' + srt.resolve().relative_to(ROOT.resolve()).as_posix()
            h = make_handler(url)
            webui.H.do_GET(h)
            code, body = read_response(h)
            self.assertEqual(code, 200)
            self.assertIn(b'-->', body)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
