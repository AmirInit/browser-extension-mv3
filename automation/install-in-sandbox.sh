#!/bin/bash
set -euo pipefail
cd /work
export HOME=/tmp PUPPETEER_SKIP_DOWNLOAD=1 HUSKY=0 CI=true
printf 'Node: '; node --version
printf 'Yarn: '; yarn --version
# No dependency or project lifecycle scripts run during installation.
yarn install --frozen-lockfile --ignore-scripts --non-interactive
if [[ $(cat .community-ci/mode) == equivalent-probe ]]; then
  # Run the trusted transport/worker tests against the unpatched upstream package.
  NODE_PATH=/work/node_modules node --test /pipeline/fixtures/tests/unit/reduxBroadcast.test.cjs
fi
# Yarn's exit code includes non-critical findings, so the trusted host-side
# parser requires a complete report and enforces zero critical findings.
yarn audit --json > .community-ci/audit.jsonl || true
