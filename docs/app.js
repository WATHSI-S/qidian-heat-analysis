/**
 * 起点天榜 · 热度洞察 — Dashboard engine v3
 * Dark ink-wash theme, ECharts rendering
 */

const DATA_BASE = window.location.pathname.includes('/docs/') ? '../data/' : './data/';
let allCharts = [];
let currentRankTab = 'yuepiao';
let allBooks = [];

// ── Helpers ───────────────────────────────────────

async function fetchJSON(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${path}`);
  return resp.json();
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

const RANK_LABELS = {
  yuepiao: '月票榜', hotsales: '畅销榜', readindex: '阅读指数榜',
  recom: '推荐榜', collect: '收藏榜', newfans: '书友榜',
  vipup: '更新榜', signnewbook: '签约新书榜',
};
function rankLabel(k) { return RANK_LABELS[k] || k; }
function esc(s) { return (s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

// ── Shared ECharts dark theme base ────────────────

const DARK_TEXT = '#9a8e7e';
const DARK_AXIS = '#362f26';
const GOLD = '#c9a96e';
const VERMILLION = '#e74c3c';

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

// ── Data Loading ──────────────────────────────────

async function loadIndex() {
  try { return await fetchJSON(DATA_BASE + 'index.json'); }
  catch { return await fetchJSON('./data/index.json'); }
}

async function loadWeekData(filename) {
  try { return await fetchJSON(DATA_BASE + filename); }
  catch { return await fetchJSON('./data/' + filename); }
}

async function loadAllWeeks(index) {
  const snaps = [];
  for (const w of (index.weeks || [])) {
    try {
      const d = await loadWeekData(w.file);
      if (d) snaps.push(d);
    } catch { /* skip */ }
  }
  return snaps;
}

// ── Overview Marks ────────────────────────────────

function renderOverview(index) {
  document.getElementById('updateTime').textContent =
    '最近天机更新: ' + (index.updated_at || '—') + ' · 收录 ' + (index.total_weeks || 0) + ' 周';

  const cats = Object.keys(index.categories || {}).length;
  document.getElementById('overviewStats').innerHTML = [
    { v: index.total_weeks || 0, l: '收录周数' },
    { v: index.unique_titles || 0, l: '收录小说' },
    { v: index.unique_authors || 0, l: '收录作者' },
    { v: cats, l: '覆盖分类' },
  ].map(s =>
    `<div class="mark"><div class="mark-val">${s.v}</div><div class="mark-label">${s.l}</div></div>`
  ).join('');
}

// ── Rank Pills ────────────────────────────────────

function buildPills() {
  const container = document.getElementById('rankTabs');
  const types = Object.keys(RANK_LABELS);
  container.innerHTML = types.map(rt =>
    `<button class="rank-pill${rt === currentRankTab ? ' active' : ''}" data-rank="${rt}">${rankLabel(rt)}</button>`
  ).join('');

  container.querySelectorAll('.rank-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.rank-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentRankTab = btn.dataset.rank;
      renderTopThree(allBooks);
      renderRankBars(allBooks);
      renderTable(allBooks);
    });
  });
}

function buildTablePick() {
  const sel = document.getElementById('tableRankFilter');
  sel.innerHTML = Object.entries(RANK_LABELS).map(([k, v]) =>
    `<option value="${k}">${v}</option>`
  ).join('');
  sel.value = currentRankTab;
  sel.addEventListener('change', () => {
    currentRankTab = sel.value;
    document.querySelectorAll('.rank-pill').forEach(b => {
      b.classList.toggle('active', b.dataset.rank === currentRankTab);
    });
    renderTopThree(allBooks);
    renderRankBars(allBooks);
    renderTable(allBooks);
  });
}

// ── Category color map (consistent across all charts) ─

const CAT_COLORS = {
  '玄幻':    ['#e8c878', '#c9a96e'],  // gold
  '都市':    ['#5b8db8', '#3d6d99'],  // steel blue
  '仙侠':    ['#6dbe8a', '#4a8a60'],  // jade green
  '历史':    ['#c97a5a', '#a05a3d'],  // terracotta
  '科幻':    ['#48c9b0', '#2e9e8a'],  // teal
  '奇幻':    ['#a569bd', '#7d3c98'],  // amethyst
  '轻小说':  ['#e8919c', '#c06d7a'],  // rose
  '游戏':    ['#58d68d', '#3a9d60'],  // bright green
  '悬疑灵异': ['#85929e', '#5d6d7a'], // slate
  '现实':    ['#e67e22', '#b85d0e'],  // orange
  '武侠':    ['#e74c3c', '#b5302a'],  // vermillion
  '军事':    ['#7d9648', '#5a6e2e'],  // olive
  '体育':    ['#5dade2', '#3a85b0'],  // sky blue
  '诸天无限': ['#7d5fb8', '#5a3d90'], // deep violet
};

function catGradient(cat) {
  const pair = CAT_COLORS[cat] || ['#9a8e7e', '#6b6058'];
  return new echarts.graphic.LinearGradient(0, 0, 1, 0, [
    { offset: 0, color: pair[0] }, { offset: 1, color: pair[1] },
  ]);
}

function catColor(cat) {
  return (CAT_COLORS[cat] || ['#9a8e7e', '#6b6058'])[0];
}

// ── Rank Bars ─────────────────────────────────────

// Score: #1 ≈ 100, #125 ≈ 0.8 — bigger bar = more popular (intuitive)
function rankToScore(rank, maxRank) {
  return Math.round((maxRank - rank + 1) / maxRank * 100);
}

function renderTopThree(books) {
  const container = document.getElementById('topThreeCards');
  if (!container) return;
  const ranked = books
    .filter(b => b.rank_type === currentRankTab)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, 3);
  const medals = ['一', '二', '三'];
  container.innerHTML = ranked.map((b, i) => `
    <div class="top-card rank-${i + 1}">
      <span class="top-card-medal">${medals[i]}</span>
      <div class="top-card-info">
        <a href="${b.url || '#'}" target="_blank" rel="noopener" class="top-card-title">${esc(b.title)}</a>
        <span class="top-card-meta">${esc(b.author)} · ${esc(b.category)}</span>
      </div>
      <span class="top-card-rank">${b.rank}</span>
    </div>
  `).join('');
}

function renderRankBars(books) {
  const chart = initChart('chart-rank-bars');
  if (!chart) return;

  const maxRank = 125;
  const ranked = books
    .filter(b => b.rank_type === currentRankTab)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, 30);

  const names = ranked.map(b => (b.title.length > 14 ? b.title.slice(0, 13) + '…' : b.title));
  const data = ranked.map(b => rankToScore(b.rank, maxRank));

  chart.setOption({
    tooltip: {
      ...darkTooltip(),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => {
        const d = Array.isArray(p) ? p[0] : p;
        const bk = ranked[d.dataIndex];
        if (!bk) return '';
        return `<div style="font-size:13px;font-weight:700;margin-bottom:4px">#${bk.rank} ${esc(bk.title)}</div>`
          + `<div>热度值: <b style="color:#c9a96e">${rankToScore(bk.rank, maxRank)}</b></div>`
          + `<div>作者: ${esc(bk.author)}</div>`
          + `<div>分类: <b style="color:${catColor(bk.category)}">${esc(bk.category)}</b> · ${esc(bk.status)}</div>`
          + `<div style="color:#9a8e7e;margin-top:4px">${esc(bk.intro)}</div>`;
      },
    },
    grid: { left: 6, right: 50, top: 8, bottom: 6, containLabel: true },
    xAxis: {
      type: 'value', max: 100,
      ...darkAxis('热度值'),
    },
    yAxis: {
      type: 'category',
      data: names,
      inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11, width: 135, overflow: 'truncate' },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      data: data.map((score, i) => ({
        value: score,
        itemStyle: {
          color: catGradient(ranked[i].category),
          borderRadius: [0, 3, 3, 0],
        },
      })),
      barWidth: 16,
      label: { show: true, position: 'right', fontSize: 10, color: DARK_TEXT,
        formatter: p => ranked[p.dataIndex].rank },
    }],
  }, true);
}

// ── Category Pie ──────────────────────────────────

function renderCategory(books) {
  const chart = initChart('chart-category');
  if (!chart) return;

  const cats = {};
  books.forEach(b => { const c = b.category || '未知'; cats[c] = (cats[c] || 0) + 1; });
  const data = Object.entries(cats).sort((a, b) => b[1] - a[1]);

  // palette: warm golds + accents
  const palette = [
    '#c9a96e','#e74c3c','#5b8db8','#27ae60','#d4a574',
    '#8e44ad','#e67e22','#2ecc71','#95a5a6','#f39c12',
    '#3498db','#1abc9c','#9b59b6','#e91e63',
  ];

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} 本 ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['48%', '78%'],
      center: ['50%', '52%'],
      roseType: 'area',
      data: data.map(([name, value]) => ({ name, value })),
      label: { color: '#c0b8a8', fontSize: 10, formatter: '{b} {d}%' },
      itemStyle: {
        borderColor: '#1e1b15',
        borderWidth: 2,
        borderRadius: 2,
      },
      color: palette,
    }],
  }, true);
}

// ── Status Donut ──────────────────────────────────

function renderStatus(books) {
  const chart = initChart('chart-status');
  if (!chart) return;

  const st = {};
  books.forEach(b => { const s = b.status || '未知'; st[s] = (st[s] || 0) + 1; });

  const colors = { '连载': '#5b8db8', '完本': '#27ae60', '未知': '#555' };

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'item', formatter: '{b}: {c} 本 ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['50%', '82%'],
      center: ['50%', '50%'],
      data: Object.entries(st).map(([name, value]) => ({
        name, value,
        itemStyle: { color: colors[name] || '#555', borderColor: '#1e1b15', borderWidth: 3 },
      })),
      label: { color: '#c0b8a8', fontSize: 13, formatter: '{b}\n{d}%' },
      emphasis: {
        scaleSize: 8,
        itemStyle: { shadowBlur: 20, shadowColor: 'rgba(0,0,0,0.5)' },
      },
    }],
  }, true);
}

// ── Author Scatter (星光图) ─────────────────────

function renderAuthors(weeks) {
  const chart = initChart('chart-authors');
  if (!chart) return;

  const counts = {};
  const authorCats = {};
  weeks.forEach(w => {
    (w.books || []).forEach(b => {
      if (b.author) {
        counts[b.author] = (counts[b.author] || 0) + 1;
        if (!authorCats[b.author]) authorCats[b.author] = {};
        const cat = b.category || '未知';
        authorCats[b.author][cat] = (authorCats[b.author][cat] || 0) + 1;
      }
    });
  });

  const data = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 20);
  const maxCount = data[0][1];

  chart.setOption({
    tooltip: {
      ...darkTooltip(), trigger: 'item',
      formatter: p => {
        const cats = authorCats[p.name];
        const primary = cats ? Object.entries(cats).sort((a, b) => b[1] - a[1])[0] : null;
        return `<div style="font-size:13px;font-weight:700">${p.name}</div>`
          + `累计上榜 <b style="color:#c9a96e">${p.value}</b> 次`
          + (primary ? `<div>主攻分类: <b style="color:${catColor(primary[0])}">${primary[0]}</b></div>` : '');
      },
    },
    grid: { left: 6, right: 50, top: 8, bottom: 28, containLabel: true },
    xAxis: { type: 'value', ...darkAxis('累计上榜次数'), nameLocation: 'center', nameGap: 22 },
    yAxis: {
      type: 'category',
      data: data.map(d => d[0]),
      inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'scatter',
      data: data.map((d, i) => {
        const cats = authorCats[d[0]];
        const primary = cats ? Object.entries(cats).sort((a, b) => b[1] - a[1])[0] : null;
        const primaryCat = primary ? primary[0] : '';
        const color = catColor(primaryCat);
        return {
          value: [d[1], i],
          symbolSize: 8 + (d[1] / maxCount) * 22,
          itemStyle: {
            color: new echarts.graphic.RadialGradient(0.5, 0.5, 1, [
              { offset: 0, color: color },
              { offset: 0.6, color: color },
              { offset: 1, color: 'rgba(30,27,21,0.1)' },
            ]),
            shadowBlur: 10,
            shadowColor: 'rgba(201,169,110,0.3)',
          },
        };
      }),
      label: { show: true, position: 'right', fontSize: 10, color: DARK_TEXT,
        formatter: p => p.value[0] + ' 次' },
      emphasis: {
        scale: 1.5,
        itemStyle: { shadowBlur: 20, shadowColor: 'rgba(201,169,110,0.7)' },
      },
    }],
  }, true);
}

// ── Cross-Rank Leaderboard ──────────────────────

function renderCrossRank(books) {
  const board = document.getElementById('crossrankBoard');
  if (!board) return;

  const rankTypes = Object.keys(RANK_LABELS);

  // Build per-book rank lookup
  const presence = {};
  books.forEach(b => {
    const key = b.title + '|' + b.author;
    if (!presence[key]) {
      presence[key] = { title: b.title, author: b.author, category: b.category, status: b.status, url: b.url, ranks: {} };
    }
    presence[key].ranks[b.rank_type] = b.rank;
  });

  const topBooks = Object.values(presence)
    .map(b => ({ ...b, coverage: Object.keys(b.ranks).length }))
    .sort((a, b) => b.coverage - a.coverage)
    .slice(0, 12);

  board.innerHTML = topBooks.map((b, i) => {
    // Badge color by rank tier
    const badgeColors = {
      yuepiao: '#c9a96e', hotsales: '#e8c878', readindex: '#5b8db8',
      recom: '#27ae60', collect: '#8e44ad', newfans: '#e67e22',
      vipup: '#e74c3c', signnewbook: '#95a5a6',
    };

    // Build sorted rank badges
    const badges = Object.entries(b.ranks)
      .sort((a, b) => a[1] - b[1])
      .map(([rt, rank]) => {
        const color = badgeColors[rt] || '#888';
        const label = rankLabel(rt).replace('榜', '');
        return `<span class="cr-badge" style="border-color:${color};color:${color}">${label}<em>#${rank}</em></span>`;
      })
      .join('');

    // Medal for top 3
    const medals = ['gold', 'silver', 'bronze'];
    const medalClass = i < 3 ? ` cr-medal-${medals[i]}` : '';

    return `
      <div class="cr-card${i < 3 ? ' cr-top' + (i + 1) : ''}">
        <div class="cr-rank${medalClass}">${i + 1}</div>
        <div class="cr-body">
          <div class="cr-title">
            <a href="${b.url || '#'}" target="_blank" rel="noopener">${esc(b.title)}</a>
            <span class="cr-coverage">霸占 <b>${b.coverage}/8</b> 榜</span>
          </div>
          <div class="cr-meta">${esc(b.author)} · ${esc(b.category)} · <span class="status-badge ${b.status === '完本' ? 'done' : 'ongoing'}">${esc(b.status)}</span></div>
          <div class="cr-badges">${badges}</div>
        </div>
      </div>`;
  }).join('');
}

// ── Ranking Table ─────────────────────────────────

function renderTable(books) {
  const tbody = document.querySelector('#rankingTable tbody');
  if (!tbody) return;

  const filtered = books
    .filter(b => b.rank_type === currentRankTab)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, 125);

  tbody.innerHTML = filtered.map(b => `
    <tr>
      <td>${b.rank || '-'}</td>
      <td><a href="${b.url || '#'}" target="_blank" rel="noopener" title="${esc(b.intro || '')}">${esc(b.title)}</a></td>
      <td>${esc(b.author)}</td>
      <td>${esc(b.category)}</td>
      <td><span class="status-badge ${b.status === '完本' ? 'done' : 'ongoing'}">${esc(b.status)}</span></td>
    </tr>
  `).join('');
}

// ── Main ──────────────────────────────────────────

async function main() {
  try {
    const index = await loadIndex();
    renderOverview(index);

    const weeks = await loadAllWeeks(index);
    const latest = weeks[weeks.length - 1];
    if (!latest) {
      document.getElementById('updateTime').textContent = '— 暂无数据，等待首次天机降临 —';
      return;
    }

    allBooks = latest.books;

    buildPills();
    buildTablePick();

    renderTopThree(allBooks);
    renderRankBars(allBooks);
    renderCategory(allBooks);
    renderStatus(allBooks);
    renderAuthors(weeks);
    renderCrossRank(allBooks);
    renderTable(allBooks);

  } catch (err) {
    console.error('天榜启动失败:', err);
    document.getElementById('updateTime').textContent = '天机紊乱: ' + err.message;
  }
}

document.addEventListener('DOMContentLoaded', main);
