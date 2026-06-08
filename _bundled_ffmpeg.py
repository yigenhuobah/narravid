"""narravid 共享：exe 打包时自动找到自带 ffmpeg"""
import os, sys
from pathlib import Path

def setup_ffmpeg():
    base = getattr(sys, '_MEIPASS', None)
    if base:
        bundled = Path(base) / 'ffmpeg'
        if bundled.is_dir():
            os.environ['PATH'] = str(bundled) + os.pathsep + os.environ.get('PATH', '')

# auto-execute on import
setup_ffmpeg()
