"""Layer 2 — HTTP security / path confinement (handler-level, no live server)."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from urllib.parse import quote

import webui
import webui_jobs
from tests.support import ROOT, make_handler, read_response, write_tiny_png

_INITIAL_SECURITY_JOB_IDS = set(webui.JOBS)


def tearDownModule():
    leaked = set(webui.JOBS) - _INITIAL_SECURITY_JOB_IDS
    for rid in leaked:
        job = webui.JOBS.pop(rid, None)
        out = job.get('out') if isinstance(job, dict) else webui._job_out_dir(rid)
        if out:
            shutil.rmtree(out, ignore_errors=True)
    webui._set_active_render(None)
    if leaked:
        raise AssertionError(f'security tests leaked jobs: {sorted(leaked)}')


class FakeThread:
    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self.target = target

    def start(self):
        # Do not run render threads in security tests
        return


def project_dirs():
    return {p.resolve() for p in webui.UPLOAD_DIR.glob('project_*') if p.is_dir()}


def remove_new_project_dirs(before):
    for path in project_dirs() - before:
        shutil.rmtree(path, ignore_errors=True)


def response_body_bytes(handler):
    raw = handler.wfile.getvalue()
    return raw.split(b'\r\n\r\n', 1)[1] if b'\r\n\r\n' in raw else b''


def valid_project_zip(extra_members=()):
    """Build an otherwise valid import archive for failure-path tests."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr('assets/scene.png', b'\x89PNG\r\n\x1a\n')
        zf.writestr('manifest.json', json.dumps({
            'scenes': [{'image': 'assets/scene.png', 'text': 'scene'}],
        }))
        for name, payload in extra_members:
            zf.writestr(name, payload)
    return buf.getvalue()


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
            rel = '/' + up.resolve().relative_to(webui.ROOT.resolve()).as_posix()
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
            url = '/' + mp4.resolve().relative_to(webui.ROOT.resolve()).as_posix()
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
            url = '/' + man.resolve().relative_to(webui.ROOT.resolve()).as_posix()
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
        rid = None
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
        finally:
            if rid:
                webui.JOBS.pop(rid, None)
                shutil.rmtree(webui._job_out_dir(rid), ignore_errors=True)
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
            error = str(data.get('error', ''))
            self.assertNotIn(str(outside.resolve()), error)
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
            zf.writestr('assets/ok.wav', b'RIFF' + b'\x00' * 12)
            zf.writestr('manifest.json', json.dumps({
                'scenes': [{'image': 'assets/ok.png', 'text': 'ok'}],
                'bgm': 'assets/ok.wav',
            }))
        body = json.dumps({'data': base64.b64encode(buf.getvalue()).decode('ascii')}).encode('utf-8')
        h = make_handler('/api/import', 'POST', body)
        webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 200)
        img = Path(data['manifest']['scenes'][0]['image'])
        self.assertTrue(webui._is_under(img, webui.UPLOAD_DIR))
        # cleanup project dir
        for parent in img.parents:
            if parent.parent == webui.UPLOAD_DIR and parent.name.startswith('project_'):
                shutil.rmtree(parent, ignore_errors=True)
                break

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
        video_url = '/' + mp4.resolve().relative_to(webui.ROOT.resolve()).as_posix()
        srt_url = '/' + srt.resolve().relative_to(webui.ROOT.resolve()).as_posix()
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
            url = '/' + srt.resolve().relative_to(webui.ROOT.resolve()).as_posix()
            h = make_handler(url)
            webui.H.do_GET(h)
            code, body = read_response(h)
            self.assertEqual(code, 200)
            self.assertIn(b'-->', body)
        finally:
            shutil.rmtree(out, ignore_errors=True)


class TestHeadAndMediaAllowlist(unittest.TestCase):
    def test_head_does_not_serve_source(self):
        h = make_handler('/webui.py', 'HEAD')
        # do_HEAD should not 200-serve source via SimpleHTTPRequestHandler
        if hasattr(webui.H, 'do_HEAD'):
            webui.H.do_HEAD(h)
            code, _ = read_response(h)
            self.assertIn(code, (403, 404))
        else:
            self.fail('do_HEAD not implemented')

    def test_export_rejects_internal_log(self):
        rid = 'maxtest_export_log'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        log = out / '_stderr.log'
        log.write_text('secret', encoding='utf-8')
        try:
            body = json.dumps({
                'manifest': {'scenes': [{'image': str(log), 'text': 'x'}]},
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 400)
        finally:
            import shutil
            shutil.rmtree(out, ignore_errors=True)


class TestB64StreamWrite(unittest.TestCase):
    def test_write_b64_enforces_max(self):
        big = base64.b64encode(b'0123456789abcdef').decode('ascii')
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / 'x.bin'
            with self.assertRaises(ValueError):
                webui._write_b64_to_file(big, dest, max_bytes=8)


class TestHandlerAlias(unittest.TestCase):
    def test_h_is_webui_handler(self):
        self.assertIs(webui.H, webui.WebUIHandler)


class TestRequestBodyValidation(unittest.TestCase):
    def test_post_global_body_limit_rejected_before_read(self):
        h = make_handler('/api/upload', 'POST')
        h.headers['Content-Length'] = str(webui.MAX_UPLOAD_SIZE + 1)
        h.rfile = mock.Mock()
        h.rfile.read.side_effect = AssertionError('oversized request body must not be read')
        webui.H.do_POST(h)
        code, _ = read_response(h)
        self.assertEqual(code, 413)
        h.rfile.read.assert_not_called()

    def test_template_post_uses_template_body_limit(self):
        h = make_handler('/api/templates', 'POST')
        h.headers['Content-Length'] = str(webui.MAX_TEMPLATE_BODY + 1)
        h.rfile = mock.Mock()
        h.rfile.read.side_effect = AssertionError('oversized template body must not be read')
        webui.H.do_POST(h)
        code, _ = read_response(h)
        self.assertEqual(code, 413)
        h.rfile.read.assert_not_called()

    def test_template_put_body_limit_rejected_before_read(self):
        h = make_handler('/api/templates/not-present', 'PUT')
        h.headers['Content-Length'] = str(webui.MAX_TEMPLATE_BODY + 1)
        h.rfile = mock.Mock()
        h.rfile.read.side_effect = AssertionError('oversized template body must not be read')
        webui.H.do_PUT(h)
        code, _ = read_response(h)
        self.assertEqual(code, 413)
        h.rfile.read.assert_not_called()

    def test_empty_command_posts_reject_non_json_content_type(self):
        for path in ('/api/cancel/not-present', '/api/clean'):
            with self.subTest(path=path):
                h = make_handler(path, 'POST', b'')
                h.headers['Content-Type'] = 'text/plain'
                webui.H.do_POST(h)
                code, data = read_response(h)
                self.assertEqual(code, 415)
                self.assertIn('Content-Type', data.get('error', ''))

    def test_post_rejects_invalid_content_lengths(self):
        raw = base64.b64encode(b'payload').decode('ascii')
        body = json.dumps({'name': 'length.png', 'data': raw, 'kind': 'image'}).encode('utf-8')
        before = {p.resolve() for p in webui.UPLOAD_DIR.iterdir()}
        try:
            for value in ('-1', 'not-an-integer'):
                with self.subTest(value=value):
                    h = make_handler('/api/upload', 'POST', body)
                    h.headers['Content-Length'] = value
                    webui.H.do_POST(h)
                    code, _ = read_response(h)
                    self.assertEqual(code, 400)
        finally:
            for path in {p.resolve() for p in webui.UPLOAD_DIR.iterdir()} - before:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)

    def test_put_rejects_invalid_content_lengths(self):
        for value in ('-1', 'not-an-integer'):
            with self.subTest(value=value):
                h = make_handler('/api/templates/not-present', 'PUT', b'{}')
                h.headers['Content-Length'] = value
                webui.H.do_PUT(h)
                code, _ = read_response(h)
                self.assertEqual(code, 400)

    def test_incomplete_request_body_rejected(self):
        h = make_handler('/api/upload', 'POST', b'{}')
        h.headers['Content-Length'] = '3'
        webui.H.do_POST(h)
        code, _ = read_response(h)
        self.assertEqual(code, 400)

    def test_explicit_non_json_content_type_rejected(self):
        cases = [
            ('/api/upload', 'POST'),
            ('/api/templates/template-id', 'PUT'),
        ]
        for path, method in cases:
            with self.subTest(path=path, method=method):
                h = make_handler(path, method, b'{}')
                h.headers['Content-Type'] = 'text/plain'
                if method == 'POST':
                    webui.H.do_POST(h)
                else:
                    webui.H.do_PUT(h)
                code, data = read_response(h)
                self.assertEqual(code, 415)
                self.assertIn('Content-Type', data.get('error', ''))

    def test_malformed_and_non_object_json_are_client_errors(self):
        cases = [
            ('/api/upload', b'{'),
            ('/api/templates', b'[]'),
            ('/api/export', b'null'),
        ]
        for path, body in cases:
            with self.subTest(path=path, body=body):
                h = make_handler(path, 'POST', body)
                h.headers['Content-Type'] = 'application/json'
                webui.H.do_POST(h)
                code, data = read_response(h)
                self.assertEqual(code, 400)
                self.assertIn('error', data)
                self.assertNotIn('line 1 column', data['error'])

    def test_non_finite_json_numbers_are_rejected_before_mutation(self):
        before = {p.resolve() for p in webui.TEMPLATE_DIR.glob('*.json')}
        try:
            for constant in ('NaN', 'Infinity', '-Infinity', '1e400'):
                with self.subTest(constant=constant):
                    body = (
                        '{"name":"bad-number","scenes":[],"value":'
                        + constant
                        + '}'
                    ).encode('ascii')
                    h = make_handler('/api/templates', 'POST', body)
                    webui.H.do_POST(h)
                    code, data = read_response(h)
                    self.assertEqual(code, 400)
                    self.assertIn('valid JSON', data.get('error', ''))
            self.assertEqual(
                {p.resolve() for p in webui.TEMPLATE_DIR.glob('*.json')}, before,
            )
        finally:
            for path in {p.resolve() for p in webui.TEMPLATE_DIR.glob('*.json')} - before:
                path.unlink(missing_ok=True)


    def test_template_and_export_reject_invalid_nested_shapes(self):
        before = {p.resolve() for p in webui.TEMPLATE_DIR.glob('*.json')}
        cases = [
            ('/api/templates', {'scenes': 1}),
            ('/api/export', {'manifest': {'scenes': 1}}),
        ]
        try:
            for path, payload in cases:
                with self.subTest(path=path):
                    body = json.dumps(payload).encode('utf-8')
                    h = make_handler(path, 'POST', body)
                    webui.H.do_POST(h)
                    code, data = read_response(h)
                    self.assertEqual(code, 400)
                    self.assertIn('error', data)
        finally:
            for path in {p.resolve() for p in webui.TEMPLATE_DIR.glob('*.json')} - before:
                path.unlink(missing_ok=True)

    def test_template_put_malformed_json_is_client_error(self):
        tid = 'maxtest_put_json'
        tp = webui.TEMPLATE_DIR / f'{tid}.json'
        tp.write_text(json.dumps({'id': tid, 'name': 'before'}), encoding='utf-8')
        try:
            h = make_handler(f'/api/templates/{tid}', 'PUT', b'{')
            h.headers['Content-Type'] = 'application/json; charset=utf-8'
            webui.H.do_PUT(h)
            code, data = read_response(h)
            self.assertEqual(code, 400)
            self.assertIn('error', data)
        finally:
            tp.unlink(missing_ok=True)


class TestUploadBoundaries(unittest.TestCase):
    def test_invalid_base64_rejected_without_artifact(self):
        before = {p.resolve() for p in webui.UPLOAD_DIR.iterdir()}
        body = json.dumps({'name': 'bad.png', 'data': '%%%%', 'kind': 'image'}).encode('utf-8')
        try:
            h = make_handler('/api/upload', 'POST', body)
            webui.H.do_POST(h)
            code, _ = read_response(h)
            self.assertEqual(code, 400)
            self.assertEqual({p.resolve() for p in webui.UPLOAD_DIR.iterdir()}, before)
        finally:
            for path in {p.resolve() for p in webui.UPLOAD_DIR.iterdir()} - before:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)

    def test_disallowed_extensions_rejected_without_artifact(self):
        before = {p.resolve() for p in webui.UPLOAD_DIR.iterdir()}
        try:
            for name in ('page.html', 'program.exe'):
                with self.subTest(name=name):
                    body = json.dumps({
                        'name': name,
                        'data': base64.b64encode(b'untrusted').decode('ascii'),
                        'kind': 'image',
                    }).encode('utf-8')
                    h = make_handler('/api/upload', 'POST', body)
                    webui.H.do_POST(h)
                    code, _ = read_response(h)
                    self.assertEqual(code, 400)
        finally:
            for path in {p.resolve() for p in webui.UPLOAD_DIR.iterdir()} - before:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        self.assertEqual({p.resolve() for p in webui.UPLOAD_DIR.iterdir()}, before)

    def test_video_extension_uses_video_size_limit(self):
        raw = b'12345678'
        body = json.dumps({
            'name': 'clip.MP4',
            'data': base64.b64encode(raw).decode('ascii'),
            'kind': 'image',
        }).encode('utf-8')
        with mock.patch.object(webui, 'MAX_IMAGE_SIZE', 4), mock.patch.object(webui, 'MAX_VIDEO_SIZE', 8):
            h = make_handler('/api/upload', 'POST', body)
            webui.H.do_POST(h)
        code, data = read_response(h)
        self.assertEqual(code, 200)
        path = Path(data['path'])
        try:
            self.assertEqual(data['size'], len(raw))
            self.assertEqual(path.suffix, '.mp4')
        finally:
            path.unlink(missing_ok=True)


class TestRenderInputBoundaries(unittest.TestCase):
    def test_scene_entries_must_be_objects(self):
        body = json.dumps({'manifest': {'scenes': ['not-an-object']}}).encode('utf-8')
        h = make_handler('/api/render', 'POST', body)
        with mock.patch('webui.threading.Thread', FakeThread):
            webui.H.do_POST(h)
        code, _ = read_response(h)
        self.assertEqual(code, 400)

    def test_bgm_outside_media_roots_rejected(self):
        media = write_tiny_png(webui.UPLOAD_DIR / '_max_bgm_scene.png')
        try:
            body = json.dumps({
                'manifest': {'scenes': [{'image': str(media), 'text': 'ok'}]},
                'bgm': str(ROOT / 'webui.py'),
            }).encode('utf-8')
            h = make_handler('/api/render', 'POST', body)
            with mock.patch('webui.threading.Thread', FakeThread):
                webui.H.do_POST(h)
            code, _ = read_response(h)
            self.assertEqual(code, 400)
        finally:
            media.unlink(missing_ok=True)

    def test_non_media_file_inside_upload_root_rejected(self):
        non_media = webui.UPLOAD_DIR / '_max_not_media.html'
        non_media.write_text('<script>bad()</script>', encoding='utf-8')
        try:
            body = json.dumps({
                'manifest': {'scenes': [{'image': str(non_media), 'text': 'x'}]},
            }).encode('utf-8')
            h = make_handler('/api/render', 'POST', body)
            with mock.patch('webui.threading.Thread', FakeThread):
                webui.H.do_POST(h)
            code, _ = read_response(h)
            self.assertEqual(code, 400)
        finally:
            non_media.unlink(missing_ok=True)

    def test_relative_upload_media_is_resolved_before_job_creation(self):
        rid = 'maxtest_relative_media'
        out = webui._job_out_dir(rid)
        media = write_tiny_png(webui.UPLOAD_DIR / '_max_relative.png')
        shutil.rmtree(out, ignore_errors=True)
        webui.JOBS.pop(rid, None)
        try:
            body = json.dumps({
                'render_id': rid,
                'manifest': {'scenes': [{'image': media.name, 'text': 'ok'}]},
            }).encode('utf-8')
            h = make_handler('/api/render', 'POST', body)
            with mock.patch('webui.threading.Thread', FakeThread):
                webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            self.assertEqual(data['render_id'], rid)
            stored = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(Path(stored['scenes'][0]['image']).resolve(), media.resolve())
        finally:
            webui.JOBS.pop(rid, None)
            shutil.rmtree(out, ignore_errors=True)
            media.unlink(missing_ok=True)

    def test_duplicate_live_render_id_is_replaced(self):
        requested = 'maxtest_duplicate_id'
        media = write_tiny_png(webui.UPLOAD_DIR / '_max_duplicate.png')
        webui.JOBS[requested] = {'done': False}
        actual = None
        try:
            body = json.dumps({
                'render_id': requested,
                'manifest': {'scenes': [{'image': str(media), 'text': 'ok'}]},
            }).encode('utf-8')
            h = make_handler('/api/render', 'POST', body)
            with mock.patch('webui.threading.Thread', FakeThread):
                webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            actual = data['render_id']
            self.assertNotEqual(actual, requested)
            self.assertEqual(webui._sanitize_render_id(actual), actual)
        finally:
            webui.JOBS.pop(requested, None)
            if actual:
                webui.JOBS.pop(actual, None)
                shutil.rmtree(webui._job_out_dir(actual), ignore_errors=True)
            media.unlink(missing_ok=True)


    def test_stale_disk_render_id_is_rewritten_without_touching_existing_output(self):
        requested = 'maxtest_stale_disk_id'
        stale_out = webui._job_out_dir(requested)
        media = write_tiny_png(webui.UPLOAD_DIR / '_max_stale_disk.png')
        stale_out.mkdir(parents=True, exist_ok=True)
        marker = stale_out / 'keep.txt'
        marker.write_text('existing render', encoding='utf-8')
        actual = None
        try:
            body = json.dumps({
                'render_id': requested,
                'manifest': {'scenes': [{'image': str(media), 'text': 'ok'}]},
            }).encode('utf-8')
            h = make_handler('/api/render', 'POST', body)
            with mock.patch('webui.threading.Thread', FakeThread):
                webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            actual = data['render_id']
            self.assertNotEqual(actual, requested)
            self.assertIn(actual, webui.JOBS)
            actual_out = webui._job_out_dir(actual)
            self.assertTrue(actual_out.is_dir())
            self.assertTrue((actual_out / 'manifest.json').is_file())
            self.assertEqual(marker.read_text(encoding='utf-8'), 'existing render')
        finally:
            webui.JOBS.pop(requested, None)
            if actual:
                webui.JOBS.pop(actual, None)
                shutil.rmtree(webui._job_out_dir(actual), ignore_errors=True)
            shutil.rmtree(stale_out, ignore_errors=True)
            media.unlink(missing_ok=True)

    def test_render_setup_failure_removes_output_and_releases_reservation(self):
        requested = 'maxtest_setup_failure'
        out = webui._job_out_dir(requested)
        media = write_tiny_png(webui.UPLOAD_DIR / '_max_setup_failure.png')
        shutil.rmtree(out, ignore_errors=True)
        try:
            body = json.dumps({
                'render_id': requested,
                'manifest': {'scenes': [{'image': str(media), 'text': 'ok'}]},
            }).encode('utf-8')
            h = make_handler('/api/render', 'POST', body)
            with mock.patch('video_auto.normalize_manifest', side_effect=ValueError('bad manifest')):
                webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 400)
            self.assertIn('manifest', data.get('error', ''))
            self.assertFalse(out.exists())
            self.assertTrue(webui._reserve_render_id(requested))
            webui._release_render_id(requested)
        finally:
            webui._release_render_id(requested)
            shutil.rmtree(out, ignore_errors=True)
            media.unlink(missing_ok=True)


class TestCleanReservationSafety(unittest.TestCase):
    def test_clean_preserves_reservation_created_during_directory_enumeration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rid = 'maxtest_pending_clean'
            protected = root / rid
            for index in range(6):
                directory = root / f'recent_{index}'
                directory.mkdir()
                os.utime(directory, (100 + index, 100 + index))

            real_iterdir = Path.iterdir
            interleaved = False

            def reserve_while_enumerating(path):
                nonlocal interleaved
                if path.resolve() == root.resolve() and not interleaved:
                    protected.mkdir()
                    os.utime(protected, (1, 1))
                    self.assertTrue(webui._reserve_render_id(rid))
                    interleaved = True
                return real_iterdir(path)

            with (
                mock.patch.object(webui, 'OUT_BASE', root),
                mock.patch.object(webui_jobs, 'OUT_BASE', root),
                mock.patch.object(Path, 'iterdir', reserve_while_enumerating),
            ):
                try:
                    h = make_handler('/api/clean', 'POST', b'{}')
                    webui.H.do_POST(h)
                finally:
                    webui._release_render_id(rid)

            code, data = read_response(h)
            self.assertTrue(interleaved)
            self.assertEqual(code, 200)
            self.assertEqual(data.get('cleaned'), 1)
            self.assertTrue(protected.is_dir())


class TestGetAndHeadPolicies(unittest.TestCase):
    def test_thumb_allows_uploaded_media_and_blocks_source(self):
        media = write_tiny_png(webui.UPLOAD_DIR / '_max_thumb.png')
        try:
            h = make_handler('/thumb?path=' + quote(str(media)))
            webui.H.do_GET(h)
            code, body = read_response(h)
            self.assertEqual(code, 200)
            self.assertEqual(body, media.read_bytes())

            denied = make_handler('/thumb?path=' + quote(str(ROOT / 'webui.py')))
            webui.H.do_GET(denied)
            denied_code, _ = read_response(denied)
            self.assertEqual(denied_code, 403)
        finally:
            media.unlink(missing_ok=True)

    def test_thumb_rejects_non_media_inside_upload_root(self):
        non_media = webui.UPLOAD_DIR / '_max_thumb_page.html'
        non_media.write_text('<script>bad()</script>', encoding='utf-8')
        try:
            h = make_handler('/thumb?path=' + quote(str(non_media)))
            webui.H.do_GET(h)
            code, _ = read_response(h)
            self.assertEqual(code, 403)
        finally:
            non_media.unlink(missing_ok=True)

    def test_thumb_uses_specific_content_types_for_webp_and_bmp(self):
        for suffix, expected in (('.webp', b'image/webp'), ('.bmp', b'image/bmp')):
            media = webui.UPLOAD_DIR / f'_max_thumb_type{suffix}'
            media.write_bytes(b'fake-image')
            try:
                h = make_handler('/thumb?path=' + quote(str(media)))
                webui.H.do_GET(h)
                code, body = read_response(h)
                self.assertEqual(code, 200)
                self.assertEqual(body, b'fake-image')
                self.assertIn(b'Content-Type: ' + expected, h.wfile.getvalue())
            finally:
                media.unlink(missing_ok=True)

    def test_bgm_list_includes_all_supported_audio_extensions(self):
        bgm = webui.UPLOAD_DIR / '_max_bgm_list.m4a'
        bgm.write_bytes(b'fake-m4a')
        try:
            h = make_handler('/api/bgm-list')
            webui.H.do_GET(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            self.assertIn(str(bgm.resolve()), {item['path'] for item in data})
        finally:
            bgm.unlink(missing_ok=True)


    def test_rendered_audio_and_source_are_not_served(self):
        rid = 'maxtest_rendered_policy'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        wav = out / 'narration.wav'
        wav.write_bytes(b'RIFF-private')
        try:
            wav_url = '/' + wav.resolve().relative_to(webui.ROOT.resolve()).as_posix()
            h = make_handler(wav_url)
            webui.H.do_GET(h)
            code, _ = read_response(h)
            self.assertEqual(code, 403)

            source = make_handler('/webui.py')
            webui.H.do_GET(source)
            source_code, source_body = read_response(source)
            self.assertEqual(source_code, 404)
            self.assertNotIn(b'class WebUIHandler', source_body)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_head_rendered_media_has_length_and_no_body(self):
        rid = 'maxtest_head_media'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        media = out / 'final.mp4'
        payload = b'fake-video-body'
        media.write_bytes(payload)
        try:
            url = '/' + media.resolve().relative_to(webui.ROOT.resolve()).as_posix()
            h = make_handler(url, 'HEAD')
            webui.H.do_HEAD(h)
            code, _ = read_response(h)
            self.assertEqual(code, 200)
            self.assertEqual(response_body_bytes(h), b'')
            self.assertIn(f'Content-Length: {len(payload)}'.encode('ascii'), h.wfile.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_head_never_writes_route_bodies(self):
        rid = 'maxtest_head_status'
        webui.JOBS[rid] = {'done': False, 'progress': 'queued', 'video': '', 'srt': ''}
        try:
            for path, expected in (
                ('/', 200),
                (f'/api/status/{rid}', 200),
                ('/webui.py', 404),
            ):
                with self.subTest(path=path):
                    h = make_handler(path, 'HEAD')
                    webui.H.do_HEAD(h)
                    code, _ = read_response(h)
                    self.assertEqual(code, expected)
                    self.assertEqual(response_body_bytes(h), b'')
        finally:
            webui.JOBS.pop(rid, None)


class TestTemplateSecurityBoundaries(unittest.TestCase):
    def test_crud_preserves_server_owned_fields(self):
        create_body = json.dumps({
            'id': '../client-controlled',
            'date': '1900-01-01',
            'count': 999,
            'name': 'before',
            'scenes': [{'image': 'placeholder.png', 'text': 'text'}],
        }).encode('utf-8')
        create = make_handler('/api/templates', 'POST', create_body)
        create.headers['Content-Type'] = 'application/json'
        webui.H.do_POST(create)
        create_code, create_data = read_response(create)
        self.assertEqual(create_code, 200)
        tid = create_data['id']
        tp = webui.TEMPLATE_DIR / f'{tid}.json'
        try:
            self.assertTrue(tp.is_file())
            self.assertNotEqual(tid, '../client-controlled')

            update_body = json.dumps({
                'id': '../replacement',
                'date': '1900-01-02',
                'count': 0,
                'name': 'after',
                'subtitle_style': 'FontSize=18',
                'scenes': [],
            }).encode('utf-8')
            update = make_handler(f'/api/templates/{tid}', 'PUT', update_body)
            webui.H.do_PUT(update)
            update_code, _ = read_response(update)
            self.assertEqual(update_code, 200)

            get_one = make_handler(f'/api/templates/{tid}')
            webui.H.do_GET(get_one)
            get_code, template = read_response(get_one)
            self.assertEqual(get_code, 200)
            self.assertEqual(template['id'], tid)
            self.assertEqual(template['name'], 'after')
            self.assertEqual(template['count'], 1)
            self.assertEqual(len(template['scenes']), 1)
            self.assertEqual(template['subtitle_style'], 'FontSize=18')

            delete = make_handler(f'/api/templates/{tid}', 'DELETE')
            webui.H.do_DELETE(delete)
            delete_code, _ = read_response(delete)
            self.assertEqual(delete_code, 200)
            self.assertFalse(tp.exists())
        finally:
            tp.unlink(missing_ok=True)

    def test_invalid_template_ids_rejected_for_all_methods(self):
        for tid in ('..\\evil', '%2e%2e', 'x' * 65):
            with self.subTest(tid=tid, method='GET'):
                h = make_handler(f'/api/templates/{tid}')
                webui.H.do_GET(h)
                code, _ = read_response(h)
                self.assertEqual(code, 404)
            with self.subTest(tid=tid, method='PUT'):
                h = make_handler(f'/api/templates/{tid}', 'PUT', b'{}')
                webui.H.do_PUT(h)
                code, _ = read_response(h)
                self.assertEqual(code, 404)
            with self.subTest(tid=tid, method='DELETE'):
                h = make_handler(f'/api/templates/{tid}', 'DELETE')
                webui.H.do_DELETE(h)
                code, _ = read_response(h)
                self.assertEqual(code, 404)


class TestExportClosure(unittest.TestCase):
    def test_export_includes_only_referenced_media(self):
        rid = 'maxtest_export_closure'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        final = out / 'final.mp4'
        final.write_bytes(b'final-video')
        (out / 'narration.wav').write_bytes(b'private-audio')
        (out / '_stderr.log').write_text('private-log', encoding='utf-8')
        (out / 'manifest.json').write_text('{"private": true}', encoding='utf-8')
        try:
            body = json.dumps({
                'manifest': {
                    'scenes': [
                        {'image': str(final), 'text': 'first'},
                        {'image': str(final), 'text': 'duplicate'},
                    ],
                },
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                self.assertEqual(set(zf.namelist()), {'manifest.json', 'assets/scene_000.mp4'})
                exported = json.loads(zf.read('manifest.json'))
                self.assertEqual(exported['scenes'][0]['image'], 'assets/scene_000.mp4')
                self.assertEqual(exported['scenes'][1]['image'], 'assets/scene_000.mp4')
                self.assertEqual(zf.read('assets/scene_000.mp4'), b'final-video')
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_large_export_rolls_spooled_zip_to_disk(self):
        scene = webui.UPLOAD_DIR / '_max_spooled_export.mp4'
        scene.write_bytes(os.urandom(9 * 1024 * 1024))
        created = []
        real_spooled_file = tempfile.SpooledTemporaryFile

        def tracked_spooled_file(*args, **kwargs):
            file_obj = real_spooled_file(*args, **kwargs)
            created.append(file_obj)
            return file_obj

        try:
            body = json.dumps({
                'manifest': {'scenes': [{'image': str(scene), 'text': 'scene'}]},
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            with mock.patch.object(
                webui.tempfile,
                'SpooledTemporaryFile',
                side_effect=tracked_spooled_file,
            ):
                webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            self.assertTrue(data.startswith(b'PK'))
            self.assertEqual(len(created), 1)
            self.assertTrue(created[0]._rolled)
        finally:
            scene.unlink(missing_ok=True)

    def test_export_rewrites_bgm_from_manifest(self):
        scene = write_tiny_png(webui.UPLOAD_DIR / '_max_manifest_bgm_scene.png')
        bgm = webui.UPLOAD_DIR / '_max_manifest_bgm.wav'
        bgm.write_bytes(b'manifest-bgm')
        try:
            body = json.dumps({
                'manifest': {
                    'scenes': [{'image': str(scene), 'text': 'scene'}],
                    'bgm': str(bgm),
                },
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                exported = json.loads(zf.read('manifest.json'))
                self.assertEqual(exported['bgm'], 'assets/bgm.wav')
                self.assertEqual(zf.read('assets/bgm.wav'), b'manifest-bgm')
                self.assertNotIn(str(bgm), zf.read('manifest.json').decode('utf-8'))
        finally:
            scene.unlink(missing_ok=True)
            bgm.unlink(missing_ok=True)

    def test_top_level_bgm_overrides_manifest_bgm(self):
        scene = write_tiny_png(webui.UPLOAD_DIR / '_max_bgm_precedence_scene.png')
        manifest_bgm = webui.UPLOAD_DIR / '_max_bgm_manifest.wav'
        request_bgm = webui.UPLOAD_DIR / '_max_bgm_request.wav'
        manifest_bgm.write_bytes(b'old-bgm')
        request_bgm.write_bytes(b'new-bgm')
        try:
            body = json.dumps({
                'manifest': {
                    'scenes': [{'image': str(scene), 'text': 'scene'}],
                    'bgm': str(manifest_bgm),
                },
                'bgm': str(request_bgm),
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, data = read_response(h)
            self.assertEqual(code, 200)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                exported = json.loads(zf.read('manifest.json'))
                self.assertEqual(exported['bgm'], 'assets/bgm.wav')
                self.assertEqual(zf.read('assets/bgm.wav'), b'new-bgm')
        finally:
            scene.unlink(missing_ok=True)
            manifest_bgm.unlink(missing_ok=True)
            request_bgm.unlink(missing_ok=True)

    def test_export_rejects_internal_file_as_bgm(self):
        rid = 'maxtest_export_internal_bgm'
        out = webui._job_out_dir(rid)
        out.mkdir(parents=True, exist_ok=True)
        internal = out / '_warnings.txt'
        internal.write_text('private warning', encoding='utf-8')
        scene = write_tiny_png(webui.UPLOAD_DIR / '_max_internal_bgm_scene.png')
        try:
            body = json.dumps({
                'manifest': {'scenes': [{'image': str(scene), 'text': 'scene'}]},
                'bgm': str(internal),
            }).encode('utf-8')
            h = make_handler('/api/export', 'POST', body)
            webui.H.do_POST(h)
            code, _ = read_response(h)
            self.assertEqual(code, 400)
        finally:
            scene.unlink(missing_ok=True)
            shutil.rmtree(out, ignore_errors=True)


class TestImportResourceLimits(unittest.TestCase):
    def _post_zip(self, raw):
        body = json.dumps({'data': base64.b64encode(raw).decode('ascii')}).encode('utf-8')
        h = make_handler('/api/import', 'POST', body)
        webui.H.do_POST(h)
        return read_response(h)

    def test_import_rejects_non_finite_manifest_numbers_and_cleans_project(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as zf:
            zf.writestr('assets/scene.png', b'png')
            zf.writestr(
                'manifest.json',
                '{"width": 1e400, "scenes": [{"image": "assets/scene.png"}]}',
            )
        before = project_dirs()
        try:
            code, data = self._post_zip(raw.getvalue())
            self.assertEqual(code, 400)
            self.assertIn('valid JSON', data.get('error', ''))
            self.assertEqual(project_dirs(), before)
        finally:
            remove_new_project_dirs(before)

    def test_import_uuid_collision_preserves_existing_project(self):
        existing_id = 'collision'
        fresh_id = 'fresh'
        existing = webui.UPLOAD_DIR / f'project_{existing_id}'
        marker = existing / 'keep.txt'
        existing.mkdir(parents=True, exist_ok=True)
        marker.write_text('existing project', encoding='utf-8')
        before = project_dirs()
        first = mock.Mock(hex=existing_id)
        second = mock.Mock(hex=fresh_id)
        try:
            with mock.patch.object(webui.uuid, 'uuid4', side_effect=[first, second]):
                code, data = self._post_zip(valid_project_zip())
            self.assertEqual(code, 200)
            self.assertEqual(marker.read_text(encoding='utf-8'), 'existing project')
            imported_scene = Path(data['manifest']['scenes'][0]['image'])
            self.assertEqual(imported_scene.parents[1], webui.UPLOAD_DIR / f'project_{fresh_id}')
        finally:
            remove_new_project_dirs(before)
            shutil.rmtree(existing, ignore_errors=True)

    def test_absolute_archive_member_rejected_and_cleaned(self):
        raw = valid_project_zip([('/escape.txt', b'outside')])
        before = project_dirs()
        try:
            code, data = self._post_zip(raw)
            self.assertEqual(code, 400)
            self.assertIn('/escape.txt', data.get('error', ''))
            self.assertEqual(project_dirs(), before)
        finally:
            remove_new_project_dirs(before)

    def test_too_many_archive_members_rejected_and_cleaned(self):
        extras = [(f'empty/{index}.txt', b'') for index in range(1999)]
        raw = valid_project_zip(extras)
        before = project_dirs()
        try:
            code, data = self._post_zip(raw)
            self.assertEqual(code, 400)
            self.assertIn('2000', data.get('error', ''))
            self.assertEqual(project_dirs(), before)
        finally:
            remove_new_project_dirs(before)

    def test_declared_extract_size_limit_rejected_and_cleaned(self):
        class OversizedInfo:
            def __init__(self, file_size):
                self.file_size = file_size

            @staticmethod
            def is_dir():
                return False

        class OversizedArchive:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def namelist():
                return ['assets/scene.png', 'manifest.json', 'large.bin']

            @staticmethod
            def getinfo(name):
                if name == 'large.bin':
                    return OversizedInfo(500 * 1024 * 1024 + 1)
                return OversizedInfo(1)

        raw = valid_project_zip()
        before = project_dirs()
        try:
            with mock.patch.object(zipfile, 'ZipFile', OversizedArchive):
                code, data = self._post_zip(raw)
            self.assertEqual(code, 400)
            self.assertIn('500MB', data.get('error', ''))
            self.assertEqual(project_dirs(), before)
        finally:
            remove_new_project_dirs(before)

    def test_archive_read_error_rejected_and_cleaned(self):
        manifest_data = json.dumps({
            'scenes': [{'image': 'assets/scene.png', 'text': 'scene'}],
        }).encode('utf-8')

        class EntryInfo:
            def __init__(self, name, data):
                self.filename = name
                self.data = data
                self.file_size = len(data)

            @staticmethod
            def is_dir():
                return False

        class BrokenArchive:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            infos = {
                'assets/scene.png': EntryInfo('assets/scene.png', b'\x89PNG'),
                'manifest.json': EntryInfo('manifest.json', manifest_data),
                'broken.bin': EntryInfo('broken.bin', b'x'),
            }

            @classmethod
            def namelist(cls):
                return list(cls.infos)

            @classmethod
            def getinfo(cls, name):
                return cls.infos[name]

            @staticmethod
            def open(info, _mode):
                if info.filename == 'broken.bin':
                    raise zipfile.BadZipFile('bad CRC')
                return io.BytesIO(info.data)

        raw = valid_project_zip()
        before = project_dirs()
        try:
            with mock.patch.object(zipfile, 'ZipFile', BrokenArchive):
                code, data = self._post_zip(raw)
            self.assertEqual(code, 400)
            self.assertEqual(data.get('error'), 'invalid zip archive')
            self.assertEqual(project_dirs(), before)
        finally:
            remove_new_project_dirs(before)

    def test_actual_extract_size_limit_rejected_and_cleaned(self):
        manifest_data = json.dumps({
            'scenes': [{'image': 'assets/scene.png', 'text': 'scene'}],
        }).encode('utf-8')

        class UnderreportedInfo:
            def __init__(self, name, data=b''):
                self.filename = name
                self.data = data
                self.file_size = 0

            @staticmethod
            def is_dir():
                return False

        class RepeatingSource:
            chunk = b'x' * (1024 * 1024)

            def __init__(self):
                self.remaining = 501

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _size):
                if self.remaining <= 0:
                    return b''
                self.remaining -= 1
                return self.chunk

        class StreamingArchive:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            infos = {
                'assets/scene.png': UnderreportedInfo('assets/scene.png', b'\x89PNG'),
                'manifest.json': UnderreportedInfo('manifest.json', manifest_data),
                'large.bin': UnderreportedInfo('large.bin'),
            }

            @classmethod
            def namelist(cls):
                return list(cls.infos)

            @classmethod
            def getinfo(cls, name):
                return cls.infos[name]

            @staticmethod
            def open(info, _mode):
                if info.filename == 'large.bin':
                    return RepeatingSource()
                return io.BytesIO(info.data)

        class Sink:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def write(data):
                return len(data)

            @staticmethod
            def close():
                return None

        raw = valid_project_zip()
        before = project_dirs()
        try:
            with (
                mock.patch.object(zipfile, 'ZipFile', StreamingArchive),
                mock.patch('builtins.open', return_value=Sink()),
                mock.patch.object(Path, 'open', return_value=Sink()),
            ):
                code, data = self._post_zip(raw)
            self.assertEqual(code, 400)
            self.assertIn('500MB', data.get('error', ''))
            self.assertEqual(project_dirs(), before)
        finally:
            remove_new_project_dirs(before)

    def test_symlink_member_is_written_as_regular_file(self):
        buf = io.BytesIO()
        link_info = zipfile.ZipInfo('assets/link.png')
        link_info.create_system = 3
        link_info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr(link_info, b'../../outside.png')
            zf.writestr('manifest.json', json.dumps({
                'scenes': [{'image': 'assets/link.png', 'text': 'scene'}],
            }))
        before = project_dirs()
        try:
            code, data = self._post_zip(buf.getvalue())
            self.assertEqual(code, 200)
            imported = Path(data['manifest']['scenes'][0]['image'])
            self.assertTrue(imported.is_file())
            self.assertFalse(imported.is_symlink())
            self.assertEqual(imported.read_bytes(), b'../../outside.png')
        finally:
            remove_new_project_dirs(before)

    def test_validation_failures_leave_no_project_directory(self):
        archives = []

        missing = io.BytesIO()
        with zipfile.ZipFile(missing, 'w') as zf:
            zf.writestr('assets/scene.png', b'png')
        archives.append(('missing-manifest', missing.getvalue()))

        malformed = io.BytesIO()
        with zipfile.ZipFile(malformed, 'w') as zf:
            zf.writestr('manifest.json', b'{')
        archives.append(('malformed-manifest', malformed.getvalue()))

        non_object = io.BytesIO()
        with zipfile.ZipFile(non_object, 'w') as zf:
            zf.writestr('manifest.json', b'[]')
        archives.append(('non-object-manifest', non_object.getvalue()))

        bad_scenes = io.BytesIO()
        with zipfile.ZipFile(bad_scenes, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({'scenes': 'not-a-list'}))
        archives.append(('invalid-scenes', bad_scenes.getvalue()))

        bad_path = io.BytesIO()
        with zipfile.ZipFile(bad_path, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({
                'scenes': [{'image': str(ROOT / 'webui.py'), 'text': 'bad'}],
            }))
        archives.append(('outside-media', bad_path.getvalue()))

        non_media = io.BytesIO()
        with zipfile.ZipFile(non_media, 'w') as zf:
            zf.writestr('assets/page.html', b'<script>bad()</script>')
            zf.writestr('manifest.json', json.dumps({
                'scenes': [{'image': 'assets/page.html', 'text': 'bad'}],
            }))
        archives.append(('non-media-scene', non_media.getvalue()))

        missing_media = io.BytesIO()
        with zipfile.ZipFile(missing_media, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({
                'scenes': [{'image': 'assets/missing.png', 'text': 'bad'}],
            }))
        archives.append(('missing-media', missing_media.getvalue()))

        empty_scenes = io.BytesIO()
        with zipfile.ZipFile(empty_scenes, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({'scenes': []}))
        archives.append(('empty-scenes', empty_scenes.getvalue()))

        missing_image = io.BytesIO()
        with zipfile.ZipFile(missing_image, 'w') as zf:
            zf.writestr('manifest.json', json.dumps({
                'scenes': [{'text': 'missing image'}],
            }))
        archives.append(('missing-scene-image', missing_image.getvalue()))

        for label, raw in archives:
            with self.subTest(label=label):
                before = project_dirs()
                try:
                    code, _ = self._post_zip(raw)
                    self.assertEqual(code, 400)
                    self.assertEqual(project_dirs(), before)
                finally:
                    remove_new_project_dirs(before)


if __name__ == '__main__':
    unittest.main()
