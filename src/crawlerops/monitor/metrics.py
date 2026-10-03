from prometheus_client import Gauge

SOURCE_SUCCESS_RATE = Gauge(
    "monitor_source_success_rate", "Taxa de sucesso na janela de avaliação", ["source"]
)
DATA_FRESHNESS = Gauge(
    "monitor_data_freshness_seconds", "Segundos desde a última captura com sucesso", ["source"]
)
QUEUE_DEPTH = Gauge("monitor_queue_depth", "Mensagens visíveis nas filas", ["queue"])
OPEN_INCIDENTS = Gauge("monitor_open_incidents", "Incidentes ativos por severidade", ["severity"])
SLA_BREACHED = Gauge("monitor_sla_breached_incidents", "Incidentes ativos com SLA de resolução estourado")
LAST_EVALUATION = Gauge("monitor_last_evaluation_timestamp_seconds", "Epoch da última avaliação")
