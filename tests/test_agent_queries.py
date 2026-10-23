"""Machine-consumer regression scenarios across CLI, Skill and HTTP."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from clash_verge_monitor.agent_api import query_response
from test_skill_scripts import seed_database
import unittest

from clash_verge_monitor.__main__ import main
from clash_verge_monitor.store import LedgerStore
from test_skill_scripts import AUDITOR, ROOT, run_json


class AgentQueriesTests(unittest.TestCase):
    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(args)
            except SystemExit as exc:
                code = exc.code
        self.assertEqual(err.getvalue(), '')
        return code, json.loads(out.getvalue())

    def test_missing_database_and_invalid_arguments_are_stdout_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'db.sqlite')
            for command in ['explore', 'audit']:
                args = [command, '--database', db]
                if command == 'explore':
                    args += ['--start', '2026-08-22', '--end', '2026-08-22']
                code, doc = self.cli(args)
                self.assertEqual(code, 3)
                self.assertEqual(doc['errors'][0]['code'], 'database_missing')
            self.assertFalse(Path(db).exists())
            code, doc = self.cli(['explore', '--by', 'invalid'])
            self.assertEqual(code, 2)
            self.assertEqual(doc['errors'][0]['code'], 'invalid_arguments')

    def test_empty_window_is_unobserved_and_carries_query_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'db.sqlite')
            LedgerStore(db)
            code, doc = self.cli(['explore', '--database', db, '--start', '2026-08-22',
                                  '--end', '2026-08-22', '--process', 'App', '--route', 'proxy'])
            self.assertEqual(code, 0)
            self.assertEqual(doc['data']['data_status'], 'unobserved')
            self.assertIn('sampling_coverage_incomplete', [w['code'] for w in doc['warnings']])
            self.assertEqual(doc['query']['process'], 'App')
            self.assertEqual(doc['query']['route'], 'proxy')
            self.assertEqual(doc['provenance']['database_schema_version'], 2)
            self.assertTrue(doc['provenance']['dataset_id'])
            self.assertIn('latest_sample', doc['provenance'])
            self.assertIn('version', doc['runtime'])

    def test_wrapper_discovers_and_queries_source_even_with_old_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'db.sqlite'
            LedgerStore(db)
            (root / 'install.json').write_text(json.dumps({'version':'0.3.0','runtime_python':'/missing/python'}))
            args = ['--app-root', root, '--runtime-source', ROOT, '--database', db]
            p, doc = run_json(AUDITOR, 'capabilities', *args, cwd=root)
            self.assertEqual(p.returncode, 0, doc)
            self.assertIn('explore', doc['data']['commands'])
            self.assertEqual(doc['runtime_selection']['mode'], 'source')
            p, doc = run_json(AUDITOR, 'explore', *args, '--start', '2026-08-22', '--end', '2026-08-22', cwd=root)
            self.assertEqual(p.returncode, 0, doc)
            self.assertEqual(doc['data']['data_status'], 'unobserved')

    def test_invalid_range_has_data_error_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'db.sqlite')
            LedgerStore(db)
            code, doc = self.cli(['explore', '--database', db, '--start', '2026-08-23', '--end', '2026-08-22'])
            self.assertEqual(code, 4)
            self.assertEqual(doc['errors'][0]['code'], 'invalid_request')

    def test_zero_requires_coverage_and_retained_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'db.sqlite'
            store = LedgerStore(db)
            store.record_sample(datetime(2026, 8, 22, 12, tzinfo=timezone.utc), [], interval=60, covered=60)
            result = query_response('explore', store, start='2026-08-22', end='2026-08-22')
            self.assertEqual(result['data']['data_status'], 'indeterminate_zero')
            # Model a fully covered closed day without spending a day polling.
            with contextlib.closing(store.connect()) as conn:
                with conn:
                    conn.execute('UPDATE sample_minutes SET covered_seconds=86400')
            result = query_response('explore', store, start='2026-08-22', end='2026-08-22')
            self.assertEqual(result['data']['data_status'], 'observed_zero')
            self.assertEqual(result['warnings'], [])
            seed_database(db)
            result = query_response('explore', store, start='2026-07-19', end='2026-07-19')
            self.assertEqual(result['data']['data_status'], 'observed_nonzero')
            self.assertEqual(result['data']['coverage']['status'], 'unknown')

    def test_legacy_runtime_is_reported_without_silent_source_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # A fake old interpreter is deterministic and never invokes the installed service.
            python = root / 'old-python'
            python.write_text('#!/bin/sh\necho "old runtime: unsupported command" >&2\nexit 2\n')
            python.chmod(0o700)
            (root / 'install.json').write_text(json.dumps({'runtime_python': str(python), 'version': '0.3.0'}))
            completed, doc = run_json(AUDITOR, 'capabilities', '--app-root', root)
            self.assertEqual(completed.returncode, 3)
            self.assertEqual(doc['errors'][0]['code'], 'runtime_upgrade_required')
            self.assertTrue((root / 'install.json').exists())

    def test_wrapper_argument_error_is_json(self):
        completed, doc = run_json(AUDITOR, 'explore', '--limit', 'bad')
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, '')
        self.assertEqual(doc['errors'][0]['code'], 'invalid_arguments')

    def test_documented_contract_tracks_runtime_policy_and_enums(self):
        import re
        from clash_verge_monitor.agent_api import capabilities
        from clash_verge_monitor.audit import POLICY_VERSION
        doc = (ROOT / '.agents/skills/clash-verge-monitor/references/output-contract.md').read_text()
        sample = json.loads(re.search(r'```json\n(.*?)\n```', doc, re.S).group(1))
        runtime = capabilities()
        self.assertEqual(sample['schema_version'], runtime['schema_version'])
        self.assertEqual(sample['runtime'], runtime['runtime'])
        self.assertEqual(int(re.search(r'Policy version (\d+)', doc).group(1)), POLICY_VERSION)
        policy_doc = (ROOT / '.agents/skills/clash-verge-monitor/references/anomaly-policy.md').read_text()
        self.assertEqual(int(re.search(r'policy version (\d+)', policy_doc).group(1)), POLICY_VERSION)
        for value in runtime['data']['data_states'] + runtime['data']['coverage_states']:
            self.assertIn('`' + value + '`', doc)
