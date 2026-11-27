import {validate} from './analytics.mjs';
import {validateExtension} from './wallets.mjs';
export const TOKEN='Ef-_fgHqEczCswLpnBEoIvgyruJUvn_QDt5QRjecY8w3lr2i';
// Same canonical JSON as Python for the candidate's restricted JSON domain.
export function canonical(v){if(v===null||typeof v==='boolean'||typeof v==='string')return JSON.stringify(v);if(typeof v==='number'){if(!Number.isSafeInteger(v))throw Error('unsafe number');return JSON.stringify(v)}if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';throw Error('invalid JSON value')}
export async function digest(v){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(v))))].map(n=>n.toString(16).padStart(2,'0')).join('')}
const hash=/^[a-f0-9]{64}$/;
export async function verifySnapshot(d){
 if(d?.token!==TOKEN)throw Error('wrong token');validateExtension(validate(d));
 if(d.cutoff===null){if(d.events.length||d.unresolved.length||d.evidence||d.digest||d.audit!=='not_indexed'||d.transfers?.length||d.transfer_count!==null||d.trace_count!==null)throw Error('invalid empty snapshot');return d}
 if(d.cutoff<=0||!hash.test(d.digest)||!Array.isArray(d.transfers)||!Number.isSafeInteger(d.trace_count))throw Error('missing history evidence');
 const {digest:expected,evidence,...candidate}=d;if(await digest(candidate)!==expected)throw Error('candidate digest mismatch');
 if(new Set(d.transfers.map(x=>x.trace)).size!==d.trace_count)throw Error('trace count mismatch');
 const traces=new Set(d.transfers.map(x=>x.trace)),seen=new Set();
 for(const r of d.transfers)if(!/^\d+$/.test(r.lt)||BigInt(r.lt)<=0n)throw Error('invalid LT');
 for(const e of d.events)if(!hash.test(e.id)||e.time<=0||BigInt(e.amount_raw)<=0n||(e.kind!=='transfer'&&BigInt(e.quote_raw)<=0n&&!(e.kind==='buy'&&e.quote_asset==='UNKNOWN'&&e.quote_raw==='0'&&e.quote_status==='unresolved')))throw Error('invalid operation');
 for(const u of d.unresolved){if(u.kind!=='unresolved'||!traces.has(u.trace)||seen.has(u.trace)||!Number.isSafeInteger(u.time)||u.time<=0||u.time>d.cutoff)throw Error('invalid unresolved trace');seen.add(u.trace)}
 if(evidence){
  if(!hash.test(evidence.digest))throw Error('missing evidence digest');
  const {digest:h,...rest}=evidence;
  if(await digest(rest)!==h)throw Error('evidence digest mismatch');
  if('revision_lineage' in evidence)lineageOf(d);
 }
 return d;
}
// Never silently discard known history, even if a new snapshot carries a valid checksum.
export function acceptNext(old,next){if(!old||old.cutoff===null)return next;if(next.cutoff===null||next.cutoff<old.cutoff)throw Error('snapshot rollback');const byTx=new Map(next.transfers.map(r=>[r.tx,r]));for(const r of old.transfers)if(!byTx.has(r.tx)||canonical(byTx.get(r.tx))!==canonical(r))throw Error('historical transfer changed');const prior=new Set(old.transfers.map(r=>r.tx));if(next.transfers.some(r=>r.time<=old.cutoff&&!prior.has(r.tx)))throw Error('late historical transfer');const byId=new Map(next.events.map(e=>[e.id,e]));for(const e of old.events)if(!byId.has(e.id)||canonical(byId.get(e.id))!==canonical(e))throw Error('historical classification changed');if(next.cutoff===old.cutoff&&next.digest!==old.digest)throw Error('same-cutoff candidate changed');return next}
// Strict append-only updates remain supported. Revisions require bound publisher lineage.
function traceStates(d){
 const m=new Map(),get=t=>{if(!m.has(t))m.set(t,{transfers:[],events:[],unresolved:null});return m.get(t)};
 for(const r of d.transfers)get(r.trace).transfers.push(r);
 for(const e of d.events)get(e.trace).events.push(e);
 for(const u of d.unresolved)get(u.trace).unresolved=u;
 for(const x of m.values()){x.transfers.sort((a,b)=>a.tx<b.tx?-1:a.tx>b.tx?1:0);x.events.sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0)}
 return m;
}
const emptyTrace=()=>({transfers:[],events:[],unresolved:null});
function lineageOf(d){
 const l=d.evidence?.revision_lineage;
 if(l?.version!==1||!hash.test(l.seed_digest)||!Array.isArray(l.heads)||!l.heads.length||l.heads[0].digest!==l.seed_digest||!l.transitions||typeof l.transitions!=='object'||Array.isArray(l.transitions))throw Error('missing revision provenance');
 const ids=new Map();let cutoff=0;
 for(const h of l.heads){if(!hash.test(h.digest)||ids.has(h.digest)||!Number.isSafeInteger(h.cutoff)||h.cutoff<=cutoff)throw Error('invalid history lineage');ids.set(h.digest,ids.size);cutoff=h.cutoff}
 if(l.heads.at(-1).digest!==d.evidence.history_head||cutoff!==d.cutoff)throw Error('lineage head mismatch');
 for(const [t,edges]of Object.entries(l.transitions)){
  if(!hash.test(t)||!Array.isArray(edges))throw Error('invalid trace transitions');
  for(const e of edges){if(!hash.test(e.from)||!hash.test(e.to)||e.from===e.to||!hash.test(e.source)||!ids.has(e.head)||!['update','repair'].includes(e.kind)||(e.kind==='update'&&e.source!==e.head))throw Error('invalid revision transition')}
 }
 return l;
}
export async function acceptRevision(old,next){
 if(!old||old.cutoff===null)return next;
 if(next.cutoff===null||next.cutoff<old.cutoff)throw Error('snapshot rollback');
 // Do not let a valid append-only path bypass an established lineage or unresolved revisions.
 if(old.evidence?.revision_lineage&&!next.evidence?.revision_lineage)throw Error('missing revision lineage');
 if(!old.evidence?.revision_lineage)return acceptNext(old,next);
 const a=lineageOf(old),b=lineageOf(next);
 if(a.seed_digest!==b.seed_digest||a.heads.length>b.heads.length||a.heads.some((h,i)=>canonical(h)!==canonical(b.heads[i])))throw Error('history lineage changed');
 const oldHead=a.heads.at(-1).digest,headIndex=new Map(b.heads.map((h,i)=>[h.digest,i])),start=headIndex.get(oldHead);
 const byTx=new Map(next.transfers.map(r=>[r.tx,r]));
 for(const r of old.transfers)if(!byTx.has(r.tx)||canonical(byTx.get(r.tx))!==canonical(r))throw Error('historical transfer changed');
 const prev=traceStates(old),now=traceStates(next);let changed=false;
 for(const [t,y] of now){
  const x=prev.get(t);
  if(!x&&y.transfers.every(r=>r.time>old.cutoff))continue;
  const before=x||emptyTrace();
  if(canonical(before)===canonical(y))continue;
  changed=true;
  const from=await digest(before),to=await digest(y);
  // Reachability in forward chronological order; no reverse repair or rollback.
  const reachable=new Set([from]);
  for(const e of b.transitions[t]||[]){
   if(e.kind==='update'&&headIndex.get(e.head)<=start)continue;
   if(e.kind==='repair'&&e.head!==b.heads.at(-1).digest)continue;
   if(reachable.has(e.from))reachable.add(e.to);
  }
  if(!reachable.has(to))throw Error('unproven historical trace revision');
 }
 if(next.cutoff===old.cutoff&&next.digest!==old.digest&&!changed)throw Error('unexplained same-cutoff revision');
 return next;
}
function database(){return new Promise((resolve,reject)=>{const r=indexedDB.open('jury-analytics-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('snapshots');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);r.onblocked=()=>reject(Error('cache blocked'))})}
async function cache(mode,value){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction('snapshots',mode),store=tx.objectStore('snapshots'),key='snapshot:'+location.pathname,r=mode==='readonly'?store.get(key):store.put(value,key);tx.oncomplete=()=>resolve(r.result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error)})}finally{db.close()}}
export const readCache=()=>cache('readonly');
// Staging evidence is not a production release. Cache isolation is path-specific.
export const writeCache=value=>cache('readwrite',value);
