from ramseyer.data.http import redact
from ramseyer import config


def test_redact_strips_api_key():
    assert redact("https://api.congress.gov/v3/bill/119/hr/1/text?format=json&api_key=SECRET") == \
        "https://api.congress.gov/v3/bill/119/hr/1/text?format=json"


def test_config_reads_pin_and_env(tmp_path, monkeypatch):
    (tmp_path / "ramseyer.toml").write_text((config.ROOT / "ramseyer.toml").read_text())
    (tmp_path / ".env").write_text("API_DATA_GOV_KEY=k\nRAMSEYER_CONTACT=ops@example.org\n")
    monkeypatch.delenv("API_DATA_GOV_KEY", raising=False)
    monkeypatch.delenv("RAMSEYER_CONTACT", raising=False)
    cfg = config.load(tmp_path)
    assert cfg.release_pin == "119-134"
    assert cfg.api_key == "k"
    assert cfg.user_agent == "ramseyer/0.0.1 (+ops@example.org)"
