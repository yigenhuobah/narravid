"""Render job registry, path sandbox, and cancel helpers for WebUI."""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path


def _package_root() -> Path:
    """Read-only package/extract root (source tree or PyInstaller _MEIPASS)."""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _app_data_root() -> Path:
    """Durable data root for uploads/jobs/templates.

    Frozen onefile must NOT write under _MEIPASS (wiped on exit). Prefer
    NARRAVID_DATA_DIR, else directory of the executable, else source tree.
    """
    env = (os.environ.get('NARRAVID_DATA_DIR') or '').strip()
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PACKAGE_ROOT = _package_root()
ROOT = _app_data_root()
OUT_BASE = ROOT / 'rendered' / 'webui'
UPLOAD_DIR = OUT_BASE / 'uploads'
TEMPLATE_DIR = OUT_BASE / 'templates'

for d in [OUT_BASE, UPLOAD_DIR, TEMPLATE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _examples_asset_dirs() -> list[Path]:
    """examples-assets may live next to data root and/or inside the package."""
    dirs: list[Path] = []
    for base in (ROOT, PACKAGE_ROOT):
        p = (base / 'examples-assets').resolve()
        if p not in dirs:
            dirs.append(p)
    return dirs


THUMB_ALLOWED_DIRS = [UPLOAD_DIR.resolve(), *_examples_asset_dirs()]

MAX_IMAGE_SIZE = 20 * 1024 * 1024
MAX_VIDEO_SIZE = 60 * 1024 * 1024
MAX_BGM_SIZE = 50 * 1024 * 1024
MAX_UPLOAD_SIZE = 60 * 1024 * 1024
MAX_TEMPLATE_BODY = 1 * 1024 * 1024  # PUT/POST template JSON
MAX_PENDING_JOBS = 8
JOB_RETENTION_SECONDS = 300
# Progress stall: monitor sleeps 2s; 150 ticks ≈ 300s without progress change
STALL_TICKS = 150
STALL_SECONDS = STALL_TICKS * 2
IMAGE_FILE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
VIDEO_FILE_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.flv'}
AUDIO_FILE_EXTS = {'.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg'}
SCENE_FILE_EXTS = IMAGE_FILE_EXTS | VIDEO_FILE_EXTS
MEDIA_FILE_EXTS = SCENE_FILE_EXTS | AUDIO_FILE_EXTS
INTERNAL_NAME_BLOCKLIST = {'_stderr.log', '_progress.txt', '_warnings.txt', '_title_card.txt', '_end_card.txt'}

JOBS = {}
_RENDER_ID_LOCK = threading.Lock()
_RESERVED_RENDER_IDS: set[str] = set()
RENDER_LOCK = threading.Lock()  # 全局渲染锁：同时只允许一个渲染任务执行
ACTIVE_RENDER_ID = None  # 当前持有 RENDER_LOCK 并执行 main() 的 job id
_ACTIVE_RENDER_LOCK = threading.Lock()
# 渲染媒体允许目录：uploads / examples-assets / 输出树
MEDIA_ALLOWED_DIRS = [
    UPLOAD_DIR.resolve(),
    *_examples_asset_dirs(),
    OUT_BASE.resolve(),
]


class RenderQueueFullError(RuntimeError):
    pass


def _reserve_render_id(rid: str) -> bool:
    """Atomically reserve a render id until its JOBS entry is installed."""
    with _RENDER_ID_LOCK:
        if rid in JOBS or rid in _RESERVED_RENDER_IDS:
            return False
        pending = sum(
            job.get('_runner_active', not job.get('done')) for job in JOBS.values()
        )
        if pending + len(_RESERVED_RENDER_IDS) >= MAX_PENDING_JOBS:
            raise RenderQueueFullError('render queue is full')
        _RESERVED_RENDER_IDS.add(rid)
        return True


def _install_reserved_job(rid: str, job: dict):
    """Atomically publish a reserved job and consume its reservation."""
    with _RENDER_ID_LOCK:
        if rid not in _RESERVED_RENDER_IDS or rid in JOBS:
            raise RuntimeError(f'render id is not exclusively reserved: {rid}')
        JOBS[rid] = job
        _RESERVED_RENDER_IDS.remove(rid)


def _release_render_id(rid: str | None):
    if not rid:
        return
    with _RENDER_ID_LOCK:
        _RESERVED_RENDER_IDS.discard(rid)


def _protected_render_ids() -> set[str]:
    with _RENDER_ID_LOCK:
        return set(JOBS) | _RESERVED_RENDER_IDS


def _set_active_render(rid):
    global ACTIVE_RENDER_ID
    with _ACTIVE_RENDER_LOCK:
        ACTIVE_RENDER_ID = rid


def _get_active_render():
    with _ACTIVE_RENDER_LOCK:
        return ACTIVE_RENDER_ID


def _prune_finished_jobs(now: float | None = None):
    """Drop terminal jobs after the status-retention window without timer threads."""
    current = time.monotonic() if now is None else now
    active = _get_active_render()
    with _RENDER_ID_LOCK:
        for rid, job in list(JOBS.items()):
            if (
                not job.get('done')
                or rid == active
                or job.get('_runner_active')
                or job.get('_monitor_active')
            ):
                continue
            done_at = job.setdefault('_done_at', current)
            if current - done_at >= JOB_RETENTION_SECONDS:
                JOBS.pop(rid, None)


def _is_under(path: Path, root: Path) -> bool:
    """True if resolved path is inside root (or is root)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_under_any(path: Path, roots) -> bool:
    for root in roots:
        if _is_under(path, root):
            return True
    return False


def _sanitize_upload_name(name: str) -> str:
    """Basename only; strip path separators / traversal; ASCII-only safe chars."""
    base = Path(str(name or '')).name or 'file.bin'
    stem = Path(base).stem
    suffix = Path(base).suffix.lower()
    # 扩展名仅保留 . + ASCII 字母数字
    if suffix:
        suffix = '.' + re.sub(r'[^A-Za-z0-9]+', '', suffix.lstrip('.'))[:12]
        if suffix == '.':
            suffix = ''
    # 仅保留 ASCII 字母数字与 _-，中文/空格/符号一律替换
    safe_stem = re.sub(r'[^A-Za-z0-9_-]+', '_', stem).strip('._-') or 'file'
    safe = safe_stem + (suffix or '')
    return safe or 'file.bin'


def _sanitize_render_id(rid) -> str | None:
    """Client render_id must be a simple token; reject path traversal/absolute."""
    rid = (str(rid) if rid is not None else '').strip()
    if not rid:
        return None
    if not re.fullmatch(r'[\w.-]{1,64}', rid):
        return None
    if rid in ('.', '..') or '..' in rid:
        return None
    return rid


def _job_out_dir(rid: str) -> Path | None:
    """Resolve job output dir strictly under OUT_BASE."""
    safe = _sanitize_render_id(rid)
    if not safe:
        return None
    out = (OUT_BASE / safe).resolve()
    if not _is_under(out, OUT_BASE):
        return None
    return out


def _is_exportable_media(path: Path) -> bool:
    """True if path is a user media file (not job internals) under allowlisted roots."""
    try:
        rp = path.resolve()
    except Exception:
        return False
    if not (rp.exists() and rp.is_file() and _is_under_any(rp, MEDIA_ALLOWED_DIRS)):
        return False
    if rp.name in INTERNAL_NAME_BLOCKLIST:
        return False
    # job outputs may include only final media under OUT_BASE; block logs/json
    if rp.suffix.lower() not in MEDIA_FILE_EXTS:
        return False
    # under OUT_BASE but inside uploads/templates is ok; inside job dirs only media exts
    return True


def _resolve_media_path(raw, base_dir: Path = None) -> Path | None:
    """Resolve scene/BGM path; must exist as media file under MEDIA_ALLOWED_DIRS."""
    if not raw:
        return None
    p = Path(str(raw))
    if not p.is_absolute():
        base = base_dir or UPLOAD_DIR
        p = (base / p).resolve()
    else:
        p = p.resolve()
    if not _is_exportable_media(p):
        return None
    return p


def _is_waiting_for_lock(rid, job: dict) -> bool:
    """Job has not yet become the active renderer (still queued)."""
    active = _get_active_render()
    if active == rid:
        return False
    if active is not None:
        return True
    return not job.get('_started')


def _looks_like_cancel(msg) -> bool:
    """User-cancel only — not internal '渲染已中止'."""
    if not isinstance(msg, str):
        return False
    return '用户取消' in msg or msg.strip() in ('已取消', '渲染已被用户取消')


def _mark_job_cancelled(job: dict, error: str = '已取消') -> bool:
    """Mark a job as cancelled/done.

    Returns False if the job is already in a non-cancel terminal state
    (success with video, or failure/timeout diagnostics). Late cancel must
    not wipe a finished video URL or rewrite timeout/fail errors.
    """
    if job.get('done') and not job.get('cancelled'):
        return False
    if job.get('cancelled') and job.get('done'):
        return True
    job['cancelled'] = True
    job['progress'] = '已取消'
    job['error'] = job.get('error') or error
    job['done'] = True
    return True


def _signal_cancel_token_if_active(rid):
    """仅当 rid 是当前正在执行的渲染时，才设置全局 CancelToken。"""
    if rid and rid == _get_active_render():
        try:
            import video_auto as _va
            _va.CancelToken.set_cancelled()
        except Exception:
            pass


def _check_edge_tts():
    """检测可用 TTS，返回 (engine, label)。

    委托 video_auto 的探测逻辑；Linux/macOS 不会谎称系统 TTS 可用。
    """
    try:
        import video_auto as _va
        if _va.edge_tts_available():
            return 'edge', 'Edge TTS'
        if _va.system_tts_available():
            return 'system', '系统 TTS'
    except Exception:
        pass
    return 'none', '无可用 TTS（请安装 edge-tts）'


def _public_media_url(path: Path) -> str:
    """URL path under durable ROOT for a file we will serve via /rendered/..."""
    rel = path.resolve().relative_to(ROOT.resolve())
    return '/' + str(rel).replace('\\', '/')


def _pick_final_mp4(out_dir) -> Path | None:
    """Prefer WebUI's manifest.mp4; else newest non-underscore mp4 in job dir."""
    od = Path(out_dir)
    preferred = od / 'manifest.mp4'
    if preferred.is_file():
        return preferred
    candidates = [
        p for p in od.glob('*.mp4')
        if p.is_file() and not p.name.startswith('_')
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return candidates[0]


def _systemexit_message(exc: BaseException) -> str:
    """Human-readable failure from SystemExit raised by video_auto.main."""
    code = getattr(exc, 'code', None)
    if code is None or code == 0:
        return '渲染异常退出'
    if isinstance(code, int):
        return f'渲染失败 (exit {code})'
    text = str(code).strip()
    return text or '渲染失败'


