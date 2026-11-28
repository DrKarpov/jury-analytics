"""Check the identity and checksum of immutable negative repair evidence."""
from indexer import digest
from recovery import read


def checked_negative_attempt(path, seed_digest, trace, rule, audit_row):
    attempt = read(path)
    expected = {'rule': rule, 'seed_digest': seed_digest, 'trace': trace,
                'audit_digest': digest(audit_row), 'status': 'no_rule_match'}
    fields = {key: value for key, value in attempt.items() if key != 'digest'}
    # Historical payout records omit version; delivery records explicitly
    # write version 1. Validate exactly the written schema and its digest.
    if rule == 'exact_swap_transfer_delivery_v1':
        expected['version'] = 1
    if fields != expected or attempt.get('digest') != digest(fields):
        raise ValueError('invalid negative repair evidence')
