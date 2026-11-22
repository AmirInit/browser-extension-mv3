from datetime import datetime, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import relevant_fingerprint, version_ok
from detect import choose, select_official_candidate
from locations import check_fresh, sanitize
from artifacts import safe_name, source_file, validate_zip
from prepare import finish_equivalent


class DetectionTests(unittest.TestCase):
    def test_version_and_injection_validation(self):
        for v in ('4.3.1', '1.2', '1.2.3.4'):
            self.assertTrue(version_ok(v))
        for v in ('v4.3.1', '1.2;touch bad', '1.02', '65536.1', '1.2.3.4.5'):
            self.assertFalse(version_ok(v))

    def test_docs_changes_do_not_force_build_but_code_changes_do(self):
        tree = [{'path': 'src/app.ts', 'mode': '100644', 'type': 'blob', 'sha': 'a'},
                {'path': 'README.md', 'mode': '100644', 'type': 'blob', 'sha': 'b'}]
        baseline = relevant_fingerprint(tree)
        tree[1]['sha'] = 'c'
        self.assertEqual(baseline, relevant_fingerprint(tree))
        tree[0]['sha'] = 'd'
        self.assertNotEqual(baseline, relevant_fingerprint(tree))
        tree.append({'path': 'src/content.md', 'mode': '100644', 'type': 'blob', 'sha': 'e'})
        self.assertNotEqual(baseline, relevant_fingerprint(tree))

    def test_numeric_release_tag_must_match_and_descend_from_public(self):
        public, tagged = 'a' * 40, 'b' * 40
        tags = [{'name': 'v4.3.2', 'commit': {'sha': tagged}},
                {'name': 'v4.4.0-beta', 'commit': {'sha': 'c' * 40}}]
        with patch('detect.file_json', return_value={'version': '4.3.2'}), patch('detect.api', return_value={'status': 'ahead'}):
            self.assertEqual(select_official_candidate(public, '4.3.1', tags), (tagged, '4.3.2', 'v4.3.2'))
        with patch('detect.file_json', return_value={'version': '4.3.2'}), patch('detect.api', return_value={'status': 'diverged'}):
            with self.assertRaises(ValueError): select_official_candidate(public, '4.3.1', tags)
        with patch('detect.file_json', return_value={'version': '4.3.1'}):
            with self.assertRaises(ValueError): select_official_candidate(public, '4.3.1', tags)
        with self.assertRaises(ValueError):
            select_official_candidate(public, '4.3.1', [{'name': 'v4.4.0', 'commit': {'sha': public}}])

    def test_completed_release_is_idempotent_and_changes_increment_revision(self):
        sha = 'a' * 40
        meta = {'version': '4.3.1', 'upstream_sha': sha, 'source_fingerprint': 'old', 'patch_digest': 'patch'}
        assets = [{'name': n, 'size': 1} for n in ('windscribe-community.zip', 'SHA256SUMS', 'CHANGELOG.md', 'BUILD-INFO.json')]
        release = {'tag_name': 'v4.3.1-wsfix.2', 'draft': False, 'body': '<!-- WSFIX-METADATA ' + json.dumps(meta) + ' -->', 'assets': assets, 'html_url': 'https://example.test/release'}
        result = choose([release], [], '4.3.1', sha, 'old', 'patch')
        self.assertEqual(result['should_build'], 'false')
        self.assertEqual(result['previous_sha'], sha)
        self.assertEqual(choose([release], [], '4.3.1', sha, 'new', 'patch')['tag'], 'v4.3.1-wsfix.3')
        self.assertEqual(choose([release], [], '4.3.1', sha, 'old', 'patch', True)['should_build'], 'true')
        release['draft'] = True
        self.assertEqual(choose([release], [], '4.3.1', sha, 'old', 'patch')['should_build'], 'true')
        self.assertEqual(choose([], ['v4.3.1-wsfix.4'], '4.3.1', sha, 'new', 'patch')['tag'], 'v4.3.1-wsfix.5')


class LocationTests(unittest.TestCase):
    def test_freshness_rejects_missing_and_stale_headers(self):
        now = time.time()
        date = format_datetime(datetime.fromtimestamp(now, timezone.utc), usegmt=True)
        old = format_datetime(datetime.fromtimestamp(now - 90000, timezone.utc), usegmt=True)
        check_fresh({'Date': date, 'Last-Modified': date, 'Age': '3'}, now)
        with self.assertRaises(ValueError): check_fresh({'Date': date, 'Last-Modified': old}, now)
        with self.assertRaises(ValueError): check_fresh({'Date': date}, now)
        with self.assertRaises(ValueError): check_fresh({'Date': date, 'Last-Modified': date, 'Age': '999999'}, now)

    def test_only_valid_public_warp_fields_survive(self):
        source = {'data': [{'id': 1, 'country_code': 'US', 'tz': 'America/New_York', 'token': 'discard',
                            'groups': [{'id': 9, 'gps': '40,-74', 'password': 'discard'}]}]}
        result = sanitize(source)
        self.assertNotIn('token', result['data'][0])
        self.assertNotIn('password', result['data'][0]['groups'][0])
        for change in ('tz', 'gps', 'id'):
            bad = json.loads(json.dumps(source))
            if change == 'tz': bad['data'][0]['tz'] = 'America/X;evil'
            if change == 'gps': bad['data'][0]['groups'][0]['gps'] = '91,0'
            if change == 'id': bad['data'][0]['id'] = -1
            with self.assertRaises(ValueError): sanitize(bad)


class EquivalentIntegrationTests(unittest.TestCase):
    def test_equivalent_dependency_gets_narrow_location_loader(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            (source / 'scripts').mkdir()
            (source / '.community-ci').mkdir()
            (source / '.community-ci/mode').write_text('equivalent-probe\n')
            original = (repo / 'scripts/build.js').read_text()
            (source / 'scripts/build.js').write_text(original)
            finish_equivalent(source)
            updated = (source / 'scripts/build.js').read_text()
            self.assertIn('process.env.BUILD_LOCATIONS_FILE', updated)
            self.assertIn('await getLocations(await login())', updated)
            self.assertTrue((source / 'scripts/loadBuildLocations.js').is_file())
            self.assertTrue((source / 'tests/unit/buildLocations.community.test.cjs').is_file())
            self.assertEqual((source / '.community-ci/mode').read_text().strip(), 'equivalent-probed')
            with self.assertRaises(ValueError): finish_equivalent(source)

    def test_changed_build_script_fails_without_injecting_loader(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            (source / 'scripts').mkdir()
            (source / '.community-ci').mkdir()
            (source / '.community-ci/mode').write_text('equivalent-probe\n')
            (source / 'scripts/build.js').write_text('// changed upstream API\n')
            with self.assertRaises(ValueError): finish_equivalent(source)
            self.assertFalse((source / 'scripts/loadBuildLocations.js').exists())


class ArtifactTests(unittest.TestCase):
    def test_path_traversal_and_ambiguous_paths_rejected(self):
        for path in ('../a', '/etc/passwd', 'a/../b', 'a//b', 'a/./b', 'C:/x', 'a\\b'):
            self.assertFalse(safe_name(path), path)
        self.assertTrue(safe_name('rulesets/main/easylist.json'))
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            (source / 'redirect').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError): source_file(source, 'redirect')
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'bad.zip'
            with zipfile.ZipFile(file, 'w') as z:
                z.writestr('../escape', 'x')
            with self.assertRaises(ValueError): validate_zip(file, '4.3.1')

    def test_incomplete_or_critical_audit_blocks(self):
        script = Path(__file__).resolve().parents[1] / 'audit.py'
        with tempfile.TemporaryDirectory() as root:
            data, out = Path(root) / 'audit', Path(root) / 'summary'
            data.write_text(json.dumps({'type': 'auditSummary', 'data': {'vulnerabilities': {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 1}}}) + '\n')
            self.assertNotEqual(subprocess.run([sys.executable, str(script), str(data), str(out)], capture_output=True).returncode, 0)
            data.write_text(json.dumps({'type': 'error', 'data': 'network failed'}) + '\n')
            self.assertNotEqual(subprocess.run([sys.executable, str(script), str(data), str(out)], capture_output=True).returncode, 0)
            data.write_text(json.dumps({'type': 'auditSummary', 'data': {'vulnerabilities': {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0}}}) + '\n')
            self.assertEqual(subprocess.run([sys.executable, str(script), str(data), str(out)], capture_output=True).returncode, 0)


if __name__ == '__main__': unittest.main()
