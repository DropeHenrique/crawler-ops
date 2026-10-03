# Runbook: mensagens na DLQ (`dlq_backlog`, `dead_letter_*`)

| Campo | Valor |
|---|---|
| Severidade | `dead_letter_*`: P2 (aberto pela Lambda) · `dlq_backlog`: P3 |
| Resolução automática | `dlq_backlog`: sim, quando a DLQ esvazia · `dead_letter_*`: **não**, exige resolução manual documentada |

## Como as mensagens chegam à DLQ

1. **Erro permanente** (layout mudou, 4xx, dado inválido): o worker envia direto para a DLQ.
2. **Erro transitório na 3ª tentativa**: o worker envia para a DLQ.
3. **Worker morreu no meio do processamento** 3 vezes: a `RedrivePolicy` do SQS move a mensagem sozinha.
   Nesse caso não há atributo `error_type` nem alerta via SNS; o `dlq_backlog` é a rede de segurança.

## Procedimento

1. Inspecione as mensagens (dashboard → *Ver mensagens*, ou `GET /api/dlq`) e veja `attributes.error_type` e `reason`.
2. **Corrija a causa antes do redrive.** Reprocessar sem corrigir só devolve as mensagens à DLQ.
3. Execute o redrive: dashboard → *Redrive da DLQ*, ou `make redrive`.
4. Acompanhe as execuções recentes para confirmar sucesso.
5. Resolva os incidentes `dead_letter_*` com a causa raiz.

## Mensagens `invalid_message`

São JSONs malformados ou sem campos obrigatórios. Não adianta fazer redrive: investigue quem publicou
a mensagem (scheduler ou DAG) e descarte-as depois de registrar a evidência.
