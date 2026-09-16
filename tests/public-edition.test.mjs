import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {apply} from '../runtime/toolkit-plugin/index.mjs';
import {presentFiles} from '../runtime/toolkit-plugin/delivery.mjs';

test('public plugin retains business tools but exposes no removed authoring engine', () => {
 const names=[];
 const ctx={tools:{register:t=>names.push(t.name)},userQuestions:{}};
 apply(ctx);
 for(const name of ['toolkit_invoices','toolkit_dashboard','toolkit_print','toolkit_clean'])assert.ok(names.includes(name),name);
 assert.ok(!names.some(name=>name.startsWith('presentation_')));
 assert.ok(!fs.existsSync(new URL('../runtime/toolkit-plugin/presentation/vendor',import.meta.url)));
});
test('artifact delivery survives engine removal and reports errors', async () => {
 const ctx={tools:{get:()=>true,execute:async()=>({additionalContexts:['context']})}};
 const deferred=[];const exec={agent:'test',deferContext:v=>deferred.push(v)};
 assert.equal((await presentFiles(ctx,exec,[{path:'example.docx'}])).status,'presented');
 assert.deepEqual(deferred,['context']);
 ctx.tools.get=()=>false;
 await assert.rejects(presentFiles(ctx,exec,[]),/没有 DSH present/);
});
