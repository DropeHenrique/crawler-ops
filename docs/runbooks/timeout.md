# Runbook: timeouts e falhas de conexão (`timeout`, `connection_error`)

| Campo | Valor |
|---|---|
| Tipo de erro | **Transitório**: re-tentado via SQS com backoff (10s, 20s), DLQ na 3ª tentativa |
| Timeout do cliente | `HTTP_TIMEOUT_SECONDS` (padrão: 8s) |

## Diagnóstico

1. O site responde de fora do worker?

```bash
time curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8081/alpha/casa
```

2. Se responde rápido daqui mas não do worker, o problema é de rede, DNS ou egress do container/VPC.
3. Se responde **lento** (próximo do limite), há duas opções:
   - temporária: aumentar `HTTP_TIMEOUT_SECONDS` e reiniciar os workers (`docker compose up -d crawler-worker`);
   - estrutural: reduzir a concorrência contra o site.
4. Veja se a fila está acumulando (`Jobs na fila` no dashboard). Com timeouts, cada worker fica
   preso até 8s por job: considere escalar (`make scale N=4`), o equivalente a aumentar o `desiredCount` no ECS.

## Encerramento

Quando o site normalizar, os jobs em retry se recuperam sozinhos. Os que foram para a DLQ precisam de **redrive**.
