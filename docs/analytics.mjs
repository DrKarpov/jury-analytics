export const NANO=1000000000n;
export function range(period,cutoff,from,to){if(cutoff===null)return [0,0];if(period==='all')return [0,cutoff];if(period==='custom'){const a=Date.parse(from+'T00:00:00Z')/1000,b=Date.parse(to+'T00:00:00Z')/1000+86399;return Number.isFinite(a)&&Number.isFinite(b)&&a<=b&&a<=cutoff?[a,Math.min(b,cutoff)]:null}const durations={'6h':21600,'24h':86400,'7d':604800,'30d':2592000};return [Math.max(0,cutoff-durations[period]+1),cutoff]}
export function summarize(events,unresolved,interval){const [a,b]=interval;const selected=events.filter(x=>x.time>=a&&x.time<=b),unknown=unresolved.filter(x=>x.time>=a&&x.time<=b);let buy=0,sell=0,transfer=0,buyQty=0n,sellQty=0n,quote=0n;const wallets=new Map(),days=new Map();for(const x of selected){if(x.kind==='transfer'){transfer++;continue}const qty=BigInt(x.amount_raw);if(x.kind==='buy'){buy++;buyQty+=qty}else{sell++;sellQty+=qty}if(x.quote_asset==='GRAM')quote+=BigInt(x.quote_raw);let w=wallets.get(x.wallet)||{wallet:x.wallet,buy:0n,sell:0n,count:0};w[x.kind]+=qty;w.count++;wallets.set(x.wallet,w);const day=new Date(x.time*1000).toISOString().slice(0,10),d=days.get(day)||{day,buy:0,sell:0};d[x.kind]++;days.set(day,d)}return {selected,unknown,buy,sell,transfer,buyQty,sellQty,quote,wallets:[...wallets.values()].sort((a,b)=>{const x=a.buy+a.sell,y=b.buy+b.sell;return x>y?-1:x<y?1:a.wallet.localeCompare(b.wallet)}),days:[...days.values()].sort((a,b)=>a.day.localeCompare(b.day))}}
export function format(raw,locale='ru'){let x=BigInt(raw),sign=x<0n?'-':'';if(x<0n)x=-x;const whole=x/NANO,frac=(x%NANO).toString().padStart(9,'0').slice(0,2);return sign+whole.toLocaleString(locale)+(locale==='ru'?',':'.')+frac}
export function validate(data){if(data.schema!==2||!Array.isArray(data.events)||!Array.isArray(data.unresolved)||!(data.cutoff===null||Number.isSafeInteger(data.cutoff)))throw Error('Invalid snapshot');const ids=new Set();for(const e of data.events){if(ids.has(e.id)||!['buy','sell','transfer'].includes(e.kind)||!Number.isSafeInteger(e.time)||e.time>data.cutoff||!/^\d+$/.test(e.amount_raw)||!/^(-?\d+):[a-f0-9]{64}$/.test(e.wallet)||!(/^[a-f0-9]{64}$/).test(e.trace)||(!['transfer'].includes(e.kind)&&(!/^\d+$/.test(e.quote_raw)||typeof e.quote_asset!=='string')))throw Error('Invalid event');ids.add(e.id)}return data}
export function csv(rows) {
    const escapeCell = value => {
        const cell = String(value ?? '');
        const safe = /^[\t\r\n]|^\s*[=+@-]/u.test(cell) ? "'" + cell : cell;
        return '"' + safe.replaceAll('"', '""') + '"';
    };
    const fields = ['time_utc','type','wallet','destination','amount_raw','quote_asset','quote_raw','trace'];
    const values = rows.map(event => [
        new Date(event.time * 1000).toISOString(), event.kind, event.wallet, event.destination,
        event.amount_raw, event.quote_asset, event.quote_raw, event.trace
    ]);
    return [fields, ...values].map(row => row.map(escapeCell).join(',')).join('\r\n') + '\r\n';
}

// UTC-aligned buckets with explicit empty intervals. All-history mode starts at
// the earliest observed trade because its logical range starts at the Unix epoch.
export function tradeBuckets(rows, [start, end]) {
    const trades = rows.filter(row => (row.kind === 'buy' || row.kind === 'sell')
        && row.time >= start && row.time <= end);
    if (!trades.length) return [];
    if (start === 0) start = trades.reduce((earliest, row) => Math.min(earliest, row.time), end);
    const widths = [900, 1800, 3600, 7200, 21600, 43200, 86400, 604800, 2592000];
    const step = widths.find(width => end-start+1 <= width*24) ?? Math.ceil((end-start+1)/24);
    const anchor = Math.floor(start/step)*step;
    const count = Math.floor((end-anchor)/step)+1;
    const buckets = Array.from({length:count}, (_, i) => ({
        from:Math.max(start, anchor+i*step), to:Math.min(end, anchor+(i+1)*step-1), buy:0, sell:0
    }));
    for (const trade of trades) buckets[Math.floor((trade.time-anchor)/step)][trade.kind]++;
    return buckets;
}
