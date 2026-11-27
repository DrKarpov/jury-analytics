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
 for(const e of d.events)if(!hash.test(e.id)||e.time<=0||BigInt(e.amount_raw)<=0n||(e.kind!=='transfer'&&BigInt(e.quote_raw)<=0n))throw Error('invalid operation');
 for(const u of d.unresolved){if(u.kind!=='unresolved'||!traces.has(u.trace)||seen.has(u.trace)||!Number.isSafeInteger(u.time)||u.time<=0||u.time>d.cutoff)throw Error('invalid unresolved trace');seen.add(u.trace)}
 if(evidence){if(!hash.test(evidence.digest))throw Error('missing evidence digest');const {digest:h,...rest}=evidence;if(await digest(rest)!==h)throw Error('evidence digest mismatch')}
 return d;
}
// Never silently discard known history, even if a new snapshot carries a valid checksum.
export function acceptNext(old,next){if(!old||old.cutoff===null)return next;if(next.cutoff===null||next.cutoff<old.cutoff)throw Error('snapshot rollback');const byTx=new Map(next.transfers.map(r=>[r.tx,r]));for(const r of old.transfers)if(!byTx.has(r.tx)||canonical(byTx.get(r.tx))!==canonical(r))throw Error('historical transfer changed');const prior=new Set(old.transfers.map(r=>r.tx));if(next.transfers.some(r=>r.time<=old.cutoff&&!prior.has(r.tx)))throw Error('late historical transfer');const byId=new Map(next.events.map(e=>[e.id,e]));for(const e of old.events)if(!byId.has(e.id)||canonical(byId.get(e.id))!==canonical(e))throw Error('historical classification changed');if(next.cutoff===old.cutoff&&next.digest!==old.digest)throw Error('same-cutoff candidate changed');return next}
function database(){return new Promise((resolve,reject)=>{const r=indexedDB.open('jury-analytics-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('snapshots');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);r.onblocked=()=>reject(Error('cache blocked'))})}
async function cache(mode,value){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction('snapshots',mode),store=tx.objectStore('snapshots'),key='snapshot:'+location.pathname,r=mode==='readonly'?store.get(key):store.put(value,key);tx.oncomplete=()=>resolve(r.result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error)})}finally{db.close()}}
export const readCache=()=>cache('readonly');
// Staging evidence is not a production release. Cache isolation is path-specific.
export const writeCache=value=>cache('readwrite',value);
