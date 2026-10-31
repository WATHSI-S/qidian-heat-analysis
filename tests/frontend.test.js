import test from 'node:test';
import assert from 'node:assert/strict';
import { esc, bookLink, safeBookURL, markdownHTML, initChart, chartCount, disposeCharts, fetchJSON } from '../docs/js/shared.js';

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
