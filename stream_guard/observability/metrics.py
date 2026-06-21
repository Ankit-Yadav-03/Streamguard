from prometheus_client import Counter, Gauge


# ============================================================
# Lifecycle Metrics
# ============================================================

streams_started = Counter(
    "streams_started_total",
    "Total number of streams started",
)

streams_aborted = Counter(
    "streams_aborted_total",
    "Total number of streams aborted",
    ["category"],
)

active_streams = Gauge(
    "active_streams",
    "Currently active streams",
)


# ============================================================
# Accounting Metrics (DERIVED, NOT PRIMARY)
# ============================================================

tokens_committed = Counter(
    "tokens_committed_total",
    "Total tokens committed (protocol authoritative)",
)

tokens_consumed = Counter(
    "tokens_consumed_total",
    "Total tokens consumed (protocol authoritative)",
)

