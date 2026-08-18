import os
from collections import namedtuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_ModxSettings = namedtuple(
    '_ModxSettings',
    [
        'modx_ssh_host',
        'modx_ssh_port',
        'modx_ssh_username',
        'modx_ssh_password',
        'modx_base_path',
    ],
)


def _require_env(name):
    value = os.environ.get(name)
    if value is None:
        raise EnvironmentError(f"Environment variable {name} is required but not set")
    return value


def get_settings():
    return _ModxSettings(
        modx_ssh_host=_require_env('MODX_SSH_HOST'),
        modx_ssh_port=int(_require_env('MODX_SSH_PORT')),
        modx_ssh_username=_require_env('MODX_SSH_USERNAME'),
        modx_ssh_password=_require_env('MODX_SSH_PASSWORD'),
        modx_base_path=_require_env('MODX_BASE_PATH'),
    )


def get_modx_db_config():
    return {
        'host': _require_env('MODX_DB_HOST'),
        'port': int(_require_env('MODX_DB_PORT')),
        'user': _require_env('MODX_DB_USER'),
        'password': _require_env('MODX_DB_PASSWORD'),
        'database': _require_env('MODX_DB_NAME'),
        'charset': os.environ.get('MODX_DB_CHARSET', 'utf8'),
    }
