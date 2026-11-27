"""Independent comparison of discovered trace swaps, not a completeness proof."""
from collections import Counter, defaultdict
import time
from provider import address, request, tonapi_request, MASTER
from indexer import TOKEN, integer, hash_id, digest, paginated


def tonapi_swaps(event, expected_trace):
    if event.get('in_progress') is not False: raise ValueError('unfinished event')
    # getEvent accepts any transaction hash, but the response may use another event ID.
    # A mismatch is unverified rather than silently comparing unrelated events.
    if hash_id(event['event_id']) != expected_trace: raise ValueError('event identity mismatch')
    actions=event['actions']
    if not isinstance(actions,list): raise ValueError('invalid event actions')
    result=Counter()
    for a in actions:
        if not isinstance(a,dict) or not isinstance(a.get('type'),str) or not isinstance(a.get('status'),str):
            raise ValueError('invalid event action')
        if a['type']!='JettonSwap': continue
        if a['status']=='failed': continue
        if a['status']!='ok': raise ValueError('invalid swap status')
        d=a['JettonSwap']
        ai=address(d['jetton_master_in']['address']) if d.get('jetton_master_in') else 'GRAM'
        ao=address(d['jetton_master_out']['address']) if d.get('jetton_master_out') else 'GRAM'
        if (ai==TOKEN)==(ao==TOKEN): continue
        def quantity(side, asset):
            if asset!='GRAM': return integer(d['amount_'+side])
            vals=[integer(d[k]) for k in ('gram_'+side,'ton_'+side) if d.get(k) is not None]
            if not vals or len(set(vals))!=1: raise ValueError('missing/conflicting native amount')
            return vals[0]
        ni,no=quantity('in',ai),quantity('out',ao)
        if not ni or not no: raise ValueError('zero swap')
        side='buy' if ao==TOKEN else 'sell'
        result[(side,address(d['user_wallet']['address']),no if side=='buy' else ni,ai if side=='buy' else ao,ni if side=='buy' else no)]+=1
    return result


def compare(snapshot, fetch=tonapi_request, max_traces=None):
    grouped=defaultdict(Counter)
    for e in snapshot['events']:
        if e['kind'] in ('buy','sell'):
            grouped[e['trace']][(e['kind'],e['wallet'],integer(e['amount_raw']),e['quote_asset'],integer(e['quote_raw']))]+=1
    # Also examine traces with zero primary swaps to detect missed trades.
    for u in snapshot['unresolved']: grouped[u['trace']]
    for e in snapshot['events']: grouped[e['trace']]
    ids=sorted(grouped); selected=ids if max_traces is None else ids[:max_traces]
    matched=0; differences=[]; unavailable=[]
    for trace in selected:
        try:
            second=tonapi_swaps(fetch('events/'+trace,{}),trace)
            if second==grouped[trace]: matched+=1
            else: differences.append({'trace':trace,'primary':sum(grouped[trace].values()),'alternate':sum(second.values())})
        except Exception as e:
            unavailable.append({'trace':trace,'error':type(e).__name__})
            # Avoid thousands of requests if transport is unavailable.
            if len(unavailable)>=3 and not matched and not differences: break
    status='mismatch' if differences else 'unavailable' if unavailable else 'partial' if len(selected)<len(ids) or not ids else 'discovered_trace_swaps_match'
    return {'scope':'swaps in primary-discovered traces; not global completeness','status':status,'checked_at':int(time.time()),'snapshot_digest':snapshot['digest'],'total_traces':len(ids),'checked':matched+len(differences)+len(unavailable),'matched':matched,'differences':differences,'unavailable':unavailable}


def holders_center(fetch):
    rows={}
    for r in paginated(fetch,'jetton/wallets','jetton_wallets',{'jetton_address':MASTER,'exclude_zero_balance':'true','sort':'desc'}):
        if address(r['jetton'])!=TOKEN: raise ValueError('foreign token')
        wallet=address(r['address']); owner=address(r['owner']); balance=integer(r['balance'])
        if not balance or wallet in rows: raise ValueError('zero or duplicate wallet')
        rows[wallet]=(owner,balance)
    return rows


def holders_api(fetch, size=1000):
    rows={}; cursor=None; total=None; count=0
    while True:
        p={'limit':size,'sort_by':'address'}
        if cursor: p['last_account_id']=cursor
        data=fetch('jettons/'+TOKEN+'/holders',p); page=data['addresses']
        if total is None: total=integer(data['total'])
        if total!=integer(data['total']) or len(page)>size: raise ValueError('holder enumeration changed')
        for r in page:
            wallet=address(r['address']); owner=address(r['owner']['address']); balance=integer(r['balance'])
            if wallet in rows: raise ValueError('duplicate wallet')
            rows[wallet]=(owner,balance); count+=1
        if len(page)<size: break
        cursor=address(page[-1]['address'])
    if count!=total: raise ValueError('holder count mismatch')
    return {k:v for k,v in rows.items() if v[1]}


def holder_snapshot(center=request, alternate=tonapi_request):
    start = int(time.time())
    first = holders_center(center)
    other = holders_api(alternate)
    info = alternate('jettons/' + TOKEN, {})
    masters = center('jetton/masters', {'address': MASTER, 'limit': 2})['jetton_masters']
    last = holders_center(center)
    # No fixed block API. The matching Toncenter reads bracket TonAPI and supply.
    if first != last or first != other:
        raise ValueError('holder observations differ; no snapshot published')
    if address(info['metadata']['address']) != TOKEN or len(masters) != 1 or address(masters[0]['address']) != TOKEN:
        raise ValueError('wrong supply token')
    decimals = integer(info['metadata']['decimals'])
    if decimals != 9:
        raise ValueError('unexpected JURY decimals')
    supply = integer(info['total_supply'])
    center_supply = integer(masters[0]['total_supply'])
    observed = sum(balance for _, balance in first.values())
    if supply != center_supply or observed != supply:
        raise ValueError('holder balance sum or independent supply differs')
    owners = defaultdict(int)
    for owner, balance in first.values():
        owners[owner] += balance
    return {
        'scope': 'current positive balances, not historical or block-pinned',
        'started_at': start,
        'observed_at': int(time.time()),
        'supply_raw': str(supply),
        'decimals': decimals,
        'wallet_count': len(first),
        'owner_count': len(owners),
        'owners': [
            {'owner': owner, 'balance_raw': str(balance)}
            for owner, balance in sorted(owners.items(), key=lambda row: (-row[1], row[0]))
        ],
    }
