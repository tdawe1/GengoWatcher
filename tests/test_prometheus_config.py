from pathlib import Path


def test_prometheus_rule_files_are_portable():
    config_text = Path("ops/prometheus/prometheus.yml").read_text()

    assert "/home/user/GengoWatcher" not in config_text
    assert "  - rules/*.yml" in config_text
