"""Low-cardinality Prometheus metrics for RootAgent operations."""

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "rootagent_http_requests_total",
    "HTTP requests handled",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "rootagent_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "route"),
)
CHAT_RUNS = Counter(
    "rootagent_chat_runs_total", "Chat runs", ("status", "executor_backend")
)
CHAT_RUN_DURATION = Histogram(
    "rootagent_chat_run_duration_seconds",
    "Chat run duration",
    ("status", "executor_backend"),
)
UPLOAD_REJECTIONS = Counter(
    "rootagent_upload_rejections_total", "Rejected uploads", ("code",)
)
GENERATED_OUTPUT_BYTES = Histogram(
    "rootagent_generated_output_bytes", "Generated artifact sizes", ("kind",)
)
CLEANUP_RETRIES = Counter(
    "rootagent_cleanup_retries_total", "External cleanup retries", ("operation",)
)
WS_AUTH_FAILURES = Counter(
    "rootagent_websocket_auth_failures_total", "WebSocket authentication failures", ("reason",)
)
RATE_LIMIT_REJECTIONS = Counter(
    "rootagent_rate_limit_rejections_total", "Rate-limit rejections", ("namespace",)
)
READINESS_FAILURES = Counter(
    "rootagent_readiness_failures_total", "Readiness failures", ("dependency",)
)
