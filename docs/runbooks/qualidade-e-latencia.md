# Runbook: qualidade de dados e latência (`data_quality`, `high_latency`)

Ambos são **P3**: sintomas sem impacto imediato, mas costumam anteceder um P1/P2.

## `data_quality`: mais de 5% de itens inválidos

- A página foi capturada, mas alguns produtos vieram sem preço, nome ou SKU.
- Até 20% de itens inválidos, a página é aceita e os itens ruins são descartados (`invalid_items` em `capture_runs`).
  Acima de 20%, a página inteira é rejeitada (`data_validation`, erro permanente).
- **Ação**: baixe o HTML bruto (`s3_raw_key` em `/api/runs`) e verifique se é um problema do site
  (produto realmente sem preço) ou um seletor frágil no parser.

## `high_latency`: p95 das capturas bem-sucedidas acima de 3s

- O risco é virar `timeout` (limite de 8s) e reduzir a vazão dos workers.
- **Ação**: verifique se a lentidão é do site (curl externo) ou nossa (CPU/memória dos workers:
  `docker stats`). Considere escalar os workers ou espaçar os lotes.
