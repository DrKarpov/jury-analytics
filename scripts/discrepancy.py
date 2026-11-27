"""Read-only discrepancy investigation: retain provider evidence and raw trace trees.

A matching token transfer proves neither swap semantics nor its quote amount.
No classifier edits, history rewrites, or publication occur here.
"""
import argparse, json, time
from collections import Counter, defaultdict
from pathlib import Path
from indexer import digest, publish, hash_id, fetch_actions, integer
from provider import request, tonapi_request
from recovery import load_seed, load_progress, primary, read
from audit import tonapi_swaps

def multiset(pairs):
    out=Counter()
    for key,count in pairs:
        if len(key)!=5 or count<=0: raise ValueError('invalid audit swap')
        side,wallet,qty,asset,quote=key
        out[(side,wallet,integer(qty),asset,integer(quote))]+=count
    return out

def category(row):
    p,a=multiset(row['primary_swaps']),multiset(row['alternate_swaps'])
    if not p:return 'primary_missing'
    if not a:return 'alternate_missing'
    if p<a:return 'alternate_extra'
    if a<p:return 'primary_extra'
    def project(c,n):
        out=Counter()
        for k,v in c.items():out[k[:n]]+=v
        return out
    if project(p,4)==project(a,4):return 'quote_difference'
    return 'endpoint_or_other_difference'

def transfer_support(swaps,rows):
    result=[]
    for key,count in sorted(swaps.items()):
        side,wallet,qty,asset,quote=key
        candidates=[r['tx'] for r in rows if not r['aborted'] and integer(r['amount_raw'])==qty and
                    r['destination' if side=='buy' else 'source']==wallet]
        # Preserve integer precision in portable evidence.
        result.append({'swap':[side,wallet,str(qty),asset,str(quote)],'multiplicity':count,
                       'candidate_transfer_hashes':sorted(candidates),
                       'unique_candidate':len(candidates)==count==1})
    return result

def tree_index(tree,expected):
    if tree.get('emulated') is True or hash_id(tree['transaction']['hash'])!=expected:
        raise ValueError('wrong or emulated raw trace root')
    result={}
    stack=[tree]
    while stack:
        n=stack.pop()
        if n.get('emulated') is True:raise ValueError('emulated trace node')
        tx=n['transaction'];h=hash_id(tx['hash'])
        if h in result:raise ValueError('duplicate raw transaction')
        result[h]=tx
        stack.extend(n.get('children') or [])
    return result

def inspect(store,out,center=request,alternate=tonapi_request,per_group=2):
    seed=load_seed(store)
    load_progress(store,seed) # checks ordered checkpoint coverage and checksums
    p=primary(seed);by_trace=defaultdict(list);events=defaultdict(list)
    for r in seed['transfers']:by_trace[r['trace']].append(r)
    for e in seed['events']:events[e['trace']].append(e)
    groups=defaultdict(list)
    for path in sorted((store/'audit').glob('batch-*.json')):
        for row in read(path)['rows']:
            if row['status']!='mismatch':continue
            if multiset(row['primary_swaps'])!=p[row['trace']]:raise ValueError('audit primary differs from seed')
            groups[category(row)].append(row)
    out.mkdir(parents=True,exist_ok=True)
    report={'seed_digest':seed['digest'],'groups':{k:len(v) for k,v in sorted(groups.items())},'cases':[],'scope':'diagnostic sample; not resolved trades'}
    deadline=time.monotonic()+360
    for kind,rows in sorted(groups.items()):
        for row in rows[:per_group]:
            if time.monotonic()>deadline:break
            t=row['trace'];raw=by_trace[t]
            entry={'trace':t,'category':kind,'primary':transfer_support(p[t],raw),
                   'alternate':transfer_support(multiset(row['alternate_swaps']),raw)}
            case={'seed_digest':seed['digest'],'audit_row':row,'transfers':raw,'seed_events':events[t]}
            try:
                case['center_actions']=fetch_actions(center,[t])[t]
                case['alternate_event']=alternate('events/'+t,{})
                current=tonapi_swaps(case['alternate_event'],t)
                entry['alternate_changed']=current!=multiset(row['alternate_swaps'])
                case['raw_trace']=alternate('traces/'+t,{})
                txs=tree_index(case['raw_trace'],t)
                entry['raw_transaction_count']=len(txs)
                entry['seed_transfer_tx_present']=sum(r['tx'] in txs for r in raw)
                entry['seed_transfer_count']=len(raw)
                entry['status']='evidence_collected'
            except (ValueError,KeyError,TypeError,AttributeError,OSError) as e:
                entry['status']='incomplete';entry['error']=type(e).__name__
            case['diagnostic']=entry;case['digest']=digest(case)
            publish(case,out/(t+'.json'))
            report['cases'].append(entry)
            print(kind,t,entry['status'],flush=True)
    report['digest']=digest(report);publish(report,out/'report.json')
    print(json.dumps({'groups':report['groups'],'cases':len(report['cases']),
                      'evidence_collected':sum(r['status']=='evidence_collected' for r in report['cases'])}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    inspect(a.store,a.out)
