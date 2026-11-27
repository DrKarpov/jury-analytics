"""Separate supply/LP evidence: never add these rows to trading volume."""
from indexer import TOKEN, MASTER, hash_id, integer, paginated, canonical
from provider import address

def collect(fetch,cutoff):
    mints=[]; burns=[]; ids=set()
    for a in paginated(fetch,'actions','actions',{'account':MASTER,'action_type':'jetton_mint','start_utime':0,'end_utime':cutoff,'sort':'asc'}):
        d=a.get('details') or {}
        if a.get('type')!='jetton_mint' or address(d['asset'])!=TOKEN: continue
        aid=hash_id(a['action_id']); stamp=integer(a['trace_end_utime'])
        if aid in ids or not 0<stamp<=cutoff or type(a['success']) is not bool: raise ValueError('invalid mint')
        ids.add(aid);mints.append({'id':aid,'trace':hash_id(a['trace_id']),'time':stamp,'owner':address(d['receiver']),'amount_raw':str(integer(d['amount'])),'success':a['success']})
    ids=set()
    for r in paginated(fetch,'jetton/burns','jetton_burns',{'jetton_master':MASTER,'start_utime':0,'end_utime':cutoff,'sort':'asc'}):
        tx=hash_id(r['transaction_hash']);stamp=integer(r['transaction_now'])
        if address(r['jetton_master'])!=TOKEN or tx in ids or not 0<stamp<=cutoff or type(r['transaction_aborted']) is not bool: raise ValueError('invalid burn')
        ids.add(tx);burns.append({'tx':tx,'trace':hash_id(r['trace_id']),'time':stamp,'owner':address(r['owner']),'amount_raw':str(integer(r['amount'])),'aborted':r['transaction_aborted']})
    return {'cutoff':cutoff,'scope':'provider-reported mint actions involving master and burn messages; not proven supply history','mints':mints,'burns':burns}

def liquidity(db,cutoff):
    import json
    from collections import defaultdict
    transfers=defaultdict(list)
    for (n,) in db.execute('SELECT normalized FROM transfers'):
        r=json.loads(n);transfers[r['trace']].append(r)
    evidence=[];unknown=[]
    for trace,acts in db.execute('SELECT id,actions FROM traces'):
        for a in json.loads(acts):
            if a.get('type') not in ('dex_deposit_liquidity','dex_withdraw_liquidity'):continue
            d=a.get('details') or {};aid=hash_id(a['action_id'])
            try:
                sides=[i for i in (1,2) if d.get('asset_'+str(i)) and address(d['asset_'+str(i)])==TOKEN]
                if not sides:continue
                if len(sides)!=1 or a.get('success') is not True or not 0<integer(a['trace_end_utime'])<=cutoff:raise ValueError('invalid LP')
                i=sides[0];qty=integer(d['amount_'+str(i)]);owner=address(d['source']);pool=address(d['pool']);deposit=a['type']=='dex_deposit_liquidity'
                if not deposit and type(d.get('is_refund')) is not bool:raise ValueError('unknown refund status')
                field='source' if deposit else 'destination'
                match=[r for r in transfers[trace] if not r['aborted'] and r[field]==owner and integer(r['amount_raw'])==qty]
                if not qty or len(match)!=1:raise ValueError('unmatched LP transfer')
                evidence.append({'id':aid,'trace':trace,'time':a['trace_end_utime'],'kind':'lp_deposit' if deposit else 'refund' if d['is_refund'] else 'lp_withdraw','owner':owner,'pool':pool,'amount_raw':str(qty),'transfer_tx':match[0]['tx']})
            except (ValueError,KeyError,TypeError):unknown.append({'trace':trace,'id':aid,'reason':'unverified_liquidity'})
    from collections import Counter
    counts=Counter(r['transfer_tx'] for r in evidence)
    for r in evidence:
        if counts[r['transfer_tx']]>1:unknown.append({'trace':r['trace'],'id':r['id'],'reason':'shared_transfer'})
    return {'scope':'matched LP actions in discovered traces; separate from trade metrics','events':[r for r in evidence if counts[r['transfer_tx']]==1],'unresolved':unknown}
