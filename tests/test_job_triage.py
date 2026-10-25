from ax import job_triage, jobs


def started(env, log_lines=()):
    jobs.new(env.config, "mine", label="Mine candidate videos", env={})
    folder = jobs.events_path(env.config, "mine").parent
    (folder / "output.log").write_text("".join(f"{line}\n" for line in log_lines))
    return jobs.get(env.config, "mine")


def test_the_diagnosis_reads_the_end_of_the_log(env):
    lines = [f"row {i} ok" for i in range(500)] + ["DuckDBError: no function read_parquet_v2"]
    job = started(env, lines)
    asked = []
    text = job_triage.diagnose(env.config, job, model=lambda p: asked.append(p) or " cause ")
    assert text == "cause" and "DuckDBError" in asked[0] and "Mine candidate videos" in asked[0]
    assert "row 0 ok" not in asked[0]  # only the tail


def test_a_health_check_returns_the_problem_or_nothing(env):
    job = started(env, ["KeyError: 'video_id'"] * 5)
    assert job_triage.check(env.config, job, model=lambda p: "OK") is None
    found = job_triage.check(env.config, job, model=lambda p: "PROBLEM: every row raises KeyError")
    assert found == "every row raises KeyError"


def test_a_job_without_a_log_is_read_from_its_events(env):
    jobs.new(env.config, "remote", env={})
    tail = job_triage.tail(env.config, jobs.get(env.config, "remote"))
    assert "created" in tail
