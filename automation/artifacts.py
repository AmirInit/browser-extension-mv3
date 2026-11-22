#!/usr/bin/env python3
"""Create and independently validate extension artifacts without executing them."""
from __future__ import annotations
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile
from common import BUILD_SUPPORT_COMMIT, LABEL, PERFORMANCE_COMMIT, ROOT, UBO_COMMIT, is_sha, patch_digest, version_ok

MAX_FILES = 20000
MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 600 * 1024 * 1024
REQUIRED_ASSETS = {'windscribe-community.zip', 'SHA256SUMS', 'CHANGELOG.md', 'BUILD-INFO.json'}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_name(name):
    parts = name.split('/')
    return bool(name) and not name.startswith('/') and '\\' not in name and '\0' not in name and ':' not in name and all(x not in ('', '.', '..') for x in parts)


def source_file(root, relative):
    root = Path(root)
    target = root / relative
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError('source file is behind a symlink: ' + str(relative))
        current = current.parent
    if not target.is_file():
        raise ValueError('missing source file: ' + str(relative))
    return target


def scan_tree(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('build root is not a real directory')
    files = {}
    total = 0
    for folder, dirs, names in os.walk(root, followlinks=False):
        for entry in dirs + names:
            path = Path(folder) / entry
            if path.is_symlink():
                raise ValueError('symlinks are not permitted in release assets')
        for entry in names:
            path = Path(folder) / entry
            name = path.relative_to(root).as_posix()
            if not safe_name(name) or not path.is_file():
                raise ValueError('unsafe build file')
            if any(part in ('.git', 'node_modules', '.ws-build-cache') or part.startswith('.env') for part in name.split('/')):
                raise ValueError('private or development files are not permitted in the extension archive')
            size = path.stat().st_size
            if size > MAX_FILE:
                raise ValueError('build file exceeds size limit')
            total += size
            files[name] = path
    if len(files) > MAX_FILES or total > MAX_TOTAL:
        raise ValueError('build exceeds release size limit')
    return files


def policy_check(manifest, version, names):
    if not isinstance(manifest, dict) or manifest.get('manifest_version') != 3 or manifest.get('version') != version:
        raise ValueError('not the expected MV3 manifest/version')
    policy = json.loads((ROOT / 'permission-policy.json').read_text())
    for key, value in policy.items():
        actual = manifest.get(key, [] if isinstance(value, list) else None)
        if isinstance(value, list):
            if not isinstance(actual, list) or sorted(actual) != sorted(value) or len(actual) != len(set(actual)):
                raise ValueError('manifest permissions changed: ' + key)
        elif actual != value:
            raise ValueError('manifest policy changed: ' + key)
    required = {'manifest.json', 'backgroundScripts.js', 'background.bundle.js', 'popup.html',
                'offscreenHub.html', 'js/background.js', '_locales/en/messages.json', 'LICENSE-Windscribe.txt', 'LICENSE-uBOL.txt'}
    required.add(str(manifest.get('background', {}).get('service_worker', '')).lstrip('/'))
    required.add(str(manifest.get('action', {}).get('default_popup', '')).lstrip('/'))
    required.update(str(x).lstrip('/') for x in manifest.get('icons', {}).values())
    dnr = manifest.get('declarative_net_request', {}).get('rule_resources', [])
    if not dnr or not any(item.get('enabled') for item in dnr):
        raise ValueError('filtering rules are missing')
    for rule in dnr:
        required.add(str(rule.get('path', '')).lstrip('/'))
    for group in manifest.get('web_accessible_resources', []):
        for pattern in group.get('resources', []):
            pattern = pattern.lstrip('/')
            if not any(fnmatch.fnmatchcase(name, pattern) for name in names):
                raise ValueError('web-accessible resource is missing: ' + pattern)
    missing = sorted(required - set(names))
    if missing or '' in required:
        raise ValueError('missing required extension resources: ' + repr(missing[:8]))


def check_generated(names, locations, useragents):
    def digest(value): return hashlib.sha256(str(value).encode()).hexdigest()
    expected = set()
    for loc in locations['data']:
        expected.add(digest(loc['id']) + 'lnw.bundle.js')
        if loc.get('tz'):
            expected.add(digest(loc['id']) + 'tzw.bundle.js')
        for group in loc.get('groups', []):
            if group.get('gps'):
                expected.add(digest(group['id']) + 'lcw.bundle.js')
    for agent in re.split(r'\r?\n', useragents):
        expected.add(hashlib.sha256(agent.encode()).hexdigest() + '.bundle.js')
    missing = expected - set(names)
    if missing:
        raise ValueError('generated privacy scripts are missing: ' + str(len(missing)))


def validate_zip(path, version):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) > MAX_FILES or len(names) != len(set(names)) or any(not safe_name(n) for n in names):
            raise ValueError('unsafe or duplicate ZIP entries')
        if sum(i.file_size for i in infos) > MAX_TOTAL or any(i.file_size > MAX_FILE or i.is_dir() or stat.S_ISLNK(i.external_attr >> 16) for i in infos):
            raise ValueError('unsafe ZIP type or size')
        policy_check(json.loads(z.read('manifest.json')), version, names)
        for info in infos:
            with z.open(info) as f:
                while f.read(1024 * 1024): pass  # CRC-check all entries without extracting.
        return len(names)


def metadata():
    keys = ('UPSTREAM_SHA', 'VERSION', 'SOURCE_FINGERPRINT', 'PIPELINE_SHA', 'PATCH_DIGEST', 'RELEASE_TAG', 'RUN_URL')
    data = {key.lower(): os.environ[key] for key in keys}
    if not is_sha(data['upstream_sha']) or not is_sha(data['pipeline_sha']) or not version_ok(data['version']):
        raise ValueError('invalid build identity')
    if not re.fullmatch(r'[0-9a-f]{64}', data['source_fingerprint']) or data['patch_digest'] != patch_digest():
        raise ValueError('invalid source fingerprint or patch identity')
    if not re.fullmatch(r'v' + re.escape(data['version']) + r'-wsfix\.[1-9][0-9]*', data['release_tag']):
        raise ValueError('invalid release tag')
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+', data['run_url']):
        raise ValueError('invalid run URL')
    previous = os.environ.get('PREVIOUS_SHA', '')
    if previous and not is_sha(previous):
        raise ValueError('invalid previous upstream SHA')
    data['previous_sha'] = previous
    data.update({'performance_commit': PERFORMANCE_COMMIT, 'build_support_commit': BUILD_SUPPORT_COMMIT,
                 'ubo_commit': UBO_COMMIT, 'classification': 'prerelease', 'notice': LABEL})
    return data


def package(source, out, location_path, audit_path):
    data = metadata()
    source, out = Path(source), Path(out)
    build = source / 'build'
    files = scan_tree(build)
    names = set(files) | {'LICENSE-Windscribe.txt', 'LICENSE-uBOL.txt'}
    manifest = json.loads(files['manifest.json'].read_text())
    if manifest != json.loads(source_file(source, 'src/manifest.json').read_text()):
        raise ValueError('built manifest differs from source manifest')
    policy_check(manifest, data['version'], names)
    check_generated(names, json.loads(Path(location_path).read_text()), source_file(source, 'useragents.txt').read_text())
    for item in manifest['declarative_net_request']['rule_resources']:
        parsed = json.loads(files[item['path'].lstrip('/')].read_bytes())
        if not isinstance(parsed, list): raise ValueError('filtering ruleset is not an array')
    audit = json.loads(Path(audit_path).read_text())
    if audit.get('counts', {}).get('critical') != 0: raise ValueError('critical dependency finding')
    data['audit_summary'] = audit['counts']
    data['high_advisories'] = audit['high_advisories']
    data['redux_integration'] = source_file(source, '.community-ci/mode').read_text().strip()
    if data['redux_integration'] not in ('reviewed-patch', 'equivalent-probed'):
        raise ValueError('invalid Redux integration mode')
    data['locations_sha256'] = sha256_file(location_path)
    data['browser_smoke'] = 'offline Chrome for Testing 131.0.6778.85: popup, Redux, rulesets, MV3 worker restart'
    out.mkdir(parents=True, exist_ok=False)
    archive = out / 'windscribe-community.zip'
    licenses = {'LICENSE-Windscribe.txt': source_file(source, 'LICENSE'), 'LICENSE-uBOL.txt': source_file(source, 'ubo-lite-mirror/LICENSE')}
    for name, path in licenses.items():
        if name in files or path.is_symlink() or not path.is_file(): raise ValueError('license collision or missing license')
        files[name] = path
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, path.read_bytes())
    count = validate_zip(archive, data['version'])
    data['archive_sha256'] = sha256_file(archive)
    data['archive_files'] = count
    (out / 'SHA256SUMS').write_text(data['archive_sha256'] + '  windscribe-community.zip\n')
    (out / 'BUILD-INFO.json').write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    (out / 'CHANGELOG.md').write_text(changelog(data))
    print('Validated extension archive:', count, 'files; SHA-256:', data['archive_sha256'])


def changelog(data):
    comparison = ('https://github.com/Windscribe/browser-extension-mv3/compare/' + data['previous_sha'] + '...' + data['upstream_sha']) if data.get('previous_sha') else 'Initial community release; no previous community build.'
    return f'''# {LABEL}\n\nWindscribe {data['version']} community prerelease. This is not an official Windscribe distribution.\n\n- Official source: https://github.com/Windscribe/browser-extension-mv3/commit/{data['upstream_sha']}\n- Upstream changes: {comparison}\n- Redux performance patch: https://github.com/AmirInit/browser-extension-mv3/commit/{PERFORMANCE_COMMIT}\n- Authenticated location build tooling: https://github.com/AmirInit/browser-extension-mv3/commit/{BUILD_SUPPORT_COMMIT}\n- Pipeline commit: {data['pipeline_sha']}\n- Build run: {data['run_url']}\n- Redux integration: {data['redux_integration']}; reviewed uBO commit: {UBO_COMMIT}\n- Dependency audit: {json.dumps(data['audit_summary'], sort_keys=True)}\n- Package SHA-256: `{data['archive_sha256']}`\n\nThe Redux transport is regression-tested at simulated 100, 1,000, and 3,000-tab workloads. An offline Chrome for Testing 131 smoke opens the actual built popup, checks Redux and enabled filtering rulesets, and stops and reactivates its MV3 worker. The official fresh public Chrome location metadata is validated at build time. **Security warning:** the full dependency audit reports {data['audit_summary']['high']} high-severity finding occurrences; distinct advisory IDs are in BUILD-INFO.json. Non-critical findings remain.\n\nAutomated tests do not establish authenticated connectivity, leak protection, or complete privacy/security. This build is unsigned and does not auto-update. Test it in a separate browser profile before considering an update. Extension settings and sign-in are separate if the extension ID changes.\n\nInstallation, updating without replacing an existing profile, and rollback: https://github.com/AmirInit/browser-extension-mv3/blob/public/docs/community-releases.md\n'''


def validate_envelope(envelope, out):
    data = metadata()
    envelope = Path(envelope)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(envelope) as z:
        infos = z.infolist()
        if {i.filename for i in infos} != REQUIRED_ASSETS or len(infos) != len(REQUIRED_ASSETS):
            raise ValueError('unexpected artifact envelope entries')
        for info in infos:
            if not safe_name(info.filename) or info.file_size > MAX_TOTAL or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('unsafe artifact envelope')
            (out / info.filename).write_bytes(z.read(info))
    build_info = json.loads((out / 'BUILD-INFO.json').read_text())
    for key, value in data.items():
        if build_info.get(key) != value:
            raise ValueError('build provenance mismatch: ' + key)
    actual = sha256_file(out / 'windscribe-community.zip')
    if build_info.get('archive_sha256') != actual or (out / 'SHA256SUMS').read_text() != actual + '  windscribe-community.zip\n':
        raise ValueError('release archive checksum mismatch')
    audit = build_info.get('audit_summary')
    if not isinstance(audit, dict) or set(audit) != {'info', 'low', 'moderate', 'high', 'critical'} or any(type(v) is not int or not 0 <= v <= 1000000 for v in audit.values()) or audit['critical'] != 0:
        raise ValueError('invalid or critical audit results')
    findings = build_info.get('high_advisories')
    if not isinstance(findings, list) or len(findings) > 5000 or any(not isinstance(x, dict) or set(x) != {'package', 'advisory'} or not re.fullmatch(r'(?:@[a-zA-Z0-9._~-]+/)?[a-zA-Z0-9._~-]+', str(x.get('package', ''))) or not re.fullmatch(r'GHSA-[A-Za-z0-9-]+|npm-[0-9]+', str(x.get('advisory', ''))) for x in findings) or (audit['high'] and not findings):
        raise ValueError('invalid high-severity audit details')
    if build_info.get('browser_smoke') != 'offline Chrome for Testing 131.0.6778.85: popup, Redux, rulesets, MV3 worker restart':
        raise ValueError('missing offline browser smoke evidence')
    if build_info.get('redux_integration') not in ('reviewed-patch', 'equivalent-probed') or not re.fullmatch(r'[0-9a-f]{64}', str(build_info.get('locations_sha256', ''))):
        raise ValueError('invalid build integration metadata')
    count = validate_zip(out / 'windscribe-community.zip', data['version'])
    if count != build_info.get('archive_files'):
        raise ValueError('archive entry count mismatch')
    # Never trust a changelog supplied by the build job. Regenerate it from
    # provenance verified above, before passing it to the release API.
    (out / 'CHANGELOG.md').write_text(changelog(build_info))
    marker = json.dumps({k: build_info[k] for k in ('version', 'upstream_sha', 'source_fingerprint', 'patch_digest')}, separators=(',', ':'), sort_keys=True)
    (out / 'release-notes.md').write_text(changelog(build_info) + '\n<!-- WSFIX-METADATA ' + marker + ' -->\n')
    print('Artifact provenance, checksums, archive, manifest and permissions verified:', count, 'files')


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'package': package(*sys.argv[2:6])
        elif sys.argv[1] == 'validate-envelope': validate_envelope(*sys.argv[2:4])
        else: raise ValueError('invalid artifact command')
    except Exception as exc:
        print('Artifact validation failed safely:', str(exc), file=sys.stderr)
        sys.exit(1)
