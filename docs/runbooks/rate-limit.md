# Runbook: rate limit / bloqueio (`rate_limited`)

| Campo | Valor |
|---|---|
| Severidade | P2 (3 ou mais respostas 429 na janela) |
| Tipo de erro | **Transitório**: o worker respeita o header `Retry-After` antes de tentar de novo |

## Por que é sério

Insistir depois de um 429 pode transformar um limite temporário em **bloqueio de IP**.

## Ações

1. **Reduza a concorrência imediatamente**: `make scale N=1`.
2. Aumente o intervalo entre lotes (`CAPTURE_INTERVAL_SECONDS` ou o `schedule` da DAG).
3. Revise o `User-Agent` e os headers (`crawler/http_client.py`).
4. Médio prazo: implemente throttling por fonte (token bucket) e respeite o `robots.txt`/crawl-delay.
5. Se o bloqueio persistir, escale para o time de produto/jurídico: pode haver mudança na política de acesso do site.
