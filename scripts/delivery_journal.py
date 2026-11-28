"""Deterministic double-entry journal for proven deliveries, in nano-JURY.

This is a shadow journal of accounted observations, not a balance or supply
certificate. Unpaired, failed, bounced and burn evidence is not guessed.
"""
import re
from collections import Counter,defaultdict
from continuation_shadow import require
from indexer import TOKEN,digest,integer
from wallet_history import graph,successful,valid_internal,INTERNAL

RULE='delivery_journal_v1'
MASTER_ACCOUNT='external:master_distributions'

def signed_delta(value):
    """Journal deltas are signed; external token amounts remain unsigned."""
    if type(value) is not str or not re.fullmatch(r'0|-?[1-9][0-9]*',value):
        raise ValueError('invalid signed journal delta')
    return int(value)

def build(obs,roots,emissions,receipts,cutoff):
    states=defaultdict(lambda:{'rows':[]})
    for w,r in obs.rows.values():
        require(r['time']<=cutoff,'ledger observation exceeds cutoff')
        states[w]['rows'].append(r)
    linked,_,_,matched=graph(states,roots)
    projection=obs.project(roots)
    entries={};gaps={};used=set()
    def gap(kind,identifier,**fields):
        k=kind+':'+identifier
        value={'kind':kind,'id':identifier,**fields}
        require(k not in gaps or gaps[k]==value,'conflicting unresolved observation')
        gaps[k]=value
    def post(mid,phase,kind,tx,lt,stamp,debit,credit,amount):
        require(0<stamp<=cutoff and integer(lt)>0 and amount>0 and debit!=credit,'invalid journal posting')
        k=mid+':'+phase
        require(k not in entries,'duplicate journal event')
        entries[k]={'id':k,'message':mid,'kind':kind,'tx':tx,'lt':str(lt),'time':stamp,
                    'postings':[{'account':debit,'delta_raw':str(-amount)},{'account':credit,'delta_raw':str(amount)}]}
    def transit(mid):return 'transit:'+mid
    for ev in projection['events']:
        mid=ev['id'];require(mid not in used,'duplicate movement');used.add(mid)
        src,dst=ev['source_wallet'],ev['destination_wallet']
        send=obs.rows[ev['sender_tx']][1];recv=obs.rows[ev['recipient_tx']][1]
        q=integer(ev['amount_raw'])
        post(mid,'send','paired_internal_send',send['tx'],send['lt'],send['time'],src,transit(mid),q)
        post(mid,'receive','paired_internal_receive',recv['tx'],recv['lt'],recv['time'],transit(mid),dst,q)
    receipt_rows=set()
    for mid,msg in sorted(emissions.items()):
        require(mid==msg['message'] and not msg['master_aborted'] and integer(msg['master_at'])<=cutoff,'wrong master emission')
        require(mid not in used,'message overlaps internal and master delivery')
        q=integer(msg['amount_raw']);require(q>0,'invalid master distribution amount')
        proof=receipts.get(mid)
        if proof is None or integer(proof['recipient_at'])>cutoff:
            gap('master_delivery_unposted',mid,wallet=msg['wallet'],amount_raw=str(q),reason='receipt_not_in_scope')
            continue
        require(proof['message']==mid and proof['wallet']==msg['wallet'] and proof['amount_raw']==msg['amount_raw'],'master receipt mismatch')
        found=obs.rows.get(proof['recipient_tx'])
        if found is None:
            gap('master_delivery_unposted',mid,wallet=msg['wallet'],amount_raw=str(q),reason='recipient_prefix_missing')
            continue
        w,r=found;m=r['in']
        require(w==msg['wallet'] and successful(r) and m and m['hash']==mid and m['source']==TOKEN
                and m['destination']==w and m['bounced'] is False and m['token_opcode']==INTERNAL
                and m['amount_raw']==msg['amount_raw'] and r['lt']==integer(proof['recipient_lt'])
                and r['time']==integer(proof['recipient_at']) and r['lt']>integer(msg['master_lt']),
                'master delivery differs from account chain')
        used.add(mid);receipt_rows.add(r['tx'])
        # Master distribution is an observed source, not a supply delta.
        post(mid,'send','master_distribution_send',msg['master_tx'],msg['master_lt'],integer(msg['master_at']),MASTER_ACCOUNT,transit(mid),q)
        post(mid,'receive','master_distribution_receive',r['tx'],r['lt'],r['time'],transit(mid),w,q)
    require(set(receipts)<=set(emissions),'orphan master receipt')
    for w in sorted(linked):
        for r in states.get(w,{}).get('rows',[]):
            for side,msgs,direction in (('incoming',[r['in']],'destination'),('outgoing',r['out'],'source')):
                for m in msgs:
                    if not m:continue
                    op=m['token_opcode'];mid=m['hash']
                    info={'wallet':w,'side':side,'tx':r['tx'],'message':mid,'opcode':op,'amount_raw':m['amount_raw']}
                    if op and (not successful(r) or m['bounced'] is not False):
                        gap('failed_bounced_or_unknown_token_message',r['tx']+':'+side+':'+mid,**info)
                    elif op in ('0x595f07bc','0x7bdd97de'):
                        gap('burn_semantics_unverified',r['tx']+':'+side+':'+mid,**info)
                    elif successful(r) and valid_internal(m,w,direction) and mid not in matched:
                        gap('unpaired_internal_'+side,mid,**info)
                    elif op==INTERNAL and mid not in used and not valid_internal(m,w,direction):
                        gap('unsupported_internal_'+side,r['tx']+':'+mid,**info)
    ordered=sorted(entries.values(),key=lambda e:(integer(e['lt']),e['id']))
    totals=defaultdict(int);negative=set();minima=defaultdict(int)
    for e in ordered:
        require(sum(signed_delta(x['delta_raw']) for x in e['postings'])==0,'unbalanced journal entry')
        for x in e['postings']:
            ac=x['account'];totals[ac]+=signed_delta(x['delta_raw'])
            if ac in linked:
                minima[ac]=min(minima[ac],totals[ac])
                if totals[ac]<0:negative.add(ac)
    require(sum(totals.values())==0,'journal conservation failure')
    require(all(v==0 for k,v in totals.items() if k.startswith('transit:')),'paired transit does not close')
    wallet_totals={w:str(totals[w]) for w in sorted(linked)}
    accounted=sum(signed_delta(v) for v in wallet_totals.values())
    external=-totals.get(MASTER_ACCOUNT,0)
    require(accounted==external,'wallet posting total differs from source postings')
    exceptions=[gaps[k] for k in sorted(gaps)]
    return {'version':1,'rule':RULE,'cutoff':cutoff,'projection_digest':digest(projection),
            'linked_accounts':len(linked),'paired_internal_deliveries':len(matched),
            'master_deliveries_posted':len(receipt_rows),'master_distribution_raw':str(external),
            'accounted_wallet_net_raw':str(accounted),'journal_entry_count':len(ordered),
            'unresolved_counts':dict(Counter(g['kind'] for g in exceptions)),
            'wallets_with_negative_running_net':len(negative),
            'wallets_with_negative_ending_net':sum(signed_delta(v)<0 for v in wallet_totals.values()),
            'journal':ordered,'unresolved':exceptions,'wallet_net_raw':wallet_totals,
            'negative_running_minima_raw':{w:str(minima[w]) for w in sorted(negative)},
            'scope':'paired delivery postings only; negative observed nets indicate incomplete or unsupported accounting, not actual negative balances; no burn/supply/owner/balance certification'}

def compact(result):
    return {**{k:v for k,v in result.items() if k not in ('journal','unresolved','wallet_net_raw','negative_running_minima_raw')},
            'journal_digest':digest(result['journal']),'unresolved_digest':digest(result['unresolved']),
            'wallet_net_digest':digest(result['wallet_net_raw']),'result_digest':digest(result)}

def preserve(old,new):
    current={e['id']:e for e in new['journal']}
    require(all(current.get(e['id'])==e for e in old['journal']),'unified journal changed historical posting')

def repair_plan(result,obs,anchor,states,regular,peer,proofs):
    """Route unresolved evidence without interpreting it as a balance change."""
    isolated={(x['edge']['side'],x['edge']['message']):x for x in proofs.values()}
    tasks=[];wallets=defaultdict(list)
    negative=result['negative_running_minima_raw']
    for g in result['unresolved']:
        task=dict(g);w=g.get('wallet');tx=g.get('tx')
        if w in negative:task['negative_running_net_wallet']=True
        if g['kind'] in ('unpaired_internal_incoming','unpaired_internal_outgoing'):
            account,row=obs.rows[tx]
            require(account==w,'repair task wallet mismatch')
            side=g['side'];mid=g['message']
            messages=[row['in']] if side=='incoming' else row['out']
            matches=[m for m in messages if m and m['hash']==mid]
            require(len(matches)==1,'repair task message not unique')
            m=matches[0];other=m['source' if side=='incoming' else 'destination']
            require(valid_internal(m,w,'destination' if side=='incoming' else 'source'),'invalid repair task message')
            task.update(peer=other,lt=str(row['lt']),time=row['time'])
            captured=isolated.get((side,mid))
            if captured:
                require(captured['edge']['peer']==other and captured['edge']['transaction']==tx,'repair counterpart identity mismatch')
                task['counterpart_digest']=captured['digest']
                task['counterpart_tx']=captured['counterpart']['tx']
            if captured and captured['counterpart']['tx'] in obs.rows:
                task['route']='inspect_observed_counterpart_conflict'
            elif row['time']<=anchor:
                task['route']='historical_message_closure'
            elif other in peer:
                task['route']='refresh_peer_prefix'
            elif states.get(other,{}).get('complete') and states[other]['rows']:
                task['route']='refresh_regular_cursor' if other in regular else 'start_regular_cursor'
            elif captured:
                task['route']='acquire_counterpart_prefix'
            else:
                task['route']='capture_exact_counterpart'
        elif g['kind']=='master_delivery_unposted':
            task['route']='resolve_master_receipt_or_prefix'
        else:
            task['route']='inspect_raw_execution_and_state'
        tasks.append(task)
        if w:wallets[w].append(task)
    tasks.sort(key=lambda x:(x['kind'],x['id']))
    accounts=[]
    for w,minimum in sorted(negative.items()):
        related=wallets[w]
        inbound=[x for x in related if x['kind']=='unpaired_internal_incoming']
        accounts.append({'wallet':w,'minimum_running_net_raw':minimum,
                         'ending_net_raw':result['wallet_net_raw'][w],
                         'unresolved_observations':len(related),
                         'unpaired_incoming_observations':len(inbound),
                         'routes':dict(Counter(x['route'] for x in related))})
    return {'tasks':tasks,'negative_net_accounts':accounts,
            'route_counts':dict(Counter(x['route'] for x in tasks)),
            'negative_accounts_without_local_unresolved':sum(not x['unresolved_observations'] for x in accounts),
            'scope':'diagnostic routing of unresolved journal observations; no inferred accounting, owner or actual balance'}
