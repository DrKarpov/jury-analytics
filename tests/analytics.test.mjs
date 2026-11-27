import assert from 'node:assert/strict';import {range,summarize,format,csv}from'../docs/analytics.mjs';
const e={time:100,kind:'buy',wallet:'w',amount_raw:'1000000001',quote_asset:'GRAM',quote_raw:'2000000000',trace:'t'};const s=summarize([e,{...e,time:101,kind:'sell'}],[],[100,100]);assert.equal(s.buy,1);assert.equal(s.sell,0);assert.equal(s.buyQty,1000000001n);assert.equal(s.quote,2000000000n);assert.equal(format(-1000000001n,'en'),'-1.00');assert.deepEqual(range('6h',30000),[8401,30000]);assert.match(csv([e]),/1000000001/);console.log('7 analytics assertions passed');

const hostile = csv([{...e, quote_asset:' \t=1+1', wallet:'-1:'+'a'.repeat(64)}]);
assert.ok(hostile.includes("\"' \t=1+1\""));
assert.ok(hostile.includes("\"'-1:"));

const {tradeBuckets}=await import('../docs/analytics.mjs');
const series=tradeBuckets([
    {kind:'buy',time:100}, {kind:'sell',time:900}, {kind:'transfer',time:901}, {kind:'buy',time:1900}
],[100,1799]);
assert.deepEqual(series,[{from:100,to:899,buy:1,sell:0},{from:900,to:1799,buy:0,sell:1}]);
assert.deepEqual(tradeBuckets([{kind:'transfer',time:1}],[1,10]),[]);
