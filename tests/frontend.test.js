import test from 'node:test';
import assert from 'node:assert/strict';
import { esc, bookLink, safeBookURL, markdownHTML, initChart, chartCount, disposeCharts, fetchJSON, loadAnalysisFile } from '../docs/js/shared.js';

test('failed JSON requests can be retried', async () => {
  const original = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async () => {
    if (++attempts <= 2) throw new DOMException('Timed out', 'TimeoutError');
    return { ok: true, json: async () => ({ recovered: true }) };
  };
  try {
    await assert.rejects(fetchJSON('retry-test'), { name: 'TimeoutError' });
    assert.deepEqual(await fetchJSON('retry-test'), { recovered: true });
    assert.equal(attempts, 3);
  } finally { globalThis.fetch = original; }
});

test('a truncated HTTP 200 JSON body is retried once for all consumers', async () => {
  const original = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async () => {
    const attempt = ++attempts;
    return { ok: true, json: async () => {
      if (attempt === 1) throw new TypeError('Failed to fetch');
      return { complete: true };
    } };
  };
  try {
    const results = await Promise.all([fetchJSON('truncated-body'), fetchJSON('truncated-body')]);
    assert.deepEqual(results, [{ complete: true }, { complete: true }]);
    assert.equal(attempts, 2);
  } finally { globalThis.fetch = original; }
});

test('required summary preserves network failure instead of claiming missing data', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new DOMException('Timed out', 'TimeoutError'); };
  try {
    await assert.rejects(loadAnalysisFile('summary.json', '2026-W45', false, true), /网络读取超时/);
    assert.equal(await loadAnalysisFile('keywords.json', '2026-W45'), null);
  } finally { globalThis.fetch = original; }
});

test('HTML text and attributes are escaped', () => {
  assert.equal(esc('<"a&\'b>'), '&lt;&quot;a&amp;&#39;b&gt;');
  const html = bookLink({ title: '<script>alert(1)</script>', intro: '" onmouseover="alert(1)', url: 'https://www.qidian.com/book/123/' });
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&quot; onmouseover=&quot;'));
});

test('unsafe and legacy category URLs become plain text', () => {
  for (const value of ['javascript:alert(1)', '//www.qidian.com/xuanhuan', 'https://www.qidian.com@evil.com/book/123/', 'https://evil.com/book/123/', 'https://www.qidian.com:444/book/123/']) {
    assert.equal(safeBookURL(value), null);
    assert.ok(!bookLink({ title: 'Book', url: value }).includes('<a '));
  }
});

test('report Markdown cannot introduce executable HTML', () => {
  const html = markdownHTML('## Title\n\n<img src=x onerror="alert(1)">\n- **Strong**');
  assert.ok(html.includes('<h2>Title</h2>'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('<ul><li><strong>Strong</strong></li></ul>'));
});

test('chart switching reuses instances and cleanup empties the registry', () => {
  let inits = 0, disposals = 0;
  globalThis.document = { getElementById: id => ({ id }) };
  globalThis.echarts = { getInstanceByDom: () => null, init: () => { inits++; return { isDisposed: () => false, dispose: () => disposals++ }; } };
  for (let i = 0; i < 50; i++) initChart('ranking');
  assert.equal(inits, 1);
  assert.equal(chartCount(), 1);
  disposeCharts();
  assert.equal(chartCount(), 0);
  assert.equal(disposals, 1);
  delete globalThis.document;
  delete globalThis.echarts;
});

test('independent consumers share one JSON request', async () => {
  const original = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => { requests++; return { ok: true, json: async () => ({ value: 1 }) }; };
  try {
    const [a, b] = await Promise.all([fetchJSON('test-cache'), fetchJSON('test-cache')]);
    assert.equal(requests, 1);
    assert.deepEqual(a, b);
  } finally { globalThis.fetch = original; }
});
