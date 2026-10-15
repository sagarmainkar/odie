from odie.app.main import scheduler_enabled


def test_a_test_instance_can_run_without_the_scheduler(monkeypatch):
    monkeypatch.delenv("ODIE_SCHEDULER", raising=False)
    assert scheduler_enabled() is True
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    assert scheduler_enabled() is False
