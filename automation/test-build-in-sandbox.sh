#!/bin/bash
set -euo pipefail
cd /work
export HOME=/tmp PUPPETEER_SKIP_DOWNLOAD=1 HUSKY=0 CI=true NODE_PATH=/work/node_modules
export NODE_ENV=production BROWSER=Chrome API_URL=windscribe.com BACKUP_API_URL=totallyacdn.com
export BUILD_LOCATIONS_FILE=/work/.community-ci/locations.json
mode=$(cat .community-ci/mode)
if [[ $mode == reviewed-patch ]]; then
  node scripts/applyReduxBroadcastPatch.js
  node scripts/verifyReduxBroadcastPatch.js
elif [[ $mode != equivalent-probed ]]; then
  echo 'Unsupported Redux integration mode' >&2; exit 1
fi
node --test /pipeline/fixtures/tests/unit/reduxBroadcast.test.cjs
if [[ $mode == reviewed-patch ]]; then node --test tests/unit/*.test.cjs; fi
if [[ $mode == equivalent-probed ]]; then node --test tests/unit/buildLocations.community.test.cjs; fi
node_modules/.bin/eslint ./src
node_modules/.bin/tsc -p tests/tsconfig.json
node_modules/.bin/tsc --noEmit
node /pipeline/fixtures/tests/performance/reduxBroadcast.bench.cjs | tee .community-ci/benchmark.jsonl
  node - <<'JS'
const fs=require('fs'); const a=fs.readFileSync('.community-ci/benchmark.jsonl','utf8').trim().split('\n').map(JSON.parse)
for(const n of [100,1000,3000]) { const x=a.find(y=>y.tabCount===n); if(!x || x.tabQueries!==0 || x.tabMessages!==0 || x.runtimeBroadcasts!==21) throw new Error('Redux scaling regression for '+n+' tabs') }
JS
# dotenv-webpack does not import process environment variables by default.
# The file contains public runtime configuration only, never credentials.
if [[ -e .env || -L .env ]]; then echo 'Unexpected candidate .env; refusing to overwrite it' >&2; exit 1; fi
previous_umask=$(umask)
umask 077
cat > .env <<'EOF'
NODE_ENV=production
API_URL=windscribe.com
BACKUP_API_URL=totallyacdn.com
BROWSER=Chrome
REACT_APP_REDUX_PORT=WS_BROWSER_EXTENSION_STORE
EOF
umask "$previous_umask"
yarn build 2>&1 | tee .community-ci/build.log
node /pipeline/check-build-output.cjs .community-ci/build.log
