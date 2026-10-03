#!/bin/bash
# Executado pelo LocalStack quando fica "ready": cria os recursos AWS da plataforma.
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT="000000000000"

echo ">> S3"
awslocal s3 mb s3://capture-data

echo ">> SQS (fila principal + DLQ com redrive após 3 recebimentos)"
awslocal sqs create-queue --queue-name capture-jobs-dlq \
    --attributes MessageRetentionPeriod=1209600
DLQ_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:capture-jobs-dlq"
awslocal sqs create-queue --queue-name capture-jobs --attributes "{
    \"VisibilityTimeout\": \"60\",
    \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"${DLQ_ARN}\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"
}"

echo ">> SNS (eventos de falha definitiva)"
TOPIC_ARN=$(awslocal sns create-topic --name capture-alerts --query TopicArn --output text)

# Marcador usado pelo healthcheck: os recursos essenciais estão prontos.
echo ok | awslocal s3 cp - s3://capture-data/_bootstrap/ready

echo ">> Lambda failure-alert (SNS -> Lambda -> API do monitor)"
deploy_lambda() {
    mkdir -p /tmp/lambda-build
    (cd /opt/lambdas/failure_alert && python3 -m zipfile -c /tmp/lambda-build/failure_alert.zip handler.py)
    awslocal lambda create-function \
        --function-name failure-alert \
        --runtime python3.12 \
        --handler handler.lambda_handler \
        --timeout 15 \
        --role "arn:aws:iam::${ACCOUNT}:role/lambda-role" \
        --zip-file fileb:///tmp/lambda-build/failure_alert.zip \
        --environment "Variables={MONITOR_URL=${MONITOR_URL:-http://monitor:8090}}"
    awslocal lambda wait function-active-v2 --function-name failure-alert
    awslocal sns subscribe \
        --topic-arn "$TOPIC_ARN" \
        --protocol lambda \
        --notification-endpoint "arn:aws:lambda:${REGION}:${ACCOUNT}:function:failure-alert"
}

# A Lambda é opcional: se falhar, a captura e o monitor continuam funcionando.
deploy_lambda || echo "AVISO: deploy da Lambda falhou; alertas via SNS ficarão desativados"

echo ">> Recursos criados com sucesso"
