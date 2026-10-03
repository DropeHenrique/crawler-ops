.DEFAULT_GOAL := help
COMPOSE := docker compose
MONITOR := http://localhost:8090

help: ## Lista os comandos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

venv: ## Cria o ambiente virtual local com dependências de dev
	python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"

lint: ## Ruff (lint)
	.venv/bin/ruff check .

test: ## Testes unitários com cobertura
	.venv/bin/pytest --cov=crawlerops --cov-report=term-missing

up: ## Sobe o núcleo + agendador leve
	$(COMPOSE) --profile lite up -d --build

up-airflow: ## Sobe o núcleo + Airflow (orquestração pela DAG)
	$(COMPOSE) --profile airflow up -d --build

up-obs: ## Adiciona Prometheus + Grafana
	$(COMPOSE) --profile observability up -d

up-all: ## Núcleo + Airflow + observabilidade (precisa de ~4 GB de RAM livres)
	$(COMPOSE) --profile airflow --profile observability up -d --build

down: ## Para tudo (mantém o volume do banco)
	$(COMPOSE) --profile lite --profile airflow --profile observability down

clean: ## Para tudo e apaga os dados
	$(COMPOSE) --profile lite --profile airflow --profile observability down -v

ps: ## Status dos containers
	$(COMPOSE) ps

logs: ## Logs do worker e do monitor
	$(COMPOSE) logs -f --tail=50 crawler-worker monitor

scale: ## Escala workers (ex.: make scale N=4), como alterar o desiredCount no ECS
	$(COMPOSE) up -d --no-recreate --scale crawler-worker=$(N)

chaos: ## Injeta falha (ex.: make chaos SOURCE=alpha MODE=layout_change P=1)
	@curl -s -X POST $(MONITOR)/api/chaos -H 'Content-Type: application/json' \
		-d '{"source":"$(or $(SOURCE),all)","mode":"$(MODE)","probability":$(or $(P),1)}' | python3 -m json.tool

chaos-reset: ## Volta o site-alvo ao normal
	@curl -s -X POST $(MONITOR)/api/chaos/reset | python3 -m json.tool

incidents: ## Lista incidentes ativos
	@curl -s $(MONITOR)/api/incidents | python3 -m json.tool

redrive: ## Reprocessa a DLQ (após corrigir a causa)
	@curl -s -X POST $(MONITOR)/api/dlq/redrive -H 'Content-Type: application/json' -d '{"limit":500}'

s3-ls: ## Lista objetos no bucket de captura
	$(COMPOSE) exec localstack awslocal s3 ls s3://capture-data --recursive | tail -20

psql: ## Abre o psql no "RDS"
	$(COMPOSE) exec postgres psql -U crawlerops -d crawlerops

.PHONY: help venv lint test up up-airflow up-obs up-all down clean ps logs scale chaos chaos-reset incidents redrive s3-ls psql
