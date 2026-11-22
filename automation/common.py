"""Constants and narrowly scoped helpers for the community release workflow."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OFFICIAL = 'Windscribe/browser-extension-mv3'
BASE = 'cfb29151334e38707d7cfffa3b52fc87c8de3f3f'
PERFORMANCE_COMMIT = '7d3beadc3ae7414f93b0f477c1b408e770899216'
BUILD_SUPPORT_COMMIT = 'a2daa80828401da49192f72ff9a00e1817c5b75c'
UBO_COMMIT = '7ec4565b320a19b19583ce03ab1a26f493dee52f'
PATCHES = ('patch-performance.diff', 'patch-build-locations.diff', 'patch-security-lock.diff')
LABEL = 'UNOFFICIAL COMMUNITY BUILD — NOT AFFILIATED WITH OR ENDORSED BY WINDSCRIBE.'


def patch_digest() -> str:
    # Any release-control change may justify a rebuild, not just patch changes.
    files = [p for p in ROOT.rglob('*') if p.is_file() and not p.is_symlink()
             and '__pycache__' not in p.parts and not p.name.endswith(('.pyc', '.pyo'))]
    workflow = ROOT.parent / '.github/workflows/community-patch-release.yml'
    if not workflow.is_file():
        raise ValueError('release workflow is missing')
    files.append(workflow)
    h = hashlib.sha256()
    for file in sorted(files, key=lambda x: x.relative_to(ROOT.parent).as_posix()):
        name = file.relative_to(ROOT.parent).as_posix()
        h.update(name.encode() + b'\0' + file.read_bytes() + b'\0')
    return h.hexdigest()



def is_sha(value: str) -> bool:
    return bool(re.fullmatch(r'[0-9a-f]{40}', value))


def version_ok(value: str) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+){1,3}', value):
        return False
    return all(0 <= int(part) <= 65535 and (part == '0' or not part.startswith('0')) for part in value.split('.'))


def write_outputs(path: str, values: dict[str, str]) -> None:
    with open(path, 'a', encoding='utf8') as f:
        for key, value in values.items():
            if not re.fullmatch(r'[a-z_]+', key) or '\n' in value or '\r' in value:
                raise ValueError('unsafe workflow output')
            f.write(f'{key}={value}\n')


def relevant_fingerprint(tree: list[dict]) -> str:
    """Hash all source entries except documentation. Includes mode and submodule IDs."""
    rows = []
    for item in tree:
        p = item['path']
        if item['type'] == 'tree' or p.startswith('docs/') or p.lower().endswith(('.md', '.rst')):
            continue
        rows.append((p, item['mode'], item['type'], item['sha']))
    if not rows:
        raise ValueError('empty upstream source tree')
    return hashlib.sha256(json.dumps(sorted(rows), separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
