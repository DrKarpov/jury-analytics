"""Resumable triage, not a trade classifier. Preserve raw samples for protocol review."""
import argparse,json,time
from collections import Counter,defaultdict
from pathlib import Path
from indexer import digest,publish,fetch_actions,hash_id
from provider import request,tonapi_request
from recovery import load_seed,read
from incremental import load_history
from repair_overlay import overlay
from payout_repair import overlay as payout_overlay
from discrepancy import tree_index

VERSION=1
def fingerprint(h,t):
    return digest({'transfers':sorted(h.traces[t],key=lambda r:r['tx']),
                   'events':sorted(h.events.get(t,[]),key=lambda e:e['id']),
                   'unresolved':h.unresolved[t]})

def profile(actions):
    types=Counter(str(a.get('type') or 'unknown') for a in actions)
    venues=Counter()
    for a in actions:
        d=a.get('details') or {}
        if isinstance(d.get('dex'),str):venues[d['dex']]+=1
    successful=[a for a in actions if a.get('success') is True]
    swap=any('swap' in str(a.get('type','')).lower() for a in successful)
    lp=any(a.get('type') in ('dex_deposit_liquidity','dex_withdraw_liquidity') for a in successful)
    refund=any((a.get('details') or {}).get('is_refund') is True for a in successful)
    if swap and lp:group='mixed_swap_lp'
    elif swap:group='swap_action_present'
    elif refund:group='refund_action_present'
    elif lp:group='liquidity_action_present'
    elif not actions:group='no_provider_actions'
    elif not successful:group='failed_or_unknown_actions'
    elif all(a.get('type')=='jetton_transfer' for a in successful):group='transfer_actions_only'
    else:group='other_or_mixed_actions'
    return {'group':group,'action_types':dict(types),'venue_labels':dict(venues)}

def raw_summary(tree,t,rows):
    txs=tree_index(tree,t)
    if any(r['tx'] not in txs for r in rows):raise ValueError('missing transfer transaction in raw tree')
    interfaces=Counter();ops=Counter();moon=[]
    stack=[tree]
    while stack:
        n=stack.pop();tx=n['transaction'];m=tx.get('in_msg') or {}
        names=[x for x in n.get('interfaces',[]) if isinstance(x,str)]
        interfaces.update(names)
        if m.get('op_code'):ops[str(m['op_code'])]+=1
        if any('moon' in x.lower() for x in names) or 'moon' in str(m.get('decoded_op_name','')).lower():
            moon.append({'tx':hash_id(tx['hash']),'account':tx['account']['address'],'interfaces':names,
                         'opcode':m.get('op_code'),'decoded_op_name':m.get('decoded_op_name')})
        stack.extend(n.get('children',[]))
    return {'transaction_count':len(txs),'interfaces':dict(interfaces),'opcodes':dict(ops),
            'moon_provider_hints':moon,'scope':'provider decoded interfaces and opcode hints; not ABI or code-hash verification'}

def validate_record(r,t,fp):
    if r.get('version')!=VERSION or r.get('trace')!=t or r.get('fingerprint')!=fp or r.get('digest')!=digest({k:v for k,v in r.items() if k!='digest'}):
        raise ValueError('triage record identity mismatch')
    if any(hash_id(a['trace_id'])!=t for a in r['actions']):raise ValueError('wrong trace action')
    if profile(r['actions'])!=r['profile']:raise ValueError('profile mismatch')
    return r

def run(store,center=request,alternate=tonapi_request,limit=100,raw_limit=12,seconds=180):
    seed=load_seed(store);h=load_history(store,seed);overlay(store,seed,h);payout_overlay(store,seed,h)
    c=h.candidate();folder=store/'triage'/'v1';folder.mkdir(parents=True,exist_ok=True)
    rawfolder=store/'triage-raw'/'v1';rawfolder.mkdir(parents=True,exist_ok=True)
    reasons=Counter();groups=Counter();known={};pending=[];raw_done=set()
    fps={t:fingerprint(h,t) for t in h.unresolved}
    for t,u in h.unresolved.items():reasons.update(u['reasons'])
    for t,fp in sorted(fps.items()):
        p=folder/(t+'-'+fp+'.json')
        if p.exists():
            r=validate_record(read(p),t,fp);known[t]=r;groups[r['profile']['group']]+=1
            rp=rawfolder/p.name
            if rp.exists():
                x=read(rp)
                if x.get('trace')!=t or x.get('fingerprint')!=fp or x.get('digest')!=digest({k:v for k,v in x.items() if k!='digest'}) or raw_summary(x['tree'],t,h.traces[t])!=x['summary']:
                    raise ValueError('raw triage record mismatch')
                raw_done.add(t)
        else:pending.append(t)
    # Prioritize remaining known swap disagreements, then diverse reason signatures.
    q=store/'repair-queue.json';priority=set()
    if q.exists():
        x=read(q)
        if x.get('seed_digest')!=seed['digest'] or x.get('digest')!=digest({k:v for k,v in x.items() if k!='digest'}):raise ValueError('repair queue mismatch')
        priority={r['trace'] for r in x['rows']}
    pending.sort(key=lambda t:(t not in priority,t))
    # Avoid spending the whole first batch on a single reason combination.
    buckets=defaultdict(list)
    for t in pending:buckets[(t not in priority,tuple(sorted(h.unresolved[t]['reasons'])))].append(t)
    selected=[]
    while buckets and len(selected)<limit:
        for k in sorted(buckets):
            selected.append(buckets[k].pop(0))
            if not buckets[k]:del buckets[k]
            if len(selected)>=limit:break
    deadline=time.monotonic()+seconds;new=0;raw_new=0;stop=None
    for i in range(0,len(selected),20):
        if time.monotonic()>=deadline:break
        chunk=selected[i:i+20]
        try:acts=fetch_actions(center,chunk)
        except (OSError,ValueError,KeyError,TypeError) as e:stop=type(e).__name__;break
        for t in chunk:
            r={'version':VERSION,'trace':t,'fingerprint':fps[t],'actions':acts[t],'profile':profile(acts[t])}
            r['digest']=digest(r);publish(r,folder/(t+'-'+fps[t]+'.json'));known[t]=r
            groups[r['profile']['group']]+=1;new+=1
    # Collect representative raw trees across categories, prioritizing explicit Moon hints.
    samples=defaultdict(int)
    for t in raw_done:samples[known[t]['profile']['group']]+=1
    for _ in range(raw_limit):
        if time.monotonic()>=deadline:break
        choices=[t for t in known if t not in raw_done]
        if not choices:break
        def rank(t):
            p=known[t]['profile'];moon=any('moon' in x.lower() for x in (*p['venue_labels'],*p['action_types']))
            return (not moon,samples[p['group']],t not in priority,t)
        t=min(choices,key=rank)
        try:
            tree=alternate('traces/'+t,{})
            s=raw_summary(tree,t,h.traces[t])
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as e:stop=type(e).__name__;break
        r={'trace':t,'fingerprint':fps[t],'tree':tree,'summary':s}
        r['digest']=digest(r);publish(r,rawfolder/(t+'-'+fps[t]+'.json'));raw_done.add(t)
        samples[known[t]['profile']['group']]+=1;raw_new+=1
    moon_count=0
    for t in raw_done:
        r=read(rawfolder/(t+'-'+fps[t]+'.json'))
        moon_count+=bool(r['summary']['moon_provider_hints'])
    report={'candidate_digest':c['digest'],'history_head':h.head,'seed_digest':seed['digest'],
            'unresolved_traces':len(fps),'reason_counts_nonexclusive':dict(reasons),
            'profiled':len(known),'profile_groups':dict(groups),'new_profiles':new,
            'raw_sampled':len(raw_done),'new_raw_samples':raw_new,'moon_hint_traces':moon_count,
            'stop_reason':stop,'scope':'triage only; no trade, refund, direct-transfer or protocol attribution inferred from action types alone'}
    report['digest']=digest(report);publish(report,store/'triage-status.json');print(json.dumps(report),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);a=p.parse_args();run(a.store)
