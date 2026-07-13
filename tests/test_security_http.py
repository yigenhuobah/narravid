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

from tests.support import ROOT, make_handler, read_response, write_tiny_png
import webui


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


class TestTemplateCrud(unittest.TestCase):
    def test_reject_bad_id(self):
        h = make_handler('/api/templates/../evil')
        webui.H.do_GET(h)
        code, _ = read_response(h)
        self.assertIn(code, (404, 403))


if __name__ == '__main__':
    unittest.main()
