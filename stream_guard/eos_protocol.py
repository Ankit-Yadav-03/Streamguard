"""
End-Of-Stream (EOS) protocol marker.

Rules:
- EOS is NOT a token
- EOS is delivered on the same channel as tokens
- EOS is emitted exactly once
- EOS is never ACKed
- EOS observation by the consumer defines stream completion
- EOS must be compared by identity (is), never equality
"""


class _EOS:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<EOS>"

    def __bool__(self) -> bool:
        # Prevent accidental truthiness checks
        raise TypeError("EOS cannot be used as a boolean")

    def __eq__(self, other) -> bool:
        # Force identity comparison only
        return self is other


# The one and only EOS instance
EOS = _EOS()
