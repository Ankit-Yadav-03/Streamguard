# Logging setup

import logging
import json
import time
import os

_INITIALIZED = False

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": time.time(),
            "level": record.levelname,
            "event": record.msg,
        }

        for k, v in record.__dict__.items():
            if k.startswith("_"):
                continue
            if k in (
                "msg", "args", "levelname", "levelno",
                "pathname", "filename", "module",
                "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created",
                "msecs", "relativeCreated",
                "thread", "threadName",
                "processName", "process", "taskName",
            ):
                continue
            payload[k] = v

        return json.dumps(payload)



def init_logging():
    global _INITIALIZED
    if _INITIALIZED:
        return

    root = logging.getLogger("streamguard")
    root.setLevel(logging.INFO)

    log_target = os.getenv("STREAMGUARD_LOG_TARGET", "stdout")
    if log_target == "file":
        handler = logging.FileHandler(
            os.getenv("STREAMGUARD_LOG_FILE", "streamguard.log")
        )
    else:
        handler = logging.StreamHandler()

    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.propagate = False

    _INITIALIZED = True


def get_logger(name: str = "streamguard"):
    init_logging()
    return logging.getLogger(name)
