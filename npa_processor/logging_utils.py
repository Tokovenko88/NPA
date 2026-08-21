"""Общие утилиты логирования для pipeline и chain."""

import sys


def _ensure_utf8_stdio():
    if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass


_ensure_utf8_stdio()


def log(msg, tag='info'):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout.buffer.write((str(msg) + '\n').encode('utf-8'))
            sys.stdout.buffer.flush()
        else:
            print(str(msg).encode('ascii', errors='replace').decode('ascii'), flush=True)
