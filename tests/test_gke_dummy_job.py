from sp26_gke.workflows.gke_dummy_job import run


def test_gke_dummy_job_success(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DUMMY_LOOP_COUNT", "2")
    monkeypatch.setenv("DUMMY_SLEEP_SECONDS", "0")
    monkeypatch.setenv("DUMMY_FAIL", "false")

    exit_code = run()

    assert exit_code == 0
    out_lines = capsys.readouterr().out.strip().splitlines()
    assert any('"event": "dummy_job_started"' in line for line in out_lines)
    assert any('"event": "dummy_job_completed"' in line for line in out_lines)


def test_gke_dummy_job_failure(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DUMMY_LOOP_COUNT", "1")
    monkeypatch.setenv("DUMMY_SLEEP_SECONDS", "0")
    monkeypatch.setenv("DUMMY_FAIL", "true")

    exit_code = run()

    assert exit_code == 1
    out_lines = capsys.readouterr().out.strip().splitlines()
    assert any('"event": "dummy_job_failed"' in line for line in out_lines)
