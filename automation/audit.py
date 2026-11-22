#!/usr/bin/env python3
"""Require a complete Yarn audit with no criticals; retain high advisory IDs."""
import json
import re
import sys
from pathlib import Path

summary = None
errors = []
critical = set()
high = set()
for line in Path(sys.argv[1]).read_text().splitlines():
    try:
        row = json.loads(line)
    except ValueError:
        continue
    if row.get('type') == 'auditSummary':
        summary = row.get('data', {}).get('vulnerabilities')
    if row.get('type') == 'error':
        errors.append(str(row.get('data', 'audit error'))[:200])
    if row.get('type') == 'auditAdvisory':
        advisory = row['data']['advisory']
        ident = advisory.get('github_advisory_id') or ('npm-' + str(advisory.get('id', '')))
        package = advisory.get('module_name', '')
        if advisory.get('severity') == 'critical':
            critical.add(ident)
        if advisory.get('severity') == 'high':
            if not re.fullmatch(r'(?:@[a-zA-Z0-9._~-]+/)?[a-zA-Z0-9._~-]+', package) or not re.fullmatch(r'GHSA-[A-Za-z0-9-]+|npm-[0-9]+', ident):
                raise SystemExit('Unexpected high-severity advisory metadata')
            high.add((package, ident))
expected = {'info', 'low', 'moderate', 'high', 'critical'}
if not isinstance(summary, dict) or set(summary) != expected or any(type(v) is not int or v < 0 for v in summary.values()) or errors:
    raise SystemExit('Security audit incomplete; refusing release: ' + '; '.join(errors))
print('Dependency audit findings:', json.dumps(summary, sort_keys=True), '; unique high advisories:', len(high))
if summary['critical'] != 0 or critical:
    raise SystemExit('Critical advisories block release: ' + ', '.join(sorted(critical)))
if summary['high'] and not high:
    raise SystemExit('Audit omitted high advisory details')
result = {'counts': summary, 'high_advisories': [{'package': p, 'advisory': a} for p, a in sorted(high)]}
Path(sys.argv[2]).write_text(json.dumps(result, sort_keys=True) + '\n')
