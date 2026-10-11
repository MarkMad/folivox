import pytest


@pytest.fixture(autouse=True)
def _private_log_dir(tmp_path_factory, monkeypatch):
    """Tests never write to the real per-user log file."""
    from folivox import diag

    logs = tmp_path_factory.mktemp("logs")
    monkeypatch.setattr(diag, "log_dir", lambda: logs)
    import logging

    for h in list(logging.getLogger(diag.LOGGER).handlers):
        logging.getLogger(diag.LOGGER).removeHandler(h)
        h.close()
