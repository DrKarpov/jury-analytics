import{renderWallets}from'./wallet-ui.mjs';
import{verifySnapshot,acceptRevision,readCache,writeCache}from'./integrity.mjs';
import{range,summarize,format,csv,tradeBuckets}from'./analytics.mjs';
const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
const words={ru:{all:'Все',history:'Доступная история',custom:'Период',from:'С',to:'По',empty:'Нет подтверждённых данных',pending:'Не индексировано',indexed:'Не сверено',notice:'История ещё не загружена. Показатели появятся после работы индексатора.',notice2:'Покрытие истории JURY неполное. Показатели рассчитаны по доступным распознанным операциям.',buy:'Покупки',sell:'Продажи',transfer:'Переводы',unresolved:'Не распознано (трейсы)',buyQty:'Куплено JURY',sellQty:'Продано JURY',volume:'Оборот пар с GRAM',chart:'Торговая активность',wallets:'Торговые кошельки',wallet:'Кошелёк',net:'Нетто JURY',tx:'Операции',type:'Тип',amount:'JURY',date:'Дата UTC',more:'Показать ещё',footer:'Независимый дашборд JURY.',contract:'Контракт',error:'Не удалось загрузить данные',invalid:'Укажите корректный период',count:'адресов'},en:{all:'All',history:'Available history',custom:'Custom',from:'From',to:'To',empty:'No confirmed data',pending:'Not indexed',indexed:'Not audited',notice:'History has not been collected yet. Metrics appear after indexing.',notice2:'JURY history coverage is incomplete. Metrics use the available classified operations.',buy:'Buys',sell:'Sells',transfer:'Transfers',unresolved:'Unresolved traces',buyQty:'JURY bought',sellQty:'JURY sold',volume:'GRAM-pair volume',chart:'Trading activity',wallets:'Trading wallets',wallet:'Wallet',net:'Net JURY',tx:'Operations',type:'Type',amount:'JURY',date:'Date UTC',more:'Show more',footer:'Independent JURY dashboard.',contract:'Contract',error:'Could not load data',invalid:'Select a valid date range',count:'addresses'}};
const labels={
    ru:{overview:'Обзор',market:'Обзор рынка',quality:'Качество данных',wallets:'Кошельки',holders:'Держатели',query:'Адрес или хеш трассы',through:'Данные до',shown:'Строк'},
    en:{overview:'Overview',market:'Market overview',quality:'Data quality',wallets:'Wallets',holders:'Holders',query:'Address or trace hash',through:'Data through',shown:'Rows'}
};
let currentSummary, hasSelection=false;
let lang=localStorage.getItem('jury-lang')==='en'?'en':'ru',period='all',filter='all',limit=30,data=null,exportRows=[],loadState='',loading=false;
const t=k=>words[lang][k]||k,fmt=x=>format(x,lang),num=x=>x.toLocaleString(lang),short=x=>x.slice(0,7)+'…'+x.slice(-5),date=x=>new Date(x*1000).toISOString().slice(0,16).replace('T',' ');
function link(text,href){let a=el('a',text);a.href=href;a.target='_blank';a.rel='noopener noreferrer';return a}
function table(root,headers,rows){root.replaceChildren();if(!rows.length){root.append(el('p',t('empty'),'empty'));return}let a=el('table',undefined,'table'),head=el('thead'),hr=el('tr');for(const h of headers)hr.append(el('th',h));head.append(hr);a.append(head);const body=el('tbody');for(const row of rows){let tr=el('tr');for(const value of row){let td=el('td');td.append(value instanceof Node?value:document.createTextNode(value));tr.append(td)}body.append(tr)}a.append(body);root.append(a)}
function chart(summary, interval) {
    const root = $('chart'), reading = $('chart-reading');
    root.replaceChildren();
    reading.textContent = '';
    const buckets = tradeBuckets(summary.selected, interval);
    if (!buckets.length) {
        root.append(el('p', t('empty'), 'empty'));
        return;
    }
    const ns = 'http://www.w3.org/2000/svg';
    const make = (tag, props, content) => {
        const elem = document.createElementNS(ns, tag);
        for (const [key, value] of Object.entries(props)) elem.setAttribute(key, value);
        if (content !== undefined) elem.textContent = content;
        return elem;
    };
    const svg = make('svg', {viewBox:'0 0 640 245', role:'group', 'aria-label':t('chart')});
    const max = Math.max(...buckets.flatMap(row => [row.buy, row.sell]));
    const tick = Math.max(1, Math.ceil(max / 4)), scale = tick * 4;
    const width = 568 / buckets.length;
    for (let i = 0; i <= 4; i++) {
        const y = 198 - i * 44;
        svg.append(make('line', {x1:52,y1:y,x2:620,y2:y,stroke:'#343437'}));
        svg.append(make('text', {x:46,y:y+4,'text-anchor':'end',fill:'#aaaab0','font-size':14}, num(i*tick)));
    }
    const describe = row => `${date(row.from)} – ${date(row.to)} UTC · ${t('buy')} ${num(row.buy)} · ${t('sell')} ${num(row.sell)}`;
    const groups = [];
    buckets.forEach((row, i) => {
        const x = 52 + i * width;
        const group = make('g', {class:'chart-bucket',role:'button',tabindex:i===buckets.length-1?0:-1,'aria-label':describe(row)});
        for (const [side, offset, color] of [['buy',.13,'#39d98a'], ['sell',.51,'#ff626d']]) {
            const height = row[side] / scale * 176;
            group.append(make('rect', {x:x+width*offset,y:198-height,width:width*.33,height,fill:color,rx:2}));
        }
        group.append(make('rect', {x,y:18,width,height:180,class:'chart-target'}));
        const show = () => {reading.textContent = describe(row);};
        group.addEventListener('pointerenter', show);
        group.addEventListener('focus', show);
        group.addEventListener('click', () => { group.focus(); show(); });
        group.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                show();
                return;
            }
            const offset = {ArrowLeft:-1,ArrowRight:1}[event.key];
            if (offset === undefined) return;
            event.preventDefault();
            const next = groups[i+offset];
            if (next) {
                group.tabIndex = -1;
                next.tabIndex = 0;
                next.focus();
            }
        });
        groups.push(group);
        svg.append(group);
        if (i % Math.ceil(buckets.length / 4) === 0) {
            const label = date(buckets[0].from).slice(0,10)===date(buckets.at(-1).to).slice(0,10)
                ? date(row.from).slice(11)
                : date(row.from).slice(5,10);
            svg.append(make('text', {x:x+width/2,y:226,'text-anchor':'middle',fill:'#aaaab0','font-size':15}, label));
        }
    });
    reading.textContent = describe(buckets.at(-1));
    root.append(svg);
}

function renderOperations() {
    const s=currentSummary;
    if (!s) return;
    const query=$('operation-query').value.trim().toLowerCase();
    const combined=[...s.selected,...s.unknown]
        .filter(row => (filter==='all'||filter===row.kind)
            && (!query || [row.trace,row.wallet,row.destination,row.transfer_tx].some(value => typeof value === 'string' && value.toLowerCase().includes(query))))
        .sort((a,b)=>b.time-a.time);
    const rows=combined.slice(0,limit).map(row => {
        const kind=el('span',t(row.kind),row.kind==='buy'?'buy':row.kind==='sell'?'sell':'');
        if (typeof row.venue==='string') kind.append(el('small',row.venue,'operation-meta'));
        const amount=el('span',row.amount_raw?fmt(row.amount_raw):'—');
        if (row.quote_asset==='GRAM') amount.append(el('small',fmt(row.quote_raw)+' GRAM','operation-meta'));
        return [
            link(date(row.time),'https://tonviewer.com/transaction/'+row.trace),
            kind,
            row.wallet?link(short(row.wallet),'https://tonviewer.com/'+row.wallet):'—',
            amount
        ];
    });
    table($('transactions'),[t('date'),t('type'),t('wallet'),t('amount')],rows);
    $('operation-count').textContent=hasSelection?`${labels[lang].shown} ${num(rows.length)} / ${num(combined.length)}`:'';
    $('more').hidden=combined.length<=limit;
    exportRows=hasSelection?combined:[];
    $('export').disabled=!exportRows.length;
}
function render(){document.documentElement.lang=lang;
const copy=labels[lang];
for(const [id,key] of [['nav-overview','overview'],['overview-title','market'],['nav-wallets','wallets'],['nav-holders','holders'],['quality-title','quality']])$(id).textContent=copy[key];
$('nav-operations').textContent=t('tx');
$('available-history').textContent=t('history');
$('operation-query').placeholder=copy.query;
$('operation-query').setAttribute('aria-label',copy.query);
$('language').textContent=lang==='ru'?'EN':'RU';for(const [id,k]of [['custom-label','custom'],['from-label','from'],['to-label','to'],['chart-title','chart'],['buy-legend','buy'],['sell-legend','sell'],['wallet-title','wallets'],['tx-title','tx'],['footer-text','footer'],['contract','contract'],['more','more']])$(id).textContent=t(k);for(const b of $('periods').querySelectorAll('button'))b.setAttribute('aria-pressed',String(b.dataset.period===period));$('custom').hidden=period!=='custom';const ready=data?.cutoff!=null,interval=ready?range(period,data.cutoff,$('from').value,$('to').value):[0,0];$('status').textContent=t(ready?'indexed':'pending');$('notice').textContent=(!data?t('error'):!interval?t('invalid'):t(ready?'notice2':'notice'))+(ready&&data.evidence?.mode==='public_beta'?(lang==='ru'?` • История до ${date(data.cutoff)} UTC.`:` • History through ${date(data.cutoff)} UTC.`):'')+(loadState==='fallback'?(lang==='ru'?' • Сохранённая версия: обновление не прошло проверку.':' • Cached version: refresh failed validation.'):'');if(ready&&data.evidence?.mode==='public_beta'&&Date.now()/1000-data.cutoff>HISTORY_STALE_SECONDS)$('notice').append(lang==='ru'?' • Данные старше 45 минут.':' • Data is over 45 minutes old.');const s=summarize(data?.events||[],data?.unresolved||[],interval||[1,0]);const hasPeriod=ready&&interval;
$('data-cutoff').textContent=ready?`${copy.through} ${date(data.cutoff)} UTC`:'';
$('chart-period').textContent=hasPeriod?period==='all'?t('history'):`${date(interval[0])} – ${date(interval[1])} UTC`:'';
$('metrics').replaceChildren();for(const [k,v,c,u]of [['buy',num(s.buy),'buy',''],['sell',num(s.sell),'sell',''],['transfer',num(s.transfer),'',''],['buyQty',fmt(s.buyQty),'buy','JURY'],['sellQty',fmt(s.sellQty),'sell','JURY'],['volume',fmt(s.quote),'','GRAM']]){const a=el('article',undefined,'card');a.append(el('span',t(k),'muted'),el('strong',hasPeriod?v:'—','metric '+c));if(u)a.append(el('span',u,'muted'));$('metrics').append(a)}$('quality-unresolved').textContent=hasPeriod?`${t('unresolved')} · ${num(s.unknown.length)}`:'';chart(s,interval||[1,0]);$('wallet-sub').textContent=hasPeriod?`${num(s.wallets.length)} ${t('count')}`:'';table($('wallets'),[t('wallet'),t('buy'),t('sell'),t('net')],s.wallets.slice(0,20).map(w=>[link(short(w.wallet),'https://tonviewer.com/'+w.wallet),fmt(w.buy),fmt(w.sell),el('span',fmt(w.buy-w.sell),w.buy>w.sell?'buy':w.buy<w.sell?'sell':'')]));$('filters').replaceChildren();for(const k of ['all','buy','sell','transfer','unresolved']){const b=el('button',t(k));b.setAttribute('aria-pressed',String(filter===k));b.addEventListener('click',()=>{filter=k;limit=30;for(const button of $('filters').children)button.setAttribute('aria-pressed',String(button===b));renderOperations()});$('filters').append(b)}currentSummary=s;hasSelection=Boolean(hasPeriod);renderOperations();renderWallets({data,interval,lang,table,el,link,short})}
$('language').addEventListener('click',()=>{lang=lang==='ru'?'en':'ru';localStorage.setItem('jury-lang',lang);render()});$('periods').addEventListener('click',e=>{if(e.target.dataset.period){period=e.target.dataset.period;limit=30;render()}});for(const id of ['from','to'])$(id).addEventListener('change',render);$('more').addEventListener('click',()=>{limit+=30;renderOperations()});
$('operation-query').addEventListener('input',()=>{limit=30;renderOperations()});$('export').addEventListener('click',()=>{if(!exportRows.length)return;const blob=new Blob([csv(exportRows)],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='jury-operations.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});

const HISTORY_STALE_SECONDS = 45 * 60;
const releaseMatches = (release, snapshot) => snapshot?.cutoff === release.cutoff
    && snapshot.digest === release.snapshot_digest
    && snapshot.evidence?.digest === release.evidence_digest;

async function checkRelease() {
    const response = await fetch('release.json', {cache: 'no-store'});
    if (response.status === 404 && !data?.evidence?.release) return null; // Legacy releases.
    if (!response.ok) throw Error('Release manifest unavailable');
    const manifest = await response.json();
    const hash = /^[a-f0-9]{64}$/;
    if (manifest?.version !== 1 || !Number.isSafeInteger(manifest.cutoff) || manifest.cutoff <= 0
            || !hash.test(manifest.snapshot_digest) || !hash.test(manifest.evidence_digest)) {
        throw Error('Invalid release manifest');
    }
    if (data?.cutoff && manifest.cutoff < data.cutoff) throw Error('Release rollback');
    return manifest;
}

function setDefaultDates() {
    if (!data?.cutoff) return;
    const day = new Date(data.cutoff * 1000).toISOString().slice(0, 10);
    if (!$('from').value) $('from').value = day;
    if (!$('to').value) $('to').value = day;
}

async function load() {
    if (loading) return;
    loading = true;
    try {
        if (!data) {
            try {
                const saved = await readCache();
                if (saved) {
                    data = await verifySnapshot(saved);
                    setDefaultDates();
                    loadState = 'fallback';
                    render();
                }
            } catch (error) {
                console.warn('Cache unavailable or invalid', error);
            }
        }
        const manifest = await checkRelease();
        if (!manifest || !releaseMatches(manifest, data)) {
            const response = await fetch('snapshot.json', {cache: 'no-store'});
            if (!response.ok) throw Error('Snapshot unavailable');
            const next = await verifySnapshot(await response.json());
            if (manifest ? !releaseMatches(manifest, next) : next.evidence?.release) {
                throw Error('Snapshot does not match release');
            }
            data = await acceptRevision(data, next);
            setDefaultDates();
            if (data.cutoff) {
                try {
                    await writeCache(data);
                } catch (error) {
                    console.warn('Cache unavailable', error);
                }
            }
        }
        loadState = '';
    } catch (error) {
        console.error(error);
        loadState = data ? 'fallback' : '';
    } finally {
        loading = false;
        render();
    }
}

load();
setInterval(() => { if (!document.hidden) load(); }, 900000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
