"""Общие утилиты логирования для pipeline и chain."""


def log(msg, tag='info'):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
        print(safe_msg, flush=True)
