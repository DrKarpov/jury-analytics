"""Append independent endpoint-swap observations for exact current trace revisions."""
import argparse
import json
import time
from collections import Counter
from pathlib import Path
from functools import partial
from urllib.error import HTTPError

from audit import tonapi_swaps
from incremental import ordered
from discrepancy import category
from indexer import digest, publish
from provider import tonapi_request
from recovery import primary, read

RETRY_AFTER = 3600
SCOPE = 'Endpoint swap multiset agreement on current primary-discovered trace revisions'


def revisions(history):
    return {
        trace: digest({
            'trace': trace,
            'transfers': ordered(rows),
            'actions_digest': history.actions_digests.get(trace),
            'events': sorted(history.events.get(trace, []), key=lambda event: event['id']),
            'unresolved': history.unresolved.get(trace),
        })
        for trace, rows in history.traces.items()
    }


def batch_digest(batch):
    return digest({key: value for key, value in batch.items() if key != 'digest'})


def replay(store, history):
    latest = {}
    head = None
    seq = 0
    for path in sorted((store / 'current-audit' / 'v1').glob('batch-*.json')):
        batch = read(path)
        if batch.get('digest') != batch_digest(batch):
            raise ValueError('current audit batch digest mismatch')
        if (batch['sequence'] != seq or path.name != f'batch-{seq:08d}.json'
                or batch['previous_digest'] != head or batch['history_head'] not in history.heads
                or not 1 <= len(batch['rows']) <= 300):
            raise ValueError('current audit checkpoint discontinuity')
        seen = set()
        for row in batch['rows']:
            key = row['trace'], row['revision']
            if key in seen or row['status'] not in ('match', 'mismatch', 'unavailable'):
                raise ValueError('invalid current audit row')
            if row['status'] != 'unavailable':
                equal = row['primary_swaps'] == row['alternate_swaps']
                if equal != (row['status'] == 'match'):
                    raise ValueError('current audit observation contradicts swap evidence')
            prior = latest.get(key)
            if prior and (prior['status'] != 'unavailable'
                          or row['observed_at'] < prior['observed_at'] + RETRY_AFTER):
                raise ValueError('invalid current audit retry')
            seen.add(key)
            latest[key] = row
        head = batch['digest']
        seq += 1
    return latest, seq, head


def summarize(current, latest, grouped):
    counts = Counter()
    mismatch_reasons = Counter()
    matched_with_swaps = 0
    last_observed_at = None
    for trace, version in current.items():
        row = latest.get((trace, version))
        counts[row['status'] if row else 'pending'] += 1
        if row:
            if row['status'] != 'unavailable' and row['primary_swaps'] != encode(grouped[trace]):
                raise ValueError('current audit primary evidence differs from replayed trace')
            if row['status'] == 'mismatch':
                mismatch_reasons[category(row)] += 1
            if row['status'] == 'match' and row['primary_swaps']:
                matched_with_swaps += 1
            last_observed_at = max(last_observed_at or 0, row['observed_at'])
    return {
        'scope': SCOPE,
        'total_traces': len(current),
        'matched': counts['match'],
        'matched_with_swaps': matched_with_swaps,
        'mismatch': counts['mismatch'],
        'mismatch_reasons': dict(sorted(mismatch_reasons.items())),
        'unavailable': counts['unavailable'],
        'pending': counts['pending'],
        'last_observed_at': last_observed_at,
    }


def primary_swaps(history):
    return primary({
        'transfers': history.transfers.values(),
        'events': [event for events in history.events.values() for event in events],
    })


def coverage(store, history):
    latest, _, _ = replay(store, history)
    return summarize(revisions(history), latest, primary_swaps(history))


def select(history, current, latest, limit, now, retry_slot):
    oldest = sorted(current, key=lambda trace: (
        max(row['time'] for row in history.traces[trace]), trace
    ))
    pending = [trace for trace in oldest if (trace, current[trace]) not in latest]
    retries = []
    for trace in oldest:
        row = latest.get((trace, current[trace]))
        if row and row['status'] == 'unavailable' and now >= row['observed_at'] + RETRY_AFTER:
            retries.append((row['observed_at'], trace))
    retries = [trace for _, trace in sorted(retries)]
    if limit == 1 and retry_slot and retries:
        return retries[:1]
    retry_count = min(len(retries), max(limit // 5, int(limit > 1)))
    fresh_count = limit - retry_count
    recent_count = fresh_count // 2
    recent = list(reversed(pending[-recent_count:])) if recent_count else []
    older = pending[:max(0, min(len(pending) - len(recent), fresh_count - len(recent)))]
    batch = recent + older
    return batch + retries[:limit - len(batch)]


def encode(swaps):
    return [[list(swap), count] for swap, count in sorted(swaps.items())]


def audit(store, history, fetch=tonapi_request, limit=100, seconds=180, now=None):
    if not 1 <= limit <= 300 or seconds <= 0:
        raise ValueError('invalid current audit budget')
    now = int(time.time()) if now is None else now
    latest, seq, head = replay(store, history)
    current = revisions(history)
    grouped = primary_swaps(history)
    summarize(current, latest, grouped)
    rows = []
    stop_reason = None
    deadline = time.monotonic() + seconds
    if fetch is tonapi_request:
        fetch = partial(tonapi_request, deadline=deadline)
    for trace in select(history, current, latest, limit, now, seq % 2 == 1):
        if time.monotonic() >= deadline:
            stop_reason = 'deadline'
            break
        row = {'trace': trace, 'revision': current[trace], 'observed_at': now}
        try:
            actual = tonapi_swaps(fetch('events/' + trace, {}), trace)
        except HTTPError as error:
            if error.code != 404:
                stop_reason = f'HTTP{error.code}'
                break
            row.update(status='unavailable', reason='HTTP404')
        except OSError as error:
            stop_reason = type(error).__name__
            break
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            row.update(status='unavailable', reason=type(error).__name__)
        else:
            want = grouped[trace]
            row.update(status='match' if actual == want else 'mismatch',
                       primary_swaps=encode(want), alternate_swaps=encode(actual))
        rows.append(row)
    if rows:
        batch = {'sequence': seq, 'previous_digest': head, 'history_head': history.head, 'rows': rows}
        batch['digest'] = batch_digest(batch)
        folder = store / 'current-audit' / 'v1'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'batch-{seq:08d}.json'
        if path.exists():
            raise ValueError('current audit checkpoint already exists')
        publish(batch, path)
        latest, _, _ = replay(store, history)
    return {**summarize(current, latest, grouped), 'requests_recorded': len(rows), 'stop_reason': stop_reason}


def main():
    from persistent_preview import corrected_history

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    history, _, _, _ = corrected_history(args.store)
    report = audit(args.store, history, limit=args.limit, seconds=args.seconds)
    print(json.dumps(report), flush=True)
    if report['stop_reason'] and report['stop_reason'] != 'deadline' and not report['requests_recorded']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
