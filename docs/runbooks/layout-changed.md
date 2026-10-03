# Runbook: mudança de layout (`layout_changed` / `dead_letter_layout_changed`)

| Campo | Valor |
|---|---|
| Severidade | P2 (costuma vir junto com um P1 de `capture_health`) |
| Tipo de erro | **Permanente**: retry não resolve; os jobs vão direto para a DLQ |
| Detecção | Regra `LayoutChangedRule` + Lambda `failure-alert` (via SNS) |

## Diagnóstico

1. Abra o incidente e copie `details.raw_html_sample`: é a chave no S3 do HTML que quebrou o parser.
2. Baixe o HTML bruto:

```bash
docker compose exec localstack awslocal s3 cp s3://capture-data/<raw_html_sample> - | head -c 2000
```

3. Compare com o que o parser espera (`src/crawlerops/crawler/parsers/<fonte>.py`):
   - `container_selector` (ex.: `main#catalog`)
   - `item_selector` (ex.: `div.product-card`)
   - seletores de cada campo em `parse_item`

## Correção (manutenção corretiva)

1. Salve o HTML novo como fixture de teste e escreva um teste que **falha** com o parser atual.
2. Ajuste o parser. Prefira **aceitar os dois layouts** durante a transição (ex.: tentar
   `main#catalog` e, se não achar, `section#vitrine`), porque sites costumam fazer rollout gradual.
3. `make test` → PR → CI verde → deploy.
4. Faça o **redrive da DLQ** para recapturar as páginas perdidas.
5. Resolva o incidente informando a causa raiz e o link do PR.

> **Exercício**: com `make chaos SOURCE=alpha MODE=layout_change`, implemente o suporte ao
> layout v2 da alpha (`section#vitrine > article.item-tile`, `.tile-name`, `.tile-price`).

## Prevenção

- Monitore a proporção de itens inválidos (`data_quality`): ela costuma subir antes da quebra total.
- Mantenha fixtures reais e atualizadas de cada fonte nos testes.
