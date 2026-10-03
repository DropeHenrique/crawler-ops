from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.queue import SqsJobQueue


@pytest.fixture
def job_alpha() -> CaptureJob:
    return CaptureJob(source="alpha", category="eletronicos", page=1, batch_id="b-1", job_id="job-a")


@pytest.fixture
def job_beta() -> CaptureJob:
    return CaptureJob(source="beta", category="livros", page=2, batch_id="b-1", job_id="job-b")


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        yield


@pytest.fixture
def sqs_queue(aws) -> SqsJobQueue:
    sqs = boto3.client("sqs", region_name="us-east-1")
    dlq_url = sqs.create_queue(QueueName="capture-jobs-dlq")["QueueUrl"]
    queue_url = sqs.create_queue(QueueName="capture-jobs")["QueueUrl"]
    return SqsJobQueue(sqs, queue_url, dlq_url)
