"""Unified shadow projection of replayed discovery sources and peer cursors.

Only complete, identity-supported peer prefixes enter this projection.
Isolated counterparts remain discovery evidence. No public ledger or balances.
"""
import argparse,json,time
from collections import Counter
from functools import partial
from pathlib import Path
from canonical_movements import Observations
from delivery_journal import build as build_journal,compact as compact_journal,preserve as preserve_journal
from continuation_shadow import capture,require
from continuation_store import cursor,apply,load,next_target
from counterpart_discovery import validate,record_key
from peer_prefix import load_prefixes,identity
from master_continuation import load as load_master,messages_from,receipt_proof
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,validate_receipt
from indexer import digest,integer,publish
from provider import request,tonapi_request
from recovery import read
from wallet_history import graph,key,load_wallets,successful,valid_internal

def add_peers(obs,bases,cursors):
    included=[];conflicts={}
    for w,s in sorted(bases.items()):
        rows=s['rows']+cursors.get(w,{}).get('new_rows',[])
        if any(x['tx'] in obs.rows and obs.rows[x['tx']]!=(w,x) for x in rows):
            conflicts[w]='normalized observation conflict';continue
        obs.ingest((w,x) for x in rows)
        included.append(w)
    return included,conflicts

def assert_preserved(before,after):
    old={x['id']:x for x in before['events']};new={x['id']:x for x in after['events']}
    require(all(new.get(k)==v for k,v in old.items()),'unified projection changed existing movement')

def frontier(obs,roots):
    states={}
    for w,row in obs.rows.values():states.setdefault(w,{'rows':[]})['rows'].append(row)
    linked,_,_,matched=graph(states,roots)
    edges=[]
    for w in sorted(linked):
        for r in states.get(w,{}).get('rows',[]):
            if r['time']<=ANCHOR or not successful(r):continue
            for side,msgs,direction,peer in (('outgoing',r['out'],'source','destination'),
                                             ('incoming',[r['in']],'destination','source')):
                for m in msgs:
                    if valid_internal(m,w,direction) and m['hash'] not in matched:
                        edges.append({'side':side,'message':m['hash'],'wallet':w,'peer':m[peer],
                                      'transaction':r['tx'],'lt':str(r['lt']),'time':r['time'],'amount_raw':m['amount_raw']})
    edges.sort(key=lambda e:(e['side'],e['message']))
    require(len({(e['side'],e['message']) for e in edges})==len(edges),'duplicate unified frontier edge')
    return edges

def run(store,center=request,alternate=tonapi_request,limit=6,seconds=40):
    require(1<=limit<=20 and 1<=seconds<=120,'invalid unified peer budget')
    g=store/'genesis'/'v1';master=read(g/'master.json');md=master['digest'];messages=validate_master(master)
    roots=set();historical_receipts={}
    historical_emissions={k:v for k,v in messages.items() if not v['master_aborted']}
    for path in sorted((g/'receipts').glob('*.json')):
        q=validate_receipt(read(path),messages[path.stem],md)
        if integer(q['recipient_at'])<=ANCHOR:
            roots.add(q['wallet']);historical_receipts[path.stem]=q
    states=load_wallets(g/'wallet-history',md)
    linked,_,_,_=graph(states,roots)
    eligible={w for w in linked if states.get(w,{}).get('complete') and states[w]['rows']}
    folder=store/'continuation'/'v1'
    target=integer(read(store/'update-status.json')['cutoff'])
    legacy_status=checked(read(folder/'status.json'))
    require(legacy_status['master_digest']==md and legacy_status['target_timestamp']==target,'legacy continuation stale')
    cursors=load(folder/'accounts',states,eligible,md)
    obs=Observations()
    obs.ingest((w,x) for w,s in states.items() for x in s['rows'])
    historical_journal=build_journal(obs,roots,historical_emissions,historical_receipts,ANCHOR)
    obs.ingest((w,x) for w,c in cursors.items() for x in c['new_rows'])
    before=obs.project(roots)
    require(digest(before)==legacy_status['projection_digest'],'legacy continuation projection mismatch')
    proofs={}
    for path in sorted((folder/'counterparts').glob('*.json')):
        rec=read(path);e=rec['edge']
        require(path.stem==record_key(e),'counterpart filename mismatch')
        validate(rec,obs.rows.get(e['transaction']),md)
        proofs[rec['digest']]=rec
    prefixes=load_prefixes(folder/'peer-prefixes',proofs,md)
    # All identity-supported complete prefixes are included in the combined
    # replay; only those ending after anchor can use the existing post-anchor
    # cursor without skipping pre-anchor rows. Never shift an old base head.
    bases={w:s for w,s in prefixes.items() if identity(s)[0] is not None}
    live={w:s for w,s in bases.items() if s['tip']['time']>ANCHOR}
    peer_dir=folder/'peer-accounts'
    peer_cursors=load(peer_dir,live,set(live),md)
    require(all(c['target']<=target for c in peer_cursors.values()),'peer continuation target rollback')
    previous_pages=sum(c['pages'] for c in peer_cursors.values())
    pending=folder/'unified-pending.json'
    old=checked(read(pending)) if pending.exists() else {'master_digest':md,'failures':{}}
    require(old['master_digest']==md and set(old['failures'])<=set(live),'unified pending identity mismatch')
    failures=dict(old['failures'])
    now=int(time.time())
    def get(w):return peer_cursors[w] if w in peer_cursors else cursor(live[w])
    todo=sorted((w for w in live if next_target(get(w),target) is not None and now-failures.get(w,{}).get('at',0)>=600),
                key=lambda w:(get(w)['tip_reached'],max(get(w)['last_observed_at'],failures.get(w,{}).get('at',0)),w))
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    attempted=written=new_rows=0;stop=None
    for w in todo[:limit]:
        if time.monotonic()>=deadline:stop='budget';break
        c=get(w);want=next_target(c,target);attempted+=1
        try:
            rec,rows,complete=capture(w,c['prefix'],md,want,center,alternate)
            rec=signed({**{k:v for k,v in rec.items() if k!='digest'},'observed_at':int(time.time())})
            advanced=apply(c,rec,w,md)
            require(len(advanced['new_rows'])-len(c['new_rows'])==len(rows) and advanced['tip_reached']==complete,'peer continuation replay differs')
        except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            failures[w]={'at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:180]}
            if isinstance(e,OSError) and getattr(e,'code',None)!=404:stop=type(e).__name__;break
            continue
        path=peer_dir/key(w)/f"page-{c['pages']:08d}.json"
        require(not path.exists(),'peer continuation record already exists')
        path.parent.mkdir(parents=True,exist_ok=True);publish(rec,path)
        peer_cursors[w]=advanced;written+=1;new_rows+=len(rows);failures.pop(w,None)
    restored=load(peer_dir,live,set(live),md)
    require(restored==peer_cursors,'peer continuation cold replay differs')
    included,conflicts=add_peers(obs,bases,restored)
    master_dir=folder/'master'
    master_status=checked(read(master_dir/'status.json'))
    require(master_status['master_digest']==md and master_status['target_timestamp']==target,'master continuation stale')
    master_cursor=load_master(master_dir,master)
    require(master_cursor['target']==master_status['cursor_target'],'master cursor status mismatch')
    emitted,_=messages_from(master_cursor['new_rows'])
    master_roots=set();receipt_count=0;pending_after_target=0
    all_emissions={**historical_emissions,**emitted};all_receipts=dict(historical_receipts)
    require(len(all_emissions)==len(historical_emissions)+len(emitted),'duplicate master emission across anchor')
    for path in sorted((master_dir/'receipts').glob('*.json')):
        require(path.stem in emitted,'orphan master receipt')
        proof,row=receipt_proof(read(path),emitted[path.stem],md,target)
        receipt_count+=1
        if row['time']<=target:
            master_roots.add(row['in']['destination']);all_receipts[path.stem]=proof
        else:pending_after_target+=1
    require(receipt_count==master_status['verified_recipient_deliveries'],'master receipt status mismatch')
    # Exact master receipts establish discovery roots, not permission to insert
    # isolated recipient rows into a complete account prefix.
    all_roots=roots|master_roots
    after=obs.project(all_roots);assert_preserved(before,after)
    journal=build_journal(obs,all_roots,all_emissions,all_receipts,target)
    preserve_journal(historical_journal,journal)
    replay_obs=Observations();items=list(obs.rows.values())
    replay_obs.ingest(reversed(items));replay_obs.ingest(items)
    repeated=build_journal(replay_obs,all_roots,dict(reversed(list(all_emissions.items()))),
                           dict(reversed(list(all_receipts.items()))),target)
    require(journal==repeated,'journal replay order or duplicate mismatch')
    require(journal['projection_digest']==digest(after),'journal projection mismatch')
    ledger_record=signed({'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,
                          'historical':compact_journal(historical_journal),'combined':compact_journal(journal),
                          'historical_postings_preserved':True,'duplicate_reverse_replay_equal':True,
                          'scope':'shadow delivery journal; no verified balances, supply, trade labels or PnL'})
    publish(ledger_record,folder/'ledger-status.json')
    print('DELIVERY JOURNAL',json.dumps(ledger_record,sort_keys=True),flush=True)
    edges=frontier(obs,all_roots)
    observed_accounts={w for w,_ in obs.rows.values()}
    new_root_without_rows=master_roots-observed_accounts
    peer_record=signed({'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,
                        'projection_digest':digest(after),'edges':edges,
                        'scope':'unified prefix-backed unmatched messages; master receipt roots without rows require acquisition'})
    publish(peer_record,folder/'unified-frontier.json')
    publish(signed({'master_digest':md,'failures':failures}),pending)
    summary={'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,
             'historical_and_regular_matched_deliveries':before['matched_deliveries'],
             'unified_matched_deliveries':after['matched_deliveries'],
             'additional_peer_or_root_deliveries':after['matched_deliveries']-before['matched_deliveries'],
             'unique_normalized_rows':len(obs.rows),'linked_accounts':after['linked_accounts'],
             'identity_supported_peer_prefixes':len(bases),'included_peer_prefixes':len(included),
             'peer_projection_conflicts':conflicts,'peer_prefixes_before_anchor_not_refreshed':len(bases)-len(live),
             'peer_cursors':len(restored),'peer_cursors_at_target':sum(c['tip_reached'] and c['target']==target for c in restored.values()),
             'peer_cursors_replayed_envelopes':previous_pages,'peer_cursor_new_envelopes':written,
             'peer_cursor_new_rows':new_rows,'peer_cursor_total_rows':sum(len(c['new_rows']) for c in restored.values()),
             'peer_attempted':attempted,'peer_pending_failures':len(failures),'peer_failure_reasons':dict(Counter(x['reason'] for x in failures.values())),
             'master_target_reached':master_status['target_reached'],'master_receipts_replayed':receipt_count,
             'master_new_roots':len(master_roots-roots),'master_roots_without_rows':len(new_root_without_rows),
             'master_receipts_after_target':pending_after_target,'unified_frontier_edges':len(edges),
             'unified_frontier_peers':len({e['peer'] for e in edges}),
             'frontier_digest':peer_record['digest'],'projection_digest':digest(after),'ledger_digest':ledger_record['digest'],
             'cold_replay_equal':True,'stop_reason':stop,
             'scope':'unified shadow replay of compared account prefixes and master discovery roots; no isolated counterpart rows, common block completeness, historical owner continuity, balance or trade proof'}
    publish(signed({**summary,'included_wallets':included,'master_roots_without_rows_addresses':sorted(new_root_without_rows)}),folder/'unified-status.json')
    print('UNIFIED SHADOW',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--limit',type=int,default=6);p.add_argument('--seconds',type=int,default=40);a=p.parse_args();run(a.store,limit=a.limit,seconds=a.seconds)
