from urllib.parse import parse_qs, urlsplit

import pytest

from ax import job_notify, jobs


class FakePost:
    def __init__(self, *failures):
        self.failures = list(failures)
        self.calls = []

    def __call__(self, url, body, headers, timeout=10):
        self.calls.append((url, body, headers))
        if self.failures:
            raise self.failures.pop(0)
        return 200


@pytest.fixture
def post(monkeypatch):
    def install(*failures):
        fake = FakePost(*failures)
        monkeypatch.setattr(job_notify, "post", fake)
        return fake

    return install


def test_settings_come_from_config_and_the_environment(env):
    assert job_notify.settings(env.config, env={}) is None
    env.config_path.write_text(env.config_path.read_text() + '\n[notify]\ntopic = "my-topic"\n')
    from ax.config import load

    ntfy = job_notify.settings(load(env.config_path), env={})
    assert (ntfy.server, ntfy.topic, ntfy.token) == ("https://ntfy.sh", "my-topic", None)
    ntfy = job_notify.settings(
        load(env.config_path),
        env={
            "AX_NTFY_SERVER": "https://ntfy.example/",
            "AX_NTFY_TOPIC": "t2",
            "AX_NTFY_TOKEN": "tk",
        },
    )
    assert (ntfy.server, ntfy.topic, ntfy.token) == ("https://ntfy.example", "t2", "tk")


def test_a_message_goes_to_the_topic_with_its_fields_in_the_query(post):
    fake = post()
    ntfy = job_notify.Ntfy("https://ntfy.sh", "my-topic", token="tk")
    error = job_notify.send(
        ntfy, "score done · ✓", "40 rows", tags=("white_check_mark",), priority=4,
        click="https://x.trycloudflare.com/?token=abc",
    )  # fmt: skip
    assert error is None
    url, body, headers = fake.calls[0]
    parts = urlsplit(url)
    assert parts.path == "/my-topic"
    query = parse_qs(parts.query)
    assert query["title"] == ["score done · ✓"]
    assert query["tags"] == ["white_check_mark"] and query["priority"] == ["4"]
    assert query["click"] == ["https://x.trycloudflare.com/?token=abc"]
    assert body == b"40 rows"
    assert headers["Authorization"] == "Bearer tk"


def test_sending_retries_then_reports_the_error(post):
    fake = post(OSError("down"), OSError("still down"))
    ntfy = job_notify.Ntfy("https://ntfy.sh", "t")
    assert job_notify.send(ntfy, "a", "b", sleep=lambda s: None) is None
    assert len(fake.calls) == 3
    fake = post(OSError("1"), OSError("2"), OSError("3"))
    error = job_notify.send(ntfy, "a", "b", sleep=lambda s: None)
    assert "3" in error and len(fake.calls) == 3


def test_messages_describe_the_job(env):
    jobs.new(env.config, "score", total=40, unit="rows")
    job = jobs.get(env.config, "score")
    job.done, job.stage = 10, "scoring"
    assert job_notify.started(job)["title"] == "score started"
    progress = job_notify.progress(job)
    assert progress["title"] == "score: 25%" and "10/40 rows" in progress["message"]
    assert "scoring" in progress["message"]
    job.status, job.message = "failed", "disk full"
    finished = job_notify.finished(job)
    assert finished["title"] == "score failed" and finished["priority"] == 4
    assert "disk full" in finished["message"]
    assert job_notify.stalled(job, 1800)["title"] == "score stalled"
    assert "30 min" in job_notify.stalled(job, 1800)["message"]
