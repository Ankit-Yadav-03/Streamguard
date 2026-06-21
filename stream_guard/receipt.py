from dataclasses import dataclass
from enum import Enum

class CancelCategory(str, Enum):
    USER = "user"
    POLICY = "policy"
    SYSTEM = "system"

@dataclass(frozen=True)
class StreamReceipt:
    stream_id: str
    cancel_reason: str
    cancel_category: CancelCategory

    started_at: float
    cancel_requested_at: float
    accounting_cutoff_at: float
    finalized_at: float

    produced: int
    committed: int
    consumed: int

    estimated_prevented: int