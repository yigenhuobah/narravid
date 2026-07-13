"""Layer 5 — live ThreadingHTTPServer API tests (no full TTS render by default)."""
from __future__ import annotations

import base64
import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.support import (
    http_json, live_webui, upload_bytes, write_tiny_png, write_tone_wav,
)
import webui


class TestLiveBasicApi(unittest.TestCase):
    def test_home_and_tts_check(self):
        with live_webui() as base:
            code, body = http_json('GET', base + '/')
            # home returns HTML not json
            self.assertEqual(code, 200)
            code, data = http_json('GET', base + '/api/tts-check')
            self.assertEqual(code, 200)
            self.assertIn(data.get('engine'), ('edge', 'system'))

    def test_upload_and_bgm_list(self):
        with live_webui() as base:
            png = write_tiny_png(Path('_tmp_live.png'))
            try:
                code, data = upload_bytes(base, 'live.png', png.read_bytes())
                self.assertEqual(code, 200)
                self.assertTrue(Path(data['path']).exists())
                # cleanup
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

    def test_render_rejects_bad_media(self):
        with live_webui() as base:
            code, data = http_json('POST', base + '/api/render', {
                'manifest': {'scenes': [{'image': str(Path('webui.py').resolve()), 'text': 'x'}]},
            })
            self.assertEqual(code, 400)
            self.assertIn('非法', str(data.get('error', '')))

    def test_render_id_escape_rewritten_live(self):
        """Live server: bad render_id is rewritten; cancel immediately to avoid full TTS."""
        with live_webui() as base:
            raw = write_tiny_png(Path('_tmp_r.png')).read_bytes()
            Path('_tmp_r.png').unlink(missing_ok=True)
            code, up = upload_bytes(base, 'r.png', raw)
            self.assertEqual(code, 200)
            path = up['path']
            # Do NOT patch threading.Thread — ThreadingHTTPServer needs it.
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
            # cancel ASAP so we don't wait for full encode
            http_json('POST', base + f'/api/cancel/{rid}')
            # brief poll
            for _ in range(20):
                c, st = http_json('GET', base + f'/api/status/{rid}')
                if c == 404 or (isinstance(st, dict) and st.get('done')):
                    break
                time.sleep(0.2)
            out = webui._job_out_dir(rid)
            if out and out.exists():
                shutil.rmtree(out, ignore_errors=True)
            Path(path).unlink(missing_ok=True)

    def test_templates_crud(self):
        with live_webui() as base:
            code, data = http_json('POST', base + '/api/templates', {
                'name': 'max-tpl',
                'scenes': [{'image': 'x', 'text': 't'}],
            })
            self.assertEqual(code, 200)
            tid = data['id']
            code, one = http_json('GET', base + f'/api/templates/{tid}')
            self.assertEqual(code, 200)
            self.assertEqual(one.get('name'), 'max-tpl')
            code, _ = http_json('PUT', base + f'/api/templates/{tid}', {'name': 'max-tpl-2'})
            self.assertEqual(code, 200)
            # bad id (path traversal rejected / not found)
            code, _ = http_json('GET', base + '/api/templates/../evil')
            self.assertIn(code, (404, 400, 403))
            code, _ = http_json('DELETE', base + f'/api/templates/{tid}')
            self.assertIn(code, (200, 404))
            # ensure file gone
            tp = webui.TEMPLATE_DIR / f'{tid}.json'
            if tp.exists():
                tp.unlink(missing_ok=True)

    def test_thumb_forbidden_outside(self):
        with live_webui() as base:
            from urllib.parse import quote
            bad = quote(str(Path('webui.py').resolve()))
            code, data = http_json('GET', base + f'/thumb?path={bad}')
            self.assertEqual(code, 403)


class TestLiveCancelStatus(unittest.TestCase):
    def test_cancel_unknown_ok(self):
        with live_webui() as base:
            code, data = http_json('POST', base + '/api/cancel/does-not-exist')
            self.assertEqual(code, 200)

    def test_status_not_found(self):
        with live_webui() as base:
            code, data = http_json('GET', base + '/api/status/nope')
            self.assertEqual(code, 404)


if __name__ == '__main__':
    unittest.main()
