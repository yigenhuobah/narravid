"""
narravid Web UI v6 — 图片上传、缩略图预览、BGM 管理、在线预览、模板、一键生成。

用法:
  python webui.py
  python webui.py --port 8080
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from webui_jobs import (  # re-export for tests / external importers
    JOBS,
    MAX_BGM_SIZE,
    MAX_IMAGE_SIZE,
    MAX_TEMPLATE_BODY,
    MAX_UPLOAD_SIZE,
    MAX_VIDEO_SIZE,
    OUT_BASE,
    PACKAGE_ROOT,
    RENDER_LOCK,
    ROOT,
    STALL_SECONDS,
    STALL_TICKS,
    TEMPLATE_DIR,
    THUMB_ALLOWED_DIRS,
    UPLOAD_DIR,
    _check_edge_tts,
    _get_active_render,
    _is_exportable_media,
    _is_under,
    _is_under_any,
    _is_waiting_for_lock,
    _job_out_dir,
    _looks_like_cancel,
    _mark_job_cancelled,
    _pick_final_mp4,
    _public_media_url,
    _resolve_media_path,
    _sanitize_render_id,
    _sanitize_upload_name,
    _set_active_render,
    _signal_cancel_token_if_active,
    _systemexit_message,
)
from webui_ui import HTML

# video_auto.py lives in package root (source tree or frozen extract dir)
SCRIPT = PACKAGE_ROOT / 'video_auto.py'

def _write_b64_to_file(b64: str, dest: Path, max_bytes: int) -> int:
    """Decode base64 in chunks to dest; enforce max_bytes. Returns size written."""
    if not b64:
        raise ValueError('empty base64')
    if len(b64) > (max_bytes * 4 // 3) + 8:
        raise ValueError('payload too large')
    cleaned = ''.join(b64.split())
    if len(cleaned) > (max_bytes * 4 // 3) + 8:
        raise ValueError('payload too large')
    step = 65536
    written = 0
    buf = ''
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, 'wb') as out:
        for i in range(0, len(cleaned), step):
            chunk = cleaned[i:i + step]
            data = buf + chunk
            take = len(data) - (len(data) % 4)
            if take <= 0:
                buf = data
                continue
            piece, buf = data[:take], data[take:]
            try:
                raw = base64.b64decode(piece, validate=False)
            except Exception as e:
                raise ValueError('base64 解码失败') from e
            written += len(raw)
            if written > max_bytes:
                raise ValueError('file too large')
            out.write(raw)
        if buf:
            pad = (-len(buf)) % 4
            try:
                raw = base64.b64decode(buf + ('=' * pad), validate=False)
            except Exception as e:
                raise ValueError('base64 解码失败') from e
            written += len(raw)
            if written > max_bytes:
                raise ValueError('file too large')
            out.write(raw)
    return written



class WebUIHandler(SimpleHTTPRequestHandler):
    def do_HEAD(self):
        """Same access policy as GET — never fall through to SimpleHTTPRequestHandler."""
        # Reuse GET handlers which call _file/_json; for HEAD only headers matter.
        # Temporarily wrap _file to skip body.
        orig_file = self._file
        def _head_file(fp, ct, as_attachment=False):
            self.send_response(200)
            self.send_header('Content-Type', ct)
            if as_attachment:
                self.send_header('Content-Disposition', f'attachment; filename="{fp.name}"')
            else:
                self.send_header('Content-Disposition', f'inline; filename="{fp.name}"')
            try:
                size = fp.stat().st_size
            except Exception:
                size = 0
            self.send_header('Content-Length', str(size))
            self.send_header('Cache-Control', 'max-age=3600')
            self.end_headers()
        self._file = _head_file  # type: ignore[method-assign]
        try:
            self.do_GET()
        finally:
            self._file = orig_file  # type: ignore[method-assign]

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == '/' or p.path == '/index.html':
            self._html(HTML)
        elif p.path.startswith('/thumb'):
            qs = urllib.parse.parse_qs(p.query)
            img = qs.get('path', [None])[0]
            if img:
                fp = Path(img).resolve()
                # 安全路径检查：必须严格在允许目录内（用 relative_to 防止前缀绕过）
                allowed = False
                for d in THUMB_ALLOWED_DIRS:
                    try:
                        fp.relative_to(d)
                        allowed = True
                        break
                    except ValueError:
                        pass
                if not allowed:
                    self._json({'error': 'forbidden'}, 403); return
                if fp.exists() and fp.is_file():
                    # 按文件类型设置正确的 Content-Type
                    ext = fp.suffix.lower()
                    if ext in ('.mp4',):
                        ct = 'video/mp4'
                    elif ext in ('.webm',):
                        ct = 'video/webm'
                    elif ext in ('.mov',):
                        ct = 'video/quicktime'
                    elif ext in ('.mkv',):
                        ct = 'video/x-matroska'
                    elif ext == '.png':
                        ct = 'image/png'
                    elif ext in ('.jpg', '.jpeg'):
                        ct = 'image/jpeg'
                    elif ext in ('.gif',):
                        ct = 'image/gif'
                    else:
                        ct = 'application/octet-stream'
                    self._file(fp, ct)
                    return
            self._json({'error': 'not found'}, 404)
        elif p.path.startswith('/api/status/'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if not j:
                self._json({'error': 'not found'}, 404); return
            done = j.get('done', False)
            progress = j.get('progress', '')
            cancelled = bool(j.get('cancelled'))
            # 终态（取消/超时/失败）以 job 字段为准，勿被仍在写的 progress_file 盖掉
            if not (done or cancelled or j.get('error')):
                pf = j.get('progress_file')
                if pf and Path(pf).exists():
                    try:
                        progress = Path(pf).read_text(encoding='utf-8').strip() or progress
                    except Exception:
                        pass
            if not cancelled:
                cancelled = _looks_like_cancel(progress) or _looks_like_cancel(j.get('error'))
            resp = {
                'done': done,
                'progress': progress,
                'video': j.get('video') if not cancelled else '',
                'srt': j.get('srt'),
                'cancelled': cancelled,
            }
            if j.get('warning'):
                resp['warning'] = j.get('warning')
            if done:
                if j.get('error'):
                    resp['error'] = j['error'][-300:]
                elif cancelled:
                    # 明确标记取消，避免前端当成成功
                    resp['cancelled'] = True
                    if not resp.get('error'):
                        resp['error'] = '已取消'
                else:
                    video = j.get('video', '')
                    # 回退：如果还没设置 video，直接扫目录（仅 job 自身 out）
                    if not video:
                        out_dir = j.get('out')
                        if out_dir:
                            try:
                                od = Path(out_dir).resolve()
                                if _is_under(od, OUT_BASE):
                                    mp4 = _pick_final_mp4(od)
                                    if mp4:
                                        video = _public_media_url(mp4)
                                        j['video'] = video
                                        if not j.get('srt'):
                                            srt_p = mp4.with_suffix('.srt')
                                            if srt_p.is_file():
                                                j['srt'] = _public_media_url(srt_p)
                            except Exception:
                                pass
                    resp['video'] = video
                    if j.get('srt'):
                        resp['srt'] = j.get('srt')
                    j['progress'] = j.get('progress') or '完成'
            self._json(resp)
        elif p.path == '/api/bgm-list':
            bgms = []
            # 递归：含导入工程 project_*/assets 下的 BGM
            seen = set()
            for pattern in ('**/*.mp3', '**/*.wav'):
                for f in sorted(UPLOAD_DIR.glob(pattern)):
                    if not f.is_file():
                        continue
                    key = str(f.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    bgms.append({'name': f.name, 'path': key})
            self._json(bgms)
        elif p.path == '/api/tts-check':
            engine, label = _check_edge_tts()
            self._json({'engine': engine, 'label': label})
        elif p.path == '/api/health':
            # Lightweight readiness for operators / reverse proxies
            engine, label = _check_edge_tts()
            ffmpeg_ok = False
            ffprobe_ok = False
            ffmpeg_path = ''
            ffprobe_path = ''
            try:
                import shutil
                import subprocess

                import _bundled_ffmpeg as _bf
                ffmpeg_path = _bf.get_ffmpeg()
                ffprobe_path = _bf.get_ffprobe()

                def _tool_ok(path: str) -> bool:
                    if not path:
                        return False
                    pth = Path(path)
                    if pth.is_file():
                        resolved = str(pth)
                    else:
                        found = shutil.which(path)
                        if not found:
                            return False
                        resolved = found
                    try:
                        r = subprocess.run(
                            [resolved, '-version'],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                        )
                        return r.returncode == 0
                    except Exception:
                        return False

                ffmpeg_ok = _tool_ok(ffmpeg_path)
                ffprobe_ok = _tool_ok(ffprobe_path)
            except Exception:
                pass
            font_path = None
            try:
                import video_auto as _va
                font_path = _va._find_zh_font()
            except Exception:
                pass
            ok = engine in ('edge', 'system') and ffmpeg_ok
            self._json({
                'ok': ok,
                'tts': {'engine': engine, 'label': label},
                'ffmpeg': {'ok': ffmpeg_ok, 'path': ffmpeg_path},
                'ffprobe': {'ok': ffprobe_ok, 'path': ffprobe_path},
                'font': {'ok': bool(font_path), 'path': font_path or ''},
                'active_render': _get_active_render(),
                'jobs': len(JOBS),
            }, 200 if ok else 503)
        elif p.path.startswith('/api/templates'):
            self._handle_templates_get(p)
        elif p.path.startswith('/rendered/'):
            fp = (ROOT / p.path.lstrip('/')).resolve()
            # 仅允许成品输出：rendered/webui/<job>/ 下的视频与字幕
            # 禁止：源码穿越、uploads/templates 媒体与 JSON、任意日志
            if not _is_under(fp, OUT_BASE):
                self._json({'error': 'forbidden'}, 403); return
            # 排除 uploads / templates
            try:
                rel = fp.relative_to(OUT_BASE.resolve())
            except ValueError:
                self._json({'error': 'forbidden'}, 403); return
            parts = rel.parts
            if not parts or parts[0] in ('uploads', 'templates'):
                self._json({'error': 'forbidden'}, 403); return
            if fp.exists() and fp.is_file():
                ext = fp.suffix.lower()
                if ext == '.mp4':
                    ct = 'video/mp4'
                elif ext == '.srt':
                    ct = 'text/plain; charset=utf-8'
                else:
                    # 不暴露 _stderr.log / manifest.json 等内部文件
                    self._json({'error': 'forbidden'}, 403); return
                self._file(fp, ct)
            else:
                self._json({'error': 'not found'}, 404)
        else:
            # 不暴露工作目录静态文件，避免源码被直接拉取
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        try:
            self._do_POST_impl()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({'error': f'server error: {e}'}, 500)

    def _do_POST_impl(self):
        p = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        if length > MAX_UPLOAD_SIZE:
            self._json({'error': f'文件过大（上限 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）'}, 413)
            return
        body = self.rfile.read(length) if length else b''

        if p.path == '/api/upload':
            data = json.loads(body)
            name = data.get('name', 'image.png')
            b64 = data.get('data', '')
            kind = data.get('kind', 'image')
            ext = Path(name).suffix.lower()
            video_exts = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.flv'}
            is_video = kind == 'video' or ext in video_exts
            if kind == 'bgm' or ext in {'.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg'}:
                max_bytes = MAX_BGM_SIZE
                kind_label = 'BGM'
            elif is_video:
                max_bytes = MAX_VIDEO_SIZE
                kind_label = '视频'
            else:
                max_bytes = MAX_IMAGE_SIZE
                kind_label = '图片'
            safe_name = _sanitize_upload_name(name)
            fp = (UPLOAD_DIR / f'{uuid.uuid4().hex}_{safe_name}').resolve()
            if not _is_under(fp, UPLOAD_DIR):
                self._json({'error': '非法文件名'}, 400); return
            try:
                size = _write_b64_to_file(b64 if isinstance(b64, str) else '', fp, max_bytes)
            except ValueError as e:
                try:
                    fp.unlink(missing_ok=True)
                except Exception:
                    pass
                msg = str(e)
                if 'too large' in msg or 'payload too large' in msg:
                    self._json({'error': f'{kind_label}超过 {max_bytes // 1024 // 1024}MB 限制'}, 413); return
                self._json({'error': 'base64 解码失败'}, 400); return
            self._json({'path': str(fp), 'size': size})

        elif p.path == '/api/render':
            data = json.loads(body)
            m = data.get('manifest', {})
            if not isinstance(m, dict):
                self._json({'error': 'manifest 必须是对象'}, 400); return
            scenes = m.get('scenes')
            if not isinstance(scenes, list) or not scenes:
                self._json({'error': 'manifest.scenes 不能为空'}, 400); return
            # 场景媒体必须在白名单目录内（防任意本地文件读入成片）
            for i, scene in enumerate(scenes):
                if not isinstance(scene, dict):
                    self._json({'error': f'scenes[{i}] 必须是对象'}, 400); return
                img = scene.get('image', '')
                if not img:
                    self._json({'error': f'scenes[{i}] 缺少 image'}, 400); return
                resolved = _resolve_media_path(img)
                if not resolved:
                    self._json({'error': f'非法媒体路径: {img}'}, 400); return
                scene['image'] = str(resolved)
            bgm = data.get('bgm')
            if bgm:
                bp = _resolve_media_path(bgm)
                if not bp:
                    self._json({'error': f'非法 BGM 路径: {bgm}'}, 400); return
                bgm = str(bp)
            tc = data.get('title_card')
            ec = data.get('end_card')
            rid = _sanitize_render_id(data.get('render_id'))
            # 防止客户端 render_id 碰撞 / 非法：重生 UUID
            if not rid or rid in JOBS:
                rid = uuid.uuid4().hex
            out = _job_out_dir(rid)
            if out is None:
                self._json({'error': '非法 render_id'}, 400); return
            out.mkdir(parents=True, exist_ok=True)
            mp = out / 'manifest.json'
            try:
                import video_auto as _va_norm
                m = _va_norm.normalize_manifest(m)
            except Exception as e:
                self._json({'error': f'manifest 无效: {e}'}, 400); return
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
            # 构建命令行参数列表（统一方式，兼容源码和 exe 模式）
            cmd = [str(SCRIPT), str(mp), '--output-dir', str(out)]
            if bgm:
                cmd += ['--bgm', bgm]
                bvol = m.get('bgm_volume')
                if bvol is not None and isinstance(bvol, (int, float)) and 0.0 <= bvol <= 1.0:
                    cmd += ['--bgm-volume', str(bvol)]
            if tc:
                # write non-ASCII title card text to temp file to avoid cmdline encoding issues
                if any(ord(c) > 127 for c in tc):
                    tcf = out / '_title_card.txt'
                    tcf.write_text(tc, encoding='utf-8')
                    cmd += ['--title-card-file', str(tcf)]
                else:
                    cmd += ['--title-card', tc]
                cd = data.get('card_duration')
                if cd and isinstance(cd, (int, float)) and cd >= 1.0:
                    cmd += ['--card-duration', str(cd)]
            if ec:
                if any(ord(c) > 127 for c in ec):
                    ecf = out / '_end_card.txt'
                    ecf.write_text(ec, encoding='utf-8')
                    cmd += ['--end-card-file', str(ecf)]
                else:
                    cmd += ['--end-card', ec]
                ecd = data.get('end_card_duration')
                if ecd and isinstance(ecd, (int, float)) and ecd >= 1.0:
                    cmd += ['--end-card-duration', str(ecd)]
            # 与 video_auto.parse_boolish 对齐：字符串 "false"/"0" 应关闭烧录
            try:
                import video_auto as _va_bs
                _burn = _va_bs.parse_boolish(m.get('burn_subtitles', True), default=True)
            except Exception:
                _bs = m.get('burn_subtitles', True)
                if isinstance(_bs, str):
                    _burn = _bs.strip().lower() not in ('0', 'false', 'no', 'off', 'n', '')
                else:
                    _burn = bool(_bs) if _bs is not None else True
            if not _burn:
                cmd += ['--no-burn']
            # 字幕样式（sanitize 后再下发，避免 force_style 注入）
            ss = m.get('subtitle_style')
            if ss and isinstance(ss, str) and len(ss) < 500:
                try:
                    import video_auto as _va_ss
                    ss = _va_ss.sanitize_subtitle_style(ss)
                except Exception:
                    ss = re.sub(r"[\\'\"\[\]:;|]", '', ss).strip()
                if ss:
                    cmd += ['--subtitle-style', ss]
            engine = m.get('tts_engine')
            if engine and engine in ('edge', 'system'):
                cmd += ['--engine', engine]
            if m.get('voice'):
                cmd += ['--voice', str(m['voice'])]
            spd = m.get('speech_speed')
            if spd and isinstance(spd, (int, float)) and 0.5 <= spd <= 3.0:
                cmd += ['--speed', str(spd)]
            wk = m.get('workers', 4)
            if wk and isinstance(wk, int) and 1 <= wk <= 32:
                cmd += ['--workers', str(wk)]
            progress_file = out / '_progress.txt'
            progress_file.write_text('初始化...', encoding='utf-8')
            env = os.environ.copy()
            env['NARRAVID_PROGRESS_FILE'] = str(progress_file)

            # 在子线程中直接调用 video_auto.main()，不再用 subprocess
            # 这样 exe 模式下无需依赖 sys.executable 指向 python 解释器
            cancel_event = threading.Event()
            JOBS[rid] = {'proc': None, 'progress': 'TTS 生成中...', 'video': '', 'srt': '',
                         'progress_file': str(progress_file), 'out': out,
                         'cancel_event': cancel_event, 'done': False, 'error': '',
                         'cancelled': False}

            # 环境变量：只设 progress_file；main(argv=...) 避免改写全局 sys.argv
            progress_env_val = str(progress_file)
            # cmd[0] 是 SCRIPT 占位，parse_args 只要选项列表
            main_argv = [str(x) for x in cmd[1:]]

            def run_in_thread():
                j = JOBS.get(rid)
                if not j:
                    return
                with RENDER_LOCK:
                    if j.get('done') or j.get('cancelled'):
                        return  # 已被取消 / 超时
                    # 在获取锁之后才重置取消令牌，避免排队期间被前一个任务的取消污染
                    import video_auto as _va
                    _va.CancelToken.reset()
                    # 再检一次：reset 与 main 之间的 cancel 窗口
                    if j.get('done') or j.get('cancelled') or (
                        j.get('cancel_event') and j['cancel_event'].is_set()
                    ):
                        _mark_job_cancelled(j)
                        return
                    j['_started'] = True
                    _set_active_render(rid)
                    # 若在 set active 瞬间被取消，立刻武装 token
                    if j.get('cancelled') or (j.get('cancel_event') and j['cancel_event'].is_set()):
                        _va.CancelToken.set_cancelled()
                    # 路径均为绝对/可解析；不再 chdir，避免污染进程工作目录
                    try:
                        os.environ['NARRAVID_PROGRESS_FILE'] = progress_env_val
                        _va.main(main_argv)
                        # 若取消/超时已抢先标记，不要把状态覆盖成“完成”
                        if j.get('cancelled') or j.get('error'):
                            prior = (j.get('error') or '').strip()
                            if prior.startswith('渲染超时'):
                                # 超时诊断优先于取消文案
                                j['progress'] = j.get('progress') or '超时（渲染卡死）'
                            elif j.get('cancelled') and not prior:
                                j['error'] = '已取消'
                                j['progress'] = '已取消'
                            elif j.get('cancelled'):
                                # 有其它 prior error 时保留 error，进度标取消
                                j['progress'] = j.get('progress') or '已取消'
                        else:
                            mp4 = _pick_final_mp4(out)
                            if mp4:
                                j['video'] = _public_media_url(mp4)
                                srt_p = mp4.with_suffix('.srt')
                                if srt_p.is_file():
                                    j['srt'] = _public_media_url(srt_p)
                                j['progress'] = '完成'
                            else:
                                j['error'] = j.get('error') or '渲染结束但未生成视频'
                                j['progress'] = '失败: 未生成视频'
                    except SystemExit as e:
                        # video_auto.main converts some fatal errors to SystemExit;
                        # must not fall through as false success (empty video/error).
                        import traceback
                        tb = traceback.format_exc()
                        err_file = out / '_stderr.log'
                        try:
                            out.mkdir(parents=True, exist_ok=True)
                            err_file.write_text(tb, encoding='utf-8', errors='ignore')
                        except Exception:
                            pass
                        msg = _systemexit_message(e)
                        prior = (j.get('error') or '').strip()
                        if prior.startswith('渲染超时'):
                            j['progress'] = j.get('progress') or '超时（渲染卡死）'
                        elif j.get('cancelled') or _looks_like_cancel(msg):
                            j['cancelled'] = True
                            j['error'] = prior or '已取消'
                            j['progress'] = '已取消'
                        elif prior:
                            j['progress'] = j.get('progress') or f'失败: {msg}'[:200]
                        else:
                            j['error'] = msg[-500:]
                            j['progress'] = f'失败: {msg}'[:200]
                    except Exception as e:
                        import traceback
                        tb = traceback.format_exc()
                        err_file = out / '_stderr.log'
                        try:
                            out.mkdir(parents=True, exist_ok=True)
                            err_file.write_text(tb, encoding='utf-8', errors='ignore')
                        except Exception:
                            pass
                        msg = str(e)
                        prior = (j.get('error') or '').strip()
                        # 超时诊断优先：monitor 已写「渲染超时」时，即使随后用户点取消也不要盖成「已取消」
                        if prior.startswith('渲染超时'):
                            j['progress'] = j.get('progress') or '超时（渲染卡死）'
                            # 保留 prior error；cancelled 标志可并存，供 UI 区分
                        elif j.get('cancelled') or _looks_like_cancel(msg):
                            j['cancelled'] = True
                            # 保留已有非空 error（如其它 mon 诊断），否则记已取消
                            j['error'] = prior or '已取消'
                            j['progress'] = '已取消'
                        elif prior:
                            # 已有 error 且非取消：勿用 CancelToken 文案覆盖
                            j['progress'] = j.get('progress') or f'失败: {e}'[:200]
                        else:
                            j['error'] = msg[-500:]
                            j['progress'] = f'失败: {e}'[:200]
                    finally:
                        # 恢复 cwd / cancel / progress env（不再改写 sys.argv）
                        if _get_active_render() == rid:
                            _set_active_render(None)
                        try:
                            _va.CancelToken.reset()
                        except Exception:
                            pass
                        if 'NARRAVID_PROGRESS_FILE' in os.environ:
                            del os.environ['NARRAVID_PROGRESS_FILE']
                        # surface BGM soft-failure warnings if any
                        try:
                            wf = Path(j.get('out') or out) / '_warnings.txt'
                            if wf.is_file() and not j.get('error'):
                                j['warning'] = wf.read_text(encoding='utf-8').strip()[:300]
                        except Exception:
                            pass
                        j['done'] = True

            def monitor_job():
                """监控线程：检查进度 + 超时检测"""
                j = JOBS.get(rid)
                if not j:
                    return
                last_progress = ''
                stall_count = 0
                while not j.get('done'):
                    time.sleep(2)
                    if j.get('done'):
                        break
                    # 仍在排队（未持有 RENDER_LOCK）时不计超时，避免“排队 3 分钟被误判卡死”
                    if _is_waiting_for_lock(rid, j):
                        stall_count = 0
                        last_progress = ''
                        continue
                    current_progress = ''
                    pf = j.get('progress_file')
                    if pf and Path(pf).exists():
                        try:
                            current_progress = Path(pf).read_text(encoding='utf-8').strip()
                        except Exception:
                            pass
                    if current_progress == last_progress:
                        stall_count += 1
                    else:
                        stall_count = 0
                        last_progress = current_progress
                    # 连续 STALL_TICKS 次（默认约 300 秒）无进度更新则判定卡死
                    if stall_count >= STALL_TICKS:
                        j['error'] = f'渲染超时：{STALL_SECONDS} 秒无进度更新'
                        j['progress'] = '超时（渲染卡死）'
                        j['done'] = True
                        # 仅打断当前真正在跑的任务；排队中的 job 超时不应误杀持锁渲染
                        _signal_cancel_token_if_active(rid)
                        if j.get('cancel_event'):
                            j['cancel_event'].set()
                        return
                    if j.get('cancel_event') and j['cancel_event'].is_set():
                        _mark_job_cancelled(j)
                        return

            # 启动渲染线程和监控线程
            threading.Thread(target=run_in_thread, daemon=True).start()
            threading.Thread(target=monitor_job, daemon=True).start()
            # 延迟清理 JOBS（5 分钟后），避免内存泄漏
            def cleanup_job():
                time.sleep(300)
                j = JOBS.get(rid)
                # done 可能被 cancel/stall 提前置位，但线程仍可能在跑；active 时不清理
                if j and (not j.get('done') or _get_active_render() == rid):
                    threading.Thread(target=cleanup_job, daemon=True).start()
                    return
                JOBS.pop(rid, None)
            threading.Thread(target=cleanup_job, daemon=True).start()
            self._json({'render_id': rid})

        elif p.path.startswith('/api/cancel'):
            rid = p.path.split('/')[-1]
            j = JOBS.get(rid)
            if j:
                # 已成功/失败终态：忽略迟到 cancel，避免抹掉 video 或诊断文案
                if j.get('done') and not j.get('cancelled'):
                    self._json({'status': 'ok', 'ignored': True}); return
                # 先设置取消信号，再标记 done，避免 monitor_job() 提前退出错过取消
                if j.get('cancel_event'):
                    j['cancel_event'].set()
                # 只取消“当前正在执行”的 job 的全局 token；排队中的 job 仅靠 done 跳过
                _signal_cancel_token_if_active(rid)
                _mark_job_cancelled(j)
            self._json({'status': 'ok'})

        elif p.path == '/api/clean':
            cleaned = 0
            # 进行中 / 排队中的任务目录不可删
            protected = set()
            for j in list(JOBS.values()):
                outp = j.get('out') if isinstance(j, dict) else None
                if outp:
                    try:
                        protected.add(str(Path(outp).resolve()))
                    except Exception:
                        pass
            # 按修改时间排序，保留最近 5 次
            dirs = sorted(
                [d for d in OUT_BASE.iterdir() if d.is_dir() and d.name not in ('uploads', 'templates')],
                key=lambda d: d.stat().st_mtime, reverse=True
            )
            keep = set()
            for d in dirs[:5]:
                try:
                    keep.add(str(d.resolve()))
                except Exception:
                    pass
            for d in dirs:
                try:
                    key = str(d.resolve())
                except Exception:
                    continue
                if key in keep or key in protected:
                    continue
                shutil.rmtree(d, ignore_errors=True)
                cleaned += 1
            self._json({'message': f'已清理 {cleaned} 个旧渲染，保留最近 5 个及进行中任务', 'cleaned': cleaned})

        elif p.path == '/api/templates':
            # POST = save template
            data = json.loads(body)
            tid = uuid.uuid4().hex[:8]
            tp = TEMPLATE_DIR / f'{tid}.json'
            data['id'] = tid
            data['date'] = time.strftime('%Y-%m-%d %H:%M')
            data['count'] = len(data.get('scenes', []))
            tp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            self._json({'id': tid})

        elif p.path == '/api/export':
            # 导出工程：manifest + 所有引用的图片/视频 + BGM 打包成 zip
            import tempfile
            import zipfile
            data = json.loads(body)
            m = data.get('manifest', {})
            bgm = data.get('bgm')
            # 创建临时 zip
            zip_buf = io.BytesIO()
            zf = zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED)
            # 收集需要打包的文件及其新路径
            collected = {}  # abs_path -> zip_relative_path
            manifest_copy = json.loads(json.dumps(m))  # deep copy
            # 确保标题页/封尾页写入 manifest（兼容 body 顶层字段）
            if data.get('title_card') and not manifest_copy.get('title_card'):
                manifest_copy['title_card'] = data.get('title_card')
            if data.get('end_card') and not manifest_copy.get('end_card'):
                manifest_copy['end_card'] = data.get('end_card')
            if data.get('card_duration') is not None and 'card_duration' not in manifest_copy:
                manifest_copy['card_duration'] = data.get('card_duration')
            if data.get('end_card_duration') is not None and 'end_card_duration' not in manifest_copy:
                manifest_copy['end_card_duration'] = data.get('end_card_duration')
            def _exportable(path: Path) -> bool:
                return _is_exportable_media(path)

            for i, scene in enumerate(manifest_copy.get('scenes', [])):
                if not isinstance(scene, dict):
                    self._json({'error': f'scenes[{i}] 必须是对象'}, 400); return
                img = scene.get('image', '')
                if not img:
                    self._json({'error': f'scenes[{i}] 缺少 image，无法导出'}, 400); return
                img_path = Path(img)
                if not img_path.is_absolute():
                    img_path = UPLOAD_DIR / img_path
                try:
                    img_path = img_path.resolve()
                except Exception:
                    self._json({'error': f'无法解析媒体路径: {img}'}, 400); return
                if not _exportable(img_path):
                    # 禁止把本机绝对路径写进 zip manifest（路径泄漏 + 坏导入）
                    self._json({
                        'error': f'无法导出：场景 {i} 媒体不在允许目录（uploads/examples-assets/输出）: {Path(img).name}'
                    }, 400); return
                if str(img_path) not in collected:
                    ext = img_path.suffix.lower()
                    zname = f'assets/scene_{i:03d}{ext}'
                    collected[str(img_path)] = zname
                scene['image'] = collected[str(img_path)]
            # BGM
            if bgm:
                bgm_path = Path(bgm)
                if not bgm_path.is_absolute():
                    bgm_path = UPLOAD_DIR / bgm_path
                try:
                    bgm_path = bgm_path.resolve()
                except Exception:
                    self._json({'error': f'无法解析 BGM 路径: {bgm}'}, 400); return
                if not _exportable(bgm_path):
                    self._json({
                        'error': f'无法导出：BGM 不在允许目录: {Path(bgm).name}'
                    }, 400); return
                zname = f'assets/bgm{bgm_path.suffix}'
                collected[str(bgm_path)] = zname
                manifest_copy['bgm'] = zname
            # 写入 manifest（仅含 zip 内相对路径，无宿主绝对路径）
            zf.writestr('manifest.json', json.dumps(manifest_copy, ensure_ascii=False, indent=2))
            # 写入所有媒体文件
            for abs_path, zname in collected.items():
                zf.write(abs_path, zname)
            zf.close()
            zip_data = zip_buf.getvalue()
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename="narravid_project.zip"')
            self.send_header('Content-Length', str(len(zip_data)))
            self.end_headers()
            self.wfile.write(zip_data)

        elif p.path == '/api/import':
            # 导入工程：上传 zip，解压到 uploads 新目录，返回修正路径后的 manifest
            import tempfile
            import zipfile
            data = json.loads(body)
            b64 = data.get('data', '')
            try:
                zip_bytes = base64.b64decode(b64)
            except Exception:
                self._json({'error': 'base64 解码失败'}, 400); return
            project_id = uuid.uuid4().hex[:8]
            project_dir = UPLOAD_DIR / f'project_{project_id}'
            project_dir.mkdir(parents=True, exist_ok=True)
            zip_buf = io.BytesIO(zip_bytes)
            try:
                zf_ctx = zipfile.ZipFile(zip_buf, 'r')
            except zipfile.BadZipFile:
                shutil.rmtree(project_dir, ignore_errors=True)
                self._json({'error': '不是有效的 zip 工程文件'}, 400); return
            with zf_ctx as zf:
                # 安全检查：防止路径穿越和 zip bomb
                total_size = 0
                max_extract = 500 * 1024 * 1024  # 500MB 上限
                max_members = 2000
                safe_members = []
                names = zf.namelist()
                if len(names) > max_members:
                    shutil.rmtree(project_dir, ignore_errors=True)
                    self._json({'error': f'zip 条目过多（上限 {max_members}）'}, 400); return
                for member in names:
                    # 检查路径穿越
                    member_path = (project_dir / member).resolve()
                    try:
                        member_path.relative_to(project_dir.resolve())
                    except ValueError:
                        shutil.rmtree(project_dir, ignore_errors=True)
                        self._json({'error': f'zip 包含非法路径: {member}'}, 400); return
                    # 检查解压后总大小（header 声明 + 实际写出字节双保险）
                    total_size += zf.getinfo(member).file_size
                    if total_size > max_extract:
                        shutil.rmtree(project_dir, ignore_errors=True)
                        self._json({'error': 'zip 解压后超过 500MB 限制'}, 400); return
                    safe_members.append(member)
                # 流式解压并累计实际写入字节，防止 header 低报
                written = 0
                for member in safe_members:
                    info = zf.getinfo(member)
                    # 目录项
                    if member.endswith('/') or info.is_dir():
                        (project_dir / member).mkdir(parents=True, exist_ok=True)
                        continue
                    target = (project_dir / member).resolve()
                    if not _is_under(target, project_dir):
                        shutil.rmtree(project_dir, ignore_errors=True)
                        self._json({'error': f'zip 包含非法路径: {member}'}, 400); return
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, 'r') as src, open(target, 'wb') as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > max_extract:
                                try:
                                    dst.close()
                                    target.unlink(missing_ok=True)
                                except Exception:
                                    pass
                                shutil.rmtree(project_dir, ignore_errors=True)
                                self._json({'error': 'zip 解压后超过 500MB 限制'}, 400); return
                            dst.write(chunk)
            # 读取 manifest 并修正路径
            mp = project_dir / 'manifest.json'
            if not mp.exists():
                self._json({'error': 'zip 中未找到 manifest.json'}, 400); return
            manifest = json.loads(mp.read_text(encoding='utf-8'))
            # 校验 manifest 基本结构
            if not isinstance(manifest, dict):
                self._json({'error': 'manifest.json 不是有效 JSON 对象'}, 400); return
            scenes = manifest.get('scenes')
            if not isinstance(scenes, list):
                self._json({'error': 'manifest.scenes 不是数组'}, 400); return
            proj_root = project_dir.resolve()
            for scene in scenes:
                if not isinstance(scene, dict):
                    self._json({'error': 'manifest.scenes 项必须是对象'}, 400); return
                img = scene.get('image', '')
                if not img:
                    continue
                img_path = Path(img)
                if not img_path.is_absolute():
                    img_path = (project_dir / img_path).resolve()
                else:
                    img_path = img_path.resolve()
                if not _is_under(img_path, proj_root):
                    self._json({'error': f'非法媒体路径: {img}'}, 400); return
                scene['image'] = str(img_path)
            bgm_val = manifest.pop('bgm', None)
            if bgm_val:
                bgm_path = Path(bgm_val)
                if not bgm_path.is_absolute():
                    bgm_path = (project_dir / bgm_path).resolve()
                else:
                    bgm_path = bgm_path.resolve()
                if not _is_under(bgm_path, proj_root):
                    self._json({'error': f'非法 BGM 路径: {bgm_val}'}, 400); return
                bgm_val = str(bgm_path)
            self._json({'manifest': manifest, 'bgm': bgm_val})

        else:
            self._json({'error': 'not found'}, 404)

    def _template_path(self, tid):
        """Resolve template id to a path strictly under TEMPLATE_DIR."""
        tid = (tid or '').strip()
        if not tid or '/' in tid or '\\' in tid or tid in ('.', '..') or '..' in tid:
            return None
        # 仅允许简单文件名，避免模板 ID 路径穿越
        if not re.fullmatch(r'[\w.-]{1,64}', tid):
            return None
        tp = (TEMPLATE_DIR / f'{tid}.json').resolve()
        if not _is_under(tp, TEMPLATE_DIR):
            return None
        return tp

    def _handle_templates_get(self, p):
        if p.path == '/api/templates':
            # 列表
            tpls = []
            for f in sorted(TEMPLATE_DIR.glob('*.json')):
                try:
                    d = json.loads(f.read_text(encoding='utf-8'))
                    tpls.append({'id': d.get('id', f.stem), 'name': d.get('name', f.stem),
                                 'count': d.get('count', 0), 'date': d.get('date', '')})
                except Exception:
                    pass
            self._json(tpls)
        else:
            # 单个模板 GET /api/templates/<id>
            tid = p.path.split('/')[-1]
            tp = self._template_path(tid)
            if tp and tp.exists():
                self._json(json.loads(tp.read_text(encoding='utf-8')))
            else:
                self._json({'error': 'not found'}, 404)

    def do_PUT(self):
        p = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        if length > MAX_TEMPLATE_BODY:
            self._json({'error': f'请求过大（上限 {MAX_TEMPLATE_BODY // 1024}KB）'}, 413)
            return
        body = self.rfile.read(length) if length else b''
        if p.path.startswith('/api/templates/'):
            tid = p.path.split('/')[-1]
            tp = self._template_path(tid)
            if not tp or not tp.exists():
                self._json({'error': 'not found'}, 404); return
            data = json.loads(body) if body else {}
            tpl = json.loads(tp.read_text(encoding='utf-8'))
            if 'name' in data:
                tpl['name'] = data['name']
            if 'subtitle_style' in data:
                tpl['subtitle_style'] = data['subtitle_style']
            tp.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding='utf-8')
            self._json({'status': 'ok'})
        else:
            self._json({'error': 'not found'}, 404)

    def do_DELETE(self):
        p = urllib.parse.urlparse(self.path)
        if p.path.startswith('/api/templates/'):
            tid = p.path.split('/')[-1]
            tp = self._template_path(tid)
            if tp and tp.exists():
                tp.unlink()
                self._json({'status': 'ok'})
            else:
                self._json({'error': 'not found'}, 404)
        else:
            self._json({'error': 'not found'}, 404)

    def _html(self, html):
        self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _json(self, data, code=200):
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _file(self, fp, ct, as_attachment=False):
        self.send_response(200); self.send_header('Content-Type', ct)
        # 缩略图/预览用 inline，下载类资源才 attachment
        if as_attachment:
            self.send_header('Content-Disposition', f'attachment; filename="{fp.name}"')
        else:
            self.send_header('Content-Disposition', f'inline; filename="{fp.name}"')
        self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers(); self.wfile.write(fp.read_bytes())

    def log_message(self, fmt, *args): pass


# Backward-compatible alias (tests use webui.H)
H = WebUIHandler


def main():
    ap = argparse.ArgumentParser(description='narravid Web UI')
    ap.add_argument('--port', type=int, default=int(os.environ.get('NARRAVID_PORT', '5000') or 5000))
    # Docker 可设 NARRAVID_HOST=0.0.0.0；本机默认仅回环
    default_host = os.environ.get('NARRAVID_HOST') or (
        '0.0.0.0' if os.environ.get('NARRAVID_DOCKER') else '127.0.0.1'
    )
    ap.add_argument('--host', default=default_host)
    args = ap.parse_args()
    for d in [OUT_BASE, UPLOAD_DIR, TEMPLATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    # ThreadingHTTPServer：上传/状态轮询/导出互不阻塞；渲染仍由 RENDER_LOCK 串行
    srv = ThreadingHTTPServer((args.host, args.port), WebUIHandler)
    display_host = '127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host
    url = f'http://{display_host}:{args.port}'
    print(f'narravid Web UI: {url}')
    if args.host in ('0.0.0.0', '::'):
        print(f'  监听 {args.host}:{args.port}（局域网/容器可访问；内网请加反代鉴权）')
    print('  在浏览器打开上述地址即可')
    # 环境探测放到后台，避免阻塞首包/accept
    def _env_probe():
        try:
            import video_auto as _va
            eng = _va.resolve_tts_engine(None)
            print(f'  TTS: {eng}' + ('' if eng != 'edge' else ' (edge-tts)'))
            if not _va._find_zh_font():
                print('  [warn] 未找到中文字体：标题页/字幕可能方块。设置 NARRAVID_FONT 或安装 Noto CJK / 放入 fonts/')
        except Exception as e:
            print(f'  [warn] 环境检测: {e}')
    threading.Thread(target=_env_probe, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('stopped'); srv.shutdown()


if __name__ == '__main__':
    main()
