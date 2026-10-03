from __future__ import annotations

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.exceptions import (
    CaptureError,
    FetchTimeoutError,
    LayoutChangedError,
    RateLimitedError,
)
from crawlerops.crawler.models import CaptureOutcome, CaptureRun
from crawlerops.crawler.queue import ReceivedMessage
from crawlerops.crawler.worker import Worker


class FakeService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def capture(self, job: CaptureJob) -> CaptureOutcome:
        if self.error:
            raise self.error
        return CaptureOutcome(products=[], invalid_count=1, raw_key="raw/x", data_key="cur/x",
                              http_status=200)


class FakeRepo:
    def __init__(self) -> None:
        self.runs: list[CaptureRun] = []

    def record(self, run: CaptureRun) -> None:
        self.runs.append(run)


class FakeAlerts:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def publish_failure(self, job, *, error_type, message, attempts) -> None:
        self.sent.append({"job": job, "error_type": error_type, "attempts": attempts})


class SpyQueue:
    """Envolve a fila real (moto) registrando o tempo de backoff aplicado."""

    def __init__(self, queue) -> None:
        self._queue = queue
        self.delays: list[int] = []

    def retry_later(self, message, delay_seconds):
        self.delays.append(delay_seconds)
        self._queue.retry_later(message, delay_seconds)

    def __getattr__(self, name):
        return getattr(self._queue, name)


def _make_worker(sqs_queue, error=None):
    repo, alerts, queue = FakeRepo(), FakeAlerts(), SpyQueue(sqs_queue)
    worker = Worker(queue, FakeService(error), repo, alerts,  # type: ignore[arg-type]
                    target_base_url="http://site", worker_id="w1", max_receive_count=3)
    return worker, repo, alerts, queue


def _receive_one(sqs_queue, job: CaptureJob, receive_count: int | None = None) -> ReceivedMessage:
    sqs_queue.send([job])
    message = sqs_queue.receive(max_messages=1, wait_seconds=0)[0]
    if receive_count is None:
        return message
    return ReceivedMessage(message.message_id, message.body, message.receipt_handle, receive_count)


def _dlq_messages(sqs_queue) -> list[dict]:
    return sqs_queue.peek_dlq(10)


def test_success_records_run_and_deletes_message(sqs_queue, job_alpha):
    worker, repo, alerts, _ = _make_worker(sqs_queue)

    worker.process(_receive_one(sqs_queue, job_alpha))

    assert repo.runs[0].status == "success"
    assert repo.runs[0].terminal is True
    assert repo.runs[0].invalid_items == 1
    assert sqs_queue.depth() == {"visible": 0, "in_flight": 0}
    assert alerts.sent == []


def test_permanent_error_goes_straight_to_dlq_with_alert(sqs_queue, job_alpha):
    error = LayoutChangedError("layout mudou")
    error.raw_key = "raw/alpha/job-a.html"
    worker, repo, alerts, _ = _make_worker(sqs_queue, error)

    worker.process(_receive_one(sqs_queue, job_alpha))

    run = repo.runs[0]
    assert (run.status, run.terminal, run.error_type) == ("failed", True, "layout_changed")
    assert run.s3_raw_key == "raw/alpha/job-a.html"
    dlq = _dlq_messages(sqs_queue)
    assert len(dlq) == 1
    assert dlq[0]["attributes"]["error_type"] == "layout_changed"
    assert alerts.sent[0]["error_type"] == "layout_changed"


def test_transient_error_schedules_retry_with_backoff(sqs_queue, job_alpha):
    worker, repo, alerts, queue = _make_worker(sqs_queue, FetchTimeoutError("lento"))

    worker.process(_receive_one(sqs_queue, job_alpha, receive_count=2))

    assert repo.runs[0].terminal is False
    assert queue.delays == [20]
    assert _dlq_messages(sqs_queue) == []
    assert alerts.sent == []


def test_rate_limit_respects_retry_after(sqs_queue, job_alpha):
    worker, _, _, queue = _make_worker(sqs_queue, RateLimitedError("429", retry_after=37))

    worker.process(_receive_one(sqs_queue, job_alpha))

    assert queue.delays == [37]


def test_transient_error_on_last_attempt_is_dead_lettered(sqs_queue, job_alpha):
    worker, repo, alerts, _ = _make_worker(sqs_queue, FetchTimeoutError("lento"))

    worker.process(_receive_one(sqs_queue, job_alpha, receive_count=3))

    assert repo.runs[0].terminal is True
    assert len(_dlq_messages(sqs_queue)) == 1
    assert alerts.sent[0]["attempts"] == 3


def test_unexpected_exception_is_wrapped_and_retried(sqs_queue, job_alpha):
    worker, repo, _, queue = _make_worker(sqs_queue, KeyError("bug"))

    worker.process(_receive_one(sqs_queue, job_alpha))

    assert repo.runs[0].error_type == "unexpected"
    assert queue.delays == [10]


def test_malformed_message_goes_to_dlq(sqs_queue):
    worker, repo, _, _ = _make_worker(sqs_queue)
    sqs_queue._sqs.send_message(QueueUrl=sqs_queue.queue_url, MessageBody="{not json")
    message = sqs_queue.receive(max_messages=1, wait_seconds=0)[0]

    worker.process(message)

    assert repo.runs == []
    assert _dlq_messages(sqs_queue)[0]["attributes"]["error_type"] == "invalid_message"


def test_repository_failure_does_not_lose_message_handling(sqs_queue, job_alpha):
    worker, repo, _, _ = _make_worker(sqs_queue)

    def broken(run):
        raise RuntimeError("RDS fora")

    repo.record = broken
    worker.process(_receive_one(sqs_queue, job_alpha))

    assert sqs_queue.depth()["visible"] == 0


def test_redrive_moves_messages_back(sqs_queue, job_alpha):
    worker, _, _, _ = _make_worker(sqs_queue, LayoutChangedError("x"))
    worker.process(_receive_one(sqs_queue, job_alpha))

    moved = sqs_queue.redrive()

    assert moved == 1
    assert sqs_queue.depth(dlq=True)["visible"] == 0
    assert CaptureJob.from_message(sqs_queue.receive(1, 0)[0].body) == job_alpha


def test_unclassified_capture_error_is_retryable_by_default():
    assert CaptureError("x").retryable is True
