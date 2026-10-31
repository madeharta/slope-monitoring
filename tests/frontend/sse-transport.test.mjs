import test from 'node:test';
import assert from 'node:assert/strict';
import { openStream } from '../../apps/frontend/src/api.js';

function response(chunks, { type = 'text/event-stream', status = 200 } = {}) {
  const encoder = new TextEncoder();
  return { ok: status === 200, status, headers: new Headers({ 'content-type': type }),
    body: new ReadableStream({ start(c) { for (const chunk of chunks) c.enqueue(encoder.encode(chunk)); c.close(); } }) };
}
async function waitUntil(predicate) {
  for (let i = 0; i < 50; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.fail('Timed out waiting for SSE result');
}
test('requires authenticated fetch', () => {
  assert.throws(() => openStream(() => {}), /requires authFetch/);
});
test('authenticated stream parses split SSE frame, fires open, and ends with error', async () => {
  const events = []; let opens = 0; let failures = 0; let signal;
  const stream = openStream(e => events.push(e), (_url, opts) => {
    signal = opts.signal;
    assert.equal(opts.headers.Accept, 'text/event-stream');
    return Promise.resolve(response(['data: {"site_id":"a",', '"quantity":"ppv"}\n\n']));
  });
  stream.onopen = () => opens++;
  stream.onerror = () => failures++;
  await waitUntil(() => failures === 1);
  assert.equal(opens, 1);
  assert.deepEqual(events, [{ site_id: 'a', quantity: 'ppv' }]);
  assert.equal(signal.aborted, false);
  stream.close();
  assert.equal(signal.aborted, true);
});
test('abort does not invoke error; token never appears in URL', async () => {
  let observedUrl; let errors = 0;
  const stream = openStream(() => {}, (url, {signal}) => {
    observedUrl = url;
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {name:'AbortError'}))));
  });
  stream.onerror = () => errors++;
  stream.close();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(observedUrl, '/api/stream');
  assert.equal(errors, 0);
});
