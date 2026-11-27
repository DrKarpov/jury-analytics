import {readFileSync} from 'node:fs';
import {verifySnapshot} from '../docs/integrity.mjs';
const d=await verifySnapshot(JSON.parse(readFileSync(process.argv[2],'utf8')));
if(d.evidence?.mode!=='staging'||d.evidence.swap_audit.checked!==0||!d.evidence.seed_audit)throw Error('unsafe preview evidence');
console.log('Actual preview SHA-256 and operation mappings valid:',d.digest);
