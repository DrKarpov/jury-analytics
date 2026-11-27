import tempfile
import unittest
from pathlib import Path

from test_incremental import seed
from incremental import History
from recovery import read
from indexer import publish
from current_audit import audit, coverage, batch_digest


class CurrentAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)
        self.history = History(seed())
        self.trace = next(iter(self.history.traces))

    @staticmethod
    def fetch(endpoint, params):
        return {'event_id': endpoint.split('/')[-1], 'in_progress': False, 'actions': []}

    def test_revision_change_invalidates_observation(self):
        self.assertEqual(audit(self.store, self.history, self.fetch, now=100)['mismatch'], 1)
        self.assertEqual(coverage(self.store, self.history)['pending'], 0)
        self.assertEqual(coverage(self.store, self.history)['mismatch_reasons'], {'alternate_missing': 1})
        self.history.traces[self.trace][0]['amount_raw'] = '3'
        self.assertEqual(coverage(self.store, self.history)['pending'], 1)
        self.assertEqual(coverage(self.store, self.history)['mismatch'], 0)
        self.assertEqual(audit(self.store, self.history, self.fetch, now=101)['mismatch'], 1)
        self.assertEqual(len(list((self.store / 'current-audit' / 'v1').glob('batch-*.json'))), 2)

    def test_unfinished_is_retried_after_cooldown(self):
        def unfinished(endpoint, params):
            return {**self.fetch(endpoint, params), 'in_progress': True}

        self.assertEqual(audit(self.store, self.history, unfinished, now=100)['unavailable'], 1)
        self.assertEqual(audit(self.store, self.history, self.fetch, now=101)['unavailable'], 1)
        self.assertEqual(audit(self.store, self.history, self.fetch, now=4000)['mismatch'], 1)

    def test_corrupt_batch_fails_replay(self):
        audit(self.store, self.history, self.fetch, now=100)
        path = next((self.store / 'current-audit' / 'v1').glob('batch-*.json'))
        batch = read(path)
        batch['rows'][0]['status'] = 'match'
        publish(batch, path)
        with self.assertRaisesRegex(ValueError, 'digest'):
            coverage(self.store, self.history)

    def test_replay_requires_primary_evidence_for_the_exact_revision(self):
        audit(self.store, self.history, self.fetch, now=100)
        path = next((self.store / 'current-audit' / 'v1').glob('batch-*.json'))
        batch = read(path)
        batch['rows'][0].update(status='match', primary_swaps=[], alternate_swaps=[])
        batch['digest'] = batch_digest(batch)
        publish(batch, path)
        with self.assertRaisesRegex(ValueError, 'primary evidence'):
            coverage(self.store, self.history)
