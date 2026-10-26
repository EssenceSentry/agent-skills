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


def test_a_health_check_summarises_the_state_and_names_any_problem(env):
    job = started(env, ["row 40 of 100 ok"] * 5)
    asked = []
    healthy = job_triage.check(env.config, job, model=lambda p: asked.append(p) or
                               "STATE: Scoring rows, 40 of 100 done.\nHEALTH: OK")  # fmt: skip
    assert healthy == job_triage.Look("Scoring rows, 40 of 100 done.", None)
    assert "STATE:" in asked[0] and "HEALTH:" in asked[0]
    sick = job_triage.check(env.config, job, model=lambda p: "STATE: Retrying row 41.\n"
                            "HEALTH: PROBLEM: every row raises KeyError")  # fmt: skip
    assert sick == job_triage.Look("Retrying row 41.", "every row raises KeyError")
    bare = job_triage.check(env.config, job, model=lambda p: "OK")
    assert bare.problem is None


def test_a_job_without_a_log_is_read_from_its_events(env):
    jobs.new(env.config, "remote", env={})
    tail = job_triage.tail(env.config, jobs.get(env.config, "remote"))
    assert "created" in tail


def test_a_health_check_asks_about_pace_against_the_expected_duration(env):
    job = started(env, ["row 40 of 100 ok"])
    jobs.expect(env.config, "mine", 1200)
    asked = []
    job_triage.check(env.config, job, model=lambda p: asked.append(p) or "STATE: ok\nHEALTH: OK")
    assert "expected to take about 20 min" in asked[0]
    assert "is this process working" in asked[0] and "pace" in asked[0]
    assert "faster than expected is fine" in asked[0]
