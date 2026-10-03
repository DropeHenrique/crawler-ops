from prometheus_client import Counter, Gauge, Histogram

CAPTURES = Counter(
    "crawler_captures_total",
    "Tentativas de captura por fonte, status e tipo de erro",
    ["source", "status", "error_type"],
)
ITEMS = Counter("crawler_items_captured_total", "Produtos válidos capturados", ["source"])
INVALID_ITEMS = Counter("crawler_invalid_items_total", "Produtos descartados na validação", ["source"])
DEAD_LETTERED = Counter(
    "crawler_dead_lettered_total", "Jobs enviados para a DLQ", ["source", "error_type"]
)
DURATION = Histogram(
    "crawler_capture_duration_seconds",
    "Duração de cada captura",
    ["source"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13),
)
IN_FLIGHT = Gauge("crawler_jobs_in_flight", "Jobs em processamento neste worker")
LAST_SUCCESS = Gauge(
    "crawler_last_success_timestamp_seconds", "Epoch da última captura bem-sucedida", ["source"]
)
