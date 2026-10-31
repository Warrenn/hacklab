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
    (s, [name, v]) => s.replace(new RegExp('(\\b' + name + '\\s*=\\s*)[-\\d.]+'), '$1' + v), src);
  function runJob(kind, { fail = false, prompts = [], sketch = null, note = '', clarify = false } = {}) {
    const id = 'preview-' + (++st.seq);
    const stages = (kind === 'ask' ? ['thinking'] : []).concat(['compiling', 'uploading', 'verifying']);
    const job = { job_id: id, kind, state: 'queued', message_kid: MESSAGES.queued, log_ref: null, prompts: [], sketch_ref: null, answer: null };
    st.jobs[id] = job;
    let i = 0;
    const step = () => {
      if (i < stages.length) {
        job.state = stages[i++]; job.message_kid = MESSAGES[job.state]; emit({ ...job });
        if (clarify && job.state === 'thinking') { setTimeout(() => { job.state = 'done'; job.answer = 'clarify'; job.message_kid = 'Which key on the remote should start it?'; emit({ ...job }); }, 900); return; }
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
        current_version: v.length ? v[v.length - 1].id : null, versions_count: v.length, source, helping: st.helping,
        current_note: v.length > 1 ? v[v.length - 1].note : '', current_created: v.length > 1 ? v[v.length - 1].created : null });
    }
    if (path === '/boxes') return json(D.boxes);
    if (path === '/box') { if (!D.data[body.id]) return json({ detail: 'No such box.' }, 404); st.box = body.id; vs(); return json({ box: st.box }); }
    if (path === '/helping') { if (source !== 'remote') return json({ detail: 'Only a remote viewer can switch helping.' }, 403); st.helping = !!body.on; emit({ type: 'status' }); return json({ helping: st.helping }); }
    if (path === '/behaviours') return needBox() || json(box.behaviours);
    if (path === '/sketch/current') { const bad = needBox(); if (bad) return bad; const v = vs(); return json({ source: v[v.length - 1].source, version: v[v.length - 1].id, box: st.box }); }
    if (path.startsWith('/jobs/')) { const j = st.jobs[path.slice(6)]; return j ? json(j) : json({ detail: 'No such job.' }, 404); }
    if (path.startsWith('/concepts/')) { const c = box && box.concepts[path.slice(10)]; return c ? json(c) : json({ detail: 'No such concept.' }, 404); }
    const bad = needBox() || write(); if (bad) return bad;
    if (path === '/ask') {
      if (!st.ai) return json({ detail: 'The AI helper is away.' }, 409);
      const prompts = Object.entries(box.concepts).slice(0, 2).map(([id, c]) => ({ id, question: c.question }));
      const sketch = '// The AI helper added a rule for: ' + body.text + '\n' + vs()[0].source;
      return json({ job_id: runJob('ask', { fail: /^fail/i.test(body.text), clarify: /^which/i.test(body.text), prompts, sketch, note: body.text }) });
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
