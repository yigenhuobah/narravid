"""Render job registry, path sandbox, and cancel helpers for WebUI."""
from __future__ import annotations

import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_BASE = ROOT / 'rendered' / 'webui'
UPLOAD_DIR = OUT_BASE / 'uploads'
TEMPLATE_DIR = OUT_BASE / 'templates'

for d in [OUT_BASE, UPLOAD_DIR, TEMPLATE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

THUMB_ALLOWED_DIRS = [UPLOAD_DIR.resolve(), (ROOT / 'examples-assets').resolve()]

MAX_IMAGE_SIZE = 20 * 1024 * 1024
MAX_VIDEO_SIZE = 60 * 1024 * 1024
MAX_BGM_SIZE = 50 * 1024 * 1024
MAX_UPLOAD_SIZE = 60 * 1024 * 1024

JOBS = {}
RENDER_LOCK = threading.Lock()  # 全局渲染锁：同时只允许一个渲染任务执行
ACTIVE_RENDER_ID = None  # 当前持有 RENDER_LOCK 并执行 main() 的 job id
_ACTIVE_RENDER_LOCK = threading.Lock()
# 渲染媒体允许目录：uploads / examples-assets / 输出树
MEDIA_ALLOWED_DIRS = [
    UPLOAD_DIR.resolve(),
    (ROOT / 'examples-assets').resolve(),
    OUT_BASE.resolve(),
]


def _set_active_render(rid):
    global ACTIVE_RENDER_ID
    with _ACTIVE_RENDER_LOCK:
        ACTIVE_RENDER_ID = rid


def _get_active_render():
    with _ACTIVE_RENDER_LOCK:
        return ACTIVE_RENDER_ID


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


def _resolve_media_path(raw, base_dir: Path = None) -> Path | None:
    """Resolve scene/BGM path; must exist as file under MEDIA_ALLOWED_DIRS."""
    if not raw:
        return None
    p = Path(str(raw))
    if not p.is_absolute():
        base = base_dir or UPLOAD_DIR
        p = (base / p).resolve()
    else:
        p = p.resolve()
    if not (p.exists() and p.is_file() and _is_under_any(p, MEDIA_ALLOWED_DIRS)):
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


