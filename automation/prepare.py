#!/usr/bin/env python3
"""Apply only reviewed patches; unknown integration states stop before release."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from common import BASE, PATCHES, ROOT, UBO_COMMIT, is_sha


def run(args, cwd, check=True):
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def apply_or_already(source, patch):
    if run(['git', 'apply', '--check', str(patch)], source, False).returncode == 0:
        run(['git', 'apply', str(patch)], source)
        return 'applied'
    if run(['git', 'apply', '--reverse', '--check', str(patch)], source, False).returncode == 0:
        return 'already-applied'
    return 'incompatible'


def check_architecture(source):
    allowed = {'src/pages/proxyStore.ts', 'src/state/webExtAdapter.ts', 'src/state/store.ts'}
    uses = set()
    for path in (source / 'src').rglob('*'):
        if path.suffix not in ('.js', '.ts', '.tsx') or not path.is_file():
            continue
        text = path.read_text(encoding='utf8')
        rel = path.relative_to(source).as_posix()
        if '@eduardoac-skimlinks/webext-redux' in text or re.search(r'\bnew\s+Store\s*\(', text):
            uses.add(rel)
        if rel.startswith('src/pages/contentScripts/') and re.search(r'proxyStore|state/hooks|state/store|webExtAdapter|webext-redux', text):
            raise ValueError('a content script may consume the Redux proxy; review messaging architecture')
    if uses != allowed:
        raise ValueError('Redux consumer set changed; review before removing tab broadcasts: ' + repr(sorted(uses)))
    # New content scripts or proxy wiring can add indirect subscribers not caught by imports.
    diff = run(['git', 'diff', '--quiet', BASE, 'HEAD', '--', 'src/pages/contentScripts', 'src/pages/proxyStore.ts', 'src/state/webExtAdapter.ts'], source, False)
    if diff.returncode:
        raise ValueError('content scripts or Redux wiring changed; review compatibility')


def prepare(source, sha):
    if not is_sha(sha) or run(['git', 'rev-parse', 'HEAD'], source).stdout.strip() != sha:
        raise ValueError('candidate checkout does not match the detected upstream commit')
    if run(['git', 'merge-base', '--is-ancestor', BASE, sha], source, False).returncode:
        raise ValueError('official history is not descended from the reviewed baseline')
    if run(['git', 'status', '--porcelain', '--untracked-files=no'], source).stdout.strip():
        raise ValueError('candidate checkout has unexpected modifications')
    check_architecture(source)
    gitlink = run(['git', 'ls-tree', 'HEAD', 'ubo-lite-mirror'], source).stdout.strip()
    if gitlink != f'160000 commit {UBO_COMMIT}\tubo-lite-mirror':
        raise ValueError('uBO submodule changed; its integration requires human review')
    path = run(['git', 'config', '-f', '.gitmodules', '--get', 'submodule.ubo-lite-mirror.path'], source).stdout.strip()
    url = run(['git', 'config', '-f', '.gitmodules', '--get', 'submodule.ubo-lite-mirror.url'], source).stdout.strip()
    if path != 'ubo-lite-mirror' or url != 'https://github.com/Windscribe/ubo-lite.git':
        raise ValueError('uBO submodule path or origin changed')
    mode = apply_or_already(source, ROOT / PATCHES[0])
    if mode != 'incompatible':
        for patch in PATCHES[1:]:
            status = apply_or_already(source, ROOT / patch)
            if status == 'incompatible':
                raise ValueError(f'reviewed {patch} is incompatible; no silent fallback')
        mode = 'reviewed-patch'
    else:
        # A trusted behavioral probe will determine if a new upstream dependency
        # already supplies equivalent messaging; failure prevents a build.
        mode = 'equivalent-probe'
    ci = source / '.community-ci'
    if ci.exists() or ci.is_symlink():
        raise ValueError('candidate uses the reserved community CI path')
    ci.mkdir()
    (ci / 'mode').write_text(mode + '\n')
    ubo = source / 'ubo-lite-mirror'
    ubo.mkdir(exist_ok=True)
    if ubo.is_symlink() or any(ubo.iterdir()):
        raise ValueError('expected an empty submodule directory')
    run(['git', 'clone', '--no-checkout', '--filter=blob:none', 'https://github.com/Windscribe/ubo-lite.git', str(ubo)], source)
    run(['git', 'checkout', '--detach', UBO_COMMIT], ubo)
    if run(['git', 'rev-parse', 'HEAD'], ubo).stdout.strip() != UBO_COMMIT:
        raise ValueError('uBO checkout mismatch')
    print('Candidate prepared:', sha, '; Redux mode:', mode, '; reviewed uBO:', UBO_COMMIT)


def finish_equivalent(source):
    ci = source / '.community-ci'
    if (ci / 'mode').read_text().strip() != 'equivalent-probe':
        raise ValueError('not an equivalent-probe candidate')
    build = source / 'scripts/build.js'
    text = build.read_text()
    if 'BUILD_LOCATIONS_FILE' in text or (source / 'scripts/loadBuildLocations.js').exists():
        raise ValueError('unreviewed upstream build-location integration; manual review required')
    anchor = "const getLocations = require('./getLocations')"
    old = '  const sessionData = await login()\n  const userAgents = getUserAgents()\n  const serverListData = await getLocations(sessionData)'
    new = "  const userAgents = getUserAgents()\n  const serverListData = process.env.BUILD_LOCATIONS_FILE\n    ? loadBuildLocations(process.env.BUILD_LOCATIONS_FILE)\n    : await getLocations(await login())"
    if text.count(anchor) != 1 or text.count(old) != 1:
        raise ValueError('upstream build script changed; authenticated location support needs review')
    text = text.replace(anchor, anchor + "\nconst loadBuildLocations = require('./loadBuildLocations')").replace(old, new)
    build.write_text(text)
    (source / 'scripts/loadBuildLocations.js').write_bytes((ROOT / 'fixtures/loadBuildLocations.js').read_bytes())
    test = source / 'tests/unit/buildLocations.community.test.cjs'
    test.parent.mkdir(parents=True, exist_ok=True)
    if test.exists():
        raise ValueError('community test path already exists')
    test.write_bytes((ROOT / 'fixtures/buildLocations.test.cjs').read_bytes())
    (ci / 'mode').write_text('equivalent-probed\n')
    print('Equivalent Redux behavior passed; added reviewed location loader. Original lockfile is audited unchanged.')


if __name__ == '__main__':
    try:
        source = Path(sys.argv[2]).resolve()
        if sys.argv[1] == 'prepare': prepare(source, sys.argv[3])
        elif sys.argv[1] == 'finish-equivalent': finish_equivalent(source)
        else: raise ValueError('invalid prepare command')
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('Candidate preparation failed safely:', str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError): print(exc.stderr[-2000:], file=sys.stderr)
        sys.exit(1)
