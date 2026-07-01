/**
 * 起点天榜 · AI洞见 — AI-powered insights dashboard
 * Dark ink-wash theme, DeepSeek LLM + jieba TF-IDF text mining
 */

const DATA_BASE = window.location.pathname.includes('/docs/') ? '../data/' : './data/';
let allCharts = [];

// ── Helpers ──

async function fetchJSON(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${path}`);
  return resp.json();
}

async function fetchText(path) {
  const resp = await fetch(path);
  if (!resp.ok) return null;
  return resp.text();
}

function resizeAll() { allCharts.forEach(c => { try { c.resize(); } catch (e) { /* ignore */ } }); }
window.addEventListener('resize', resizeAll);

function initChart(domId) {
  const dom = document.getElementById(domId);
  if (!dom) return null;
  const existing = echarts.getInstanceByDom(dom);
  if (existing) existing.dispose();
  const chart = echarts.init(dom, null, { renderer: 'svg' });
  allCharts.push(chart);
  return chart;
}

function esc(s) { return (s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

const DARK_TEXT = '#9a8e7e';
const DARK_AXIS = '#362f26';
const GOLD = '#c9a96e';
const JADE = '#27ae60';
const AZURE = '#5b8db8';
const VERMILLION = '#c0392b';

function darkAxis(name) {
  return {
    axisLine: { lineStyle: { color: DARK_AXIS } },
    axisTick: { show: false },
    axisLabel: { color: DARK_TEXT, fontSize: 11 },
    splitLine: { lineStyle: { color: 'rgba(54,47,38,0.3)' } },
    name: name || '',
    nameTextStyle: { color: DARK_TEXT, fontSize: 11 },
  };
}

function darkTooltip() {
  return {
    backgroundColor: '#2a2218',
    borderColor: '#5a4a30',
    textStyle: { color: '#e0d6c2', fontSize: 12, fontFamily: 'Noto Sans SC' },
  };
}

// Chart color palette
const CHART_COLORS = ['#c9a96e', '#27ae60', '#5b8db8', '#c0392b', '#8b7355', '#6c5b9e', '#3d8b7e', '#b87a4a'];

// ── Data Loading ──

async function loadAnalysisData() {
  const base = DATA_BASE + 'analysis/';
  const files = ['keywords.json', 'category_keywords.json', 'genre_tags.json', 'llm_insights.json', 'weekly_report.md'];
  const results = {};

  for (const file of files) {
    const key = file.replace('.json', '').replace('.md', '');
    try {
      if (file.endsWith('.md')) {
        results[key] = await fetchText(base + file);
      } else {
        results[key] = await fetchJSON(base + file);
      }
    } catch (e) {
      results[key] = null;
    }
  }

  if (results.llm_insights && results.llm_insights.error) {
    results.llm_insights = null;
  }

  return results;
}

// ── Section: Overview ──

function renderOverview(data) {
  const container = document.getElementById('aiStats');
  if (!container) return;

  const kw = data.keywords;
  const gt = data.genre_tags;
  const llm = data.llm_insights;

  const marks = [
    { value: kw ? kw.n_books || 0 : '—', label: '分析书籍' },
    { value: kw ? (kw.top || []).length : '—', label: 'TF-IDF 关键词' },
    { value: gt ? (gt.books_with_tags || 0) : '—', label: '流派标签覆盖' },
    { value: llm ? (llm.n_books || 0) : '—', label: 'LLM 深度解析' },
  ];

  container.innerHTML = marks.map(m =>
    `<div class="mark-card"><div class="mark-value">${esc(String(m.value))}</div><div class="mark-label">${esc(m.label)}</div></div>`
  ).join('');
}

// ── Section: Market Report (Markdown → HTML) ──

function renderMarketReport(md) {
  const container = document.getElementById('marketReport');
  if (!container) return;

  if (!md) {
    container.innerHTML = '<p class="placeholder">AI 市场报告暂未生成，请等待下次数据更新。</p>';
    return;
  }

  // Simple markdown → HTML converter for the expected format
  let html = md
    // Headings
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Unordered list items
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // Wrap consecutive <li> in <ul>
    .replace(/((?:<li>.*<\/li>\s*)+)/g, '<ul>$1</ul>')
    // Paragraphs (double newlines)
    .replace(/\n\n/g, '</p><p>')
    // Single newlines within paragraphs → space
    .replace(/\n/g, ' ');

  html = '<p>' + html + '</p>';
  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');
  html = html.replace(/<p>\s*<h2>/g, '<h2>');
  html = html.replace(/<\/h2>\s*<\/p>/g, '</h2>');

  container.innerHTML = html;
}

// ── Section: Global Keywords (horizontal bar) ──

function renderKeywordChart(data) {
  const chart = initChart('chart-keywords');
  if (!chart) return;

  const kw = data.keywords;
  if (!kw || !kw.top || kw.top.length === 0) {
    chart.setOption({
      title: { text: '暂无关键词数据', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  const items = kw.top.slice(0, 40);
  const names = items.map(d => d.token).reverse();
  const values = items.map(d => d.tfidf).reverse();

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => `${p[0].name}<br/>TF-IDF: ${p[0].value.toFixed(4)}` },
    grid: { left: 6, right: 50, top: 8, bottom: 6, containLabel: true },
    xAxis: { type: 'value', ...darkAxis('TF-IDF 权重'), axisLabel: { color: DARK_TEXT, fontSize: 10 } },
    yAxis: {
      type: 'category', data: names, inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', data: values, barWidth: 12,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#c9a96e' }, { offset: 1, color: '#8b7355' }
        ]),
        borderRadius: [0, 3, 3, 0],
      },
    }],
  }, true);
}

// ── Section: Genre Tags (horizontal bar) ──

function renderGenreTagChart(data) {
  const chart = initChart('chart-genretags');
  if (!chart) return;

  const gt = data.genre_tags;
  if (!gt || !gt.global || gt.global.length === 0) {
    chart.setOption({
      title: { text: '暂无标签数据', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  const items = gt.global.slice(0, 25);
  const names = items.map(d => d.tag).reverse();
  const values = items.map(d => d.count).reverse();

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => `${p[0].name}<br/>出现次数: ${p[0].value}` },
    grid: { left: 6, right: 40, top: 8, bottom: 6, containLabel: true },
    xAxis: { type: 'value', ...darkAxis('出现次数') },
    yAxis: {
      type: 'category', data: names, inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', data: values, barWidth: 12,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: JADE }, { offset: 1, color: '#1a5c3a' }
        ]),
        borderRadius: [0, 3, 3, 0],
      },
    }],
  }, true);
}

// ── Section: Category Keywords (tabbed bar chart) ──

let currentCatTab = '';

function renderCategoryKeywords(data) {
  const chart = initChart('chart-catkeywords');
  if (!chart) return;

  const ckData = data.category_keywords;
  if (!ckData || !ckData.categories || Object.keys(ckData.categories).length === 0) {
    chart.setOption({
      title: { text: '暂无分类数据', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  const categories = Object.keys(ckData.categories).sort((a, b) =>
    (ckData.categories[b].n_books || 0) - (ckData.categories[a].n_books || 0)
  );
  const tabsEl = document.getElementById('catTabs');
  if (tabsEl) {
    tabsEl.innerHTML = categories.map(c =>
      `<span class="rank-pill${c === (currentCatTab || categories[0]) ? ' active' : ''}" data-cat="${esc(c)}">${esc(c)} (${ckData.categories[c].n_books || 0})</span>`
    ).join('');
    tabsEl.querySelectorAll('.rank-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        tabsEl.querySelectorAll('.rank-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        currentCatTab = pill.dataset.cat;
        renderCatKeywordsChart(chart, ckData, currentCatTab);
      });
    });
  }

  const activeCat = currentCatTab || categories[0];
  if (!currentCatTab) currentCatTab = activeCat;
  renderCatKeywordsChart(chart, ckData, activeCat);
}

function renderCatKeywordsChart(chart, ckData, cat) {
  const catData = ckData.categories[cat];
  if (!catData || !catData.top) return;

  const items = catData.top.slice(0, 20);
  const names = items.map(d => d.token).reverse();
  const scores = items.map(d => d.tfidf).reverse();

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => `${cat} · ${p[0].name}<br/>TF-IDF: ${p[0].value.toFixed(4)}` },
    grid: { left: 6, right: 50, top: 8, bottom: 6, containLabel: true },
    xAxis: { type: 'value', ...darkAxis('TF-IDF 权重') },
    yAxis: {
      type: 'category', data: names, inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', data: scores, barWidth: 14,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: AZURE }, { offset: 1, color: '#2d4a6e' }
        ]),
        borderRadius: [0, 3, 3, 0],
      },
    }],
  }, true);
}

// ── Section: Protagonist Archetypes (rose pie) ──

function renderArchetypeChart(data) {
  const chart = initChart('chart-archetypes');
  if (!chart) return;

  const llm = data.llm_insights;
  if (!llm || !llm.aggregations || !llm.aggregations.archetype_distribution) {
    chart.setOption({
      title: { text: 'AI 分析暂不可用', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  const items = llm.aggregations.archetype_distribution;
  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { color: DARK_TEXT, fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
    series: [{
      type: 'pie', radius: ['30%', '65%'], roseType: 'area', center: ['50%', '45%'],
      itemStyle: { borderRadius: 4, borderColor: 'var(--ink)', borderWidth: 2 },
      label: { color: DARK_TEXT, fontSize: 10 },
      data: items.map((d, i) => ({ name: d.type, value: d.count, itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length] } })),
    }],
  }, true);
}

// ── Section: Golden Finger (pie) ──

function renderGoldenFingerChart(data) {
  const chart = initChart('chart-goldenfinger');
  if (!chart) return;

  const llm = data.llm_insights;
  if (!llm || !llm.aggregations || !llm.aggregations.golden_finger_distribution) {
    chart.setOption({
      title: { text: 'AI 分析暂不可用', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  const items = llm.aggregations.golden_finger_distribution;
  const pieColors = ['#c9a96e', '#27ae60', '#5b8db8', '#c0392b', '#6c5b9e', '#8b7355', '#3d8b7e'];

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { color: DARK_TEXT, fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
    series: [{
      type: 'pie', radius: ['35%', '60%'], center: ['50%', '45%'],
      itemStyle: { borderRadius: 4, borderColor: 'var(--ink)', borderWidth: 2 },
      label: { color: DARK_TEXT, fontSize: 10 },
      data: items.map((d, i) => ({ name: d.type, value: d.count, itemStyle: { color: pieColors[i % pieColors.length] } })),
    }],
  }, true);
}

// ── Section: World Keywords Heatmap ──

function renderWorldKeywordHeatmap(data) {
  const chart = initChart('chart-worldmap');
  if (!chart) return;

  const llm = data.llm_insights;
  if (!llm || !llm.books || llm.books.length === 0) {
    chart.setOption({
      title: { text: 'AI 分析暂不可用', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  // Build category x keyword matrix from LLM insights
  const catKwMap = {};
  const allKws = new Set();
  const catTotals = {};

  for (const book of llm.books) {
    // Try to find the original book's category from the text mining data
    // For now, use genre_tags as proxy — actually, we don't have category in llm_insights books.
    // We need to join on title. Since llm_insights books don't have category, let's skip this.
  }

  // The llm_insights books don't have category info directly. Let's build from available data.
  // Use genre_tags by_category as fallback, or just show top world keywords as a bar chart.
  if (!llm.aggregations || !llm.aggregations.top_world_keywords) {
    chart.setOption({
      title: { text: '暂无世界观数据', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  // Show top world keywords as horizontal bar instead (since book-level category join isn't available)
  const items = llm.aggregations.top_world_keywords.slice(0, 25);
  const names = items.map(d => d.keyword).reverse();
  const values = items.map(d => d.count).reverse();

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => `${p[0].name}<br/>提及次数: ${p[0].value}` },
    grid: { left: 6, right: 40, top: 8, bottom: 6, containLabel: true },
    xAxis: { type: 'value', ...darkAxis('提及次数') },
    yAxis: {
      type: 'category', data: names, inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', data: values, barWidth: 12,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#6c5b9e' }, { offset: 1, color: '#3a2d5e' }
        ]),
        borderRadius: [0, 3, 3, 0],
      },
    }],
  }, true);
}

// ── Section: Genre Tag Co-occurrence (chord diagram) ──

function renderCooccurrenceChart(data) {
  const chart = initChart('chart-cooccurrence');
  if (!chart) return;

  const gt = data.genre_tags;
  if (!gt || !gt.cooccurrences || gt.cooccurrences.length === 0) {
    chart.setOption({
      title: { text: '暂无共现数据', left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 14 } }
    }, true);
    return;
  }

  // Build node map and edges from co-occurrence data (top 25 pairs)
  const nodeMap = {};
  const edges = [];

  for (const item of gt.cooccurrences.slice(0, 25)) {
    const [t1, t2] = item.tags;
    if (!nodeMap[t1]) nodeMap[t1] = 0;
    if (!nodeMap[t2]) nodeMap[t2] = 0;
    nodeMap[t1] += item.count;
    nodeMap[t2] += item.count;
    edges.push({ source: t1, target: t2, value: item.count });
  }

  // Supplement node values from global tag counts
  if (gt.global) {
    for (const tag of gt.global) {
      if (nodeMap[tag.tag] !== undefined) {
        nodeMap[tag.tag] = Math.max(nodeMap[tag.tag], tag.count);
      }
    }
  }

  const nodes = Object.entries(nodeMap)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value], i) => ({
      name,
      value,
      itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length] },
    }));

  chart.setOption({
    tooltip: {
      ...darkTooltip(),
      trigger: 'item',
      formatter: p => {
        if (p.dataType === 'node') return `${p.name}<br/>总关联: ${p.value}`;
        return `${p.data.source} ↔ ${p.data.target}<br/>共现次数: ${p.data.value}`;
      },
    },
    series: [{
      type: 'chord',
      data: nodes,
      links: edges,
      label: {
        show: true,
        rotate: true,
        color: '#c0b8a8',
        fontSize: 11,
        fontFamily: 'Noto Sans SC',
      },
      itemStyle: {
        borderColor: 'var(--ink)',
        borderWidth: 2,
      },
      lineStyle: {
        color: GOLD,
        opacity: 0.4,
        curveness: 0.3,
      },
    }],
  }, true);
}

// ── Main ──

async function main() {
  try {
    // Load index for time display
    let index;
    try { index = await fetchJSON(DATA_BASE + 'index.json'); } catch (e) { index = null; }

    document.getElementById('updateTime').textContent = index
      ? '天机更新: ' + (index.updated_at || '—') + ' · 收录 ' + (index.total_weeks || 0) + ' 周'
      : '— 等待天机降临 —';

    const data = await loadAnalysisData();

    // Check if any data is available
    const hasAny = data.keywords || data.genre_tags || data.llm_insights || data.weekly_report;
    if (!hasAny) {
      document.getElementById('updateTime').textContent = '— 分析数据尚未生成，等待首次运行 —';
      return;
    }

    renderOverview(data);
    renderMarketReport(data.weekly_report);
    renderKeywordChart(data);
    renderGenreTagChart(data);
    renderCategoryKeywords(data);
    renderArchetypeChart(data);
    renderGoldenFingerChart(data);
    renderWorldKeywordHeatmap(data);
    renderCooccurrenceChart(data);

  } catch (err) {
    console.error('AI洞见启动失败:', err);
    document.getElementById('updateTime').textContent = '天机紊乱: ' + err.message;
  }
}

document.addEventListener('DOMContentLoaded', main);
