"""Compare the entire JURY master account chain at a common provider tip."""
import argparse
import base64
from collections import Counter
from functools import partial
from pathlib import Path
import time

from incremental import load_history
from indexer import MASTER, TOKEN, digest, hash_id, integer, publish
from provider import address, request, tonapi_request
from recovery import read


def identity(tx, alternate):
    account = tx['account']['address'] if alternate else tx['account']
    if address(account) != TOKEN:
        raise ValueError('foreign master transaction')
    previous_lt = integer(tx.get('prev_trans_lt', 0))
    previous_hash = hash_id(tx['prev_trans_hash']) if previous_lt else None
    aborted = tx['aborted'] if alternate else tx['description']['aborted']
    if type(aborted) is not bool:
        raise ValueError('missing master abort flag')
    return {
        'tx': hash_id(tx['hash']),
        'lt': integer(tx['lt']),
        'time': integer(tx['utime' if alternate else 'now']),
        'previous_lt': previous_lt,
        'previous_tx': previous_hash,
        'before': tx['orig_status'],
        'after': tx['end_status'],
        'aborted': aborted,
    }


def outbound(tx, alternate):
    results = {}
    for msg in tx['out_msgs']:
        if msg.get('op_code' if alternate else 'opcode') != '0x178d4519':
            continue
        source, destination = msg['source'], msg['destination']
        if alternate:
            source, destination = source['address'], destination['address']
            amount = msg['decoded_body']['amount']
        else:
            amount = msg['message_content']['decoded']['amount']['value']
        key = hash_id(msg['hash'])
        if address(source) != TOKEN or key in results:
            raise ValueError('invalid outbound JURY message')
        results[key] = {'message': key, 'wallet': address(destination), 'amount_raw': str(integer(amount))}
    return results


def scan(center, alternate, cutoff=None, size=100):
    endpoint = f'blockchain/accounts/{TOKEN}/transactions'
    a_params = {'limit':1, 'sort_order':'desc'}
    c_params = {'account':MASTER, 'limit':1, 'sort':'desc'}
    if cutoff is not None:
        c_params['end_utime'] = cutoff
    center_tip = identity(center('transactions', c_params)['transactions'][0], False)
    # Query TonAPI at the exact LT selected by Toncenter. For a live scan, also
    # require that its newest observed transaction is the same tip.
    if cutoff is not None:
        a_params['before_lt'] = center_tip['lt'] + 1
    alternate_tip = identity(alternate(endpoint, a_params)['transactions'][0], True)
    if center_tip != alternate_tip:
        raise ValueError('indexers disagree on the master tip')

    rows = []
    previous_lt, previous_tx = 0, None
    while previous_lt < center_tip['lt']:
        center_page = center('transactions', {
            'account': MASTER, 'sort': 'asc', 'limit': size,
            'start_lt': previous_lt+1, 'end_lt': center_tip['lt'],
        })['transactions']
        params = {'sort_order':'asc','limit':size,'before_lt':center_tip['lt']+1}
        if previous_lt:
            params['after_lt'] = previous_lt
        alternate_page = alternate(endpoint, params)['transactions']
        if not center_page or len(center_page) != len(alternate_page) or len(center_page)>size:
            raise ValueError('missing or unequal master transaction pages')
        for primary_tx, alternate_tx in zip(center_page, alternate_page, strict=True):
            row = identity(primary_tx, False)
            if (row != identity(alternate_tx, True)
                    or (row['previous_lt'],row['previous_tx']) != (previous_lt,previous_tx)
                    or not previous_lt < row['lt'] <= center_tip['lt']):
                raise ValueError('master predecessor chain mismatch')
            if not rows and (row['before'] != 'nonexist' or row['after'] != 'active' or row['aborted']):
                raise ValueError('first master transaction does not establish deployment')
            deliveries = outbound(primary_tx, False)
            if deliveries != outbound(alternate_tx, True):
                raise ValueError('indexers disagree on master outbound message')
            row['outbound'] = list(deliveries.values())
            incoming = primary_tx['in_msg']
            row['in_opcode'] = incoming.get('opcode') if incoming else None
            rows.append(row)
            previous_lt, previous_tx = row['lt'], row['tx']
    return rows


def receipt(center, alternate, message):
    key = message['message']
    encoded = base64.b64encode(bytes.fromhex(key)).decode('ascii')
    matches = center('transactionsByMessage', {
        'msg_hash': encoded, 'direction': 'in', 'limit': 2
    })['transactions']
    if len(matches) != 1:
        raise ValueError('recipient transaction lacks a unique match')
    primary = matches[0]
    other = alternate(f'blockchain/messages/{key}/transaction', {})
    pm, am = primary['in_msg'], other['in_msg']
    tx = hash_id(primary['hash'])
    if (tx != hash_id(other['hash']) or integer(primary['lt']) != integer(other['lt'])
            or integer(primary['now']) != integer(other['utime'])
            or primary['description']['aborted'] is not False
            or other['aborted'] is not False or other['success'] is not True
            or address(primary['account']) != message['wallet']
            or address(other['account']['address']) != message['wallet']
            or hash_id(pm['hash']) != key or hash_id(am['hash']) != key
            or pm['bounced'] is not False or am['bounced'] is not False
            or pm.get('opcode') != '0x178d4519' or am.get('op_code') != '0x178d4519'
            or address(pm['source']) != TOKEN or address(am['source']['address']) != TOKEN
            or integer(pm['message_content']['decoded']['amount']['value']) != integer(message['amount_raw'])
            or integer(am['decoded_body']['amount']) != integer(message['amount_raw'])):
        raise ValueError('recipient delivery does not match emitted message')
    return {**message, 'recipient_tx': tx, 'recipient_lt': primary['lt'], 'recipient_at': primary['now']}


def verify_deliveries(center, alternate, messages, folder, limit):
    """Persist each successful receipt independently so a retry skips completed work."""
    if not 1 <= limit <= 100:
        raise ValueError('receipt limit outside 1–100')
    folder.mkdir(parents=True, exist_ok=True)
    verified = []
    attempts = 0
    for message in messages:
        record_path = folder / (message['message'] + '.json')
        if record_path.exists():
            record = read(record_path)
            fields = {key:value for key,value in record.items() if key != 'digest'}
            if (digest(fields) != record.get('digest')
                    or any(fields.get(key) != value for key,value in message.items())
                    or hash_id(fields['recipient_tx']) != fields['recipient_tx']
                    or integer(fields['recipient_lt']) <= 0 or integer(fields['recipient_at']) <= 0):
                raise ValueError('invalid saved receipt')
        elif attempts < limit:
            attempts += 1
            fields = receipt(center, alternate, message)
            publish({**fields, 'digest': digest(fields)}, record_path)
        else:
            continue
        verified.append(fields)
    return verified


def summarize(rows, history):
    first_transfer = min(row['time'] for row in history.transfers.values())
    discovered = set(history.transfers)
    by_opcode = Counter()
    for row in rows:
        if not row['aborted']:
            for message in row['outbound']:
                by_opcode[row['in_opcode'] or 'no_opcode'] += integer(message['amount_raw'])
    return {
        'deployment': rows[0],
        'master_tip': rows[-1],
        'master_transactions': len(rows),
        'master_outbound_messages': sum(len(row['outbound']) for row in rows if not row['aborted']),
        'outbound_amount_by_inbound_opcode_raw': {key:str(value) for key,value in sorted(by_opcode.items())},
        'preceding_first_discovered_transfer': sum(
            len(row['outbound']) for row in rows if not row['aborted'] and row['time'] < first_transfer
        ),
        'master_transactions_in_transfer_index': sum(row['tx'] in discovered for row in rows),
        'first_discovered_transfer_at': first_transfer,
        'history_cutoff': history.cutoff,
        'history_head': history.head,
        'scope': 'Master transactions and outbound Jetton messages. Recipient execution and wallet-history completeness are separate.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--receipts-dir', type=Path)
    parser.add_argument('--receipt-limit', type=int, default=20)
    args = parser.parse_args()
    history = load_history(args.store)
    deadline = time.monotonic()+240
    center = partial(request, deadline=deadline)
    alternate = partial(tonapi_request, deadline=deadline)
    rows = scan(center, alternate, history.cutoff)
    report = summarize(rows, history)
    successful_messages = [msg for row in rows if not row['aborted'] for msg in row['outbound']]
    early_ids = {
        msg['message'] for row in rows
        if not row['aborted'] and row['time'] < report['first_discovered_transfer_at']
        for msg in row['outbound']
    }
    if args.receipts_dir:
        deliveries = verify_deliveries(center, alternate, successful_messages, args.receipts_dir, args.receipt_limit)
    else:
        deliveries = [receipt(center, alternate, msg) for msg in successful_messages if msg['message'] in early_ids]
    early_deliveries = [row for row in deliveries if row['message'] in early_ids]
    report['verified_deliveries'] = len(deliveries)
    report['verified_deliveries_before_first_transfer'] = len(early_deliveries)
    bundle = {'report': report, 'transactions': rows, 'early_deliveries': early_deliveries}
    bundle['digest'] = digest(bundle)
    publish(bundle, args.out)
    print(report, flush=True)


if __name__ == '__main__':
    main()
