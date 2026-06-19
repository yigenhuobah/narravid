"""narravid 共享：exe 打包时自动找到自带 ffmpeg/ffprobe 绝对路径。

提供 get_ffmpeg() / get_ffprobe() 返回可执行文件绝对路径，
所有模块统一用这两个函数，不再硬编码 'ffmpeg' / 'ffprobe'。
"""
import os
import shutil
import sys
from pathlib import Path

_ffmpeg_path = None
_ffprobe_path = None


def _resolve():
    """查找 ffmpeg/ffprobe 的绝对路径，结果缓存到模块级变量。"""
    global _ffmpeg_path, _ffprobe_path
    if _ffmpeg_path and _ffprobe_path:
        return

    # 1) PyInstaller --onefile 解压目录 (_MEIPASS)
    base = getattr(sys, '_MEIPASS', None)
    if base:
        bundled_dir = Path(base) / 'ffmpeg'
        if bundled_dir.is_dir():
            ff = bundled_dir / 'ffmpeg.exe'
            fp = bundled_dir / 'ffprobe.exe'
            if ff.exists():
                _ffmpeg_path = str(ff)
            if fp.exists():
                _ffprobe_path = str(fp)

    # 2) PyInstaller --onedir 模式 (exe 同级 ffmpeg/ 目录)
    if not _ffmpeg_path or not _ffprobe_path:
        exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
        bundled_dir = exe_dir / 'ffmpeg'
        if bundled_dir.is_dir():
            if not _ffmpeg_path:
                ff = bundled_dir / 'ffmpeg.exe'
                if ff.exists():
                    _ffmpeg_path = str(ff)
            if not _ffprobe_path:
                fp = bundled_dir / 'ffprobe.exe'
                if fp.exists():
                    _ffprobe_path = str(fp)

    # 3) PATH 中查找
    if not _ffmpeg_path:
        found = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
        if found:
            _ffmpeg_path = found
    if not _ffprobe_path:
        found = shutil.which('ffprobe') or shutil.which('ffprobe.exe')
        if found:
            _ffprobe_path = found

    # 4) 最终回退：直接用命令名，让系统自己找
    if not _ffmpeg_path:
        _ffmpeg_path = 'ffmpeg'
    if not _ffprobe_path:
        _ffprobe_path = 'ffprobe'

    # 同时加入 PATH 以兼容其他可能直接调用 'ffmpeg' 的场景
    bundled_parent = Path(_ffmpeg_path).parent
    if str(bundled_parent) not in os.environ.get('PATH', ''):
        os.environ['PATH'] = str(bundled_parent) + os.pathsep + os.environ.get('PATH', '')


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


# import 时自动解析
_resolve()
