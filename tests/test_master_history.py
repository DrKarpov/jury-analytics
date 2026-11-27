import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from test_indexer import H
from indexer import TOKEN
from master_history import scan, verify_deliveries


def transaction(i, previous):
    return {
        'account': TOKEN, 'hash': H(f'tx-{i}'), 'lt': i,
        'now': i + 100, 'orig_status': 'active' if previous else 'nonexist',
        'end_status': 'active', 'prev_trans_lt': previous,
        'prev_trans_hash': H(f'tx-{previous}'),
        'description': {'aborted': False}, 'out_msgs': [], 'in_msg': {},
    }


def query(rows):
    def center(endpoint, params):
        items = [row for row in rows if params.get('start_lt', 0) <= row['lt'] <= params.get('end_lt', 99)]
        return {'transactions': sorted(items, key=lambda row: row['lt'], reverse=params['sort']=='desc')[:params['limit']]}

    def alternate(endpoint, params):
        items = [row for row in rows if params.get('after_lt', 0) < row['lt'] < params.get('before_lt', 100)]
        items = sorted(items, key=lambda row: row['lt'], reverse=params['sort_order']=='desc')
        return {'transactions': [
            {**row, 'account': {'address': TOKEN}, 'utime': row['now'], 'aborted': False}
            for row in items[:params['limit']]
        ]}
    return center, alternate


class MasterHistoryTests(unittest.TestCase):
    def test_paginates_to_pinned_tip(self):
        rows = [transaction(1, 0), transaction(4, 1), transaction(10, 4)]
        master = scan(*query(rows), cutoff=120, size=1)
        self.assertEqual([row['lt'] for row in master], [1, 4, 10])

    def test_rejects_omitted_predecessor_even_when_providers_agree(self):
        rows = [transaction(1, 0), transaction(10, 4)]
        with self.assertRaisesRegex(ValueError, 'predecessor'):
            scan(*query(rows), cutoff=120)

    def test_rejects_unmatched_provider_tip(self):
        first = transaction(1, 0)
        center, _ = query([first, transaction(4, 1)])
        _, alternate = query([first])
        with self.assertRaisesRegex(ValueError, 'tip'):
            scan(center, alternate, cutoff=120)

    def test_receipts_resume_without_repeating_completed_deliveries(self):
        messages = [{'message': H(f'msg-{i}'), 'wallet': TOKEN, 'amount_raw': str(i)}
                    for i in (1, 2)]

        def proof(center, alternate, message):
            return {**message, 'recipient_tx': H('receipt-'+message['message']),
                    'recipient_lt': '100', 'recipient_at': 200}

        with tempfile.TemporaryDirectory() as directory, patch('master_history.receipt', side_effect=proof) as check:
            folder = Path(directory)
            first = verify_deliveries(None, None, messages, folder, 1)
            second = verify_deliveries(None, None, messages, folder, 1)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 2)
            self.assertEqual(check.call_count, 2)
