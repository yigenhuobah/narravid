"""Layer 3 — cancel / abort / active-render concurrency semantics."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest import mock

import video_auto
import webui
from tests.support import make_handler, read_response


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

    def test_pre_cancel_rejects_run_without_spawning_child(self):
        with mock.patch.object(video_auto.subprocess, 'Popen') as popen:
            video_auto.CancelToken.set_cancelled()
            with self.assertRaises(RuntimeError) as raised:
                video_auto.run(['ffmpeg', '-version'], silent=True)

        self.assertIn('用户取消', str(raised.exception))
        popen.assert_not_called()

    def test_mid_wait_cancel_kills_registered_child_and_cleans_registry(self):
        class FakeProc:
            def __init__(self):
                self.pid = 23456
                self.alive = True
                self.returncode = None
                self.wait_calls = 0

            def poll(self):
                return None if self.alive else 0

            def wait(self, timeout=None):
                self.wait_calls += 1
                if self.wait_calls == 1:
                    video_auto.CancelToken.set_cancelled()
                    raise __import__('subprocess').TimeoutExpired(cmd=['x'], timeout=timeout or 0)
                if self.alive:
                    raise __import__('subprocess').TimeoutExpired(
                        cmd=['x'], timeout=timeout or 0,
                    )
                return 0

            def kill(self):
                self.alive = False
                self.returncode = -9

        proc = FakeProc()
        killed = []

        def kill(candidate):
            killed.append(candidate)
            candidate.kill()

        with mock.patch.object(video_auto.subprocess, 'Popen', return_value=proc), \
             mock.patch.object(video_auto, '_kill_process', side_effect=kill):
            with self.assertRaises(RuntimeError) as raised:
                video_auto.run(['ffmpeg', '-version'], silent=True)

        self.assertGreaterEqual(proc.wait_calls, 1)
        self.assertIn(proc, killed)
        self.assertIn('用户取消', str(raised.exception))
        self.assertNotIn(proc, video_auto._ACTIVE_PROCS)


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

    def test_signal_cancel_token_only_for_active_job(self):
        with mock.patch.object(video_auto.CancelToken, 'set_cancelled') as set_cancelled:
            webui._set_active_render('active')
            webui._signal_cancel_token_if_active('queued')
            webui._signal_cancel_token_if_active(None)
            set_cancelled.assert_not_called()

            webui._signal_cancel_token_if_active('active')
            set_cancelled.assert_called_once_with()

    def test_internal_abort_text_is_not_user_cancel(self):
        self.assertTrue(webui._looks_like_cancel('渲染已被用户取消'))
        self.assertTrue(webui._looks_like_cancel('已取消'))
        self.assertFalse(webui._looks_like_cancel('渲染已中止'))
        self.assertFalse(webui._looks_like_cancel(None))

    def test_mark_cancelled_is_idempotent(self):
        job = {
            'done': True,
            'cancelled': True,
            'error': 'original cancel detail',
            'progress': '已取消',
        }
        self.assertTrue(webui._mark_job_cancelled(job, error='replacement'))
        self.assertEqual(job['error'], 'original cancel detail')
        self.assertEqual(job['progress'], '已取消')


class TestJobLifecycleOrchestration(unittest.TestCase):
    """Exercise render/monitor/cleanup closures without real TTS or ffmpeg."""

    def setUp(self):
        video_auto.CancelToken.reset()
        self._active_before = webui._get_active_render()
        webui._set_active_render(None)
        self._progress_before = os.environ.get('NARRAVID_PROGRESS_FILE')
        self._rids = []
        self.media = webui.UPLOAD_DIR / f'_cancel_contract_{id(self)}.png'
        self.media.parent.mkdir(parents=True, exist_ok=True)
        self.media.write_bytes(b'test image placeholder')

    def tearDown(self):
        video_auto.CancelToken.reset()
        webui._set_active_render(self._active_before)
        if self._progress_before is None:
            os.environ.pop('NARRAVID_PROGRESS_FILE', None)
        else:
            os.environ['NARRAVID_PROGRESS_FILE'] = self._progress_before
        self.media.unlink(missing_ok=True)
        for rid in self._rids:
            job = webui.JOBS.pop(rid, None)
            out = job.get('out') if isinstance(job, dict) else webui._job_out_dir(rid)
            if out:
                shutil.rmtree(out, ignore_errors=True)

    def _submit_captured_job(self, rid):
        captured = []

        class CapturedThread:
            def __init__(self, target=None, args=(), kwargs=None, **_thread_kwargs):
                self.target = target
                self.args = args
                self.kwargs = kwargs or {}

            def start(self):
                captured.append(self)

        payload = {
            'render_id': rid,
            'manifest': {
                'workers': 1,
                'burn_subtitles': False,
                'scenes': [{'image': str(self.media), 'text': 'test'}],
            },
        }
        body = json.dumps(payload).encode('utf-8')
        handler = make_handler('/api/render', method='POST', body=body)
        with mock.patch.object(webui.threading, 'Thread', CapturedThread):
            handler.do_POST()
        code, data = read_response(handler)
        self.assertEqual(code, 200, data)
        actual_rid = data['render_id']
        self._rids.append(actual_rid)
        self.assertEqual(len(captured), 2)
        return actual_rid, tuple(thread.target for thread in captured)

    @staticmethod
    def _write_fake_output(argv):
        output_arg = argv.index('--output-dir') + 1
        out = Path(argv[output_arg])
        out.mkdir(parents=True, exist_ok=True)
        (out / 'manifest.mp4').write_bytes(b'fake mp4')

    def test_concurrent_same_requested_id_reserves_distinct_jobs_and_outputs(self):
        requested_rid = 'contract_same_requested_id'
        barrier = threading.Barrier(2)
        response_lock = threading.Lock()
        responses = []
        captured = []
        real_thread = threading.Thread
        real_job_out_dir = webui._job_out_dir
        jobs_before = set(webui.JOBS)

        class CapturedThread:
            def __init__(self, target=None, args=(), kwargs=None, **_thread_kwargs):
                self.target = target
                self.args = args
                self.kwargs = kwargs or {}

            def start(self):
                captured.append(self)

        def gated_job_out_dir(rid):
            barrier.wait(timeout=3)
            return real_job_out_dir(rid)

        def submit():
            payload = {
                'render_id': requested_rid,
                'manifest': {
                    'workers': 1,
                    'burn_subtitles': False,
                    'scenes': [{'image': str(self.media), 'text': 'test'}],
                },
            }
            body = json.dumps(payload).encode('utf-8')
            handler = make_handler('/api/render', method='POST', body=body)
            handler.do_POST()
            response = read_response(handler)
            with response_lock:
                responses.append(response)

        with mock.patch.object(webui, '_job_out_dir', side_effect=gated_job_out_dir), \
             mock.patch.object(webui.threading, 'Thread', CapturedThread):
            first = real_thread(target=submit)
            second = real_thread(target=submit)
            first.start()
            second.start()
            first.join(5)
            second.join(5)

        new_job_ids = set(webui.JOBS) - jobs_before
        self._rids.extend(sorted(new_job_ids))
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(len(responses), 2)
        self.assertTrue(all(code == 200 for code, _data in responses), responses)

        response_ids = [data['render_id'] for _code, data in responses]
        self.assertEqual(len(set(response_ids)), 2, response_ids)
        self.assertIn(requested_rid, response_ids)
        self.assertEqual(set(response_ids), new_job_ids)
        self.assertEqual(len(captured), 4)

        first_job = webui.JOBS[response_ids[0]]
        second_job = webui.JOBS[response_ids[1]]
        self.assertIsNot(first_job, second_job)
        first_out = Path(first_job['out']).resolve()
        second_out = Path(second_job['out']).resolve()
        self.assertNotEqual(first_out, second_out)
        self.assertEqual(first_out.parent, webui.OUT_BASE.resolve())
        self.assertEqual(second_out.parent, webui.OUT_BASE.resolve())
        self.assertEqual(Path(first_job['progress_file']).parent.resolve(), first_out)
        self.assertEqual(Path(second_job['progress_file']).parent.resolve(), second_out)
        self.assertTrue((first_out / 'manifest.json').is_file())
        self.assertTrue((second_out / 'manifest.json').is_file())


    def test_render_queue_capacity_returns_429_without_creating_output(self):
        blockers = [
            f'contract_queue_blocker_{id(self)}_{index}'
            for index in range(webui.MAX_PENDING_JOBS)
        ]
        requested = f'contract_queue_full_{id(self)}'
        out = webui._job_out_dir(requested)
        self.assertIsNotNone(out)
        try:
            for rid in blockers:
                webui.JOBS[rid] = {'done': True, '_runner_active': True}
            payload = {
                'render_id': requested,
                'manifest': {
                    'workers': 1,
                    'burn_subtitles': False,
                    'scenes': [{'image': str(self.media), 'text': 'test'}],
                },
            }
            body = json.dumps(payload).encode('utf-8')
            handler = make_handler('/api/render', method='POST', body=body)
            handler.do_POST()
            code, data = read_response(handler)
            self.assertEqual(code, 429, data)
            self.assertIn('queue', data.get('error', ''))
            self.assertFalse(out.exists())
            webui.JOBS.pop(blockers[-1], None)
            self.assertTrue(webui._reserve_render_id(requested))
            webui._release_render_id(requested)
        finally:
            for rid in blockers:
                webui.JOBS.pop(rid, None)

    def test_queue_accepts_last_slot_and_ignores_finished_runner(self):
        blockers = [
            f'contract_queue_boundary_{id(self)}_{index}'
            for index in range(webui.MAX_PENDING_JOBS - 1)
        ]
        finished = f'contract_queue_finished_{id(self)}'
        try:
            for rid in blockers:
                webui.JOBS[rid] = {'done': True, '_runner_active': True}
            webui.JOBS[finished] = {'done': True, '_runner_active': False}
            rid, targets = self._submit_captured_job(f'contract_queue_last_{id(self)}')
            self.assertEqual(len(targets), 2)
            self.assertTrue(webui.JOBS[rid]['_runner_active'])
        finally:
            for rid in [*blockers, finished]:
                webui.JOBS.pop(rid, None)

    def test_reservations_alone_consume_queue_capacity(self):
        reserved = []
        try:
            for index in range(webui.MAX_PENDING_JOBS):
                rid = f'contract_reserved_{id(self)}_{index}'
                self.assertTrue(webui._reserve_render_id(rid))
                reserved.append(rid)
            with self.assertRaises(webui.RenderQueueFullError):
                webui._reserve_render_id(f'contract_reserved_overflow_{id(self)}')
        finally:
            for rid in reserved:
                webui._release_render_id(rid)

    def test_thread_constructor_failure_terminalizes_job_and_releases_capacity(self):
        requested = f'contract_thread_ctor_{id(self)}'
        payload = {
            'render_id': requested,
            'manifest': {
                'workers': 1,
                'burn_subtitles': False,
                'scenes': [{'image': str(self.media), 'text': 'test'}],
            },
        }
        body = json.dumps(payload).encode('utf-8')
        handler = make_handler('/api/render', method='POST', body=body)
        with mock.patch.object(webui.threading, 'Thread', side_effect=RuntimeError('no threads')):
            handler.do_POST()
        code, data = read_response(handler)
        self.assertEqual(code, 503, data)
        self.assertEqual(data.get('render_id'), requested)
        job = webui.JOBS[requested]
        self._rids.append(requested)
        self.assertTrue(job['done'])
        self.assertFalse(job['_runner_active'])
        self.assertFalse(job['_monitor_active'])
        probe = f'contract_after_ctor_failure_{id(self)}'
        self.assertTrue(webui._reserve_render_id(probe))
        webui._release_render_id(probe)

    def test_first_thread_start_failure_terminalizes_job(self):
        requested = f'contract_first_start_{id(self)}'

        class StartFails:
            def __init__(self, target=None, **_kwargs):
                self.target = target

            def start(self):
                raise RuntimeError('first start failed')

        payload = {
            'render_id': requested,
            'manifest': {'scenes': [{'image': str(self.media), 'text': 'test'}]},
        }
        handler = make_handler(
            '/api/render',
            method='POST',
            body=json.dumps(payload).encode('utf-8'),
        )
        with mock.patch.object(webui.threading, 'Thread', StartFails):
            handler.do_POST()
        code, data = read_response(handler)
        self.assertEqual(code, 503, data)
        self._rids.append(requested)
        job = webui.JOBS[requested]
        self.assertTrue(job['done'])
        self.assertFalse(job['_runner_active'])
        self.assertFalse(job['_monitor_active'])

    def test_second_thread_start_failure_cancels_started_runner(self):
        requested = f'contract_second_start_{id(self)}'
        real_thread = threading.Thread
        started_threads = []

        class SecondStartFails:
            starts = 0

            def __init__(self, target=None, **_kwargs):
                self.target = target

            def start(self):
                type(self).starts += 1
                if type(self).starts == 2:
                    raise RuntimeError('second start failed')
                thread = real_thread(target=self.target, daemon=True)
                started_threads.append(thread)
                thread.start()

        payload = {
            'render_id': requested,
            'manifest': {'scenes': [{'image': str(self.media), 'text': 'test'}]},
        }
        handler = make_handler(
            '/api/render',
            method='POST',
            body=json.dumps(payload).encode('utf-8'),
        )
        webui.RENDER_LOCK.acquire()
        try:
            with mock.patch.object(webui.threading, 'Thread', SecondStartFails):
                handler.do_POST()
        finally:
            webui.RENDER_LOCK.release()
        code, data = read_response(handler)
        self.assertEqual(code, 503, data)
        self._rids.append(requested)
        for thread in started_threads:
            thread.join(3)
        job = webui.JOBS[requested]
        self.assertTrue(job['done'])
        self.assertFalse(job['_runner_active'])
        self.assertFalse(job['_monitor_active'])

    def test_prune_waits_for_runner_and_monitor_lifecycle(self):
        rid = f'contract_prune_lifecycle_{id(self)}'
        job = {
            'done': True,
            '_runner_active': True,
            '_monitor_active': False,
            '_done_at': 0.0,
        }
        webui.JOBS[rid] = job
        self._rids.append(rid)

        webui._prune_finished_jobs(now=1000.0)
        self.assertIn(rid, webui.JOBS)
        job['_runner_active'] = False
        job['_monitor_active'] = True
        webui._prune_finished_jobs(now=1000.0)
        self.assertIn(rid, webui.JOBS)
        job['_monitor_active'] = False
        webui._prune_finished_jobs(now=1000.0)
        self.assertNotIn(rid, webui.JOBS)

    def test_render_lock_prevents_main_overlap(self):
        rid_a, targets_a = self._submit_captured_job('contract_lock_a')
        rid_b, targets_b = self._submit_captured_job('contract_lock_b')
        release_first = threading.Event()
        first_entered = threading.Event()
        second_entered = threading.Event()
        second_attempted = threading.Event()
        state_lock = threading.Lock()
        calls = 0
        active_calls = 0
        max_active_calls = 0

        def gated_main(argv):
            nonlocal calls, active_calls, max_active_calls
            with state_lock:
                calls += 1
                call_number = calls
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            if call_number == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(3))
            else:
                second_entered.set()
            self._write_fake_output(argv)
            with state_lock:
                active_calls -= 1

        def run_second():
            second_attempted.set()
            targets_b[0]()

        with mock.patch.object(video_auto, 'main', side_effect=gated_main):
            thread_a = threading.Thread(target=targets_a[0])
            thread_b = threading.Thread(target=run_second)
            thread_a.start()
            self.assertTrue(first_entered.wait(2))
            thread_b.start()
            self.assertTrue(second_attempted.wait(2))
            self.assertFalse(second_entered.wait(0.1))
            release_first.set()
            thread_a.join(3)
            thread_b.join(3)

        self.assertFalse(thread_a.is_alive() or thread_b.is_alive())
        self.assertEqual(calls, 2)
        self.assertEqual(max_active_calls, 1)
        self.assertTrue(webui.JOBS[rid_a]['done'])
        self.assertTrue(webui.JOBS[rid_b]['done'])
        self.assertTrue(webui.JOBS[rid_a]['video'])
        self.assertTrue(webui.JOBS[rid_b]['video'])
        self.assertIsNone(webui._get_active_render())

    def test_queued_cancel_never_enters_main_or_cancels_active_job(self):
        rid_active, targets_active = self._submit_captured_job('contract_active')
        rid_queued, targets_queued = self._submit_captured_job('contract_queued')
        active_entered = threading.Event()
        release_active = threading.Event()
        queued_attempted = threading.Event()
        calls = []

        def gated_main(argv):
            calls.append(argv)
            active_entered.set()
            self.assertTrue(release_active.wait(3))
            self._write_fake_output(argv)

        def run_queued():
            queued_attempted.set()
            targets_queued[0]()

        with mock.patch.object(video_auto, 'main', side_effect=gated_main), \
             mock.patch.object(video_auto.CancelToken, 'set_cancelled') as set_cancelled:
            active_thread = threading.Thread(target=targets_active[0])
            queued_thread = threading.Thread(target=run_queued)
            active_thread.start()
            self.assertTrue(active_entered.wait(2))
            self.assertEqual(webui._get_active_render(), rid_active)
            queued_thread.start()
            self.assertTrue(queued_attempted.wait(2))

            handler = make_handler(f'/api/cancel/{rid_queued}', method='POST')
            handler.do_POST()
            code, data = read_response(handler)
            self.assertEqual(code, 200, data)
            set_cancelled.assert_not_called()
            self.assertFalse(video_auto.CancelToken.is_cancelled())

            release_active.set()
            active_thread.join(3)
            queued_thread.join(3)

        self.assertFalse(active_thread.is_alive() or queued_thread.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertTrue(webui.JOBS[rid_active]['video'])
        self.assertTrue(webui.JOBS[rid_queued]['done'])
        self.assertTrue(webui.JOBS[rid_queued]['cancelled'])
        self.assertFalse(webui.JOBS[rid_queued]['video'])

    def test_successful_render_restores_existing_progress_environment(self):
        rid, targets = self._submit_captured_job('contract_progress_env')
        os.environ['NARRAVID_PROGRESS_FILE'] = 'caller-owned-progress.txt'

        def fake_main(argv):
            self.assertEqual(
                os.environ.get('NARRAVID_PROGRESS_FILE'),
                webui.JOBS[rid]['progress_file'],
            )
            self._write_fake_output(argv)

        with mock.patch.object(video_auto, 'main', side_effect=fake_main):
            targets[0]()

        self.assertEqual(os.environ.get('NARRAVID_PROGRESS_FILE'), 'caller-owned-progress.txt')
        self.assertTrue(webui.JOBS[rid]['done'])

    def test_monitor_marks_active_stall_and_arms_cancel(self):
        rid, targets = self._submit_captured_job('contract_stall')
        job = webui.JOBS[rid]
        job['_started'] = True
        webui._set_active_render(rid)

        with mock.patch.object(job['cancel_event'], 'wait', return_value=False), \
             mock.patch.object(webui, 'STALL_TICKS', 2), \
             mock.patch.object(webui, 'STALL_SECONDS', 4), \
             mock.patch.object(webui, '_signal_cancel_token_if_active') as signal_cancel:
            targets[1]()

        self.assertTrue(job['done'])
        self.assertEqual(job['progress'], '超时（渲染卡死）')
        self.assertEqual(job['error'], '渲染超时：4 秒无进度更新')
        self.assertTrue(job['cancel_event'].is_set())
        signal_cancel.assert_called_once_with(rid)

    def test_monitor_does_not_stall_queued_job(self):
        rid, targets = self._submit_captured_job('contract_queued_monitor')
        job = webui.JOBS[rid]
        sleeps = 0

        def finish_after_queue_checks(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                job['done'] = True

        with mock.patch.object(job['cancel_event'], 'wait', side_effect=finish_after_queue_checks), \
             mock.patch.object(webui, 'STALL_TICKS', 1), \
             mock.patch.object(webui, '_signal_cancel_token_if_active') as signal_cancel:
            targets[1]()

        self.assertEqual(sleeps, 3)
        self.assertFalse(job['error'])
        self.assertFalse(job['cancel_event'].is_set())
        signal_cancel.assert_not_called()

    def test_prune_defers_active_job_and_honors_retention_window(self):
        rid, _targets = self._submit_captured_job('contract_cleanup')
        job = webui.JOBS[rid]
        job['done'] = True
        job['_runner_active'] = False
        job['_monitor_active'] = False
        webui._set_active_render(rid)
        webui._prune_finished_jobs(now=1000.0)
        self.assertIn(rid, webui.JOBS)

        webui._set_active_render(None)
        webui._prune_finished_jobs(now=1000.0)
        self.assertIn(rid, webui.JOBS)
        webui._prune_finished_jobs(now=1299.9)
        self.assertIn(rid, webui.JOBS)
        webui._prune_finished_jobs(now=1300.0)
        self.assertNotIn(rid, webui.JOBS)

    def test_active_cancel_route_signals_token_and_sets_terminal_state(self):
        rid, _targets = self._submit_captured_job('contract_active_cancel')
        webui._set_active_render(rid)

        with mock.patch.object(video_auto.CancelToken, 'set_cancelled') as set_cancelled:
            handler = make_handler(f'/api/cancel/{rid}', method='POST')
            handler.do_POST()

        code, data = read_response(handler)
        self.assertEqual(code, 200, data)
        self.assertNotIn('ignored', data)
        set_cancelled.assert_called_once_with()
        job = webui.JOBS[rid]
        self.assertTrue(job['done'])
        self.assertTrue(job['cancelled'])
        self.assertEqual(job['error'], '已取消')
        self.assertTrue(job['cancel_event'].is_set())

    def test_terminal_timeout_status_ignores_late_progress_file_update(self):
        rid, _targets = self._submit_captured_job('contract_terminal_status')
        job = webui.JOBS[rid]
        Path(job['progress_file']).write_text('完成', encoding='utf-8')
        job.update(
            done=True,
            error='渲染超时：4 秒无进度更新',
            progress='超时（渲染卡死）',
        )

        handler = make_handler(f'/api/status/{rid}')
        handler.do_GET()
        code, data = read_response(handler)

        self.assertEqual(code, 200, data)
        self.assertTrue(data['done'])
        self.assertEqual(data['progress'], '超时（渲染卡死）')
        self.assertEqual(data['error'], '渲染超时：4 秒无进度更新')
        self.assertFalse(data['cancelled'])
        self.assertFalse(data['video'])


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
