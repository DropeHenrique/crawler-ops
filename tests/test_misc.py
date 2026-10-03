import json

import pytest
from failure_alert import handler
from fastapi.testclient import TestClient
from target_site.app import app as target_app

from crawlerops.common.models import CaptureJob
from crawlerops.scheduler.batch import build_batch


def test_capture_job_roundtrip(job_alpha):
    assert CaptureJob.from_message(job_alpha.to_message()) == job_alpha
    assert job_alpha.url_path == "/alpha/eletronicos?page=1"


@pytest.mark.parametrize(
    "body",
    ["{not json", '{"source": "alpha"}', '{"source":"a","category":"c","page":0,"batch_id":"b","job_id":"j"}'],
)
def test_capture_job_rejects_invalid_messages(body):
    with pytest.raises(ValueError):
        CaptureJob.from_message(body)


def test_build_batch_covers_every_source_category_and_page():
    jobs = build_batch("b-1")

    assert len(jobs) == 2 * 3 * 2
    assert len({j.job_id for j in jobs}) == len(jobs)
    assert {j.batch_id for j in jobs} == {"b-1"}


def test_lambda_builds_report_and_posts_each_sns_record(monkeypatch):
    posted = []
    monkeypatch.setattr(handler, "post_report",
                        lambda report, url: posted.append((report, url)) or {"action": "opened"})
    alert = {"source": "alpha", "error_type": "layout_changed", "job_id": "j1", "category": "casa",
             "page": 1, "attempts": 1, "message": "contêiner não encontrado"}
    event = {"Records": [{"Sns": {"Message": json.dumps(alert)}}]}

    result = handler.lambda_handler(event, None)

    assert result == {"processed": 1}
    report, _ = posted[0]
    assert report["rule"] == "dead_letter_layout_changed"
    assert report["severity"] == "P2"
    assert report["details"]["last_error"] == "contêiner não encontrado"


def test_lambda_unknown_error_defaults_to_p2():
    assert handler.build_report({"error_type": "novo_erro", "source": "beta"})["severity"] == "P2"


class TestTargetSiteChaos:
    @pytest.fixture(autouse=True)
    def client(self):
        with TestClient(target_app) as client:
            client.post("/admin/chaos/reset")
            self.client = client
            yield
            client.post("/admin/chaos/reset")

    def test_normal_page(self):
        response = self.client.get("/alpha/casa?page=1")
        assert response.status_code == 200
        assert "product-card" in response.text

    @pytest.mark.parametrize(("mode", "status"), [("error_500", 500), ("unavailable", 503), ("rate_limit", 429)])
    def test_http_failure_modes(self, mode, status):
        self.client.post("/admin/chaos", json={"source": "beta", "mode": mode})

        assert self.client.get("/beta/casa").status_code == status
        assert self.client.get("/alpha/casa").status_code == 200

    def test_layout_change_mode(self):
        self.client.post("/admin/chaos", json={"source": "alpha", "mode": "layout_change"})

        html = self.client.get("/alpha/livros").text
        assert "item-tile" in html and "product-card" not in html

    def test_unknown_category_is_404(self):
        assert self.client.get("/alpha/brinquedos").status_code == 404
