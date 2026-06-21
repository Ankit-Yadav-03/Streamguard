import json
import os
import threading

_RECEIPT_LOCK = threading.Lock()

class ReceiptSink:
    def __init__(self, path: str):
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, receipt) -> None:
        """
        Fire-and-forget, crash-safe receipt persistence.
        MUST NEVER raise.
        """
        try:
            line = json.dumps(receipt.__dict__, separators=(",", ":"))
            with _RECEIPT_LOCK:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            # Intentionally swallow:
            # receipt persistence must not affect correctness
            pass