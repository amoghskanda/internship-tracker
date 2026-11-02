import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import { loadTracker, safeUrl } from '../lib/tracker.ts';

const originalFetch = globalThis.fetch;
const originalLocation = Object.getOwnPropertyDescriptor(
  globalThis,
  'location',
);
let requests: string[];

beforeEach(() => {
  requests = [];
  Object.defineProperty(globalThis, 'location', {
    configurable: true,
    value: { hostname: 'localhost' },
  });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalLocation)
    Object.defineProperty(globalThis, 'location', originalLocation);
  else Reflect.deleteProperty(globalThis, 'location');
});

function serve(routes: Record<string, () => Response>) {
  globalThis.fetch = async (input) => {
    const endpoint =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    requests.push(endpoint);
    return routes[endpoint]?.() ?? new Response('', { status: 404 });
  };
}

const job = {
  id: 'example-job',
  company: 'Fictional Co',
  role: 'Intern',
  url: 'https://example.com',
};

void test('a standalone dev server loads the example without reading real application records', async () => {
  serve({
    '/api/jobs': () =>
      new Response('<html>Not an API</html>', {
        headers: { 'content-type': 'text/html' },
      }),
    '/tracker-data.example.json': () => Response.json({ jobs: [job] }),
    '/api/applications': () =>
      Response.json({
        applications: [{ id: job.id, notes: 'Private record' }],
      }),
  });
  const result = await loadTracker();
  assert.equal(result.example, true);
  assert.equal(result.readOnly, true);
  assert.equal(result.local, false);
  assert.deepEqual(result.jobs, [job]);
  assert.equal(requests.includes('/api/applications'), false);
});

void test('the local Python service supplies editable workbook data', async () => {
  serve({ '/api/jobs': () => Response.json({ jobs: [job] }) });
  const result = await loadTracker();
  assert.equal(result.local, true);
  assert.equal(result.example, false);
  assert.equal(result.readOnly, false);
  assert.deepEqual(requests, ['/api/jobs']);
});

void test('a static feed remains read-only when hosted application storage is unavailable', async () => {
  serve({
    '/tracker-data.json': () => Response.json({ jobs: [job] }),
    '/api/applications': () =>
      Response.json({ error: 'Unavailable' }, { status: 503 }),
  });
  const result = await loadTracker();
  assert.equal(result.readOnly, true);
  assert.equal(result.example, false);
});

void test('a hosted feed merges stored application state by stable id', async () => {
  serve({
    '/tracker-data.json': () => Response.json({ jobs: [job] }),
    '/api/applications': () =>
      Response.json({ applications: [{ id: job.id, status: 'Applied' }] }),
  });
  const result = await loadTracker();
  assert.equal(result.readOnly, false);
  assert.equal(result.jobs[0].status, 'Applied');
});

void test('malformed real data reports an error instead of silently switching to the example', async () => {
  serve({ '/api/jobs': () => Response.json({ jobs: 'invalid' }) });
  await assert.rejects(loadTracker(), /could not be read/);
  assert.deepEqual(requests, ['/api/jobs']);
});

void test('posting links accept only HTTP and HTTPS URLs', () => {
  assert.equal(safeUrl('javascript:alert(1)'), undefined);
  assert.equal(safeUrl('file:///private/record'), undefined);
  assert.equal(
    safeUrl('https://example.com/jobs/1'),
    'https://example.com/jobs/1',
  );
});
