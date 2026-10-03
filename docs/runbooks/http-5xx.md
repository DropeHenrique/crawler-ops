# Runbook: erros HTTP 5xx (`http_5xx`)

| Campo | Valor |
|---|---|
| Tipo de erro | **Transitório**: 2 retries imediatos no cliente (backoff exponencial + jitter) e depois retry via SQS |

## Diagnóstico

- **500**: erro interno do site. Geralmente passageiro; se persistir, a página pode ter sido removida ou mudado de rota.
- **502/503/504**: site em manutenção ou sobrecarregado. Verifique se ocorre em **todas** as categorias.
- Verifique se não fomos nós que causamos a sobrecarga (pico de jobs, muitos workers).

## Ações

1. Se for só uma fonte e o site estiver fora: **comunique o negócio** (dados daquela fonte vão atrasar) e acompanhe.
2. Reduza a pressão: escale os workers para baixo ou pause o agendamento (`docker compose stop scheduler`
   ou pause a DAG no Airflow).
3. Quando normalizar: faça o redrive da DLQ e resolva o incidente.
