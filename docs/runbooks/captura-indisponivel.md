# Runbook: captura indisponível ou degradada (`capture_health`)

| Campo | Valor |
|---|---|
| Severidade | P1 (sucesso < 50%) / P2 (sucesso < 90%) |
| SLA | P1: resposta 15 min, resolução 2 h · P2: 30 min / 8 h |
| Detecção | Monitor, regra `CaptureHealthRule` (janela de 5 min, mínimo de 4 execuções) |

## 1. Triagem (primeiros 5 minutos)

1. **Assuma o incidente** no dashboard (botão *Assumir*). Isso registra o horário de resposta para o SLA.
2. Veja os **erros predominantes** no card da fonte ou em `details.errors` do incidente:

| `error_type` | Provável causa | Runbook |
|---|---|---|
| `timeout` | site lento ou fora do ar | [timeout.md](timeout.md) |
| `http_5xx` | erro no servidor do site | [http-5xx.md](http-5xx.md) |
| `rate_limited` | bloqueio por excesso de requisições | [rate-limit.md](rate-limit.md) |
| `layout_changed` / `data_validation` | o HTML mudou | [layout-changed.md](layout-changed.md) |
| `connection_error` | DNS, rede, site fora | [timeout.md](timeout.md) |
| `unexpected` | bug no nosso código | veja o stacktrace nos logs |

3. Confirme se o problema é **só uma fonte** ou **todas**. Todas as fontes falhando ao mesmo tempo
   aponta para a nossa infraestrutura (worker, rede, SQS), não para o site.

## 2. Comandos úteis

```bash
make logs                                   # logs JSON do worker/monitor
docker compose logs crawler-worker | grep '"source": "alpha"' | grep ERROR | tail
curl -s localhost:8090/api/runs?source=alpha | jq '.[0:5]'
make ps                                     # workers estão de pé?
```

## 3. Comunicação

Para P1, avise a área de negócio em até 15 minutos usando o modelo de
[processo-de-incidentes.md](../processo-de-incidentes.md#modelo-de-comunicação).

## 4. Encerramento

- Normalmente o incidente **se resolve sozinho** quando a taxa de sucesso volta ao normal.
- Se houver jobs na DLQ, execute o **redrive** depois de confirmar a correção.
- Registre nota com a causa raiz, mesmo nos auto-resolvidos que tiveram ação humana.
