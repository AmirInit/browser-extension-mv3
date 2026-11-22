#!/usr/bin/env python3
"""Check that GitHub stored exactly the validated release assets."""
import hashlib
import json
import os
from pathlib import Path
import sys

result = json.loads(Path(sys.argv[1]).read_text())
if isinstance(result, list):
    # The tag endpoint only returns published releases; drafts are listed to
    # authorized writers. --paginate --slurp gives a list of pages.
    releases = [release for page in result for release in (page if isinstance(page, list) else [page])]
    matches = [release for release in releases if release.get('tag_name') == os.environ['RELEASE_TAG']]
    if len(matches) != 1:
        raise SystemExit('Could not uniquely identify the draft release')
    release = matches[0]
else:
    release = result
folder = Path(sys.argv[2])
want_draft = sys.argv[3] == 'draft'
if release.get('tag_name') != os.environ['RELEASE_TAG'] or release.get('draft') is not want_draft or release.get('prerelease') is not True:
    raise SystemExit('Release state or tag is invalid')
expected = {'windscribe-community.zip', 'SHA256SUMS', 'CHANGELOG.md', 'BUILD-INFO.json'}
assets = release.get('assets', [])
if {x.get('name') for x in assets} != expected or len(assets) != len(expected):
    raise SystemExit('GitHub release has missing, duplicate, or extra assets')
for asset in assets:
    path = folder / asset['name']
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if asset.get('size') != path.stat().st_size or asset.get('digest') != 'sha256:' + digest or asset.get('state') != 'uploaded':
        raise SystemExit('GitHub asset checksum, size, or state mismatch: ' + asset['name'])
print('GitHub release state and all asset digests verified')
