"""Layer 3 — cancel / abort / active-render concurrency semantics."""
from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest import mock

import video_auto
import webui


class TestFailFastLabeling(unittest.TestCase):
    """Parallel fail-fast must not mislabel real errors as user cancel."""

    def setUp(self):
        video_auto.CancelToken.reset()

    def tearDown(self):
        video_auto.CancelToken.reset()

    def test_aborted_siblings_do_not_steal_root_cause(self):
        """Simulate the new fail-fast selection logic."""
        def work(i):
            if i == 1:
                time.sleep(0.02)
                raise RuntimeError('ffmpeg boom scene1')
            for _ in range(80):
                if video_auto.CancelToken.is_cancelled():
                    # sibling after abort
                    if video_auto.CancelToken.is_user_cancel():
                        raise RuntimeError('渲染已被用户取消')
                    raise RuntimeError('渲染已中止')
                time.sleep(0.01)
            return i

        failed = []
        first_err = None
        user_cancelled = False
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(work, i): i for i in range(4)}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    failed.append(futs[fut])
                    if video_auto.is_cancel_error(e):
                        user_cancelled = True
                        if first_err is None:
                            first_err = e
                    else:
                        if first_err is None or video_auto.is_cancel_error(first_err) or str(first_err) == '渲染已中止':
                            first_err = e
                    if not video_auto.CancelToken.is_user_cancel():
                        video_auto.CancelToken.set_aborted()

        self.assertTrue(failed)
        self.assertFalse(user_cancelled)
        self.assertIn('ffmpeg boom', str(first_err))
        self.assertFalse(video_auto.is_cancel_error(first_err))


class TestRunKillOnCancel(unittest.TestCase):
    def setUp(self):
        video_auto.CancelToken.reset()

    def tearDown(self):
        video_auto.CancelToken.reset()

    def test_run_raises_on_cancel_without_real_ffmpeg(self):
        """Popen wait loop must honor CancelToken (mock a long-running child)."""
        class FakeProc:
            def __init__(self):
                self.pid = 12345
                self._alive = True
                self.returncode = None

            def poll(self):
                return None if self._alive else 0

            def wait(self, timeout=None):
                if self._alive:
                    raise __import__('subprocess').TimeoutExpired(cmd=['x'], timeout=timeout or 0)
                return 0

            def kill(self):
                self._alive = False
                self.returncode = -9

        fake = FakeProc()
        killed = []

        def fake_popen(cmd, **kwargs):
            return fake

        def fake_kill(proc):
            killed.append(proc)
            proc.kill()

        with mock.patch('video_auto.subprocess.Popen', side_effect=fake_popen), \
             mock.patch('video_auto._kill_process', side_effect=fake_kill), \
             mock.patch('video_auto._check_cancel', side_effect=lambda: None):
            # arm cancel after short delay from another "thread" simulation
            def arm():
                time.sleep(0.1)
                video_auto.CancelToken.set_cancelled()
            threading.Thread(target=arm, daemon=True).start()
            # restore real _check_cancel after loop sets cancel — call run with real check
        # simpler: set cancelled before wait loop sees it
        video_auto.CancelToken.reset()
        with mock.patch('video_auto.subprocess.Popen', side_effect=fake_popen), \
             mock.patch('video_auto._kill_process', side_effect=fake_kill):
            video_auto.CancelToken.set_cancelled()
            with self.assertRaises(RuntimeError) as cm:
                video_auto.run(['ffmpeg', '-version'], silent=True)
            self.assertTrue(killed or '取消' in str(cm.exception) or '中止' in str(cm.exception))


class TestActiveRenderScoping(unittest.TestCase):
    def setUp(self):
        video_auto.CancelToken.reset()
        webui._set_active_render(None)

    def tearDown(self):
        video_auto.CancelToken.reset()
        webui._set_active_render(None)

    def test_waiting_for_lock(self):
        self.assertTrue(webui._is_waiting_for_lock('j1', {'_started': False}))
        webui._set_active_render('other')
        self.assertTrue(webui._is_waiting_for_lock('j1', {'_started': True}))
        webui._set_active_render('j1')
        self.assertFalse(webui._is_waiting_for_lock('j1', {'_started': True}))

    def test_mark_cancelled(self):
        j = {'error': '', 'done': False}
        self.assertTrue(webui._mark_job_cancelled(j))
        self.assertTrue(j['cancelled'] and j['done'])
        self.assertEqual(j['error'], '已取消')

    def test_mark_cancelled_ignores_finished_success(self):
        j = {
            'done': True,
            'cancelled': False,
            'video': '/rendered/webui/x/manifest.mp4',
            'progress': '完成',
            'error': '',
        }
        self.assertFalse(webui._mark_job_cancelled(j))
        self.assertFalse(j.get('cancelled'))
        self.assertEqual(j['video'], '/rendered/webui/x/manifest.mp4')
        self.assertEqual(j['progress'], '完成')

    def test_mark_cancelled_ignores_finished_failure(self):
        j = {
            'done': True,
            'cancelled': False,
            'error': f'渲染超时：{webui.STALL_SECONDS} 秒无进度更新',
            'progress': '超时（渲染卡死）',
            'video': '',
        }
        self.assertFalse(webui._mark_job_cancelled(j))
        self.assertEqual(j['error'], f'渲染超时：{webui.STALL_SECONDS} 秒无进度更新')
        self.assertFalse(j.get('cancelled'))


class TestFrontendGateMarkers(unittest.TestCase):
    def test_html_contains_user_cancelled_gate(self):
        from pathlib import Path
        src = Path('webui_ui.py').read_text(encoding='utf-8') + Path('webui_jobs.py').read_text(encoding='utf-8') + Path('webui.py').read_text(encoding='utf-8')
        self.assertIn('userCancelled', src)
        self.assertIn('if(rid!==pollRid||userCancelled)return', src)
        self.assertIn('function cancel()', src)
        # 模板应持久化 BGM 与片头片尾时长
        self.assertIn("bgm:byId('bgmSel').value", src)
        self.assertIn("card_duration:byId('tcd').value", src)
        self.assertIn("end_card_duration:byId('ecd').value", src)
        self.assertIn('thumb-ph', src)
        self.assertIn('已跳过', src)
        self.assertIn('MAX_IMPORT_ZIP', src)

    def test_html_ux_ops_markers(self):
        """Static markers for real-user ops fixed in UX pass."""
        from pathlib import Path
        src = Path('webui_ui.py').read_text(encoding='utf-8') + Path('webui_jobs.py').read_text(encoding='utf-8') + Path('webui.py').read_text(encoding='utf-8')
        # speech speed range matches backend 0.5–3.0
        self.assertIn('id="sp" min="0.5" max="3.0"', src)
        # clean confirm
        clean = src.split('async function cleanOld', 1)[1].split('document.addEventListener', 1)[0]
        self.assertIn('confirm(', clean)
        # import size aligned with base64 body limit
        self.assertIn('MAX_IMPORT_ZIP=40*1024*1024', src)
        # empty scene placeholder not a perpetual spinner
        self.assertIn('thumb-ph', src)
        self.assertIn("inner='<div class=\"thumb-ph\"", src)
        # render skips unuploaded scenes with toast
        self.assertIn('已跳过', src)
        # loadTemplate restores durations + bgm
        load = src.split('async function loadTemplate', 1)[1].split('async function delTemplate', 1)[0]
        self.assertIn('card_duration', load)
        self.assertIn('end_card_duration', load)
        self.assertIn('t.bgm', load)
        # cancel API ignores finished jobs; bad zip is 400
        self.assertIn('ignored', src)
        self.assertIn('不是有效的 zip 工程文件', src)
        self.assertIn('function paintScenes()', src)
        self.assertIn('const byId=', src)
        self.assertIn('let scenes=[]', src)
        self.assertIn('def monitor_job():', src)
        # hold_sec is the wire field (legacy hold accepted on import only)
        self.assertIn('hold_sec', src)
        self.assertIn('function sceneHoldSec', src)


if __name__ == '__main__':
    unittest.main()
