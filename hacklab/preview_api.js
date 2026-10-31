// ponytail: a hand-rolled stand-in for the 12 routes the page calls; the real contract is
// STRATEGY.md "API contract" and tests/pwa/pwa.spec.js. Timing mirrors FakeJobRunner.
(function () {
  const D = window.__HACKLAB_PREVIEW__;
  const MESSAGES = __MESSAGES__;
  const q = new URLSearchParams(location.search);
  const source = q.get('remote') === '1' ? 'remote' : 'local';
  const st = { box: null, versions: {}, helping: false, jobs: {}, seq: 0,
               ai: q.get('offline') !== '1', board: q.get('unplugged') !== '1' };
  const listeners = new Set();
  window.EventSource = class { constructor() { listeners.add(this); } close() { listeners.delete(this); } };
  const emit = (o) => listeners.forEach((es) => es.onmessage && es.onmessage({ data: JSON.stringify(o) }));
  const vs = () => st.versions[st.box] || (st.versions[st.box] = [{ id: 'stock', source: D.data[st.box].stock, note: '', created: null }]);
  const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json' } });
  const locked = () => source === 'remote' && !st.helping;
  const render = (src, values) => Object.entries(values || {}).reduce(
    (s, [name, v]) => s.replace(new RegExp('(\\b' + name + '\\s*=\\s*)(-?[\\d.]+f?|true|false)'), '$1' + v)
                       .replace(new RegExp('(#define\\s+' + name + '\\s+)(-?[\\d.]+f?)'), '$1' + v), src);
  const EXPLANATION = { title: 'The box waits, then acts', story: ['Think of the box as a dog that sits very still, listening for a whistle.', 'Every key on the remote is a different whistle. When one arrives, the code looks it up and runs the matching trick, then goes back to listening.'], steps: [{ label: 'Wait', from_line: 1, to_line: 3, detail: 'loop() runs round and round, checking for a key.' }, { label: 'Hear a key', from_line: 4, to_line: 6, detail: 'The IR eye turns the flash of light into a number.' }, { label: 'Pick the trick', from_line: 7, to_line: 9, detail: 'switch matches the number to one case.' }, { label: 'Do it', from_line: 10, to_line: 12, detail: 'A helper function moves a servo for a short moment.' }], metaphor: 'A servo is like a tap: open it for a second and water runs, then close it.', watch_for: 'Press 7 and count how many times it shakes.' };
  function runJob(kind, { fail = false, prompts = [], sketch = null, note = '', clarify = false, explanation = null, go = false } = {}) {
    const id = 'preview-' + (++st.seq);
    // an ask only thinks and answers (ready | clarify); the go job flashes the held plan
    const stages = kind === 'explain' || (kind === 'ask' && !go) ? ['thinking'] : ['compiling', 'uploading', 'verifying'];
    const job = { job_id: id, kind, state: 'queued', message_kid: MESSAGES.queued, log_ref: null, prompts: [], sketch_ref: null, answer: null, explanation: null };
    st.jobs[id] = job;
    let i = 0;
    const step = () => {
      if (job.cancelled) { job.state = 'failed'; job.message_kid = 'Stopped. Nothing was changed.'; emit({ ...job }); return; }
      if (i < stages.length) {
        job.state = stages[i++]; job.message_kid = MESSAGES[job.state]; emit({ ...job });
        if (kind === 'explain') { setTimeout(() => { job.state = 'done'; job.explanation = explanation; job.message_kid = 'Here is what the code does.'; emit({ ...job }); }, 900); return; }
        if (clarify && job.state === 'thinking') { setTimeout(() => { job.state = 'done'; job.answer = 'clarify'; job.message_kid = 'Which key on the remote should start it?'; emit({ ...job }); }, 900); return; }
        if (kind === 'ask' && !go && job.state === 'thinking') { setTimeout(() => { job.state = 'done'; job.answer = 'ready'; job.message_kid = 'I know what to do. Press Go! and watch the box.'; job.held = { fail, prompts, sketch, note }; emit({ ...job }); }, 900); return; }
        if (fail && job.state === 'compiling') { setTimeout(() => { job.state = 'failed'; job.message_kid = MESSAGES.failed; emit({ ...job }); }, 900); return; }
        setTimeout(step, 1100); return;
      }
      const v = vs();
      if (kind === 'undo') { if (v.length > 1) v.pop(); }
      else if (kind === 'reset') v.splice(1);
      else v.push({ id: 'v' + (v.length + 1), source: sketch, note, created: Math.floor(Date.now() / 1000) });
      job.state = 'done'; job.message_kid = MESSAGES.done; job.prompts = prompts; job.sketch_ref = v[v.length - 1].id; if (kind === 'ask') job.answer = 'sketch';
      emit({ ...job });
    };
    setTimeout(step, 300);
    return id;
  }
  const realFetch = window.fetch.bind(window);
  window.fetch = async (url, opts = {}) => {
    const u = String(url);
    if (!u.startsWith('/api')) return realFetch(url, opts);
    const path = u.slice(4), body = opts.body ? JSON.parse(opts.body) : null;
    const box = st.box ? D.data[st.box] : null;
    const needBox = () => box ? null : json({ detail: 'Pick a box first.' }, 409);
    const write = () => locked() ? json({ detail: 'Remote view is read only. Turn on helping to change things.' }, 403) : null;
    if (path === '/status') {
      const v = st.box ? vs() : [];
      return json({ box: st.box, online: true, ai_available: st.ai, board_connected: st.board,
        current_version: v.length ? v[v.length - 1].id : null, versions_count: v.length, changed: v.length > 1, source, helping: st.helping,
        current_note: v.length > 1 ? v[v.length - 1].note : '', current_created: v.length > 1 ? v[v.length - 1].created : null });
    }
    if (path === '/boxes') return json(D.boxes);
    if (path === '/box') { if (!D.data[body.id]) return json({ detail: 'No such box.' }, 404); st.box = body.id; vs(); return json({ box: st.box }); }
    if (path === '/helping') { if (source !== 'remote') return json({ detail: 'Only a remote viewer can switch helping.' }, 403); st.helping = !!body.on; emit({ type: 'status' }); return json({ helping: st.helping }); }
    if (path === '/behaviours') return needBox() || json(box.behaviours);
    if (path === '/sketch/current') { const bad = needBox(); if (bad) return bad; const v = vs(); return json({ source: v[v.length - 1].source, version: v[v.length - 1].id, box: st.box }); }
    if (path === '/explain') {
      const bad = needBox(); if (bad) return bad;
      if (body.scope === 'changed' && vs().length < 2) return json({ detail: 'Nothing changed yet.' }, 409);
      const x = body.scope === 'lines' ? { ...EXPLANATION, title: `Lines ${body.from} to ${body.to}: ${EXPLANATION.title}` }
        : body.scope === 'changed' ? { ...EXPLANATION, title: `What changed: ${EXPLANATION.title}` } : EXPLANATION;
      return json({ job_id: runJob('explain', { explanation: x }) });
    }
    if (path.startsWith('/jobs/') && path.endsWith('/cancel')) {
      const j = st.jobs[path.slice(6, -7)];
      if (!j) return json({ detail: 'No such job.' }, 404);
      if (j.state === 'done' || j.state === 'failed') return json({ detail: 'Already finished.' }, 409);
      if (j.state === 'uploading' || j.state === 'verifying') return json({ detail: 'Too late to stop: the box is being written.' }, 409);
      j.cancelled = true; return json({ ok: true });
    }
    if (path.startsWith('/jobs/')) { const j = st.jobs[path.slice(6)]; return j ? json(j) : json({ detail: 'No such job.' }, 404); }
    if (path.startsWith('/concepts/')) { const c = box && box.concepts[path.slice(10)]; return c ? json(c) : json({ detail: 'No such concept.' }, 404); }
    const bad = needBox() || write(); if (bad) return bad;
    if (path === '/ask') {
      if (!st.ai) return json({ detail: 'The AI helper is away.' }, 409);
      if (Object.values(st.jobs).some((j) => (j.kind === 'ask' || j.kind === 'explain') && j.state !== 'done' && j.state !== 'failed')) return json({ detail: 'The AI helper is busy with one idea. Wait a moment.' }, 409);
      const prompts = Object.entries(box.concepts).slice(0, 2).map(([id, c]) => ({ id, question: c.question }));
      const sketch = '// The AI helper added a rule for: ' + body.text + '\n' + vs()[0].source;
      return json({ job_id: runJob('ask', { fail: /^fail/i.test(body.text), clarify: /^which/i.test(body.text), prompts, sketch, note: body.text }) });
    }
    if (path === '/go') {
      const plan = st.jobs[body.job_id];
      if (!plan || plan.answer !== 'ready') return json({ detail: 'That idea is gone. Say it again.' }, 409);
      return json({ job_id: runJob('ask', { ...plan.held, go: true }) });
    }
    if (path === '/tweakables') return json({ files: box.files || [] });
    if (path === '/flash/numbers') {
      const main = (box.files || []).find((f) => f.name.endsWith('.ino'));
      return json({ job_id: runJob('flash', { sketch: render(main ? main.source : vs()[0].source, body.values), note: 'My numbers' }) });
    }
    if (path === '/flash/behaviour') {
      const src = box.sketches[body.id]; if (!src) return json({ detail: 'No such trick.' }, 404);
      const title = (box.behaviours.find((b) => b.id === body.id) || {}).title || body.id;
      return json({ job_id: runJob('flash', { sketch: render(src, body.tweakables), note: body.label || title }) });
    }
    if (path === '/flash/template') { const src = box.sketches[body.id] || vs()[0].source; return json({ job_id: runJob('flash', { sketch: render(src, body.values) }) }); }
    if (path === '/flash/sketch') return json({ job_id: runJob('flash', { fail: /fail/i.test(body.source.slice(0, 40)), sketch: body.source }) });
    if (path === '/undo') return json({ job_id: runJob('undo') });
    if (path === '/reset') return json({ job_id: runJob('reset') });
    return json({ detail: 'Not in the preview.' }, 404);
  };
})();
