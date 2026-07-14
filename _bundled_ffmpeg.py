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
            return str(p)
    return None


def _which_tool(tool: str):
    for name in _binary_names(tool):
        found = shutil.which(name)
        if found:
            return found
    return None


def _resolve():
    """查找 ffmpeg/ffprobe 的绝对路径，结果缓存到模块级变量。"""
    global _ffmpeg_path, _ffprobe_path
    if _ffmpeg_path and _ffprobe_path:
        return

    # 0) 环境变量覆盖（Docker / 自定义安装）
    env_ff = os.environ.get('NARRAVID_FFMPEG') or os.environ.get('FFMPEG')
    env_fp = os.environ.get('NARRAVID_FFPROBE') or os.environ.get('FFPROBE')
    if env_ff and Path(env_ff).exists():
        _ffmpeg_path = env_ff
    if env_fp and Path(env_fp).exists():
        _ffprobe_path = env_fp

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
        bundled_parent = Path(_ffmpeg_path).parent
        if bundled_parent.is_dir() and str(bundled_parent) not in os.environ.get('PATH', ''):
            os.environ['PATH'] = str(bundled_parent) + os.pathsep + os.environ.get('PATH', '')
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
