# CrawlerOps: laboratório de sustentação de crawlers

Simulação completa, rodando localmente, de uma plataforma de **captura de dados (crawlers/scrapers)** e do
trabalho do time de **sustentação**: monitorar, detectar incidentes P1/P2/P3, cumprir SLA, diagnosticar,
corrigir, reprocessar e documentar.

Tudo roda com Docker, sem custo de AWS: S3, SQS, SNS e Lambda via **LocalStack**, RDS via **PostgreSQL**,
ECS/Fargate via réplicas de container e **Airflow** para orquestração. Um **site-alvo falso com injeção de
falhas** permite provocar incidentes reais e treinar a tratativa.

Diagrama e decisões de design: [docs/arquitetura.md](docs/arquitetura.md).

## Requisitos da vaga → onde estão no projeto

| Requisito | Implementação |
|---|---|
| Python + OO | Hierarquia de exceções, `ProductParser` (Template Method) com `AlphaParser`/`BetaParser`, regras de monitoramento como classes (`Rule`), injeção de dependências no `Worker` e no `CaptureService` |
| Testes | 74 testes com pytest: moto (AWS), respx (HTTP), fakes em memória e teste de contrato parser × site |
| Monitoramento/sustentação | `monitor/`: regras de detecção, SLA, deduplicação, escalonamento, resolução automática, dashboard, `/metrics` |
| Incidentes P1/P2/P3 + SLA | `monitor/sla.py`, `monitor/service.py` e [processo de incidentes](docs/processo-de-incidentes.md) |
| Bugs, timeouts, falhas de integração | Classificação transitório × permanente, retry com backoff, DLQ, redrive ([runbooks](docs/runbooks/)) |
| Manutenção preventiva/corretiva | Runbooks, exercício de correção de parser, regras P3 que antecipam falhas |
| Documentação | `docs/`: arquitetura, processo, 8 runbooks, modelos de comunicação e post-mortem |
| AWS (Lambda, S3, SQS, ECS, Fargate, RDS, EC2) | LocalStack + mapeamento para produção em [arquitetura.md](docs/arquitetura.md#mapeamento-local--aws-real) |
| Microserviços | site-alvo, workers, monitor, scheduler e Lambda independentes, comunicando via fila/HTTP |
| CI/CD | `.github/workflows/ci.yml`: lint, testes com cobertura mínima, validação da DAG, build das imagens |
| Docker, Git, SQL | `docker-compose.yml` com perfis, SQL de monitoramento em `monitor/stats.py` (percentil, `FILTER`, janelas) |
| **Airflow** (diferencial) | `airflow/dags/capture_products.py`: enqueue → sensor → quality gate → manifesto, com callback de incidente |

## Como rodar

Pré-requisitos: Docker com Compose v2, `make` e [uv](https://docs.astral.sh/uv/) (para os testes locais).

```bash
make up            # núcleo + agendador leve (~1,5 GB de RAM)
make up-obs        # + Prometheus e Grafana (opcional)
make up-airflow    # alternativa: núcleo + Airflow no lugar do agendador leve (~3 GB)
make down          # para tudo
```

| Serviço | URL |
|---|---|
| **Central de Sustentação** (dashboard) | http://localhost:8090 |
| API do monitor (Swagger) | http://localhost:8090/docs |
| Site-alvo | http://localhost:8081/alpha/eletronicos |
| Airflow (perfil `airflow`) | http://localhost:8080 |
| Grafana (perfil `observability`) | http://localhost:3000 |
| Prometheus (perfil `observability`) | http://localhost:9090 |
| PostgreSQL ("RDS") | `localhost:5433` (usuário, senha e banco: `crawlerops`) |

Testes locais:

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
make lint test
```

## Cenários de treino

Injete falhas pelo painel **Laboratório de falhas** do dashboard ou via `make chaos`:

| Comando | O que acontece | Incidentes esperados | Runbook |
|---|---|---|---|
| `make chaos SOURCE=alpha MODE=layout_change` | O HTML muda e o parser quebra; jobs vão direto para a DLQ | P1 `capture_health`, P2 `layout_changed`, P2 `dead_letter_layout_changed` (Lambda), P3 `dlq_backlog` | [layout-changed](docs/runbooks/layout-changed.md) |
| `make chaos SOURCE=beta MODE=timeout` | Respostas em 30s estouram o timeout de 8s; 3 tentativas e DLQ | P1 `capture_health`, depois P1 `stale_data` | [timeout](docs/runbooks/timeout.md) |
| `make chaos SOURCE=beta MODE=error_500 P=0.3` | 30% de erros 500; o retry imediato absorve a maioria | Possivelmente P2 `capture_health` | [http-5xx](docs/runbooks/http-5xx.md) |
| `make chaos SOURCE=alpha MODE=rate_limit` | HTTP 429 com `Retry-After: 20` | P2 `rate_limited` | [rate-limit](docs/runbooks/rate-limit.md) |
| `make chaos SOURCE=beta MODE=slow` | Respostas de 4 a 6s | P3 `high_latency` | [qualidade-e-latencia](docs/runbooks/qualidade-e-latencia.md) |
| `make chaos SOURCE=alpha MODE=partial` | 15% dos produtos sem preço | P3 `data_quality` | [qualidade-e-latencia](docs/runbooks/qualidade-e-latencia.md) |
| `docker compose stop scheduler` | Nenhum lote novo é agendado | P1 `stale_data` após 10 min | [dados-desatualizados](docs/runbooks/dados-desatualizados.md) |
| `docker compose stop crawler-worker` | Fila acumula | P1 `stale_data` / alerta `WorkerSemMetricas` no Prometheus | [dados-desatualizados](docs/runbooks/dados-desatualizados.md) |

Fluxo de tratativa para praticar:

1. Injete a falha e espere o incidente aparecer (avaliação a cada 20s, lote a cada 60s).
2. **Assuma** o incidente e acompanhe o SLA.
3. Investigue: execuções recentes, `details` do incidente, HTML bruto no S3 (`make s3-ls`), logs (`make logs`).
4. Corrija (`make chaos-reset` ou, de verdade, ajuste o parser) e **registre notas**.
5. Faça o **redrive da DLQ** e confirme as capturas com sucesso.
6. **Resolva** com a causa raiz. Incidentes de métrica se resolvem sozinhos quando normalizam.

> **Desafio de manutenção corretiva**: com `layout_change` ativo na alpha, faça o `AlphaParser`
> suportar os dois layouts, escreva o teste e veja os incidentes se resolverem após o redrive.

## Estrutura

```
src/crawlerops/
  common/      configuração, logs JSON, modelos, fábrica de clientes AWS, acesso ao banco
  crawler/     worker (ECS), cliente HTTP, parsers (OO), validação, S3, SQS, SNS, métricas
  monitor/     regras P1/P2/P3, SLA, incidentes, avaliador, API FastAPI + dashboard
  scheduler/   montagem de lotes e agendador leve
lambdas/failure_alert/   Lambda SNS → incidente
airflow/dags/            DAG de captura com sensor e quality gate
services/target_site/    site-alvo com chaos
infra/                   init do LocalStack (S3/SQS/DLQ/SNS/Lambda) e schema do RDS
monitoring/              Prometheus (com regras de alerta) e Grafana (dashboard provisionado)
docs/                    arquitetura, processo de incidentes, runbooks
tests/                   testes unitários
```

## Observações

- O LocalStack está fixado na versão **4.14.0**, a última community. Desde março de 2026, as versões
  novas exigem conta e token.
- Os thresholds das regras (janela de 5 min, freshness de 10 min etc.) foram reduzidos para o laboratório
  responder rápido. Em produção, calibre-os com base no histórico para evitar ruído.
