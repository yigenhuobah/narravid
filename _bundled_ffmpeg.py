"""narravid 共享：exe 打包时自动找到自带 ffmpeg/ffprobe 绝对路径。

提供 get_ffmpeg() / get_ffprobe() 返回可执行文件绝对路径，
所有模块统一用这两个函数，不再硬编码 'ffmpeg' / 'ffprobe'。

跨平台：Windows 优先 *.exe；POSIX 优先无后缀名；均回退 PATH。
"""
import os
import shutil
import sys
from pathlib import Path

_ffmpeg_path = None
_ffprobe_path = None


def _binary_names(tool: str):
    """Candidate basenames for a tool on this platform."""
    if os.name == 'nt':
        return (f'{tool}.exe', tool)
    return (tool, f'{tool}.exe')


def _first_existing(directory: Path, tool: str):
    if not directory.is_dir():
        return None
    for name in _binary_names(tool):
        p = directory / name
        if p.is_file():
            return str(p.resolve())
    return None


def _which_tool(tool: str):
    for name in _binary_names(tool):
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())
    return None


def _resolve():
    """查找 ffmpeg/ffprobe 的绝对路径，结果缓存到模块级变量。"""
    global _ffmpeg_path, _ffprobe_path
    if _ffmpeg_path and _ffprobe_path:
        return

    # 0) 环境变量覆盖（Docker / 自定义安装）
    env_ff = os.environ.get('NARRAVID_FFMPEG') or os.environ.get('FFMPEG')
    env_fp = os.environ.get('NARRAVID_FFPROBE') or os.environ.get('FFPROBE')
    if env_ff:
        env_ff_path = Path(env_ff).expanduser()
        if env_ff_path.is_file():
            _ffmpeg_path = str(env_ff_path.resolve())
    if env_fp:
        env_fp_path = Path(env_fp).expanduser()
        if env_fp_path.is_file():
            _ffprobe_path = str(env_fp_path.resolve())

    # 1) PyInstaller --onefile 解压目录 (_MEIPASS)
    base = getattr(sys, '_MEIPASS', None)
    if base:
        bundled_dir = Path(base) / 'ffmpeg'
        if not _ffmpeg_path:
            _ffmpeg_path = _first_existing(bundled_dir, 'ffmpeg')
        if not _ffprobe_path:
            _ffprobe_path = _first_existing(bundled_dir, 'ffprobe')

    # 2) PyInstaller --onedir / 源码旁 ffmpeg/ 目录
    if not _ffmpeg_path or not _ffprobe_path:
        exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
        bundled_dir = exe_dir / 'ffmpeg'
        if not _ffmpeg_path:
            _ffmpeg_path = _first_existing(bundled_dir, 'ffmpeg')
        if not _ffprobe_path:
            _ffprobe_path = _first_existing(bundled_dir, 'ffprobe')

    # 3) PATH
    if not _ffmpeg_path:
        _ffmpeg_path = _which_tool('ffmpeg')
    if not _ffprobe_path:
        _ffprobe_path = _which_tool('ffprobe')

    # 4) 最终回退：直接用命令名
    if not _ffmpeg_path:
        _ffmpeg_path = 'ffmpeg'
    if not _ffprobe_path:
        _ffprobe_path = 'ffprobe'

    # 同时加入 PATH 以兼容其他可能直接调用 'ffmpeg' 的场景
    try:
        resolved_ffmpeg = Path(_ffmpeg_path)
        if resolved_ffmpeg.is_absolute() and resolved_ffmpeg.is_file():
            bundled_parent = str(resolved_ffmpeg.resolve().parent)
            current_path = os.environ.get('PATH', '')
            normalized_entries = {
                os.path.normcase(os.path.abspath(entry))
                for entry in current_path.split(os.pathsep)
                if entry
            }
            if os.path.normcase(bundled_parent) not in normalized_entries:
                separator = os.pathsep if current_path else ''
                os.environ['PATH'] = bundled_parent + separator + current_path
    except Exception:
        pass


def get_ffmpeg() -> str:
    """返回 ffmpeg 可执行文件的绝对路径"""
    if not _ffmpeg_path:
        _resolve()
    return _ffmpeg_path


def get_ffprobe() -> str:
    """返回 ffprobe 可执行文件的绝对路径"""
    if not _ffprobe_path:
        _resolve()
    return _ffprobe_path


def reset_cache_for_tests():
    """测试用：清空缓存以便重新解析。"""
    global _ffmpeg_path, _ffprobe_path
    _ffmpeg_path = None
    _ffprobe_path = None


# 懒解析：首次 get_ffmpeg()/get_ffprobe() 再扫盘（import 不阻塞）
