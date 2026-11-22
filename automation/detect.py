#!/usr/bin/env python3
"""Read-only, idempotent upstream and release discovery; no upstream code runs."""
from __future__ import annotations
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from common import OFFICIAL, is_sha, patch_digest, relevant_fingerprint, version_ok, write_outputs

API = 'https://api.github.com'
MARKER = re.compile(r'<!-- WSFIX-METADATA (\{[^\r\n]*\}) -->')


def api(path: str):
    req = urllib.request.Request(API + path, headers={
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'windscribe-community-release-check',
        **({'Authorization': 'Bearer ' + os.environ['GH_TOKEN']} if os.getenv('GH_TOKEN') else {}),
    })
    with urllib.request.urlopen(req, timeout=35) as res:
        return json.load(res)


def pages(path: str, maximum: int = 20):
    out = []
    for page in range(1, maximum + 1):
        result = api(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
        if not isinstance(result, list):
            raise ValueError('unexpected paginated API response')
        out += result
        if len(result) < 100:
            return out
    raise ValueError('pagination limit reached; refusing incomplete release detection')


def file_json(path: str, sha: str):
    response = api(f'/repos/{OFFICIAL}/contents/{path}?ref={sha}')
    if response.get('encoding') != 'base64':
        raise ValueError('unexpected GitHub content encoding')
    return json.loads(base64.b64decode(response['content'], validate=False))


def release_metadata(body: str):
    match = MARKER.search(body or '')
    if not match:
        return None
    try:
        obj = json.loads(match.group(1))
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def choose(releases, tags, version, upstream, fingerprint, patches, force=False):
    max_rev = 0
    already = None
    previous = ''
    pattern = re.compile(r'^v' + re.escape(version) + r'-wsfix\.(\d+)$')
    for tag in tags:
        match = pattern.fullmatch(tag)
        if match:
            max_rev = max(max_rev, int(match.group(1)))
    for release in releases:
        match = pattern.fullmatch(release.get('tag_name', ''))
        if match:
            max_rev = max(max_rev, int(match.group(1)))
        meta = release_metadata(release.get('body', ''))
        assets = {asset.get('name') for asset in release.get('assets', []) if asset.get('size', 0) > 0}
        complete = not release.get('draft', False) and {'windscribe-community.zip', 'SHA256SUMS', 'CHANGELOG.md', 'BUILD-INFO.json'} <= assets
        if complete and meta and is_sha(meta.get('upstream_sha', '')) and not previous:
            previous = meta['upstream_sha']
        if complete and meta and meta.get('version') == version and meta.get('source_fingerprint') == fingerprint and meta.get('patch_digest') == patches:
            already = release.get('html_url', '')
    tag = f'v{version}-wsfix.{max_rev + 1}'
    return {'should_build': 'false' if already and not force else 'true', 'tag': tag,
            'previous_sha': previous, 'existing_url': already or ''}


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('invalid repository name')
    info = api('/repos/' + OFFICIAL)
    if info.get('default_branch') != 'public':
        raise ValueError('upstream default branch changed; manual review required')
    branches = pages('/repos/' + OFFICIAL + '/branches')
    public = next((x for x in branches if x['name'] == 'public'), None)
    if not public:
        raise ValueError('official public branch missing')
    head = public['commit']['sha']
    if not is_sha(head) or api('/repos/' + OFFICIAL + '/commits/public')['sha'] != head:
        raise ValueError('official public branch changed while checking; retry')
    tags = pages('/repos/' + OFFICIAL + '/tags')
    pkg, manifest = file_json('package.json', head), file_json('src/manifest.json', head)
    version = pkg.get('version')
    if not version_ok(version) or manifest.get('version') != version:
        raise ValueError('official package/manifest versions are invalid or disagree')
    tree = api(f'/repos/{OFFICIAL}/git/trees/{head}?recursive=1')
    if tree.get('truncated') or not isinstance(tree.get('tree'), list):
        raise ValueError('official source tree is incomplete')
    fingerprint = relevant_fingerprint(tree['tree'])
    releases = pages('/repos/' + repo + '/releases')
    refs = pages('/repos/' + repo + '/git/matching-refs/tags/v' + version + '-wsfix.')
    existing_tags = [x['ref'].removeprefix('refs/tags/') for x in refs]
    choice = choose(releases, existing_tags, version, head, fingerprint, patch_digest(), os.getenv('FORCE_BUILD') == 'true')
    values = {'upstream_sha': head, 'version': version, 'source_fingerprint': fingerprint,
              'patch_digest': patch_digest(), **choice}
    write_outputs(os.environ['GITHUB_OUTPUT'], values)
    print('Official default branch: public; commit:', head, 'version:', version)
    print('Branches checked:', len(branches), '; tags checked:', len(tags), '; matching source tags:',
          sum(1 for tag in tags if tag.get('commit', {}).get('sha') == head))
    print('Source fingerprint:', fingerprint, '; build needed:', values['should_build'])
    if choice['existing_url']:
        print('Existing complete release:', choice['existing_url'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Upstream/release detection failed safely:', str(exc), file=sys.stderr)
        sys.exit(1)
