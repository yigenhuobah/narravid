"""Console stream compatibility for localized CLI output."""

import sys


def configure_console_io():
    """Keep localized output from crashing on restrictive Windows code pages."""
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors='replace')
        except (OSError, ValueError):
            pass
