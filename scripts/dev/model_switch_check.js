// Model switching and handoff check against the scratch server (fake runner only).
// Drives the chat UI through five scenarios and records what the fake runner
// receives; read it with scripts/dev/model_switch_log.py.
//   1  switch models between turns in one chat (history, unload, caption, label)
//   2  switch while a reply is still streaming
//   3  switch to a model the RAM guard refuses, then recover
//   4  the same inside a project (folder) chat, including reopening it
//   5  a tool-calling turn, handed to a model on the other tool path and back
//
//   scripts/dev/scratch_server.sh start
//   NODE_PATH=<dir with puppeteer-core>/node_modules \
//     node scripts/dev/model_switch_check.js OUT_DIR [scenario]
//   python3 scripts/dev/model_switch_log.py
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const OUT = process.argv[2] || '.';
const ONLY = process.argv[3] ? Number(process.argv[3]) : 0;
const LOG = process.env.DMR_LOG || '/tmp/odysseus-scratch/dmr.jsonl';
const nlines = () => (fs.existsSync(LOG) ? fs.readFileSync(LOG, 'utf8').split('\n').filter(Boolean).length : 0);
const marks = [];
const step = name => { marks.push({ name, at: nlines() }); console.log('\n== ' + name); };

(async () => {
  const browser = await puppeteer.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: 'new' });
  const page = await browser.newPage();
  await page.setViewport({ width: 1320, height: 860 });
  const errs = [];
  page.on('pageerror', e => errs.push('pageerror: ' + e.message));
  page.on('dialog', d => { errs.push('dialog: ' + d.message()); d.dismiss(); });

  const load = async () => { await page.goto('http://127.0.0.1:7863/', { waitUntil: 'networkidle2' }); await sleep(2500); };
  const pickerLabel = () => page.evaluate(() => (document.getElementById('model-picker-btn') || {}).textContent?.trim().replace(/\s+/g, ' '));
  const pick = async key => {
    await page.evaluate(() => document.getElementById('model-picker-btn').click());
    await sleep(500);
    await page.evaluate(() => { const t = document.querySelector('[data-mp-tab="all"]'); if (t) t.click(); });
    for (let i = 0; i < 20; i++) { if (await page.evaluate(() => document.querySelectorAll('.mp-model-name').length)) break; await sleep(400); }
    const ok = await page.evaluate(k => { const n = [...document.querySelectorAll('.mp-model-name')].find(x => x.textContent.includes(k)); if (!n) return false; n.closest('[class]').click(); return true; }, key);
    await sleep(900);
    console.log(`  pick ${key}: ${ok ? 'clicked' : 'NOT FOUND'} -> picker shows "${await pickerLabel()}"`);
    return ok;
  };
  const send = async text => { await page.focus('#message'); await page.keyboard.type(text); await page.keyboard.press('Enter'); };
  const lastAiText = () => page.evaluate(() => { const a = [...document.querySelectorAll('#chat-history .msg-ai')]; return a.length + '|' + (a.length ? a[a.length - 1].innerText : ''); });
  const waitIdle = async (max = 20000) => {
    const t0 = Date.now(); let prev = '', same = 0;
    while (Date.now() - t0 < max) {
      const cur = await lastAiText();
      same = cur === prev ? same + 1 : 0; prev = cur;
      if (same >= 4 && !/^0\|/.test(cur)) return;
      await sleep(500);
    }
  };
  const snap = async label => {
    const rows = await page.evaluate(() => [...document.querySelectorAll('#chat-history > *')].map(el => {
      const cls = String(el.className).split(/\s+/).filter(c => /^msg/.test(c)).join('.');
      const role = (el.querySelector('.role') || {}).textContent;
      const body = (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 110);
      return { cls, role: role ? role.trim() : '', body };
    }).filter(r => r.cls));
    const sess = await page.evaluate(async () => { const r = await fetch('/api/sessions'); const j = await r.json(); return (Array.isArray(j) ? j : j.sessions || []).map(s => ({ id: s.id.slice(0, 6), model: s.model, folder: s.folder })); });
    console.log(`  [${label}] picker="${await pickerLabel()}" sessions=${JSON.stringify(sess)}`);
    rows.forEach(r => console.log(`    ${r.cls.padEnd(18)} ${r.role ? '[' + r.role + '] ' : ''}${r.body}`));
    return rows;
  };

  await load();

  if (!ONLY || ONLY === 1) {
    step('S1 plain chat: small-chat -> big-chat -> small-chat');
    await pick('small-chat');
    await send('Remember the code word PINEAPPLE.'); await waitIdle();
    await snap('after turn 1 (small-chat)');
    step('S1 switch to big-chat (idle, between turns)');
    await pick('big-chat');
    await snap('right after switch');
    step('S1 turn 2 on big-chat');
    await send('What was my code word?'); await waitIdle();
    await snap('after turn 2 (big-chat)');
    step('S1 switch back to small-chat, turn 3');
    await pick('small-chat');
    await send('And what did the other model say?'); await waitIdle();
    await snap('after turn 3 (small-chat)');
    step('S1 reload page');
    await load(); await sleep(1000);
    await snap('after reload (session list loads latest?)');
  }

  if (!ONLY || ONLY === 2) {
    step('S2 switch while a reply is streaming');
    await load();
    await pick('big-chat');
    await send('SLOWTEST count to three'); await sleep(1700);
    console.log('  (mid-stream) switching to small-chat now');
    await pick('small-chat');
    await waitIdle(15000);
    await snap('after mid-stream switch finished');
    step('S2 next turn after the mid-stream switch');
    await send('follow up after mid-stream switch'); await waitIdle();
    await snap('after follow-up');
  }

  if (!ONLY || ONLY === 3) {
    step('S3 switch to a model the RAM guard refuses (vllm-coder)');
    await pick('vllm-coder');
    await send('hello refused model'); await sleep(6000);
    await snap('after sending to refused model');
    step('S3 recover: switch back to big-chat');
    await pick('big-chat');
    await send('recovered?'); await waitIdle();
    await snap('after recovery turn');
  }

  if (!ONLY || ONLY === 4) {
    step('S4 project chat: move current chat into a project, reopen, switch models');
    const sid = await page.evaluate(async () => { const r = await fetch('/api/sessions'); const j = await r.json(); const l = Array.isArray(j) ? j : j.sessions; return l[0].id; });
    await page.evaluate(async id => { const fd = new FormData(); fd.append('folder', 'Proj1'); await fetch('/api/session/' + id, { method: 'PATCH', body: fd }); }, sid);
    await load();
    const opened = await page.evaluate(id => { const el = document.querySelector(`.list-item[data-session-id="${id}"]`); if (el) { el.click(); return true; } return false; }, sid);
    await sleep(2500);
    console.log('  opened project chat from sidebar:', opened);
    await snap('project chat opened');
    await pick('small-chat');
    await send('inside the project, what was the code word?'); await waitIdle();
    await snap('project chat after switch + send');
    await pick('big-chat');
    await send('and again on the other model'); await waitIdle();
    await snap('project chat after second switch');
    step('S4 reopen project chat after reload');
    await load();
    await page.evaluate(id => { const el = document.querySelector(`.list-item[data-session-id="${id}"]`); if (el) el.click(); }, sid);
    await sleep(2500);
    await snap('project chat reopened');
  }

  const agentOn = async () => console.log('  agent toggle:', await page.evaluate(() => { const a = [...document.querySelectorAll('button,div,span')].find(e => e.textContent.trim() === 'Agent' && e.children.length === 0); if (a) { a.click(); return 'clicked Agent'; } return 'no Agent button'; }));
  if (!ONLY || ONLY === 5) {
  step('S5 tool turn on qwen3-test (native tools), then hand off to small-chat and back');
  await pick('qwen3-test'); await agentOn(); await sleep(600);
  await send('TOOLTEST please update the plan'); await waitIdle(25000); await sleep(3000);
  await snap('after tool turn on qwen3-test');
  step('S5 switch to small-chat (other tool path), follow up');
  await pick('small-chat');
  await send('what did the tool just do?'); await waitIdle(25000); await sleep(2000);
  await snap('after follow-up on small-chat');
  step('S5 back to qwen3-test, follow up');
  await pick('qwen3-test');
  await send('and now back on qwen3, summarize'); await waitIdle(25000); await sleep(2000);
  await snap('after return to qwen3-test');
  }

  marks.push({ name: 'END', at: nlines() });
  fs.writeFileSync(OUT + '/marks.json', JSON.stringify(marks));
  console.log('\npage errors/dialogs:', JSON.stringify(errs));
  await page.screenshot({ path: OUT + '/handoff-end.png' });
  await browser.close();
})();
