"""Cross-platform helpers: fonts, TTS gates, process kill, ffmpeg names."""
from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import _bundled_ffmpeg
import test_e2e
import video_auto
import webui_jobs


class TestE2EHarness(unittest.TestCase):
    def test_existing_server_requires_destructive_opt_in(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            test_e2e.parse_args(['--base-url', 'http://127.0.0.1:5000'])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn('--allow-destructive-existing-server', stderr.getvalue())

    def test_existing_server_opt_in_is_accepted(self):
        args = test_e2e.parse_args([
            '--base-url',
            'http://127.0.0.1:5000',
            '--allow-destructive-existing-server',
        ])
        self.assertTrue(args.allow_destructive_existing_server)

    def test_default_workspace_is_removed_after_context(self):
        with test_e2e.e2e_workspace(keep=False) as run_dir:
            sentinel = run_dir / 'sentinel.txt'
            sentinel.write_text('temporary', encoding='utf-8')
            self.assertTrue(sentinel.exists())

        self.assertFalse(run_dir.exists())

    def test_keep_workspace_is_unique_and_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as td:
            output_root = Path(td) / 'test_output'
            output_root.mkdir()
            existing = output_root / 'existing.txt'
            existing.write_text('keep me', encoding='utf-8')

            with test_e2e.e2e_workspace(keep=True, output_root=output_root) as first:
                (first / 'first.txt').write_text('one', encoding='utf-8')
            with test_e2e.e2e_workspace(keep=True, output_root=output_root) as second:
                (second / 'second.txt').write_text('two', encoding='utf-8')

            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, output_root)
            self.assertEqual(second.parent, output_root)
            self.assertEqual(existing.read_text(encoding='utf-8'), 'keep me')
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_start_server_uses_file_log_and_isolated_data_dir(self):
        proc = mock.Mock()
        with tempfile.TemporaryDirectory() as td:
            test_dir = Path(td)
            with mock.patch.object(test_e2e.subprocess, 'Popen', return_value=proc) as popen:
                actual, log_path = test_e2e.start_webui_server(5012, test_dir)

            self.assertIs(actual, proc)
            self.assertEqual(log_path, test_dir / 'webui-server.log')
            self.assertTrue(log_path.exists())
            argv = popen.call_args.args[0]
            self.assertEqual(argv[-4:], ['--host', '127.0.0.1', '--port', '5012'])
            kwargs = popen.call_args.kwargs
            self.assertIs(kwargs['stderr'], subprocess.STDOUT)
            self.assertIsNot(kwargs['stdout'], subprocess.PIPE)
            self.assertEqual(
                kwargs['env']['NARRAVID_DATA_DIR'],
                str(test_dir / 'server-data'),
            )

    def test_startup_failure_reports_log_tail_and_terminates_tree(self):
        args = mock.Mock(base_url=None, port=5013, workers=1)
        proc = mock.Mock()
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as td:
            test_dir = Path(td)
            log_path = test_dir / 'webui-server.log'
            log_path.write_text('startup detail', encoding='utf-8')
            with (
                mock.patch.object(
                    test_e2e,
                    'start_webui_server',
                    return_value=(proc, log_path),
                ),
                mock.patch.object(test_e2e, 'wait_for_server', return_value=False),
                mock.patch.object(test_e2e, 'terminate_process_tree') as terminate,
                redirect_stdout(stdout),
            ):
                exit_code = test_e2e.run_e2e(args, test_dir)

        self.assertEqual(exit_code, 1)
        self.assertIn('startup detail', stdout.getvalue())
        terminate.assert_called_once_with(proc)

    def test_owned_server_refuses_an_occupied_port(self):
        args = mock.Mock(base_url=None, port=5014, workers=1)
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as td:
            with (
                mock.patch.object(test_e2e, 'local_port_available', return_value=False),
                mock.patch.object(test_e2e, 'start_webui_server') as start_server,
                redirect_stdout(stdout),
            ):
                exit_code = test_e2e.run_e2e(args, Path(td))

        self.assertEqual(exit_code, 1)
        self.assertIn('端口 5014 已被占用', stdout.getvalue())
        start_server.assert_not_called()

    def test_server_process_boundary_matches_platform(self):
        with mock.patch.object(test_e2e.os, 'name', 'nt'):
            windows = test_e2e.server_process_kwargs()
        with mock.patch.object(test_e2e.os, 'name', 'posix'):
            posix = test_e2e.server_process_kwargs()

        self.assertIn('creationflags', windows)
        self.assertNotIn('start_new_session', windows)
        self.assertEqual(posix, {'start_new_session': True})

    def test_windows_tree_termination_uses_taskkill(self):
        proc = mock.Mock(pid=4242)
        proc.poll.side_effect = [None, 0]
        proc.wait.return_value = 0
        with (
            mock.patch.object(test_e2e.os, 'name', 'nt'),
            mock.patch.object(test_e2e.subprocess, 'run') as run,
        ):
            test_e2e.terminate_process_tree(proc, timeout=0.1)

        command = run.call_args.args[0]
        self.assertEqual(command, ['taskkill', '/PID', '4242', '/T', '/F'])
        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()

    def test_posix_tree_termination_escalates_to_sigkill(self):
        proc = mock.Mock(pid=4243)
        with (
            mock.patch.object(test_e2e.os, 'name', 'posix'),
            mock.patch.object(test_e2e.os, 'killpg', create=True) as killpg,
            mock.patch.object(
                test_e2e, '_wait_for_process_group_exit', side_effect=[False, True]
            ) as wait_for_group,
        ):
            test_e2e.terminate_process_tree(proc, timeout=0.1)

        self.assertEqual(
            killpg.call_args_list,
            [
                mock.call(4243, signal.SIGTERM),
                mock.call(4243, getattr(signal, 'SIGKILL', 9)),
            ],
        )
        self.assertEqual(wait_for_group.call_count, 2)

    def test_posix_still_signals_group_after_parent_exit(self):
        proc = mock.Mock(pid=4244)
        proc.poll.return_value = 0
        with (
            mock.patch.object(test_e2e.os, 'name', 'posix'),
            mock.patch.object(test_e2e.os, 'killpg', create=True) as killpg,
            mock.patch.object(test_e2e, '_wait_for_process_group_exit', return_value=True) as wait_for_group,
        ):
            test_e2e.terminate_process_tree(proc, timeout=0.1)

        killpg.assert_called_once_with(4244, signal.SIGTERM)
        wait_for_group.assert_called_once_with(proc, 0.1)
        proc.wait.assert_not_called()


    def test_wait_for_process_group_exit_observes_descendants(self):
        proc = mock.Mock(pid=4245)
        with (
            mock.patch.object(test_e2e, '_process_group_exists', side_effect=[True, False]),
            mock.patch.object(test_e2e.time, 'monotonic', side_effect=[10.0, 10.0]),
            mock.patch.object(test_e2e.time, 'sleep') as sleep,
        ):
            self.assertTrue(test_e2e._wait_for_process_group_exit(proc, 1.0))

        sleep.assert_called_once_with(0.05)
        self.assertEqual(proc.poll.call_count, 2)

    def test_wait_for_process_group_exit_times_out(self):
        proc = mock.Mock(pid=4246)
        with (
            mock.patch.object(test_e2e, '_process_group_exists', return_value=True),
            mock.patch.object(test_e2e.time, 'monotonic', side_effect=[10.0, 11.0]),
            mock.patch.object(test_e2e.time, 'sleep') as sleep,
        ):
            self.assertFalse(test_e2e._wait_for_process_group_exit(proc, 1.0))

        sleep.assert_not_called()


class TestReleaseWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'build-exe.yml'
        ).read_text(encoding='utf-8')

    def test_native_commands_fail_fast(self):
        commands = (
            'python -m coverage erase',
            'python -m coverage run run_tests.py --layer unit,security,cancel,live,pipeline',
            'python -m coverage report',
            r'.\dist\narravid.exe --help',
            r'.\dist\narravid-webui.exe --help',
        )
        for command in commands:
            with self.subTest(command=command):
                marker = f'{command}\n          if ($LASTEXITCODE -ne 0)'
                self.assertIn(marker, self.workflow)

    def test_manual_release_targets_an_existing_tag(self):
        self.assertIn('release_tag:', self.workflow)
        self.assertIn('RELEASE_TAG: ${{ inputs.release_tag || github.ref_name }}', self.workflow)
        self.assertIn('ref: ${{ inputs.release_tag || github.ref }}', self.workflow)
        self.assertIn('tag_name: ${{ env.RELEASE_TAG }}', self.workflow)

    def test_job_environment_does_not_use_runner_context(self):
        job_env = self.workflow.split('    env:', 1)[1].split('    steps:', 1)[0]
        self.assertNotIn('${{ runner.', job_env)
        self.assertIn('${{ github.workspace }}', job_env)

    def test_frozen_smoke_proves_bundled_tools_and_edge_tts(self):
        self.assertIn("Join-Path $env:ChocolateyInstall 'lib\\ffmpeg'", self.workflow)
        self.assertIn('$ffmpegDir -ne $ffprobeDir', self.workflow)
        self.assertIn('$env:PATH = "$env:SystemRoot\\System32;$env:SystemRoot"', self.workflow)
        self.assertIn("$health.tts.engine -ne 'edge'", self.workflow)
        self.assertIn('$bundledFfprobe', self.workflow)
        self.assertIn("$extractLeaf.StartsWith('_MEI')", self.workflow)

    def test_checksum_writer_forces_lf(self):
        self.assertIn('hashlib.file_digest', self.workflow)
        self.assertIn("newline='\\n'", self.workflow)


class TestWebuiDataRoots(unittest.TestCase):
    def test_frozen_package_and_durable_data_roots_are_separate(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            extract = base / 'onefile-extract'
            executable_dir = base / 'installed-app'
            extract.mkdir()
            executable_dir.mkdir()
            executable = executable_dir / 'narravid-webui.exe'
            with (
                mock.patch.dict(os.environ, {'NARRAVID_DATA_DIR': ''}, clear=False),
                mock.patch.object(sys, 'frozen', True, create=True),
                mock.patch.object(sys, '_MEIPASS', str(extract), create=True),
                mock.patch.object(sys, 'executable', str(executable)),
            ):
                self.assertEqual(webui_jobs._package_root(), extract)
                self.assertEqual(webui_jobs._app_data_root(), executable_dir.resolve())

    def test_data_dir_environment_override_wins_when_frozen(self):
        with tempfile.TemporaryDirectory() as td:
            custom = Path(td) / 'custom-data'
            executable = Path(td) / 'bin' / 'narravid-webui.exe'
            with (
                mock.patch.dict(
                    os.environ,
                    {'NARRAVID_DATA_DIR': f'  {custom}  '},
                    clear=False,
                ),
                mock.patch.object(sys, 'frozen', True, create=True),
                mock.patch.object(sys, '_MEIPASS', str(Path(td) / 'extract'), create=True),
                mock.patch.object(sys, 'executable', str(executable)),
            ):
                self.assertEqual(webui_jobs._app_data_root(), custom.resolve())

    def test_source_roots_use_module_directory(self):
        expected = Path(webui_jobs.__file__).resolve().parent
        with (
            mock.patch.dict(os.environ, {'NARRAVID_DATA_DIR': ''}, clear=False),
            mock.patch.object(sys, 'frozen', False, create=True),
        ):
            self.assertEqual(webui_jobs._package_root(), expected)
            self.assertEqual(webui_jobs._app_data_root(), expected)


class TestPathContainment(unittest.TestCase):
    def test_is_under_accepts_root_and_child_but_not_prefix_sibling(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / 'allowed'
            sibling = base / 'allowed-escape'
            root.mkdir()
            sibling.mkdir()

            self.assertTrue(webui_jobs._is_under(root, root))
            self.assertTrue(webui_jobs._is_under(root / 'nested' / 'clip.mp4', root))
            self.assertFalse(webui_jobs._is_under(sibling / 'clip.mp4', root))
            self.assertFalse(webui_jobs._is_under(root / '..' / sibling.name / 'clip.mp4', root))

    def test_resolve_media_path_enforces_root_file_and_extension(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            allowed = base / 'allowed'
            outside = base / 'outside'
            allowed.mkdir()
            outside.mkdir()
            clip = allowed / 'clip.mp4'
            clip.write_bytes(b'media')
            internal = allowed / '_stderr.log'
            internal.write_text('private', encoding='utf-8')
            outside_clip = outside / 'clip.mp4'
            outside_clip.write_bytes(b'media')

            with mock.patch.object(webui_jobs, 'MEDIA_ALLOWED_DIRS', [allowed.resolve()]):
                self.assertEqual(
                    webui_jobs._resolve_media_path('clip.mp4', base_dir=allowed),
                    clip.resolve(),
                )
                self.assertIsNone(webui_jobs._resolve_media_path(internal))
                self.assertIsNone(webui_jobs._resolve_media_path(outside_clip))
                self.assertIsNone(webui_jobs._resolve_media_path(allowed))

    def test_public_media_url_requires_data_root_containment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'data'
            media = root / 'rendered' / 'job' / 'video.mp4'
            outside = Path(td) / 'outside.mp4'
            with mock.patch.object(webui_jobs, 'ROOT', root):
                self.assertEqual(
                    webui_jobs._public_media_url(media),
                    '/rendered/job/video.mp4',
                )
                with self.assertRaises(ValueError):
                    webui_jobs._public_media_url(outside)



class TestSystemTtsGate(unittest.TestCase):
    def test_system_tts_available_matches_nt(self):
        self.assertEqual(video_auto.system_tts_available(), os.name == 'nt')

    def test_resolve_engine_system_rejected_off_windows(self):
        with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
            with mock.patch.object(video_auto, 'edge_tts_available', return_value=True):
                with self.assertRaises(RuntimeError) as cm:
                    video_auto.resolve_tts_engine('system')
                self.assertIn('Windows', str(cm.exception))

    def test_resolve_engine_auto_edge(self):
        with mock.patch.object(video_auto, 'edge_tts_available', return_value=True):
            self.assertEqual(video_auto.resolve_tts_engine(None), 'edge')

    def test_resolve_engine_auto_none(self):
        with mock.patch.object(video_auto, 'edge_tts_available', return_value=False):
            with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
                with self.assertRaises(RuntimeError):
                    video_auto.resolve_tts_engine(None)

    def test_synthesize_system_tts_guard(self):
        with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
            with self.assertRaises(RuntimeError):
                video_auto.synthesize_system_tts('hi', Path('x.wav'), 'v')

    def test_edge_retry_no_system_fallback_off_windows(self):
        calls = {'n': 0}

        def boom(*_a, **_k):
            calls['n'] += 1
            raise RuntimeError('edge down')

        with mock.patch.object(video_auto, 'synthesize_edge_tts', side_effect=boom):
            with mock.patch.object(video_auto, 'system_tts_available', return_value=False):
                with mock.patch.object(video_auto, 'MAX_TTS_RETRIES', 0):
                    with self.assertRaises(RuntimeError) as cm:
                        video_auto.synthesize_audio_with_retry(
                            'text', Path('out.mp3'), 'edge', 'zh-CN-XiaoxiaoNeural',
                        )
                    self.assertIn('无系统 TTS', str(cm.exception))
                    # must not call system path
        self.assertGreaterEqual(calls['n'], 1)


class TestFontDiscovery(unittest.TestCase):
    def setUp(self):
        video_auto.clear_font_cache_for_tests()

    def tearDown(self):
        video_auto.clear_font_cache_for_tests()

    def test_narravid_font_env(self):
        with tempfile.TemporaryDirectory() as td:
            font = Path(td) / 'CustomFont.ttf'
            font.write_bytes(b'\x00' * 16)
            with mock.patch.dict(os.environ, {'NARRAVID_FONT': str(font)}):
                video_auto.clear_font_cache_for_tests()
                found = video_auto._find_zh_font()
            self.assertEqual(Path(found).resolve(), font.resolve())

    def test_bundled_fonts_dir(self):
        with tempfile.TemporaryDirectory() as td:
            fonts = Path(td) / 'fonts'
            fonts.mkdir()
            target = fonts / 'NotoSansSC-Regular.otf'
            target.write_bytes(b'\x00' * 8)
            with mock.patch.dict(os.environ, {'NARRAVID_FONT': ''}, clear=False):
                os.environ.pop('NARRAVID_FONT', None)
                with mock.patch.object(video_auto, '_font_search_roots', return_value=[fonts]):
                    with mock.patch.object(video_auto, '_system_zh_font_candidates', return_value=[]):
                        video_auto.clear_font_cache_for_tests()
                        found = video_auto._find_zh_font()
            self.assertTrue(found)
            self.assertTrue(found.endswith('NotoSansSC-Regular.otf'))

    def test_default_subtitle_font_name_fallback(self):
        with mock.patch.object(video_auto, '_find_zh_font', return_value=None):
            video_auto.clear_font_cache_for_tests()
            name = video_auto.default_subtitle_font_name()
        self.assertTrue(isinstance(name, str) and len(name) > 0)

    def test_font_name_from_path_heuristics(self):
        self.assertEqual(video_auto._font_name_from_path('/x/msyh.ttc'), 'Microsoft YaHei')
        self.assertEqual(video_auto._font_name_from_path('/usr/share/fonts/NotoSansCJK-Regular.ttc'), 'Noto Sans CJK SC')
        self.assertEqual(video_auto._font_name_from_path('/usr/share/fonts/wqy-microhei.ttc'), 'WenQuanYi Micro Hei')

    def test_default_subtitle_style_contains_font(self):
        with mock.patch.object(video_auto, 'default_subtitle_font_name', return_value='Noto Sans CJK SC'):
            s = video_auto.default_subtitle_style()
        self.assertIn('FontName=Noto Sans CJK SC', s)

    def test_font_cache_reuses_result(self):
        with mock.patch.object(video_auto, '_system_zh_font_candidates', return_value=[]) as sys_cands:
            with mock.patch.object(video_auto, '_iter_bundled_font_files', return_value=iter([])):
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop('NARRAVID_FONT', None)
                    video_auto.clear_font_cache_for_tests()
                    a = video_auto._find_zh_font()
                    b = video_auto._find_zh_font()
                    self.assertEqual(a, b)
                    # second call should not re-scan system list
                    self.assertEqual(sys_cands.call_count, 1)


class TestKillProcess(unittest.TestCase):
    def test_windows_uses_taskkill(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4242
        with mock.patch.object(video_auto.os, 'name', 'nt'):
            with mock.patch.object(video_auto.subprocess, 'run') as run:
                video_auto._kill_process(proc)
                run.assert_called()
                args = run.call_args[0][0]
                self.assertEqual(args[0], 'taskkill')
                self.assertIn('/PID', args)
                self.assertIn('4242', args)

    def test_posix_uses_killpg(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 99
        proc.wait.return_value = 0  # after SIGTERM
        with mock.patch.object(video_auto.os, 'name', 'posix'):
            with mock.patch.object(video_auto.os, 'killpg', create=True) as killpg:
                video_auto._kill_process(proc)
                killpg.assert_called()
                self.assertEqual(killpg.call_args[0][0], 99)
                self.assertEqual(killpg.call_args[0][1], signal.SIGTERM)

    def test_already_exited_process_is_not_terminated_again(self):
        proc = mock.Mock()
        proc.poll.return_value = 0
        with (
            mock.patch.object(video_auto.os, 'name', 'nt'),
            mock.patch.object(video_auto.subprocess, 'run') as run,
        ):
            video_auto._kill_process(proc)
        run.assert_not_called()
        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()

    def test_windows_taskkill_failure_falls_back_to_process_method(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4243
        failed = mock.Mock(returncode=1)
        with (
            mock.patch.object(video_auto.os, 'name', 'nt'),
            mock.patch.object(video_auto.subprocess, 'run', return_value=failed),
        ):
            video_auto._kill_process(proc)
        self.assertTrue(proc.terminate.called or proc.kill.called)

    def test_posix_escalates_to_sigkill_after_term_timeout(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 100
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd=['x'], timeout=2)
        sigkill = mock.sentinel.sigkill
        with (
            mock.patch.object(video_auto.os, 'name', 'posix'),
            mock.patch.object(video_auto.os, 'killpg', create=True) as killpg,
            mock.patch.object(video_auto.signal, 'SIGKILL', sigkill, create=True),
        ):
            video_auto._kill_process(proc)
        self.assertEqual(
            killpg.call_args_list,
            [mock.call(100, signal.SIGTERM), mock.call(100, sigkill)],
        )

    def test_posix_missing_process_group_falls_back_to_terminate(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 101
        proc.wait.return_value = 0
        with (
            mock.patch.object(video_auto.os, 'name', 'posix'),
            mock.patch.object(
                video_auto.os,
                'killpg',
                side_effect=ProcessLookupError,
                create=True,
            ),
        ):
            video_auto._kill_process(proc)
        proc.terminate.assert_called_once_with()
        proc.kill.assert_not_called()


class TestSubprocessSessionBoundary(unittest.TestCase):
    def setUp(self):
        video_auto.CancelToken.reset()
        with video_auto._ACTIVE_PROCS_LOCK:
            video_auto._ACTIVE_PROCS.clear()

    def tearDown(self):
        video_auto.CancelToken.reset()
        with video_auto._ACTIVE_PROCS_LOCK:
            video_auto._ACTIVE_PROCS.clear()

    def test_run_uses_new_posix_session_and_unregisters_child(self):
        proc = mock.Mock()

        def wait(timeout=None):
            self.assertIn(proc, video_auto._ACTIVE_PROCS)
            return 0

        proc.wait.side_effect = wait
        with (
            mock.patch.object(video_auto.os, 'name', 'posix'),
            mock.patch.object(video_auto.subprocess, 'Popen', return_value=proc) as popen,
        ):
            video_auto.run(['ffmpeg', '-version'], silent=True)

        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(popen.call_args.kwargs['stdout'], subprocess.DEVNULL)
        self.assertNotIn(proc, video_auto._ACTIVE_PROCS)

    def test_run_does_not_request_new_session_on_windows(self):
        proc = mock.Mock()
        proc.wait.return_value = 0
        with (
            mock.patch.object(video_auto.os, 'name', 'nt'),
            mock.patch.object(video_auto.subprocess, 'Popen', return_value=proc) as popen,
        ):
            video_auto.run(['ffmpeg', '-version'])

        self.assertNotIn('start_new_session', popen.call_args.kwargs)
        self.assertNotIn(proc, video_auto._ACTIVE_PROCS)

    def test_ffprobe_uses_new_posix_session_and_unregisters_child(self):
        proc = mock.Mock()
        proc.returncode = 0

        def communicate(timeout=None):
            self.assertIn(proc, video_auto._ACTIVE_PROCS)
            return '1.25', None

        proc.communicate.side_effect = communicate
        media_path = Path('media.mp4')
        with (
            mock.patch.object(video_auto.os, 'name', 'posix'),
            mock.patch.object(video_auto.subprocess, 'Popen', return_value=proc) as popen,
        ):
            duration = video_auto.ffprobe_duration(media_path)

        self.assertEqual(duration, 1.25)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertNotIn(proc, video_auto._ACTIVE_PROCS)

    def test_capture_text_cancels_registered_probe_without_waiting_for_timeout(self):
        proc = mock.Mock()
        proc.returncode = None
        proc.poll.return_value = None
        proc.wait.return_value = -1

        def communicate(timeout=None):
            self.assertEqual(timeout, 0.4)
            self.assertIn(proc, video_auto._ACTIVE_PROCS)
            with video_auto.CancelToken._lock:
                video_auto.CancelToken._cancelled = True
                video_auto.CancelToken._user = True
            raise subprocess.TimeoutExpired(['ffprobe'], timeout)

        proc.communicate.side_effect = communicate
        with (
            mock.patch.object(video_auto.os, 'name', 'posix'),
            mock.patch.object(video_auto.subprocess, 'Popen', return_value=proc),
            mock.patch.object(video_auto, '_kill_process') as kill_process,
        ):
            with self.assertRaisesRegex(RuntimeError, '用户取消'):
                video_auto.run_capture_text(['ffprobe'], timeout=60)

        kill_process.assert_called_once_with(proc)
        self.assertNotIn(proc, video_auto._ACTIVE_PROCS)



class TestBundledFfmpeg(unittest.TestCase):
    def setUp(self):
        self._path_present = 'PATH' in os.environ
        self._path_before = os.environ.get('PATH')
        _bundled_ffmpeg.reset_cache_for_tests()

    def tearDown(self):
        _bundled_ffmpeg.reset_cache_for_tests()
        if self._path_present:
            os.environ['PATH'] = self._path_before
        else:
            os.environ.pop('PATH', None)

    @staticmethod
    def _write_bundle(root):
        binary_dir = root / 'ffmpeg'
        binary_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for tool in ('ffmpeg', 'ffprobe'):
            path = binary_dir / _bundled_ffmpeg._binary_names(tool)[0]
            path.write_bytes(b'executable placeholder')
            path.chmod(path.stat().st_mode | 0o111)
            paths[tool] = path
        return paths

    def test_binary_names_nt(self):
        with mock.patch.object(_bundled_ffmpeg.os, 'name', 'nt'):
            self.assertEqual(_bundled_ffmpeg._binary_names('ffmpeg')[0], 'ffmpeg.exe')

    def test_binary_names_posix(self):
        with mock.patch.object(_bundled_ffmpeg.os, 'name', 'posix'):
            self.assertEqual(_bundled_ffmpeg._binary_names('ffmpeg')[0], 'ffmpeg')

    def test_first_existing_extensionless(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'ffmpeg').write_text('x', encoding='utf-8')
            with mock.patch.object(_bundled_ffmpeg.os, 'name', 'posix'):
                found = _bundled_ffmpeg._first_existing(d, 'ffmpeg')
            self.assertTrue(found)
            self.assertTrue(found.endswith('ffmpeg'))

    def test_first_existing_prefers_native_name_when_both_exist(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            primary, fallback = _bundled_ffmpeg._binary_names('ffmpeg')
            (directory / primary).write_bytes(b'primary')
            (directory / fallback).write_bytes(b'fallback')
            self.assertEqual(
                _bundled_ffmpeg._first_existing(directory, 'ffmpeg'),
                str(directory / primary),
            )

    def test_environment_override_wins_over_bundled_and_path(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            custom_ffmpeg = base / 'custom-ffmpeg'
            custom_ffprobe = base / 'custom-ffprobe'
            custom_ffmpeg.write_bytes(b'ffmpeg')
            custom_ffprobe.write_bytes(b'ffprobe')
            custom_ffmpeg.chmod(custom_ffmpeg.stat().st_mode | 0o111)
            custom_ffprobe.chmod(custom_ffprobe.stat().st_mode | 0o111)
            extract = base / 'extract'
            self._write_bundle(extract)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        'NARRAVID_FFMPEG': str(custom_ffmpeg),
                        'NARRAVID_FFPROBE': str(custom_ffprobe),
                        'FFMPEG': '',
                        'FFPROBE': '',
                    },
                    clear=False,
                ),
                mock.patch.object(sys, '_MEIPASS', str(extract), create=True),
                mock.patch.object(_bundled_ffmpeg, '_which_tool') as which_tool,
            ):
                self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), str(custom_ffmpeg))
                self.assertEqual(_bundled_ffmpeg.get_ffprobe(), str(custom_ffprobe))
            which_tool.assert_not_called()

    def test_environment_override_directory_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            found = {
                'ffmpeg': str(Path(td) / 'ffmpeg-from-path'),
                'ffprobe': str(Path(td) / 'ffprobe-from-path'),
            }
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        'NARRAVID_FFMPEG': td,
                        'NARRAVID_FFPROBE': '',
                        'FFMPEG': '',
                        'FFPROBE': '',
                    },
                    clear=False,
                ),
                mock.patch.object(sys, '_MEIPASS', None, create=True),
                mock.patch.object(_bundled_ffmpeg, '_first_existing', return_value=None),
                mock.patch.object(_bundled_ffmpeg, '_which_tool', side_effect=found.get),
            ):
                self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), found['ffmpeg'])

    def test_relative_environment_override_is_returned_as_absolute_path(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            custom_ffmpeg = Path(td) / 'custom-ffmpeg'
            custom_ffprobe = Path(td) / 'custom-ffprobe'
            custom_ffmpeg.write_bytes(b'ffmpeg')
            custom_ffprobe.write_bytes(b'ffprobe')
            relative_ffmpeg = custom_ffmpeg.relative_to(Path.cwd())
            custom_ffmpeg.chmod(custom_ffmpeg.stat().st_mode | 0o111)
            custom_ffprobe.chmod(custom_ffprobe.stat().st_mode | 0o111)
            relative_ffprobe = custom_ffprobe.relative_to(Path.cwd())
            with mock.patch.dict(
                os.environ,
                {
                    'NARRAVID_FFMPEG': str(relative_ffmpeg),
                    'NARRAVID_FFPROBE': str(relative_ffprobe),
                    'FFMPEG': '',
                    'FFPROBE': '',
                },
                clear=False,
            ):
                self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), str(custom_ffmpeg.resolve()))
                self.assertEqual(_bundled_ffmpeg.get_ffprobe(), str(custom_ffprobe.resolve()))

    def test_meipass_precedes_executable_adjacent_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            extract_paths = self._write_bundle(base / 'extract')
            executable_dir = base / 'installed'
            self._write_bundle(executable_dir)
            executable = executable_dir / 'narravid.exe'
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        'NARRAVID_FFMPEG': '',
                        'NARRAVID_FFPROBE': '',
                        'FFMPEG': '',
                        'FFPROBE': '',
                    },
                    clear=False,
                ),
                mock.patch.object(sys, 'frozen', True, create=True),
                mock.patch.object(sys, '_MEIPASS', str(base / 'extract'), create=True),
                mock.patch.object(sys, 'executable', str(executable)),
            ):
                self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), str(extract_paths['ffmpeg']))
                self.assertEqual(_bundled_ffmpeg.get_ffprobe(), str(extract_paths['ffprobe']))

    def test_frozen_executable_adjacent_bundle_without_meipass(self):
        with tempfile.TemporaryDirectory() as td:
            executable_dir = Path(td) / 'installed'
            adjacent_paths = self._write_bundle(executable_dir)
            executable = executable_dir / 'narravid.exe'
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        'NARRAVID_FFMPEG': '',
                        'NARRAVID_FFPROBE': '',
                        'FFMPEG': '',
                        'FFPROBE': '',
                    },
                    clear=False,
                ),
                mock.patch.object(sys, 'frozen', True, create=True),
                mock.patch.object(sys, '_MEIPASS', None, create=True),
                mock.patch.object(sys, 'executable', str(executable)),
            ):
                self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), str(adjacent_paths['ffmpeg']))
                self.assertEqual(_bundled_ffmpeg.get_ffprobe(), str(adjacent_paths['ffprobe']))

    def test_path_lookup_is_used_when_no_bundle_exists(self):
        with tempfile.TemporaryDirectory() as td:
            found = {
                'ffmpeg': str(Path(td) / 'ffmpeg-from-path'),
                'ffprobe': str(Path(td) / 'ffprobe-from-path'),
            }
            for path in found.values():
                Path(path).write_bytes(b'executable placeholder')
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        'NARRAVID_FFMPEG': '',
                        'NARRAVID_FFPROBE': '',
                        'FFMPEG': '',
                        'FFPROBE': '',
                    },
                    clear=False,
                ),
                mock.patch.object(sys, '_MEIPASS', None, create=True),
                mock.patch.object(_bundled_ffmpeg, '_first_existing', return_value=None),
                mock.patch.object(_bundled_ffmpeg, '_which_tool', side_effect=found.get) as which_tool,
            ):
                self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), found['ffmpeg'])
                self.assertEqual(_bundled_ffmpeg.get_ffprobe(), found['ffprobe'])
                self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), found['ffmpeg'])
            self.assertEqual(
                which_tool.call_args_list,
                [mock.call('ffmpeg'), mock.call('ffprobe')],
            )


    def test_bare_fallback_does_not_prepend_current_directory_to_path(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    'PATH': 'sentinel-path',
                    'NARRAVID_FFMPEG': '',
                    'NARRAVID_FFPROBE': '',
                    'FFMPEG': '',
                    'FFPROBE': '',
                },
                clear=False,
            ),
            mock.patch.object(sys, '_MEIPASS', None, create=True),
            mock.patch.object(_bundled_ffmpeg, '_first_existing', return_value=None),
            mock.patch.object(_bundled_ffmpeg, '_which_tool', return_value=None),
        ):
            self.assertEqual(_bundled_ffmpeg.get_ffmpeg(), 'ffmpeg')
            self.assertEqual(_bundled_ffmpeg.get_ffprobe(), 'ffprobe')
            self.assertEqual(os.environ['PATH'], 'sentinel-path')


class TestSubtitleFilterUsesDefault(unittest.TestCase):
    def test_no_override_uses_default_style(self):
        with tempfile.TemporaryDirectory() as td:
            srt = Path(td) / 'a.srt'
            srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nhi\n', encoding='utf-8')
            with mock.patch.object(video_auto, 'default_subtitle_style', return_value='FontName=TestFont,FontSize=16'):
                arg = video_auto.subtitle_filter_arg(srt, None)
            self.assertIn('TestFont', arg)
            self.assertIn('force_style', arg)


if __name__ == '__main__':
    unittest.main()


class TestMainArgvApi(unittest.TestCase):
    def test_main_accepts_explicit_argv(self):
        """main(argv=...) must parse without mutating process sys.argv."""
        import sys
        before = list(sys.argv)
        try:
            try:
                video_auto.main(['__no_such_manifest__.json', '--workers', '1'])
            except (SystemExit, FileNotFoundError, ValueError, Exception):
                pass
        finally:
            self.assertEqual(list(sys.argv), before)


class TestRunFromManifestFile(unittest.TestCase):
    def test_run_from_manifest_file_builds_argv(self):
        import sys
        before = list(sys.argv)
        with self.assertRaises((SystemExit, FileNotFoundError, ValueError, Exception)):
            video_auto.run_from_manifest_file('__nope__.json', output_dir='out', workers=1, no_burn=True)
        self.assertEqual(list(sys.argv), before)
