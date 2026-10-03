# Runbook: dados desatualizados (`stale_data`)

| Campo | Valor |
|---|---|
| Severidade | P1 |
| Condição | Nenhuma captura bem-sucedida da fonte há mais de 10 minutos |

Este é o alerta que **o negócio sente**: mesmo que nenhum erro apareça, os dados pararam de chegar.

## Causas comuns

| Sintoma | Causa |
|---|---|
| Não há execuções recentes de nenhuma fonte | agendador parado (scheduler/DAG pausada) ou workers fora do ar |
| Há execuções, mas todas falham | ver [captura-indisponivel.md](captura-indisponivel.md) |
| Fila crescendo sem parar | workers insuficientes ou travados |

## Verificações

```bash
make ps                                            # scheduler / airflow / workers rodando?
curl -s localhost:8090/api/overview | jq .queues   # fila acumulando?
docker compose logs --tail=20 scheduler            # lotes sendo enfileirados?
```

No Airflow (http://localhost:8080), verifique se a DAG `capture_products` está ativa e sem runs travados.
