#!/usr/bin/env bash
set -euo pipefail

PROMTOOL_BIN="${PROMTOOL_BIN:-promtool}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROM_DIR="${ROOT_DIR}/ops/prometheus"

"${PROMTOOL_BIN}" check config "${PROM_DIR}/prometheus.yml"
"${PROMTOOL_BIN}" check rules "${PROM_DIR}/rules/gengowatcher.rules.yml"

printf 'Prometheus config and rules are valid.\n'
