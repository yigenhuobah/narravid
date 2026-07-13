"""Focused regression tests for post-v1.8.0 security/cancel/path fixes.

Run:
  python test_regressions.py
"""
from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import video_auto  # noqa: E402
import webui  # noqa: E402


class Checker:
    def __init__(self):
        self.failed = 0
        self.passed = 0

    def check(self, name: str, cond: bool, detail: str = ''):
        if cond:
            self.passed += 1
            print(f'  PASS  {name}' + (f' — {detail}' if detail else ''))
        else:
            self.failed += 1
            print(f'  FAIL  {name}' + (f' — {detail}' if detail else ''))


C = Checker()


def section(title: str):
    print(f'\n[{title}]')


# ── pure helpers (video_auto) ─────────────────────────────────────

def test_video_auto_helpers():
    section('video_auto helpers')
    C.check('parse_boolish false strings',
            video_auto.parse_boolish('false') is False
            and video_auto.parse_boolish('0') is False
            and video_auto.parse_boolish('off') is False
            and video_auto.parse_boolish('n') is False
            and video_auto.parse_boolish('disabled') is False
            and video_auto.parse_boolish('') is False)
    C.check('parse_boolish true values',
            video_auto.parse_boolish('true') is True
            and video_auto.parse_boolish(1) is True
            and video_auto.parse_boolish('yes') is True)
    C.check('parse_boolish unknown uses default',
            video_auto.parse_boolish('maybe', default=True) is True
            and video_auto.parse_boolish('maybe', default=False) is False)
    C.check('parse_boolish default None',
            video_auto.parse_boolish(None, default=True) is True)

    C.check('resolve_positive_duration 0 -> fallback',
            video_auto.resolve_positive_duration(0, 3.0) == 3.0)
    C.check('resolve_positive_duration neg -> fallback',
            video_auto.resolve_positive_duration(-1, 2.5) == 2.5)
    C.check('resolve_positive_duration None -> fallback',
            video_auto.resolve_positive_duration(None, 4.0) == 4.0)
    C.check('resolve_positive_duration positive',
            video_auto.resolve_positive_duration(5, 3.0) == 5.0)
    C.check('resolve_positive_duration invalid string',
            video_auto.resolve_positive_duration('x', 3.0) == 3.0)

    C.check('is_cancel_error user only',
            video_auto.is_cancel_error(RuntimeError('渲染已被用户取消'))
            and not video_auto.is_cancel_error(RuntimeError('渲染已中止'))
            and not video_auto.is_cancel_error(RuntimeError('scene boom')))

    video_auto.CancelToken.reset()
    video_auto.CancelToken.set_aborted()
    C.check('set_aborted is not user cancel',
            video_auto.CancelToken.is_cancelled()
            and not video_auto.CancelToken.is_user_cancel())
    try:
        video_auto._check_cancel()
        C.check('abort raises 中止', False)
    except RuntimeError as e:
        C.check('abort raises 中止', '中止' in str(e) and '用户' not in str(e), str(e))
    video_auto.CancelToken.reset()
    video_auto.CancelToken.set_cancelled()
    C.check('set_cancelled is user cancel', video_auto.CancelToken.is_user_cancel())
    try:
        video_auto._check_cancel()
        C.check('user cancel raises 用户取消', False)
    except RuntimeError as e:
        C.check('user cancel raises 用户取消', '用户取消' in str(e), str(e))
    video_auto.CancelToken.reset()


def test_webui_path_helpers():
    section('webui path helpers')
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        child = root / 'a' / 'b.txt'
        child.parent.mkdir(parents=True)
        child.write_text('x', encoding='utf-8')
        outside = root.parent / 'outside.txt'
        C.check('under root', webui._is_under(child, root))
        C.check('not under root', not webui._is_under(outside, root))
        C.check('under any', webui._is_under_any(child, [root / 'missing', root]))
        C.check('sanitize basename only',
                webui._sanitize_upload_name('../../evil.png') == 'evil.png')
        C.check('sanitize weird chars',
                webui._sanitize_upload_name('a b/../c?.png').endswith('.png'))

    C.check('looks_like_cancel user only',
            webui._looks_like_cancel('已取消')
            and webui._looks_like_cancel('渲染已被用户取消')
            and not webui._looks_like_cancel('渲染已中止')
            and not webui._looks_like_cancel('完成'))

    C.check('sanitize_render_id ok', webui._sanitize_render_id('r_abc-12') == 'r_abc-12')
    C.check('sanitize_render_id reject traversal',
            webui._sanitize_render_id('../pwn') is None
            and webui._sanitize_render_id('..\\x') is None
            and webui._sanitize_render_id('a/b') is None
            and webui._sanitize_render_id('C:\\Temp\\x') is None)
    C.check('job_out_dir confined',
            webui._job_out_dir('../pwn') is None
            and webui._job_out_dir('normal_id') is not None
            and webui._is_under(webui._job_out_dir('normal_id'), webui.OUT_BASE))


def test_active_render_cancel_scoping():
    section('active render cancel scoping')
    video_auto.CancelToken.reset()
    webui._set_active_render(None)

    webui._set_active_render('job-a')
    C.check('get active', webui._get_active_render() == 'job-a')

    webui._signal_cancel_token_if_active('job-b')
    C.check('cancel other does not set token', not video_auto.CancelToken.is_cancelled())

    webui._signal_cancel_token_if_active('job-a')
    C.check('cancel active sets token', video_auto.CancelToken.is_cancelled())
    C.check('cancel active is user cancel', video_auto.CancelToken.is_user_cancel())

    video_auto.CancelToken.reset()
    webui._set_active_render(None)

    waiting = {'_started': False}
    C.check('waiting when none active/unstarted', webui._is_waiting_for_lock('j1', waiting))
    webui._set_active_render('other')
    C.check('waiting when other active', webui._is_waiting_for_lock('j1', {'_started': True}))
    webui._set_active_render('j1')
    C.check('not waiting when self active', not webui._is_waiting_for_lock('j1', {'_started': True}))
    webui._set_active_render(None)


def test_template_path_guard():
    section('template path guard')
    h = webui.H.__new__(webui.H)
    C.check('reject slash', h._template_path('../x') is None)
    C.check('reject backslash', h._template_path('..\\x') is None)
    C.check('reject dots', h._template_path('..') is None)
    C.check('reject empty', h._template_path('') is None)
    C.check('reject long', h._template_path('a' * 80) is None)
    ok_id = 'abc12-34'
    tp = h._template_path(ok_id)
    if tp is None:
        C.check('accept simple id', False, 'returned None')
    else:
        C.check('accept simple id under templates',
                webui._is_under(tp, webui.TEMPLATE_DIR), str(tp))


def _make_handler(path: str, method: str = 'GET', body: bytes = b'', headers=None):
    h = webui.H.__new__(webui.H)
    h.client_address = ('127.0.0.1', 0)
    h.server = mock.Mock()
    h.requestline = f'{method} {path} HTTP/1.1'
    h.command = method
    h.path = path
    h.request_version = 'HTTP/1.1'
    h.headers = headers or {'Content-Length': str(len(body))}
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    h.close_connection = True
    h.directory = str(ROOT)
    return h


def _read_response(h) -> tuple[int, dict | bytes]:
    raw = h.wfile.getvalue()
    try:
        head, body = raw.split(b'\r\n\r\n', 1)
    except ValueError:
        return 0, raw
    status_line = head.split(b'\r\n', 1)[0].decode('latin1', 'ignore')
    try:
        code = int(status_line.split()[1])
    except Exception:
        code = 0
    ctype = b''
    for line in head.split(b'\r\n')[1:]:
        if line.lower().startswith(b'content-type:'):
            ctype = line.split(b':', 1)[1].strip().lower()
    if b'json' in ctype:
        try:
            return code, json.loads(body.decode('utf-8'))
        except Exception:
            return code, body
    return code, body


def test_rendered_path_traversal_http():
    section('/rendered confinement')
    secret = ROOT / '_regtest_secret.txt'
    secret.write_text('SECRET', encoding='utf-8')
    try:
        h = _make_handler('/rendered/../_regtest_secret.txt')
        webui.H.do_GET(h)
        code, data = _read_response(h)
        C.check('traversal forbidden', code == 403, f'code={code} data={data!r}')
    finally:
        secret.unlink(missing_ok=True)

    # uploads under rendered/webui must not be served via /rendered/
    up = webui.UPLOAD_DIR / '_regtest_block_serve.png'
    up.write_bytes(b'\x89PNG\r\n\x1a\n')
    try:
        rel = up.resolve().relative_to(ROOT.resolve()).as_posix()
        h2 = _make_handler('/' + rel)
        webui.H.do_GET(h2)
        code2, data2 = _read_response(h2)
        C.check('uploads not via /rendered', code2 == 403, f'code={code2} data={data2!r}')
    finally:
        up.unlink(missing_ok=True)

    h3 = _make_handler('/rendered/webui/__no_such__/x.mp4')
    webui.H.do_GET(h3)
    code3, data3 = _read_response(h3)
    C.check('missing under job out is 404', code3 == 404, f'code={code3} data={data3!r}')


def test_upload_path_sanitization_http():
    section('upload name sanitization')
    raw = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16
    payload = json.dumps({
        'name': '../../evil.png',
        'data': base64.b64encode(raw).decode('ascii'),
        'kind': 'image',
    }).encode('utf-8')
    h = _make_handler('/api/upload', method='POST', body=payload)
    webui.H.do_POST(h)
    code, data = _read_response(h)
    C.check('upload 200', code == 200, f'code={code} data={data!r}')
    if isinstance(data, dict) and data.get('path'):
        p = Path(data['path'])
        C.check('upload under uploads/', webui._is_under(p, webui.UPLOAD_DIR), str(p))
        C.check('upload basename no traversal', '..' not in p.name and p.name.endswith('evil.png'))
        p.unlink(missing_ok=True)
    else:
        C.check('upload path returned', False, repr(data))


def test_render_id_confinement():
    section('render_id confinement')
    # plant a real media under uploads
    media = webui.UPLOAD_DIR / '_regtest_scene.png'
    media.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8)
    try:
        body = json.dumps({
            'render_id': '../pwn_escape',
            'manifest': {
                'scenes': [{'image': str(media), 'text': 'hi'}],
                'workers': 1,
            },
        }).encode('utf-8')
        h = _make_handler('/api/render', method='POST', body=body)
        # Avoid starting real TTS: patch thread start? Handler will start threads.
        # Instead only test sanitize helpers + that bad id is rewritten before mkdir.
        # Full HTTP will spawn render — mock threading.Thread
        started = []
        class FakeThread:
            def __init__(self, target=None, daemon=None):
                self.target = target
            def start(self):
                started.append(self.target)
        with mock.patch('webui.threading.Thread', FakeThread):
            webui.H.do_POST(h)
        code, data = _read_response(h)
        C.check('render accepts rewritten id', code == 200 and isinstance(data, dict) and 'render_id' in data,
                f'code={code} data={data!r}')
        if isinstance(data, dict) and data.get('render_id'):
            rid = data['render_id']
            C.check('render_id not traversal', webui._sanitize_render_id(rid) == rid and '..' not in rid)
            out = webui._job_out_dir(rid)
            C.check('out under OUT_BASE', out is not None and webui._is_under(out, webui.OUT_BASE), str(out))
            # cleanup job dir if created
            if out and out.exists():
                import shutil
                shutil.rmtree(out, ignore_errors=True)
            # ensure escape dir not created
            escape = (webui.OUT_BASE / '../pwn_escape').resolve()
            C.check('escape path not used as job', not (escape / 'manifest.json').exists() if escape.exists() else True)

        # absolute outside media rejected
        body2 = json.dumps({
            'manifest': {
                'scenes': [{'image': str(ROOT / 'webui.py'), 'text': 'x'}],
            }
        }).encode('utf-8')
        h2 = _make_handler('/api/render', method='POST', body=body2)
        with mock.patch('webui.threading.Thread', FakeThread):
            webui.H.do_POST(h2)
        code2, data2 = _read_response(h2)
        C.check('absolute outside media rejected',
                code2 == 400 and isinstance(data2, dict) and '非法' in str(data2.get('error', '')),
                f'code={code2} data={data2!r}')
    finally:
        media.unlink(missing_ok=True)


def test_export_allowlist():
    section('export allowlist')
    outside = ROOT / '_regtest_outside_media.bin'
    outside.write_bytes(b'OUTSIDE')
    inside = webui.UPLOAD_DIR / '_regtest_inside.png'
    inside.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8)
    try:
        # outside path must be rejected (no host path leak in zip)
        body = json.dumps({
            'manifest': {
                'scenes': [
                    {'image': str(outside), 'text': 'a'},
                    {'image': str(inside), 'text': 'b'},
                ]
            }
        }).encode('utf-8')
        h = _make_handler('/api/export', method='POST', body=body)
        webui.H.do_POST(h)
        code, data = _read_response(h)
        C.check('export rejects outside media', code == 400 and '无法导出' in str(data), f'code={code} data={data!r}')

        body2 = json.dumps({
            'manifest': {'scenes': [{'image': str(inside), 'text': 'b'}]}
        }).encode('utf-8')
        h2 = _make_handler('/api/export', method='POST', body=body2)
        webui.H.do_POST(h2)
        code2, data2 = _read_response(h2)
        C.check('export 200', code2 == 200, f'code={code2}')
        if code2 == 200 and isinstance(data2, (bytes, bytearray)):
            zf = zipfile.ZipFile(io.BytesIO(data2))
            man = json.loads(zf.read('manifest.json'))
            C.check('inside rewritten', man['scenes'][0]['image'].startswith('assets/'))
            C.check('no host path leak', str(ROOT) not in zf.read('manifest.json').decode('utf-8'))
        else:
            C.check('export zip body', False, repr(type(data2)))
    finally:
        outside.unlink(missing_ok=True)
        inside.unlink(missing_ok=True)


def test_import_path_confinement():
    section('import path confinement')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('assets/ok.png', b'\x89PNG')
        bad_manifest = {
            'scenes': [
                {'image': 'assets/ok.png', 'text': 'ok'},
                {'image': str((ROOT / 'webui.py').resolve()), 'text': 'bad'},
            ]
        }
        zf.writestr('manifest.json', json.dumps(bad_manifest))
    payload = json.dumps({'data': base64.b64encode(buf.getvalue()).decode('ascii')}).encode('utf-8')
    h = _make_handler('/api/import', method='POST', body=payload)
    webui.H.do_POST(h)
    code, data = _read_response(h)
    C.check('import rejects absolute outside path',
            code == 400 and isinstance(data, dict) and '非法' in str(data.get('error', '')),
            f'code={code} data={data!r}')

    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, 'w') as zf:
        zf.writestr('assets/ok.png', b'\x89PNG')
        zf.writestr('manifest.json', json.dumps({
            'scenes': [{'image': 'assets/ok.png', 'text': 'ok'}],
            'bgm': 'assets/ok.png',
        }))
    payload2 = json.dumps({'data': base64.b64encode(buf2.getvalue()).decode('ascii')}).encode('utf-8')
    h2 = _make_handler('/api/import', method='POST', body=payload2)
    webui.H.do_POST(h2)
    code2, data2 = _read_response(h2)
    C.check('import good 200', code2 == 200, f'code={code2} data={data2!r}')
    if isinstance(data2, dict):
        img = Path(data2['manifest']['scenes'][0]['image'])
        C.check('import image under uploads', webui._is_under(img, webui.UPLOAD_DIR), str(img))


def test_import_zip_slip_member():
    section('import zip slip member')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('../escape_slip.txt', b'pwn')
        zf.writestr('manifest.json', json.dumps({'scenes': [{'image': 'a.png', 'text': 'x'}]}))
    payload = json.dumps({'data': base64.b64encode(buf.getvalue()).decode('ascii')}).encode('utf-8')
    h = _make_handler('/api/import', method='POST', body=payload)
    webui.H.do_POST(h)
    code, data = _read_response(h)
    C.check('zip slip rejected',
            code == 400 and isinstance(data, dict) and '非法' in str(data.get('error', '')),
            f'code={code} data={data!r}')
    slip = webui.UPLOAD_DIR.parent / 'escape_slip.txt'
    C.check('slip file not written', not slip.exists())


def test_hold_uses_process_audio_source():
    section('hold_sec uses process_audio')
    src = Path('video_auto.py').read_text(encoding='utf-8')
    scene_fn = src[src.find('def process_single_scene'):src.find('\ndef main(')]
    C.check('hold calls process_audio',
            'process_audio(wav, padded_wav, 1.0, hold_sec)' in scene_fn)
    C.check('hold uses actual duration', 'scene_duration = actual' in scene_fn)
    C.check('no direct hold apad in scene',
            'apad=pad_dur={hold_sec' not in scene_fn)


def test_fail_fast_markers():
    section('fail-fast markers')
    src = Path('video_auto.py').read_text(encoding='utf-8')
    C.check('parallel fail-fast uses set_aborted',
            'set_aborted()' in src and 'first_err' in src)
    C.check('serial fail-fast break',
            'break  # fail-fast' in src or 'break  # fail-fast：不再继续后续场景' in src)
    C.check('run() killable subprocess',
            'kill_active_subprocesses' in src and 'Popen' in src)
    C.check('concat checks cancel',
            '_check_cancel()' in src[src.find('# ── concat'):src.find('# ── concat') + 200])


def test_frontend_cancel_gate_markers():
    section('frontend cancel gate markers')
    src = Path('webui.py').read_text(encoding='utf-8')
    C.check('userCancelled hard gate', 'userCancelled' in src)
    C.check('cancel keeps button disabled briefly', 'E(\'rb\').disabled=false' in src and '2000' in src)
    C.check('poll drops when userCancelled', 'userCancelled' in src[src.find('function poll()'):src.find('function done(')])


def test_media_resolve_helper():
    section('media resolve helper')
    inside = webui.UPLOAD_DIR / '_regtest_media_ok.png'
    inside.write_bytes(b'\x89PNG')
    try:
        p = webui._resolve_media_path(str(inside))
        C.check('resolve inside ok', p is not None and p == inside.resolve())
        p2 = webui._resolve_media_path(str(ROOT / 'webui.py'))
        C.check('resolve outside rejected', p2 is None)
        p3 = webui._resolve_media_path('../../webui.py')
        C.check('resolve relative escape rejected', p3 is None)
    finally:
        inside.unlink(missing_ok=True)


def main():
    print('narravid regression tests (post-review fixes)')
    test_video_auto_helpers()
    test_webui_path_helpers()
    test_active_render_cancel_scoping()
    test_template_path_guard()
    test_rendered_path_traversal_http()
    test_upload_path_sanitization_http()
    test_render_id_confinement()
    test_export_allowlist()
    test_import_path_confinement()
    test_import_zip_slip_member()
    test_hold_uses_process_audio_source()
    test_fail_fast_markers()
    test_frontend_cancel_gate_markers()
    test_media_resolve_helper()

    print()
    print(f'{C.passed} passed, {C.failed} failed')
    if C.failed:
        sys.exit(1)
    print('ALL CHECKS PASSED')
    sys.exit(0)


if __name__ == '__main__':
    main()
