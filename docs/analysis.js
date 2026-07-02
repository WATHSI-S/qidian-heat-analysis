/**
 * 起点天榜 · 深度分析 — Analysis engine
 * Dark ink-wash theme, algorithmic ranking insights
 */

const DATA_BASE = window.location.pathname.includes('/docs/') ? '../data/' : './data/';
let allCharts = [];
let currentChangeTab = 'yuepiao';

// ── Helpers ──

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

// ── Shared ECharts dark theme ──

const DARK_TEXT = '#9a8e7e';
const DARK_AXIS = '#362f26';
const GOLD = '#c9a96e';

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

// ── Data Loading ──

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

async function loadAnalysisFile(filename) {
  try { return await fetchJSON(DATA_BASE + 'analysis/' + filename); }
  catch { return null; }
}

// ═══════════════════════════════════════════════
// ALGORITHMS
// ═══════════════════════════════════════════════

// Weights calibrated by signal quality:
//  月票 = real spend, 畅销 = real revenue, 阅读指数 = engagement
const RANK_WEIGHTS = {
  yuepiao: 1.0,
  hotsales: 0.95,
  readindex: 0.85,
  recom: 0.8,
  collect: 0.75,
  signnewbook: 0.7,
  newfans: 0.6,
  vipup: 0.5,
};

// Contribution per list entry: weight / sqrt(rank)
// sqrt dampens #1→#2 cliff while keeping rank signal meaningful
function rankContribution(rank, weight) {
  return weight / Math.sqrt(rank);
}

// Aggregate heat score per unique book across all ranking types
function computeHeatScores(books) {
  const map = {};
  books.forEach(b => {
    const key = b.title + '|' + b.author;
    if (!map[key]) {
      map[key] = {
        title: b.title, author: b.author, category: b.category,
        status: b.status, url: b.url, score: 0, ranks: [],
        bestRank: Infinity, bestRankType: '',
      };
    }
    const w = RANK_WEIGHTS[b.rank_type] || 0.5;
    map[key].score += rankContribution(b.rank, w);
    map[key].ranks.push({ type: b.rank_type, rank: b.rank, weight: w });
    if (b.rank < map[key].bestRank) {
      map[key].bestRank = b.rank;
      map[key].bestRankType = b.rank_type;
    }
  });

  return Object.values(map)
    .map(b => ({
      ...b,
      score: Math.round(b.score * 1000) / 1000,
      listCount: b.ranks.length,
      bestRankLabel: '#' + b.bestRank + ' ' + rankLabel(b.bestRankType),
    }))
    .sort((a, b) => b.score - a.score);
}

// Build a lookup: title|author → { heatScore, heatRank } from previous week
function buildPrevHeatMap(prevBooks) {
  if (!prevBooks) return null;
  const scored = computeHeatScores(prevBooks);
  const map = {};
  scored.forEach((b, i) => {
    map[b.title + '|' + b.author] = { score: b.score, rank: i + 1 };
  });
  return map;
}

// Compute week-over-week momentum per book
function computeMomentum(currentBooks, prevBooks) {
  const prevMap = buildPrevHeatMap(prevBooks);
  if (!prevMap) return {};

  const curScored = computeHeatScores(currentBooks);
  const momentum = {};
  curScored.forEach((b, i) => {
    const key = b.title + '|' + b.author;
    const prev = prevMap[key];
    if (prev) {
      momentum[key] = {
        prevHeatRank: prev.rank,
        curHeatRank: i + 1,
        heatDelta: prev.rank - (i + 1),  // positive = improved
        prevScore: prev.score,
        curScore: b.score,
      };
    } else {
      momentum[key] = { isNew: true };
    }
  });
  return momentum;
}

// Compute rank changes for a specific ranking list between two weeks
function computeRankChanges(currentWeek, previousWeek, rankType) {
  const curBooks = (currentWeek.books || []).filter(b => b.rank_type === rankType);
  if (!previousWeek) {
    return curBooks.map(b => ({ ...b, changeLabel: '—', changeClass: 'none', prevRank: null, delta: null }));
  }

  const prevMap = {};
  (previousWeek.books || []).filter(b => b.rank_type === rankType).forEach(b => {
    prevMap[b.title + '|' + b.author] = b.rank;
  });

  return curBooks.map(b => {
    const key = b.title + '|' + b.author;
    const prevRank = prevMap[key];
    if (prevRank == null) return { ...b, changeLabel: '新晋', changeClass: 'new', prevRank: null, delta: null };
    const delta = prevRank - b.rank;
    if (delta > 0) return { ...b, changeLabel: '↑' + delta, changeClass: 'up', prevRank, delta };
    if (delta < 0) return { ...b, changeLabel: '↓' + Math.abs(delta), changeClass: 'down', prevRank, delta };
    return { ...b, changeLabel: '—', changeClass: 'none', prevRank, delta: 0 };
  });
}

// Count unique weeks each book has appeared (any ranking list)
function computeAppearances(allWeeks) {
  const map = {};
  allWeeks.forEach(w => {
    const seen = new Set();
    (w.books || []).forEach(b => {
      const key = b.title + '|' + b.author;
      if (!seen.has(key)) {
        seen.add(key);
        if (!map[key]) map[key] = { title: b.title, author: b.author, category: b.category, weeks: 0 };
        map[key].weeks++;
      }
    });
  });
  return Object.values(map).sort((a, b) => b.weeks - a.weeks);
}

// Rank books within each category by heat score
function computeCategoryRankings(books) {
  const scored = computeHeatScores(books);
  const cats = {};
  scored.forEach(b => {
    const cat = b.category || '未知';
    if (!cats[cat]) cats[cat] = [];
    cats[cat].push(b);
  });

  // Sort categories by total heat score
  const result = Object.entries(cats)
    .map(([name, items]) => ({
      name,
      total: items.length,
      totalHeat: Math.round(items.reduce((s, b) => s + b.score, 0) * 100) / 100,
      top5: items.slice(0, 5),
    }))
    .sort((a, b) => b.totalHeat - a.totalHeat);

  return result;
}

// ═══════════════════════════════════════════════
// RENDERING
// ═══════════════════════════════════════════════

// ── Overview Cards ──

function renderOverview(index, heatScores, momentum, allWeeks) {
  document.getElementById('updateTime').textContent =
    '天机更新: ' + (index.updated_at || '—') + ' · 收录 ' + (index.total_weeks || 0) + ' 周';

  const topBook = heatScores[0];
  const mostLists = [...heatScores].sort((a, b) => b.listCount - a.listCount)[0];
  const newEntries = Object.values(momentum).filter(m => m.isNew).length;
  const improvers = Object.values(momentum).filter(m => m.heatDelta > 0).length;

  document.getElementById('analysisStats').innerHTML = [
    { v: index.total_weeks || 0, l: '收录周数', sub: '累计天机' },
    { v: heatScores.length, l: '本周收录', sub: '去重后书目' },
    { v: topBook ? esc(topBook.title) : '—', l: '热度魁首', sub: topBook ? (topBook.score + ' 分') : '' },
    { v: mostLists ? mostLists.listCount + ' 榜' : '—', l: '最多覆盖', sub: mostLists ? esc(mostLists.title) : '' },
  ].map(s =>
    `<div class="mark">
      <div class="mark-val">${s.v}</div>
      <div class="mark-label">${s.l}</div>
      <div class="mark-sub">${s.sub}</div>
    </div>`
  ).join('');
}

// ── Heat Score Table ──

function renderHeatTable(heatScores, momentum) {
  const tbody = document.querySelector('#heatTable tbody');
  if (!tbody) return;

  const top50 = heatScores.slice(0, 50);

  tbody.innerHTML = top50.map((b, i) => {
    const mom = momentum[b.title + '|' + b.author];
    let momHTML = '';
    if (mom && !mom.isNew) {
      const d = mom.heatDelta;
      if (d > 0) momHTML = `<span class="mom-tag up">↑${d}</span>`;
      else if (d < 0) momHTML = `<span class="mom-tag down">↓${Math.abs(d)}</span>`;
      else momHTML = `<span class="mom-tag none">—</span>`;
    } else {
      momHTML = `<span class="mom-tag new">新晋</span>`;
    }

    const rankBadges = b.ranks
      .sort((a, b) => b.weight - a.weight)
      .map(r => `<span class="list-badge lb-${r.type}" title="${rankLabel(r.type)} #${r.rank}">${rankLabel(r.type).charAt(0)}${r.rank}</span>`)
      .join('');

    return `
      <tr>
        <td class="td-rank">${i + 1}</td>
        <td><a href="${b.url || '#'}" target="_blank" rel="noopener">${esc(b.title)}</a></td>
        <td>${esc(b.author)}</td>
        <td>${esc(b.category)}</td>
        <td class="td-score">${b.score.toFixed(2)}</td>
        <td class="td-badges">${rankBadges}</td>
        <td>${b.bestRankLabel}</td>
        <td>${momHTML}</td>
      </tr>
    `;
  }).join('');
}

// ── Rank Changes Table ──

function renderChangesTable(currentWeek, previousWeek, rankType, anomalyMap) {
  const tbody = document.querySelector('#changesTable tbody');
  if (!tbody) return;

  const changes = computeRankChanges(currentWeek, previousWeek, rankType);
  anomalyMap = anomalyMap || {};

  // Stats
  const newCount = changes.filter(c => c.changeClass === 'new').length;
  const upCount = changes.filter(c => c.changeClass === 'up').length;
  const downCount = changes.filter(c => c.changeClass === 'down').length;
  document.getElementById('changesStats').textContent =
    `新晋 ${newCount} · 上升 ${upCount} · 下降 ${downCount} · 持平 ${changes.length - newCount - upCount - downCount}`;

  tbody.innerHTML = changes.slice(0, 125).map(c => {
    const anomalyKey = c.title + '|' + c.author + '|' + c.rank_type;
    const anomaly = anomalyMap[anomalyKey];
    let anomalyCls = '';
    let anomalyMarker = '';
    if (anomaly) {
      anomalyCls = anomaly.z_score > 0 ? ' anomaly-up' : ' anomaly-down';
      anomalyMarker = `<span class="anomaly-tag" title="Z-score: ${anomaly.z_score}">⚠</span>`;
    }

    let cls, marker;
    if (c.changeClass === 'new') { cls = 'chg-new'; marker = '<span class="chg-badge new">新晋</span>'; }
    else if (c.changeClass === 'up') { cls = 'chg-up'; marker = `<span class="chg-badge up">↑${c.delta}</span>`; }
    else if (c.changeClass === 'down') { cls = 'chg-down'; marker = `<span class="chg-badge down">↓${Math.abs(c.delta)}</span>`; }
    else { cls = ''; marker = '<span class="chg-badge none">—</span>'; }

    return `
      <tr class="${cls}${anomalyCls}">
        <td>${c.rank}</td>
        <td><a href="${c.url || '#'}" target="_blank" rel="noopener">${esc(c.title)} ${anomalyMarker}</a></td>
        <td>${esc(c.author)}</td>
        <td>${c.prevRank != null ? '#' + c.prevRank : '—'}</td>
        <td>#${c.rank}</td>
        <td>${marker}</td>
        <td>${esc(c.category)}</td>
      </tr>
    `;
  }).join('');
}

// ── Rank Changes Pill Selector ──

function buildChangesPills(currentWeek, previousWeek, anomalyMap) {
  const container = document.getElementById('changesTabs');
  container.innerHTML = Object.entries(RANK_LABELS).map(([k, v]) =>
    `<button class="rank-pill${k === currentChangeTab ? ' active' : ''}" data-rank="${k}">${v}</button>`
  ).join('');

  container.querySelectorAll('.rank-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.rank-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentChangeTab = btn.dataset.rank;
      renderChangesTable(currentWeek, previousWeek, currentChangeTab, anomalyMap);
    });
  });
}

// ── Longevity Chart ──

// Week-tier color: cool (1w) → warm (max weeks), same data = same color
function longevityColor(weeks, maxWeeks) {
  const t = maxWeeks > 1 ? (weeks - 1) / (maxWeeks - 1) : 0;
  // Interpolate: steel blue (low) → teal → gold (high)
  const r = Math.round(91 + t * (201 - 91));
  const g = Math.round(141 + t * (169 - 141));
  const b = Math.round(184 + t * (110 - 184));
  const c0 = `rgb(${r},${g},${b})`;
  // Darker variant for gradient end
  const r2 = Math.round(r * 0.75);
  const g2 = Math.round(g * 0.75);
  const b2 = Math.round(b * 0.75);
  return [c0, `rgb(${r2},${g2},${b2})`];
}

function renderLongevityChart(appearances) {
  const chart = initChart('chart-longevity');
  if (!chart) return;

  const data = appearances.slice(0, 20);
  const names = data.map(d => (d.title.length > 12 ? d.title.slice(0, 11) + '…' : d.title));
  const values = data.map(d => d.weeks);
  const maxW = Math.max(...values);

  chart.setOption({
    tooltip: {
      ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => {
        const d = data[p[0].dataIndex];
        return `<div style="font-size:13px;font-weight:700">${esc(d.title)}</div>`
          + `<div>作者: ${esc(d.author)} · ${esc(d.category)}</div>`
          + `<div style="color:#c9a96e;margin-top:4px">累计上榜 <b>${d.weeks}</b> 周</div>`;
      },
    },
    grid: { left: 6, right: 45, top: 8, bottom: 6, containLabel: true },
    xAxis: { type: 'value', ...darkAxis('上榜周数'), min: 0 },
    yAxis: {
      type: 'category',
      data: names.reverse(),
      axisLabel: { color: '#c0b8a8', fontSize: 11, width: 130, overflow: 'truncate' },
      axisLine: { show: false }, axisTick: { show: false },
      inverse: true,
    },
    series: [{
      type: 'bar',
      data: values.reverse().map(v => {
        const [c0, c1] = longevityColor(v, maxW);
        return {
          value: v,
          itemStyle: {
            borderRadius: [0, 3, 3, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: c0 }, { offset: 1, color: c1 },
            ]),
          },
        };
      }),
      barWidth: 14,
      label: { show: true, position: 'right', fontSize: 10, color: DARK_TEXT, formatter: '{c}周' },
    }],
  }, true);
}

// ── List Coverage Chart ──

function renderCoverageChart(heatScores) {
  const chart = initChart('chart-coverage');
  if (!chart) return;

  const dist = {};
  heatScores.forEach(b => {
    const n = Math.min(b.listCount, 8);
    dist[n] = (dist[n] || 0) + 1;
  });

  const data = [];
  for (let i = 1; i <= 8; i++) data.push({ name: i + '榜', value: dist[i] || 0 });

  chart.setOption({
    tooltip: { ...darkTooltip(), trigger: 'item', formatter: '出现于 <b>{b}</b> 个榜单: {c} 本书 ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['45%', '78%'],
      center: ['50%', '52%'],
      roseType: 'radius',
      data,
      label: { color: '#c0b8a8', fontSize: 11, formatter: '{b}\n{c}本' },
      itemStyle: {
        borderColor: '#1e1b15', borderWidth: 2, borderRadius: 2,
      },
      color: ['#5b8db8', '#27ae60', '#c9a96e', '#e67e22', '#e74c3c', '#8e44ad', '#c44569', '#f39c12'],
    }],
  }, true);
}

// ── Category Rankings Grid ──

function renderCategoryGrid(catRankings) {
  const grid = document.getElementById('categoryGrid');
  if (!grid) return;

  // Show top categories (those with most books)
  const topCats = catRankings.slice(0, 12);

  grid.innerHTML = topCats.map(cat => `
    <div class="cat-card">
      <div class="cat-card-header">
        <span class="cat-name">${esc(cat.name)}</span>
        <span class="cat-count">${cat.total} 本 · 热度 ${cat.totalHeat}</span>
      </div>
      <ol class="cat-list">
        ${cat.top5.map((b, i) => `
          <li>
            <span class="cat-rank ${i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : ''}">${i + 1}</span>
            <span class="cat-title">${esc(b.title.length > 10 ? b.title.slice(0, 9) + '…' : b.title)}</span>
            <span class="cat-score">${b.score.toFixed(1)}</span>
          </li>
        `).join('')}
      </ol>
    </div>
  `).join('');
}

// ── Association Rules Sankey ──

function renderAssociationSankey(assocData) {
  const chart = initChart('chart-association');
  if (!chart) return;

  if (!assocData || assocData.error || !assocData.rules || assocData.rules.length === 0) {
    chart.setOption({
      title: { text: '关联规则数据暂不可用', left: 'center', top: 'center',
        textStyle: { color: DARK_TEXT, fontSize: 13 } },
    });
    return;
  }

  const rules = assocData.rules;
  const nodes = [];
  const nodeMap = {};
  const seen = new Set();

  rules.forEach(r => {
    [r.antecedent, r.consequent].forEach(name => {
      if (!nodeMap[name]) {
        nodeMap[name] = RANK_LABELS[name] || name;
        nodes.push({ name: nodeMap[name] });
      }
    });
  });

  // Deduplicate bidirectional pairs to avoid cycles (sankey requires DAG)
  const links = [];
  rules.forEach(r => {
    const pair = [r.antecedent, r.consequent].sort().join('|');
    if (!seen.has(pair)) {
      seen.add(pair);
      links.push({
        source: nodeMap[r.antecedent],
        target: nodeMap[r.consequent],
        value: Math.round(r.lift * 100) / 100,
      });
    }
  });

  chart.setOption({
    tooltip: {
      ...darkTooltip(),
      trigger: 'item',
      formatter: p => {
        if (p.dataType === 'edge' || p.data && p.data.source) {
          return `<b>${p.data.source}</b> → <b>${p.data.target}</b><br/>提升度: ${p.data.value}`;
        }
        return p.name;
      },
    },
    series: [{
      type: 'sankey',
      emphasis: { focus: 'adjacency' },
      nodeAlign: 'left',
      data: nodes,
      links: links,
      label: { color: '#c0b8a8', fontSize: 11 },
      lineStyle: { color: 'gradient', curveness: 0.5 },
      itemStyle: { borderColor: '#1e1b15', borderWidth: 1 },
      color: ['#e8c878', '#5b8db8', '#27ae60', '#e67e22', '#e74c3c', '#8e44ad', '#1abc9c', '#e91e63'],
    }],
  }, true);
}

// ── K-means Clustering Scatter ──

const CLUSTER_COLORS = ['#e8c878', '#5b8db8', '#27ae60', '#e67e22', '#e74c3c', '#8e44ad'];

function renderClusterScatter(clusterData) {
  const chart = initChart('chart-clusters');
  if (!chart) return;

  if (!clusterData || clusterData.error || !clusterData.clusters || clusterData.clusters.length === 0) {
    chart.setOption({
      title: { text: '聚类数据暂不可用', left: 'center', top: 'center',
        textStyle: { color: DARK_TEXT, fontSize: 13 } },
    });
    return;
  }

  const series = clusterData.clusters.map((cl, idx) => ({
    name: cl.label + ' (' + cl.size + '本)',
    type: 'scatter',
    data: cl.books.map(b => ({
      value: b.coords,
      title: b.title,
      author: b.author,
      category: b.category,
    })),
    symbolSize: 10,
    itemStyle: { color: CLUSTER_COLORS[idx % CLUSTER_COLORS.length], opacity: 0.85 },
    emphasis: { scale: 2, focus: 'series' },
  }));

  const pcaVar = clusterData.pca_variance || [];
  const xLabel = pcaVar[0] ? `PC1 (${Math.round(pcaVar[0] * 100)}%)` : 'PC1';
  const yLabel = pcaVar[1] ? `PC2 (${Math.round(pcaVar[1] * 100)}%)` : 'PC2';

  chart.setOption({
    tooltip: {
      ...darkTooltip(),
      trigger: 'item',
      formatter: p => {
        const d = p.data;
        return `<b>${esc(d.title)}</b><br/>`
          + `作者: ${esc(d.author)}<br/>`
          + `分类: ${esc(d.category)}<br/>`
          + `聚类: ${p.seriesName}`;
      },
    },
    legend: {
      bottom: 0,
      textStyle: { color: DARK_TEXT, fontSize: 11 },
      data: series.map(s => s.name),
    },
    grid: { left: 10, right: 20, top: 10, bottom: 40, containLabel: true },
    xAxis: {
      type: 'value', ...darkAxis(xLabel),
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value', ...darkAxis(yLabel),
      splitLine: { show: false },
    },
    series,
  }, true);
}

// ── Anomaly Highlights (integrated into rank changes table) ──

function loadAnomalyMap(anomalyData) {
  if (!anomalyData || anomalyData.error || !anomalyData.anomalies) return {};
  const map = {};
  anomalyData.anomalies.forEach(a => {
    const key = a.title + '|' + a.author + '|' + a.rank_type;
    map[key] = a;
  });
  return map;
}

// ═══════════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════════

async function main() {
  try {
    const index = await loadIndex();
    document.getElementById('updateTime').textContent =
      '天机更新: ' + (index.updated_at || '—') + ' · 收录 ' + (index.total_weeks || 0) + ' 周';

    const allWeeks = await loadAllWeeks(index);
    const currentWeek = allWeeks[allWeeks.length - 1];
    const previousWeek = allWeeks.length > 1 ? allWeeks[allWeeks.length - 2] : null;

    if (!currentWeek) {
      document.getElementById('updateTime').textContent = '— 暂无数据，等待首次天机降临 —';
      return;
    }

    const books = currentWeek.books;
    const heatScores = computeHeatScores(books);
    const momentum = computeMomentum(books, previousWeek ? previousWeek.books : null);
    const appearances = computeAppearances(allWeeks);
    const catRankings = computeCategoryRankings(books);

    // Render core sections
    renderOverview(index, heatScores, momentum, allWeeks);
    renderHeatTable(heatScores, momentum);

    // Load data mining results (non-blocking)
    const [assocData, clusterData, anomalyData] = await Promise.allSettled([
      loadAnalysisFile('association_rules.json'),
      loadAnalysisFile('clusters.json'),
      loadAnalysisFile('anomalies.json'),
    ]);

    const assoc = assocData.status === 'fulfilled' ? assocData.value : null;
    const clusters = clusterData.status === 'fulfilled' ? clusterData.value : null;
    const anomalies = anomalyData.status === 'fulfilled' ? anomalyData.value : null;
    const anomalyMap = loadAnomalyMap(anomalies);

    // Render with anomaly highlights
    buildChangesPills(currentWeek, previousWeek, anomalyMap);
    renderChangesTable(currentWeek, previousWeek, currentChangeTab, anomalyMap);
    renderLongevityChart(appearances);
    renderCoverageChart(heatScores);
    renderCategoryGrid(catRankings);
    try { renderAssociationSankey(assoc); } catch (e) { console.error('Sankey 渲染失败:', e); }
    try { renderClusterScatter(clusters); } catch (e) { console.error('聚类图渲染失败:', e); }

  } catch (err) {
    console.error('分析启动失败:', err);
    document.getElementById('updateTime').textContent = '天机紊乱: ' + err.message;
  }
}

document.addEventListener('DOMContentLoaded', main);
