"""Token transfer discovery + trace-level actions. Python stdlib only."""
import argparse, hashlib, json, sqlite3, time, os, base64, re
from pathlib import Path
from provider import address, request, MASTER, normalized
ROOT=Path(__file__).resolve().parents[1]
TOKEN=address(MASTER)
OVERLAP=3600
PAGE=1000

def canonical(x): return json.dumps(x, sort_keys=True, separators=(',',':'), ensure_ascii=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def integer(x):
    if not isinstance(x,(str,int)) or isinstance(x,bool) or not re.fullmatch(r'[0-9]+',str(x)): raise ValueError('invalid amount')
    return int(x)
def hash_id(s):
    if not isinstance(s,str): raise ValueError('missing hash')
    if re.fullmatch(r'[0-9a-fA-F]{64}',s): return s.lower()
    b=base64.b64decode(s.replace('-','+').replace('_','/')+'='*((-len(s))%4),validate=True)
    if len(b)!=32: raise ValueError('invalid hash')
    return b.hex()
def asset(x): return 'GRAM' if x is None else address(x)
def paginated(fetch, endpoint, key, params, size=PAGE):
    offset=0
    while True:
        batch=fetch(endpoint,{**params,'limit':size,'offset':offset})[key]
        if not isinstance(batch,list) or len(batch)>size: raise ValueError('invalid response page')
        yield from batch
        offset+=len(batch)
        if len(batch)<size: break

def transfer_windows(fetch,start,end,size=PAGE):
    """Time-filtered Toncenter results sort by tx_now, not tx_lt.
    Bisect a saturated time window instead of using offsets across equal timestamps.
    Fail closed if one second alone saturates the page.
    """
    if start>end: return
    batch=fetch('jetton/transfers',{'jetton_master':MASTER,'start_utime':start,'end_utime':end,'sort':'asc','limit':size,'offset':0})['jetton_transfers']
    if not isinstance(batch,list) or len(batch)>size: raise ValueError('invalid transfer response page')
    if len(batch)==size:
        if start==end: raise ValueError(f'saturated transfer window at {start}; cannot prove completeness')
        mid=(start+end)//2
        yield from transfer_windows(fetch,start,mid,size)
        yield from transfer_windows(fetch,mid+1,end,size)
        return
    previous=-1
    for raw in batch:
        stamp=int(raw['transaction_now'])
        if not start<=stamp<=end: raise ValueError(f'transfer outside requested window: {stamp} not in [{start},{end}]')
        if stamp<previous: raise ValueError(f'transfer timestamp order violation: {stamp} < {previous}')
        previous=stamp
        yield raw

def discover(fetch,start,end):
    rows={}
    for raw in transfer_windows(fetch,start,end):
        r=normalized(raw); r['tx']=hash_id(r['tx']);r['trace']=hash_id(r['trace'])
        if r['tx'] in rows: raise ValueError(f'duplicate transfer transaction: {r["tx"]}')
        rows[r['tx']]=(r,raw)
    return rows

def fetch_actions(fetch, ids):
    out={i:[] for i in ids}; seen=set()
    for a in paginated(fetch,'actions','actions',{'trace_id':[base64.b64encode(bytes.fromhex(i)).decode() for i in ids],'sort':'asc'},size=256):
        t=hash_id(a['trace_id']); k=(t,hash_id(a['action_id']))
        if t not in out or k in seen: raise ValueError('unexpected or duplicate action')
        seen.add(k); out[t].append(a)
    return out

def endpoint_asset(value, expected, dex, allow_alias=True):
    # Observed Toncenter legacy DeDust transfer field encodes JURY workchain -1 as unsigned 255.
    # Do not normalize arbitrary addresses or other assets; require canonical endpoint identity.
    actual=asset(value)
    if allow_alias and dex=='dedust' and expected==TOKEN and actual=='255:'+TOKEN.split(':',1)[1]:
        return TOKEN
    return actual

def classify(trace, actions, rows, cutoff, allow_alias=True):
    """Count settled provider-classified endpoint swaps, not intermediate peer legs.
    No inference from direction of transfer alone. Unresolved traces remain visible.
    """
    events=[]; uncertain=False; reasons=[]; transfer_actions=[]
    for a in actions:
        t=a.get('type'); d=a.get('details') or {}; aid=hash_id(a['action_id']); stamp=a.get('trace_end_utime')
        if not isinstance(stamp,int) or isinstance(stamp,bool) or stamp<=0 or stamp>cutoff: uncertain=True; reasons.append('pending_or_invalid_time'); continue
        if a.get('success') is not True:
            uncertain=True; reasons.append('failed_or_unknown_action'); continue
        if t in ('jetton_swap','tonco_jetton_swap'):
            try:
                if 'asset_in' not in d or 'asset_out' not in d: raise ValueError('missing assets')
                ai,ao=asset(d['asset_in']),asset(d['asset_out'])
                if (ai==TOKEN)==(ao==TOKEN):
                    if any(TOKEN in (asset(p.get('asset_in')),asset(p.get('asset_out'))) for p in d.get('peer_swaps') or []): uncertain=True; reasons.append('intermediate_route')
                    continue
                i,o=d['dex_incoming_transfer'],d['dex_outgoing_transfer']
                # Require endpoint asset agreement and positive amounts.
                if 'asset' not in i or 'asset' not in o or endpoint_asset(i['asset'],ai,d.get('dex'),allow_alias)!=ai or endpoint_asset(o['asset'],ao,d.get('dex'),allow_alias)!=ao: raise ValueError('asset mismatch')
                ni,no=integer(i['amount']),integer(o['amount']); sender=address(d['sender'])
                if not ni or not no: raise ValueError('zero swap')
                side='buy' if ao==TOKEN else 'sell'; qty=no if side=='buy' else ni
                # Require matching non-aborted token transfer in this trace, to/from endpoint owner.
                field='destination' if side=='buy' else 'source'
                owner=address(o['destination'] if side=='buy' else i['source'])
                matches=[r for r in rows if not r['aborted'] and r[field]==owner and int(r['amount_raw'])==qty]
                if len(matches)!=1: raise ValueError('no unique matching transfer')
                events.append(dict(id=aid,trace=trace,time=stamp,kind=side,wallet=owner,initiator=sender,amount_raw=str(qty),quote_asset=ai if side=='buy' else ao,quote_raw=str(ni if side=='buy' else no),venue=d.get('dex') or 'unknown',transfer_tx=matches[0]['tx']))
            except (KeyError,ValueError,TypeError,AttributeError): uncertain=True; reasons.append('unverified_swap')
        elif t=='jetton_transfer': transfer_actions.append((a,d,aid,stamp))
    # A multi-action trace may contain fees, LP movements, or refunds. Only treat a simple,
    # standalone, matched transfer as a direct transfer; everything else is unresolved.
    if not events and not uncertain and len(actions)==1 and len(transfer_actions)==1:
        a,d,aid,stamp=transfer_actions[0]
        try:
            if address(d['asset'])==TOKEN:
                source,dest=address(d['sender']),address(d['receiver']); amount=integer(d['amount'])
                matches=[r for r in rows if not r['aborted'] and r['source']==source and r['destination']==dest and int(r['amount_raw'])==amount]
                if len(matches)==1: events.append(dict(id=aid,trace=trace,time=stamp,kind='transfer',wallet=source,destination=dest,amount_raw=str(amount),transfer_tx=matches[0]['tx']))
        except (KeyError,ValueError,TypeError): pass
    used=[e['transfer_tx'] for e in events]
    if len(used)!=len(set(used)): events=[]; used=[]; reasons.append('ambiguous_multiple_actions')
    unresolved=[r['tx'] for r in rows if r['tx'] not in used]
    if unresolved or uncertain or not events:
        return events, {'trace':trace,'time':max(r['time'] for r in rows),'kind':'unresolved','transfer_count':len(unresolved),'reasons':sorted(set(reasons or ['unclassified_trace']))}
    return events,None

def open_db(path):
    db=sqlite3.connect(path);db.executescript('CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT NOT NULL); CREATE TABLE IF NOT EXISTS transfers(tx TEXT PRIMARY KEY, trace TEXT NOT NULL, stamp INTEGER NOT NULL, normalized TEXT NOT NULL, raw TEXT NOT NULL); CREATE INDEX IF NOT EXISTS transfers_trace ON transfers(trace); CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY, actions TEXT NOT NULL);');return db

def run(db, fetch=request, cutoff=None, full=False):
    cutoff=int(time.time())-180 if cutoff is None else cutoff
    prev=db.execute("SELECT v FROM meta WHERE k='cutoff'").fetchone(); old=int(prev[0]) if prev else 0
    if old and cutoff<old: raise ValueError('cutoff rollback')
    start=0 if full or not old else max(0,old-OVERLAP)
    rows=discover(fetch,start,cutoff)
    if full:
        second=discover(fetch,start,cutoff)
        if {k:v[0] for k,v in rows.items()}!={k:v[0] for k,v in second.items()}: raise ValueError('full history differs between reads')
    existing={tx:n for tx,n in db.execute('SELECT tx,normalized FROM transfers WHERE stamp BETWEEN ? AND ?', (start,old))} if old else {}
    if any(tx not in rows or canonical(rows[tx][0])!=n for tx,n in existing.items()): raise ValueError('history mismatch in checked interval; refusing replacement')
    # Unseen rows within the previously indexed overlap are a possible indexer lag. Fail closed.
    if old and any(r['time']<=old and tx not in existing for tx,(r,_) in rows.items()): raise ValueError('late historical transfer; full investigation required')
    with db:
        db.executemany('INSERT OR IGNORE INTO transfers VALUES(?,?,?,?,?)',[(tx,r['trace'],r['time'],canonical(r),canonical(raw)) for tx,(r,raw) in rows.items()])
        ids=[r[0] for r in db.execute('SELECT DISTINCT trace FROM transfers ORDER BY trace')]
        previous={i:json.loads(a) for i,a in db.execute('SELECT id,actions FROM traces')}
        refresh=ids if full else sorted(set(i for i in ids if i not in previous or not previous[i]) | {r['trace'] for r,_ in rows.values()})
        for i in range(0,len(refresh),20):
            chunk=refresh[i:i+20]; retrieved=fetch_actions(fetch,chunk)
            for t,acts in retrieved.items():
                if previous.get(t) and canonical(sorted(previous[t],key=lambda a:a['action_id']))!=canonical(sorted(acts,key=lambda a:a['action_id'])): raise ValueError('action history changed; review required')
                db.execute('INSERT OR REPLACE INTO traces VALUES(?,?)',(t,canonical(acts)))
        db.execute("INSERT OR REPLACE INTO meta VALUES('cutoff',?)",(str(cutoff),))
        grouped={}
        for (n,) in db.execute('SELECT normalized FROM transfers'): r=json.loads(n);grouped.setdefault(r['trace'],[]).append(r)
        events=[]; unresolved=[]
        for t,acts in db.execute('SELECT id,actions FROM traces'):
            if t not in grouped: raise ValueError('orphan trace')
            es,u=classify(t,json.loads(acts),grouped[t],cutoff);events.extend(es)
            if u: unresolved.append(u)
        events.sort(key=lambda e:(e['time'],e['id']));unresolved.sort(key=lambda e:(e['time'],e['trace']))
        data={'schema':2,'token':MASTER,'cutoff':cutoff,'source':'Toncenter v3','audit':'single_provider_unverified','transfer_count':sum(len(r) for r in grouped.values()),'trace_count':len(grouped),'events':events,'unresolved':unresolved,'transfers':sorted([r for group in grouped.values() for r in group],key=lambda r:(r['time'],int(r['lt']),r['tx']))}
        data['digest']=digest(data)
    return data

def publish(data,path):
    tmp=path.with_suffix('.tmp');tmp.write_text(canonical(data)+'\n');os.replace(tmp,path)
def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,default=ROOT/'data/index.sqlite');p.add_argument('--out',type=Path,default=ROOT/'data/candidate.json');p.add_argument('--full',action='store_true');a=p.parse_args();a.db.parent.mkdir(parents=True,exist_ok=True);a.out.parent.mkdir(parents=True,exist_ok=True)
    if a.out.resolve()==(ROOT/'docs/snapshot.json').resolve() or (ROOT/'docs').resolve() in a.out.resolve().parents: p.error('public snapshot cannot be written by unaudited indexer')
    with open_db(a.db) as db: data=run(db,full=a.full)
    publish(data,a.out);print(f"{data['trace_count']} traces; {len(data['events'])} classified actions; {len(data['unresolved'])} unresolved traces")
if __name__=='__main__':main()
