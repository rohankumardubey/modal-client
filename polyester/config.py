import logging
import os

try:
    import icecream

    icecream.install()
except ImportError:
    pass


config = {
    "loglevel": os.environ.get("LOGLEVEL", "WARNING").upper(),
    "server.url": os.environ.get("POLYESTER_SERVER_URL", "https://api.modal.com"),
    "token.id": os.environ.get("POLYESTER_TOKEN_ID"),
    "token.secret": os.environ.get("POLYESTER_TOKEN_SECRET"),
    "task.id": os.environ.get("POLYESTER_TASK_ID"),  # Maybe redundant since it's also passed as a cmd arg
    "task.secret": os.environ.get("POLYESTER_TASK_SECRET"),
    "sync_entrypoint": os.environ.get("POLYESTER_SYNC_ENTRYPOINT"),
    "logs_timeout": float(os.environ.get("POLYESTER_LOGS_TIMEOUT", 10)),
    "image_python_version": os.environ.get("POLYESTER_IMAGE_PYTHON_VERSION"),
}

logging.basicConfig(
    level=config["loglevel"], format="%(threadName)s %(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
)
logger = logging.getLogger()
