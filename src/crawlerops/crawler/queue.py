from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import batched
from typing import Any

from crawlerops.common.models import CaptureJob

logger = logging.getLogger(__name__)

_SQS_BATCH_LIMIT = 10
_SQS_MAX_VISIBILITY = 43_200


@dataclass(frozen=True)
class ReceivedMessage:
    message_id: str
    body: str
    receipt_handle: str
    receive_count: int


class SqsJobQueue:
    def __init__(self, sqs_client: Any, queue_url: str, dlq_url: str) -> None:
        self._sqs = sqs_client
        self.queue_url = queue_url
        self.dlq_url = dlq_url

    def send(self, jobs: Iterable[CaptureJob]) -> int:
        sent = 0
        for chunk in batched(jobs, _SQS_BATCH_LIMIT):
            response = self._sqs.send_message_batch(
                QueueUrl=self.queue_url,
                Entries=[{"Id": str(i), "MessageBody": job.to_message()} for i, job in enumerate(chunk)],
            )
            if response.get("Failed"):
                logger.error("falha ao enfileirar jobs", extra={"failed": response["Failed"]})
            sent += len(response.get("Successful", []))
        return sent

    def receive(self, max_messages: int = 5, wait_seconds: int = 10) -> list[ReceivedMessage]:
        response = self._sqs.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        return [
            ReceivedMessage(
                message_id=m["MessageId"],
                body=m["Body"],
                receipt_handle=m["ReceiptHandle"],
                receive_count=int(m.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
            )
            for m in response.get("Messages", [])
        ]

    def delete(self, message: ReceivedMessage) -> None:
        self._sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message.receipt_handle)

    def retry_later(self, message: ReceivedMessage, delay_seconds: int) -> None:
        """Devolve a mensagem para a fila após ``delay_seconds`` (backoff via visibility timeout)."""
        self._sqs.change_message_visibility(
            QueueUrl=self.queue_url,
            ReceiptHandle=message.receipt_handle,
            VisibilityTimeout=min(max(delay_seconds, 0), _SQS_MAX_VISIBILITY),
        )

    def dead_letter(self, message: ReceivedMessage, *, error_type: str, reason: str) -> None:
        self._sqs.send_message(
            QueueUrl=self.dlq_url,
            MessageBody=message.body,
            MessageAttributes={
                "error_type": {"DataType": "String", "StringValue": error_type},
                "reason": {"DataType": "String", "StringValue": reason[:1000] or "-"},
                "attempts": {"DataType": "Number", "StringValue": str(message.receive_count)},
            },
        )
        self.delete(message)

    def depth(self, *, dlq: bool = False) -> dict[str, int]:
        attrs = self._sqs.get_queue_attributes(
            QueueUrl=self.dlq_url if dlq else self.queue_url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
        return {
            "visible": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
        }

    def peek_dlq(self, limit: int = 10) -> list[dict]:
        """Lê mensagens da DLQ sem removê-las (ficam invisíveis por poucos segundos)."""
        response = self._sqs.receive_message(
            QueueUrl=self.dlq_url,
            MaxNumberOfMessages=min(limit, _SQS_BATCH_LIMIT),
            VisibilityTimeout=2,
            MessageAttributeNames=["All"],
        )
        return [
            {
                "message_id": m["MessageId"],
                "body": m["Body"],
                "attributes": {k: v.get("StringValue") for k, v in m.get("MessageAttributes", {}).items()},
            }
            for m in response.get("Messages", [])
        ]

    def redrive(self, limit: int = 100) -> int:
        """Move mensagens da DLQ de volta para a fila principal (após a causa ser corrigida)."""
        moved = 0
        while moved < limit:
            response = self._sqs.receive_message(
                QueueUrl=self.dlq_url,
                MaxNumberOfMessages=min(_SQS_BATCH_LIMIT, limit - moved),
                WaitTimeSeconds=1,
            )
            messages = response.get("Messages", [])
            if not messages:
                break
            for m in messages:
                self._sqs.send_message(QueueUrl=self.queue_url, MessageBody=m["Body"])
                self._sqs.delete_message(QueueUrl=self.dlq_url, ReceiptHandle=m["ReceiptHandle"])
                moved += 1
        return moved
