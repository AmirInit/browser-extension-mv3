#!/usr/bin/env python3
"""Bind the downloaded artifact to the current GitHub run and trusted upload output."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

info = json.loads(Path(sys.argv[1]).read_text())
archive = Path(sys.argv[2])
expected_id = os.environ['ARTIFACT_ID']
expected_digest = os.environ['ARTIFACT_DIGEST'].removeprefix('sha256:')
run_id = os.environ['GITHUB_RUN_ID']
if not re.fullmatch(r'[0-9]+', expected_id) or not re.fullmatch(r'[0-9]+', run_id) or not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
    raise SystemExit('Invalid artifact identity')
if str(info.get('id')) != expected_id or str(info.get('workflow_run', {}).get('id')) != run_id:
    raise SystemExit('Artifact did not originate in this workflow run')
if info.get('workflow_run', {}).get('head_sha') != os.environ['PIPELINE_SHA']:
    raise SystemExit('Artifact workflow commit mismatch')
api_digest = str(info.get('digest', '')).removeprefix('sha256:')
if api_digest != expected_digest:
    raise SystemExit('Artifact API digest does not match the upload step')
h = hashlib.sha256()
with archive.open('rb') as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
if h.hexdigest() != expected_digest:
    raise SystemExit('Downloaded artifact digest mismatch')
print('Artifact API, upload output, workflow run, commit, and downloaded SHA-256 match')
