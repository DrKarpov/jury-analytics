"""Recover the completed primary candidate and audit it in persistent, bounded batches."""
import argparse, json, time, urllib.error
from pathlib import Path
from collections import Counter, defaultdict
from indexer import digest, publish, integer, MASTER
from audit import tonapi_swaps
from provider import tonapi_request

SEED_DIGEST = '7cd7b398c0b86bca5b6e95db19b74995e52c676fe4fc1b73e82ecd92bba660f7'
ARRAYS = ('transfers', 'events', 'unresolved')
EVIDENCE = ('liquidity', 'lifecycle')
CHUNK = 500

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def check_candidate(c, expected=SEED_DIGEST):
    if c.get('token') != MASTER or c.get('schema') != 2 or c.get('digest') != expected:
        raise ValueError('unexpected seed identity')
    if digest({k:v for k,v in c.items() if k!='digest'}) != expected:
        raise ValueError('seed digest mismatch')
    if len(c['transfers']) != c['transfer_count']:
        raise ValueError('transfer count mismatch')
    traces = {r['trace'] for r in c['transfers']}
    if len(traces) != c['trace_count'] or len({r['tx'] for r in c['transfers']}) != len(c['transfers']):
        raise ValueError('trace or transfer identity mismatch')
    if ({r['trace'] for r in c['events']} | {r['trace'] for r in c['unresolved']}) != traces:
        raise ValueError('trace classification coverage mismatch')
    return c

def recover(src, store, expected=SEED_DIGEST):
    seed=store/'seed'; manifest=seed/'manifest.json'
    if manifest.exists():
        load_seed(store, expected)
        return
    c=check_candidate(read(src/'candidate.json'), expected)
    evidence={k:read(src/(k+'.json')) for k in EVIDENCE}
    if any(v.get('candidate_digest') != expected for v in evidence.values()):
        raise ValueError('mixed source evidence')
    seed.mkdir(parents=True, exist_ok=True)
    m={'version':1,'candidate_digest':expected,'metadata':{k:v for k,v in c.items() if k not in ARRAYS},'arrays':{},'evidence':{}}
    for key in ARRAYS:
        folder=seed/key;folder.mkdir(exist_ok=True)
        parts=[]
        for i in range(0,len(c[key]),CHUNK):
            name=f'{i//CHUNK:06d}.json'; rows=c[key][i:i+CHUNK]
            publish(rows,folder/name)
            parts.append({'name':name,'count':len(rows),'digest':digest(rows)})
        m['arrays'][key]=parts
    for k,v in evidence.items():
        publish(v,seed/(k+'.json'));m['evidence'][k]=digest(v)
    publish(m,manifest)
    load_seed(store,expected)
    print(f"Recovered {c['transfer_count']} transfers / {c['trace_count']} traces; independent audit pending",flush=True)

def load_seed(store, expected=SEED_DIGEST):
    seed=store/'seed';m=read(seed/'manifest.json')
    if m.get('version')!=1 or m.get('candidate_digest')!=expected: raise ValueError('unexpected manifest')
    c=dict(m['metadata'])
    for key in ARRAYS:
        rows=[]
        for i,part in enumerate(m['arrays'][key]):
            name=f'{i:06d}.json'
            if part['name']!=name: raise ValueError('segment sequence mismatch')
            page=read(seed/key/name)
            if not isinstance(page,list) or len(page)!=part['count'] or digest(page)!=part['digest']:
                raise ValueError('segment mismatch')
            rows.extend(page)
        c[key]=rows
    for k in EVIDENCE:
        v=read(seed/(k+'.json'))
        if digest(v)!=m['evidence'][k] or v.get('candidate_digest')!=expected: raise ValueError('evidence mismatch')
    return check_candidate(c,expected)

def primary(c):
    grouped=defaultdict(Counter)
    for r in c['transfers']: grouped[r['trace']]
    for e in c['events']:
        if e['kind'] in ('buy','sell'):
            grouped[e['trace']][(e['kind'],e['wallet'],integer(e['amount_raw']),e['quote_asset'],integer(e['quote_raw']))]+=1
    return grouped

def load_progress(store,c):
    ids=sorted(primary(c)); cursor=0; counts=Counter()
    for p in sorted((store/'audit').glob('batch-*.json')):
        b=read(p); rows=b['rows']; end=cursor+len(rows)
        if not rows or b['candidate_digest']!=c['digest'] or b['start']!=cursor or b['end']!=end or p.name!=f'batch-{cursor:08d}-{end:08d}.json':
            raise ValueError('audit checkpoint sequence mismatch')
        if b['digest']!=digest({k:v for k,v in b.items() if k!='digest'}):
            raise ValueError('audit checkpoint digest mismatch')
        if [r['trace'] for r in rows]!=ids[cursor:end]: raise ValueError('audit trace coverage mismatch')
        if any(r['status'] not in ('match','mismatch','unavailable') for r in rows): raise ValueError('unknown audit status')
        counts.update(r['status'] for r in rows);cursor=end
    return ids,cursor,counts

def audit_batch(store,c,fetch=tonapi_request,limit=100,seconds=240):
    if not 1<=limit<=300 or seconds<=0: raise ValueError('invalid batch limits')
    ids,start,counts=load_progress(store,c); grouped=primary(c); rows=[]; deadline=time.monotonic()+seconds
    for trace in ids[start:start+limit]:
        if time.monotonic()>=deadline: break
        try:
            actual=tonapi_swaps(fetch('events/'+trace,{}),trace)
            want=grouped[trace]
            row={'trace':trace,'status':'match' if actual==want else 'mismatch','primary':sum(want.values()),'alternate':sum(actual.values())}
            if row['status']=='mismatch':
                row['primary_swaps']=[[list(k),v] for k,v in sorted(want.items())]
                row['alternate_swaps']=[[list(k),v] for k,v in sorted(actual.items())]
        except urllib.error.HTTPError as e:
            if e.code!=404:
                print(f'Provider HTTP {e.code}; stop without advancing failed trace',flush=True);break
            row={'trace':trace,'status':'unavailable','error':'HTTP404'}
        except (urllib.error.URLError,TimeoutError,OSError) as e:
            print(f'Provider transport failure: {type(e).__name__}; stop without advancing failed trace',flush=True);break
        except (ValueError,KeyError,TypeError,AttributeError) as e:
            row={'trace':trace,'status':'unavailable','error':type(e).__name__}
        rows.append(row)
        if len(rows)%10==0: print(f'Audit {start+len(rows)}/{len(ids)}',flush=True)
    end=start+len(rows)
    if rows:
        folder=store/'audit';folder.mkdir(exist_ok=True)
        b={'candidate_digest':c['digest'],'start':start,'end':end,'rows':rows}
        b['digest']=digest(b)
        publish(b,folder/f'batch-{start:08d}-{end:08d}.json')
    ids,end,counts=load_progress(store,c)
    report={'candidate_digest':c['digest'],'total_traces':len(ids),'attempted':end,'matched':counts['match'],'mismatch':counts['mismatch'],'unavailable':counts['unavailable'],'status':'partial' if end<len(ids) else 'review_required' if counts['mismatch'] or counts['unavailable'] else 'discovered_trace_swaps_match','scope':'seed discovered traces only; not global completeness'}
    p=store/'audit-status.json'
    if not p.exists() or read(p)!=report: publish(report,p)
    print(json.dumps(report),flush=True)
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['seed','audit']);p.add_argument('--store',type=Path,required=True);p.add_argument('--input',type=Path);p.add_argument('--limit',type=int,default=100);p.add_argument('--seconds',type=int,default=240);a=p.parse_args()
    if a.command=='seed':
        if not a.input: p.error('--input required')
        recover(a.input,a.store)
    else: audit_batch(a.store,load_seed(a.store),limit=a.limit,seconds=a.seconds)

if __name__=='__main__':main()
