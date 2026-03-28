# Prometheus setup for GengoWatcher

This repo now includes a local Prometheus layout intended for a single-user workstation setup.

## What it monitors

- `prometheus` on `127.0.0.1:9090`
- `node_exporter` on `127.0.0.1:9100`
- `gengowatcher` on `127.0.0.1:9091/metrics`

The main `gengowatcher` CLI/TUI process can expose Prometheus metrics when enabled in `config.toml`:

```toml
[Metrics]
enabled = true
host = "127.0.0.1"
port = 9091
```

Those metrics include:

- `gengowatcher_api_initialized`
- `gengowatcher_watcher_running`
- `gengowatcher_failure_count`
- `gengowatcher_session_new_entries`
- `gengowatcher_session_total_value_usd`

Note: `gengowatcher_api_initialized` is only emitted by the optional web API. The main CLI/TUI path emits the watcher/session metrics.

You also get the default Python/process metrics from `prometheus_client` and the host metrics exported by `node_exporter`.

## Files

- `ops/prometheus/prometheus.yml`
- `ops/prometheus/rules/gengowatcher.rules.yml`
- `ops/systemd/user/node_exporter.service`
- `ops/systemd/user/prometheus.service`
- `scripts/validate-prometheus.sh`

## Expected binary locations

These service files assume:

- `prometheus` at `~/.local/bin/prometheus`
- `promtool` at `~/.local/bin/promtool` or otherwise on `PATH`
- `node_exporter` at `~/.local/bin/node_exporter`
- GengoWatcher virtualenv at `~/GengoWatcher/.venv`

Adjust the `ExecStart=` lines if you install them elsewhere.

If your existing virtualenv predates the Prometheus integration, install the dependency into it:

```bash
~/GengoWatcher/.venv/bin/pip install prometheus-client
```

## Install the user services

Copy or symlink the unit files into your user systemd directory:

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/GengoWatcher/ops/systemd/user/node_exporter.service ~/.config/systemd/user/node_exporter.service
ln -sf ~/GengoWatcher/ops/systemd/user/prometheus.service ~/.config/systemd/user/prometheus.service
systemctl --user daemon-reload
systemctl --user enable --now node_exporter.service prometheus.service
```

Run `gengowatcher` normally in another terminal. When `[Metrics].enabled = true`, it will expose metrics on `127.0.0.1:9091` for as long as the app is running.

If you want these user services to keep running after logout, enable lingering once:

```bash
loginctl enable-linger "$USER"
```

## Validation

Validate Prometheus configuration:

```bash
PROMTOOL_BIN=~/.local/bin/promtool ./scripts/validate-prometheus.sh
```

Check metrics endpoints directly:

```bash
curl http://127.0.0.1:9091/metrics
curl http://127.0.0.1:9100/metrics
curl http://127.0.0.1:9090/api/v1/targets
```

Open Prometheus in the browser:

```text
http://127.0.0.1:9090
```

## Useful example queries

```promql
up
gengowatcher_watcher_running
gengowatcher_failure_count
gengowatcher_session_new_entries
gengowatcher_session_total_value_usd
instance:node_cpu_utilization:ratio
instance:node_memory_utilization:ratio
```

## Notes

- All listeners are bound to `127.0.0.1`.
- Alerting rules are included, but they only notify externally if you later add Alertmanager.
- The node exporter runs as a user service here because this setup is intentionally user-scoped.
