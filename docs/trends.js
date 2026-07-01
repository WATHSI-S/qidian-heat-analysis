/**
 * 起点天榜 · 风向分析与题材推荐 — Trends & Recommendation Engine v2
 * Dark ink-wash theme, multi-factor market analysis algorithms
 *
 * Key algorithms:
 *   CMI  (Category Momentum Index) — chart week-over-week direction per category
 *   EFS  (Entry Friendliness Score) — cross-sectional: signnew density + rank accessibility + spread
 *   MGS  (Market Gap Score / 风口指数) — weighted composite: demand + competition + entry + momentum
 */

const DATA_BASE = window.location.pathname.includes('/docs/') ? '../data/' : './data/';
let allCharts = [];

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

// ═══════════════════════════════════════════════
// ALGORITHM 1: Heat Score (same as analysis.js)
// ═══════════════════════════════════════════════

const RANK_WEIGHTS = {
  yuepiao: 1.0, hotsales: 0.95, readindex: 0.85,
  recom: 0.8, collect: 0.75, signnewbook: 0.7, newfans: 0.6, vipup: 0.5,
};

function rankContribution(rank, weight) {
  return weight / Math.sqrt(rank);
}

function computeHeatScores(books) {
  const map = {};
  books.forEach(b => {
    const key = b.title + '|' + b.author;
    if (!map[key]) {
      map[key] = {
        title: b.title, author: b.author, category: b.category,
        status: b.status, url: b.url, score: 0, ranks: [],
      };
    }
    const w = RANK_WEIGHTS[b.rank_type] || 0.5;
    map[key].score += rankContribution(b.rank, w);
    map[key].ranks.push({ type: b.rank_type, rank: b.rank, weight: w });
  });
  return Object.values(map)
    .map(b => ({ ...b, score: Math.round(b.score * 1000) / 1000 }))
    .sort((a, b) => b.score - a.score);
}

// ═══════════════════════════════════════════════
// ALGORITHM 2: Category Momentum Index (CMI)
// ═══════════════════════════════════════════════

function computeCategoryMomentum(currentBooks, previousBooks) {
  const catSet = new Set();
  currentBooks.forEach(b => { if (b.category) catSet.add(b.category); });
  if (previousBooks) previousBooks.forEach(b => { if (b.category) catSet.add(b.category); });

  const result = [];

  catSet.forEach(cat => {
    const curScored = computeHeatScores(currentBooks.filter(b => b.category === cat));
    const curTotalHeat = curScored.reduce((s, b) => s + b.score, 0);
    const curCount = curScored.length;

    let prevTotalHeat = 0;
    let prevCount = 0;

    if (previousBooks) {
      const prevScored = computeHeatScores(previousBooks.filter(b => b.category === cat));
      prevTotalHeat = prevScored.reduce((s, b) => s + b.score, 0);
      prevCount = prevScored.length;
    }

    // Heat delta as % change, clamped to avoid extremes from sparse data
    const heatDelta = prevTotalHeat > 0
      ? Math.round(((curTotalHeat - prevTotalHeat) / prevTotalHeat) * 1000) / 10
      : 0;

    // Count delta (book count change)
    const countDelta = prevCount > 0
      ? Math.round(((curCount - prevCount) / prevCount) * 1000) / 10
      : 0;

    // CMI: heat change dominates, count change supplementary
    // Use tanh to dampen outliers (sparse categories can swing wildly)
    const cmi = 0.6 * Math.tanh(heatDelta / 30) + 0.4 * Math.tanh(countDelta / 20);

    result.push({
      category: cat,
      curTotalHeat: Math.round(curTotalHeat * 100) / 100,
      prevTotalHeat: Math.round(prevTotalHeat * 100) / 100,
      heatDelta,
      countDelta,
      curCount,
      prevCount,
      cmi: Math.round(cmi * 1000) / 1000,
    });
  });

  // CMI is already bounded to [-1, 1] by tanh, scale directly to [-100, 100]
  result.forEach(c => {
    c.cmiNorm = Math.round(c.cmi * 100);
  });

  return result.sort((a, b) => b.cmiNorm - a.cmiNorm);
}

// ═══════════════════════════════════════════════
// ALGORITHM 3: Entry Friendliness Score (EFS)
// ═══════════════════════════════════════════════
// Cross-sectional — does NOT depend on week-over-week overlap.
//
// 3 factors:
//   a) 签约新书密度 — signnewbook entries / total entries in category
//      (起点官方 "签约新书榜" 是衡量新书活跃度的最直接指标)
//   b) 头部竞争空间 — 1 - top-3 Herfindahl (heat concentration)
//      (Top 3 占比越低 → 市场越分散 → 新人越有机会)
//   c) 平均排名可及性 — normalized inverse avg best rank
//      (整体排名越靠前 → 榜单可及性越高 → 新人更容易被看见)
//
// Composite: signnewDensity*0.45 + competitionSpread*0.30 + accessibility*0.25
// Normalized across categories to 0–100.

function computeEntryFriendliness(currentBooks) {
  const allScored = computeHeatScores(currentBooks);

  // Group by category
  const catBooks = {};
  allScored.forEach(b => {
    const cat = b.category || '未知';
    if (!catBooks[cat]) catBooks[cat] = [];
    catBooks[cat].push(b);
  });

  // Also count signnewbook entries per category (raw entries, not unique)
  const signnewByCat = {};
  currentBooks.filter(b => b.rank_type === 'signnewbook').forEach(b => {
    const cat = b.category || '未知';
    signnewByCat[cat] = (signnewByCat[cat] || 0) + 1;
  });

  const totalSignnew = Object.values(signnewByCat).reduce((s, v) => s + v, 0);

  const result = [];

  Object.entries(catBooks).forEach(([cat, books]) => {
    const totalHeat = books.reduce((s, b) => s + b.score, 0);
    const top3Heat = books.slice(0, 3).reduce((s, b) => s + b.score, 0);

    // a) Signnew density: fraction of this category's books that come from signnew list
    const signnewCount = signnewByCat[cat] || 0;
    const signnewDensity = books.length > 0 ? signnewCount / Math.min(books.length, 125) : 0;

    // b) Competition spread: 1 - concentration (higher = more spread = friendlier)
    const concentration = totalHeat > 0 ? top3Heat / totalHeat : 0.5;
    const competitionSpread = 1 - concentration;

    // c) Rank accessibility: average best rank, lower = more accessible
    let avgBestRank = 0;
    let rankCount = 0;
    books.forEach(b => {
      b.ranks.forEach(r => {
        avgBestRank += r.rank;
        rankCount++;
      });
    });
    const avgRank = rankCount > 0 ? avgBestRank / rankCount : 62.5;
    const accessibility = 1 - (avgRank / 125);

    // Raw composite
    const raw = signnewDensity * 0.45 + competitionSpread * 0.30 + accessibility * 0.25;

    result.push({
      category: cat,
      signnewCount,
      signnewDensity: Math.round(signnewDensity * 100),
      concentration: Math.round(concentration * 100),
      competitionSpread: Math.round(competitionSpread * 100),
      avgRank: Math.round(avgRank),
      accessibility: Math.round(accessibility * 100),
      raw,
    });
  });

  // Normalize raw scores to 10-90 range for meaningful differentiation
  const raws = result.map(r => r.raw);
  const rawMin = Math.min(...raws);
  const rawMax = Math.max(...raws);
  const rawRange = rawMax - rawMin || 1;

  result.forEach(r => {
    r.entryScore = Math.round(10 + ((r.raw - rawMin) / rawRange) * 80);
  });

  return result.sort((a, b) => b.entryScore - a.entryScore);
}

// ═══════════════════════════════════════════════
// ALGORITHM 4: Market Gap Score (MGS) — 风口指数
// ═══════════════════════════════════════════════

function computeMarketGap(currentBooks, catMomentum, entryScores) {
  const momMap = {};
  catMomentum.forEach(c => { momMap[c.category] = c; });

  const entryMap = {};
  entryScores.forEach(c => { entryMap[c.category] = c; });

  const allScored = computeHeatScores(currentBooks);
  const catBooks = {};
  allScored.forEach(b => {
    const cat = b.category || '未知';
    if (!catBooks[cat]) catBooks[cat] = [];
    catBooks[cat].push(b);
  });

  const result = [];

  Object.entries(catBooks).forEach(([cat, books]) => {
    const cm = momMap[cat] || {};
    const es = entryMap[cat] || { entryScore: 50, concentration: 50 };

    // 1. Demand signal: yuepiao + hotsales rank quality per category
    //    (月票/畅销 = real reader spending = strongest demand proxy)
    let demandAcc = 0;
    let demandN = 0;
    books.forEach(b => {
      b.ranks.forEach(r => {
        if (r.type === 'yuepiao' || r.type === 'hotsales') {
          demandAcc += (125 - r.rank + 1) / 125;
          demandN++;
        }
      });
    });
    const demandRaw = demandN > 0 ? demandAcc / demandN : 0;

    // 2. Competition intensity: Herfindahl (top 3 heat share)
    const totalHeat = books.reduce((s, b) => s + b.score, 0);
    const top3Heat = books.slice(0, 3).reduce((s, b) => s + b.score, 0);
    const concentration = totalHeat > 0 ? top3Heat / totalHeat : 0.5;

    // 3. Entry friendliness: from EFS algorithm (already normalized 0-100)
    const entryRaw = es.entryScore / 100;

    // 4. Growth momentum: from CMI (normalized to 0-1, floor at 0)
    const growthRaw = Math.max(0, (cm.cmiNorm || 0) + 100) / 200;

    // MGS composite
    const mgs = demandRaw * 0.35
              + (1 - concentration) * 0.25
              + entryRaw * 0.25
              + growthRaw * 0.15;

    result.push({
      category: cat,
      demandScore: Math.round(demandRaw * 100),
      concentration: Math.round(concentration * 100),
      entryFriendliness: es.entryScore,
      signnewCount: es.signnewCount || 0,
      competitionSpread: es.competitionSpread || 0,
      avgRank: es.avgRank || 62,
      growthSignal: Math.round(growthRaw * 100),
      mgs: Math.round(mgs * 100),
      totalHeat: Math.round(totalHeat * 100) / 100,
      bookCount: books.length,
      topBooks: books.slice(0, 5),
    });
  });

  return result.sort((a, b) => b.mgs - a.mgs);
}

// ═══════════════════════════════════════════════
// ALGORITHM 5: Writing Advice Generator
// ═══════════════════════════════════════════════
// Advice is dynamically generated per category based on its metrics profile.
// No two categories should get identical advice.

const STRATEGY = {
  highDemandLowComp:  { label: '强烈推荐', color: '#2ecc71' },
  highDemandHighComp: { label: '差异化切入', color: '#e67e22' },
  newFriendly:        { label: '新人友好', color: '#5b8db8' },
  growingFast:        { label: '风口赛道', color: '#e74c3c' },
  steady:             { label: '稳健深耕', color: '#c9a96e' },
};

function classifyStrategy(gap) {
  const d = gap.demandScore;
  const c = gap.concentration;
  const e = gap.entryFriendliness;
  const g = gap.growthSignal;

  // Tiny / no market signal → steady niche
  if (d < 15) return 'steady';

  // High opportunity: strong demand + dispersed market
  if (d >= 45 && c < 30) return 'highDemandLowComp';
  // Hot but crowded: strong demand but concentrated
  if (d >= 45 && c >= 45) return 'highDemandHighComp';
  // Growing fast
  if (g >= 40) return 'growingFast';
  // Newcomer friendly: easy entry
  if (e >= 50) return 'newFriendly';
  // Niche/stable
  return 'steady';
}

function buildAdviceText(gap, strategy) {
  const cat = gap.category;
  const demand = gap.demandScore;
  const conc = gap.concentration;
  const entry = gap.entryFriendliness;
  const growth = gap.growthSignal;
  const books = gap.bookCount;
  const sn = gap.signnewCount || 0;
  const spread = gap.competitionSpread || 0;

  // Build category-specific, data-driven advice paragraphs
  const parts = [];

  // ── Market overview (category-specific) ──
  if (books >= 80) {
    parts.push(`${cat}类当前在榜 ${books} 本，是起点的主力大品类，读者池庞大。`);
  } else if (books >= 30) {
    parts.push(`${cat}类在榜 ${books} 本，属中等体量品类，有稳定的读者群体和成长空间。`);
  } else {
    parts.push(`${cat}类在榜仅 ${books} 本，属小众品类，竞争绝对量小但读者池也相应有限。`);
  }

  // ── Demand analysis ──
  if (demand >= 65) {
    parts.push(`月票/畅销活跃度 ${demand} 分，读者付费意愿很强——愿意为好书花钱的读者多。`);
  } else if (demand >= 40) {
    parts.push(`需求信号 ${demand} 分，付费读者基础尚可，需要靠质量和更新节奏拉动追读。`);
  } else {
    parts.push(`需求信号仅 ${demand} 分，读者付费活跃度偏低。建议在开篇强化"钩子"设计，用强悬念拉动前期追读数据。`);
  }

  // ── Competition landscape ──
  if (conc <= 25) {
    parts.push(`头部集中度仅 ${conc}%，市场分散、尚未形成寡头垄断——新人突围的窗口期还在。`);
  } else if (conc <= 45) {
    parts.push(`头部集中度 ${conc}%，Top 3 有一定优势但未锁死榜单，中腰部仍有空间。`);
  } else {
    parts.push(`头部集中度高达 ${conc}%，榜单被少数作品牢牢占据。不建议正面冲榜，更适合从细分题材或跨界融合角度切入。`);
  }

  // ── Entry barrier ──
  if (entry >= 60) {
    parts.push(`签约新书本月有 ${sn} 本上榜，新人友好度 ${entry} 分——说明新书在这里仍有被看见的机会。`);
  } else if (entry >= 35) {
    parts.push(`新人友好度 ${entry} 分，签约新书 ${sn} 本。新书有一定能见度，但需要更精细的题材选择。`);
  } else {
    parts.push(`新人友好度仅 ${entry} 分，签约新书寥寥。如果坚持写这个品类，建议绑定热门标签或IP同人来借力。`);
  }

  // ── Strategy-specific actionable advice ──
  const topBook = gap.topBooks && gap.topBooks[0];
  const topTitle = topBook ? `《${topBook.title}》` : '头部作品';

  switch (strategy) {
    case 'highDemandLowComp':
      parts.push(`具体建议：研究当前榜首 ${topTitle} 的切入点，找一个它没覆盖的细分角度。${cat}类读者付费意愿强，前30章需要快速建立"付费理由"——独特世界观、强人设、或反套路开篇。`);
      break;
    case 'highDemandHighComp':
      parts.push(`具体建议：避开 ${topTitle} 所在的正面赛道。${cat}类读者基数大但口味分化——找"大品类中的小蓝海"：比如在玄幻大类里做科幻融合、在都市大类里做悬疑探案。`);
      break;
    case 'newFriendly':
      parts.push(`具体建议：快速试错、高频更新。${cat}类榜单流动性好，趁着窗口期用3-5万字快速验证题材吸引力，根据追读数据决定是深耕还是换赛道。`);
      break;
    case 'growingFast':
      parts.push(`具体建议：${cat}类是当前风口，但窗口期可能有限。优先拆解最近4周该品类上榜新书的共同特征（开篇节奏、金手指类型、章节长度），找到"品类密码"后快速上线。`);
      break;
    case 'steady':
      parts.push(`具体建议：${cat}是成熟品类，不适合追逐短期热点。建议深耕一个细分方向（如特定历史朝代、特定职业背景），用专业性建立壁垒，走"慢热精品"路线。`);
      break;
  }

  return parts.join('');
}

// Sub-genre hints grounded in 2025-2026 market trends
const SUBGENRE_HINTS = {
  '玄幻': ['东方玄幻', '修行体系创新', '高武星际', '灵气复苏'],
  '仙侠': ['古典仙侠', '凡人流', '苟道种田', '两界穿梭'],
  '都市': ['都市异能', '重生年代文', '文娱明星', '职业写实', '悬疑怪谈'],
  '历史': ['架空考据', '东晋/大明', '争霸种田', '历史脑洞'],
  '科幻': ['星际文明', '末世生存', '赛博朋克', '硬核科幻'],
  '奇幻': ['西幻史诗', '克苏鲁', '领主种田', '游戏异界'],
  '轻小说': ['同人衍生', '反套路修仙', '脑洞创新', '恶役千金'],
  '游戏': ['电竞竞技', '虚拟现实', '第四天灾', '游戏异界'],
  '悬疑': ['灵异恐怖', '刑侦推理', '心理悬疑', '无限流'],
  '现实': ['社会写实', '职场商战', '年代怀旧', '专业领域'],
  '武侠': ['国术传承', '新派武侠', '高武都市'],
  '军事': ['战争史诗', '特种兵王', '谍战悬疑'],
  '体育': ['热血竞技', '足球', '极限运动'],
};

function getSubgenreHints(category) {
  for (const [key, hints] of Object.entries(SUBGENRE_HINTS)) {
    if (category.includes(key)) return hints;
  }
  return ['题材融合创新', '热点元素组合', '反套路设计', '人设差异化'];
}

function generateAdvice(gap) {
  const hints = getSubgenreHints(gap.category);
  const strategyKey = classifyStrategy(gap);
  const strategy = STRATEGY[strategyKey];
  const text = buildAdviceText(gap, strategyKey);

  return { ...gap, advice: { label: strategy.label, color: strategy.color, text }, hints };
}

// ═══════════════════════════════════════════════
// RENDERING
// ═══════════════════════════════════════════════

// ── Overview Marks ──
function renderOverview(index, catMomentum, marketGaps, entryScores) {
  document.getElementById('updateTime').textContent =
    '天机更新: ' + (index.updated_at || '—') + ' · 收录 ' + (index.total_weeks || 0) + ' 周';

  const hottest = catMomentum[0];
  const bestGap = marketGaps[0];
  const mostFriendly = entryScores[0];
  const risingCount = catMomentum.filter(c => c.cmiNorm > 10).length;

  document.getElementById('trendStats').innerHTML = [
    { v: hottest ? esc(hottest.category) : '—', l: '势头最强', sub: (hottest ? (hottest.cmiNorm > 0 ? '+' : '') + hottest.cmiNorm : '') + ' 动量', accent: hottest && hottest.cmiNorm > 0 },
    { v: bestGap ? esc(bestGap.category) : '—', l: '最佳风口', sub: bestGap ? (bestGap.mgs + ' 风口指数') : '', accent: true },
    { v: mostFriendly ? esc(mostFriendly.category) : '—', l: '最新人友好', sub: mostFriendly ? (mostFriendly.entryScore + ' 友好度') : '' },
    { v: risingCount + ' / ' + catMomentum.length, l: '上升分类', sub: '本周动量 > 0' },
  ].map(s =>
    `<div class="mark${s.accent ? ' mark-accent' : ''}">
      <div class="mark-val">${s.v}</div>
      <div class="mark-label">${s.l}</div>
      <div class="mark-sub">${s.sub}</div>
    </div>`
  ).join('');
}

// ── Entry Friendliness Chart ──
function renderEntryChart(entryScores) {
  const chart = initChart('chart-entry');
  if (!chart) return;

  const data = entryScores.slice(0, 15);
  const names = data.map(d => d.category);

  // Stacked bar showing factor contributions
  const signnewVals = data.map(d => Math.round(d.signnewDensity * 0.45));
  const spreadVals = data.map(d => Math.round((d.competitionSpread / 100) * 30));
  const accessVals = data.map(d => Math.round((d.accessibility / 100) * 25));

  chart.setOption({
    tooltip: {
      ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => {
        const d = data[p[0].dataIndex];
        return `<div style="font-size:13px;font-weight:700">${esc(d.category)}</div>`
          + `<div>友好度: <b style="color:#c9a96e">${d.entryScore}/100</b></div>`
          + `<div>签约新书密度: <b>${d.signnewDensity}%</b> (${d.signnewCount} 本)</div>`
          + `<div>竞争分散度: <b>${d.competitionSpread}%</b></div>`
          + `<div>平均排名: <b>#${d.avgRank}</b> · 可及性 ${d.accessibility}%</div>`;
      },
    },
    legend: {
      data: ['签约新书密度', '竞争分散度', '排名可及性'],
      textStyle: { color: DARK_TEXT, fontSize: 11 },
      bottom: 0,
    },
    grid: { left: 6, right: 40, top: 8, bottom: 36, containLabel: true },
    xAxis: { type: 'value', ...darkAxis(''), max: 100 },
    yAxis: {
      type: 'category', data: names.reverse(), inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [
      {
        name: '签约新书密度', type: 'bar', stack: 'total',
        data: signnewVals.reverse(),
        barWidth: 14,
        itemStyle: { color: '#5b8db8', borderRadius: [0, 0, 0, 0] },
        label: { show: false },
      },
      {
        name: '竞争分散度', type: 'bar', stack: 'total',
        data: spreadVals.reverse(),
        itemStyle: { color: '#27ae60' },
        label: { show: false },
      },
      {
        name: '排名可及性', type: 'bar', stack: 'total',
        data: accessVals.reverse(),
        itemStyle: { color: '#8e44ad', borderRadius: [0, 3, 3, 0] },
        label: { show: true, position: 'right', fontSize: 10, color: DARK_TEXT,
          formatter: p => {
            const d = data[names.length - 1 - p.dataIndex];
            return d ? d.entryScore : '';
          },
        },
      },
    ],
  }, true);
}

// ── Momentum Chart ──
function renderMomentumChart(catMomentum) {
  const chart = initChart('chart-momentum');
  if (!chart) return;

  // Sort ascending by cmiNorm for display: lowest at index 0 (bottom with inverse:true)
  const displayData = [...catMomentum].sort((a, b) => a.cmiNorm - b.cmiNorm).slice(0, 15);
  const names = displayData.map(d => d.category);
  const values = displayData.map(d => d.cmiNorm);

  chart.setOption({
    tooltip: {
      ...darkTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => {
        const d = displayData[p[0].dataIndex];
        return `<div style="font-size:13px;font-weight:700">${esc(d.category)}</div>`
          + `<div>动量指数: <b style="color:${d.cmiNorm >= 0 ? '#2ecc71' : '#e74c3c'}">${d.cmiNorm > 0 ? '+' : ''}${d.cmiNorm}</b></div>`
          + `<div>热度变化: <b>${d.heatDelta > 0 ? '+' : ''}${d.heatDelta}%</b></div>`
          + `<div>书目变化: <b>${d.countDelta > 0 ? '+' : ''}${d.countDelta}%</b> (${d.curCount} vs ${d.prevCount})</div>`;
      },
    },
    grid: { left: 6, right: 45, top: 8, bottom: 6, containLabel: true },
    xAxis: { type: 'value', ...darkAxis('动量指数'), min: -100, max: 100 },
    yAxis: {
      type: 'category', data: names, inverse: true,
      axisLabel: { color: '#c0b8a8', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      data: values.map(v => ({
        value: v,
        itemStyle: {
          color: v >= 0
            ? new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#27ae60' }, { offset: 1, color: '#1a7a40' }])
            : new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#e74c3c' }, { offset: 1, color: '#a93226' }]),
          borderRadius: v >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3],
        },
      })),
      barWidth: 14,
      label: { show: true, position: 'right', fontSize: 10, color: DARK_TEXT,
        formatter: p => (p.value > 0 ? '+' : '') + p.value },
    }],
  }, true);
}

// ── Market Gap Chart (radar: multi-dimension profile comparison) ──
const RADAR_COLORS = [
  '#e8c878', '#e67e22', '#5b8db8', '#27ae60', '#e74c3c', '#8e44ad',
];
const RADAR_FILLS = [
  'rgba(232,200,120,0.15)', 'rgba(230,126,34,0.12)', 'rgba(91,141,184,0.12)',
  'rgba(39,174,96,0.12)', 'rgba(231,76,60,0.10)', 'rgba(142,68,173,0.10)',
];

function renderMarketChart(marketGaps) {
  const chart = initChart('chart-market');
  if (!chart) return;

  const top = marketGaps.slice(0, 6);
  const maxDemand = Math.max(...top.map(d => d.demandScore), 1);
  const maxSpace = Math.max(...top.map(d => 100 - d.concentration), 1);
  const maxEntry = Math.max(...top.map(d => d.entryFriendliness), 1);
  const maxGrowth = Math.max(...top.map(d => d.growthSignal), 1);

  const radarInd = [
    { name: '需求\n信号', max: 100 },
    { name: '竞争\n空间', max: 100 },
    { name: '新人\n友好', max: 100 },
    { name: '增长\n动量', max: 100 },
  ];

  chart.setOption({
    tooltip: {
      ...darkTooltip(), trigger: 'item',
    },
    legend: {
      data: top.map(d => d.category),
      textStyle: { color: DARK_TEXT, fontSize: 10 },
      bottom: 0,
      itemWidth: 10, itemHeight: 6,
    },
    radar: {
      center: ['50%', '48%'],
      radius: '62%',
      indicator: radarInd,
      axisName: { color: DARK_TEXT, fontSize: 10, borderRadius: 3, padding: [2, 4] },
      shape: 'polygon',
      splitNumber: 4,
      axisLine: { lineStyle: { color: 'rgba(54,47,38,0.5)' } },
      splitLine: { lineStyle: { color: 'rgba(54,47,38,0.25)' } },
      splitArea: {
        areaStyle: { color: ['rgba(30,27,21,0.3)', 'rgba(30,27,21,0.1)'] },
      },
    },
    series: top.map((d, i) => ({
      type: 'radar',
      name: d.category,
      data: [{
        value: [d.demandScore, 100 - d.concentration, d.entryFriendliness, d.growthSignal],
        name: d.category + ' · 风口' + d.mgs,
      }],
      symbol: 'circle',
      symbolSize: 4,
      lineStyle: { color: RADAR_COLORS[i], width: 1.5, opacity: 0.85 },
      areaStyle: { color: RADAR_FILLS[i] },
      itemStyle: { color: RADAR_COLORS[i] },
      emphasis: {
        areaStyle: { color: RADAR_FILLS[i] },
        lineStyle: { width: 2.5 },
      },
    })),
  }, true);
}

// ── Market Gap Table ──
function renderMarketTable(marketGaps) {
  const tbody = document.querySelector('#gapTable tbody');
  if (!tbody) return;

  tbody.innerHTML = marketGaps.map((g, i) => {
    const mgsColor = g.mgs >= 60 ? '#2ecc71' : g.mgs >= 45 ? '#c9a96e' : '#9a8e7e';
    const demandColor = g.demandScore >= 60 ? '#2ecc71' : g.demandScore >= 35 ? '#e67e22' : '#e74c3c';
    const compColor = g.concentration <= 30 ? '#2ecc71' : g.concentration <= 50 ? '#e67e22' : '#e74c3c';
    const entryColor = g.entryFriendliness >= 55 ? '#2ecc71' : g.entryFriendliness >= 35 ? '#e67e22' : '#e74c3c';

    return `
      <tr>
        <td class="td-rank">${i + 1}</td>
        <td>${esc(g.category)}</td>
        <td><span class="mom-score" style="color:${mgsColor}">${g.mgs}</span></td>
        <td><span style="color:${demandColor}">${g.demandScore}</span></td>
        <td><span style="color:${compColor}">${g.concentration}%</span></td>
        <td><span style="color:${entryColor}">${g.entryFriendliness}%</span></td>
        <td>${g.growthSignal}</td>
        <td>${g.bookCount}</td>
        <td>
          <div class="td-bar-wrap"><div class="td-bar-fill" style="width:${g.mgs}%;background:${mgsColor}"></div></div>
        </td>
      </tr>`;
  }).join('');
}

// ── Recommendation Cards ──
function renderRecommendations(marketGaps) {
  const grid = document.getElementById('recGrid');
  if (!grid) return;

  const topRecs = marketGaps.slice(0, 6).map(generateAdvice);

  grid.innerHTML = topRecs.map((rec, i) => {
    const cls = i === 0 ? ' rec-top1' : i === 1 ? ' rec-top2' : i === 2 ? ' rec-top3' : '';
    const badgeCls = i < 3 ? '' : ' rec-norm';

    return `
      <div class="rec-card${cls}">
        <div class="rec-header">
          <div class="rec-badge${badgeCls}">${i + 1}</div>
          <div>
            <div class="rec-cat">${esc(rec.category)}</div>
            <div style="font-size:10px;color:${rec.advice.color};letter-spacing:1px">${rec.advice.label}</div>
          </div>
          <div class="rec-score-tag">风口 ${rec.mgs}</div>
        </div>
        <div class="rec-body">
          <div class="rec-metrics">
            <div class="rec-metric">
              <div class="rec-metric-label">读者需求</div>
              <div class="rec-metric-val ${rec.demandScore >= 60 ? 'good' : rec.demandScore >= 35 ? 'warn' : 'hot'}">${rec.demandScore}/100</div>
            </div>
            <div class="rec-metric">
              <div class="rec-metric-label">头部集中度</div>
              <div class="rec-metric-val ${rec.concentration <= 30 ? 'good' : rec.concentration <= 50 ? 'warn' : 'hot'}">${rec.concentration}%</div>
            </div>
            <div class="rec-metric">
              <div class="rec-metric-label">新人友好度</div>
              <div class="rec-metric-val ${rec.entryFriendliness >= 55 ? 'good' : rec.entryFriendliness >= 35 ? 'warn' : 'hot'}">${rec.entryFriendliness}/100</div>
            </div>
            <div class="rec-metric">
              <div class="rec-metric-label">增长动量</div>
              <div class="rec-metric-val ${rec.growthSignal >= 45 ? 'good' : rec.growthSignal >= 30 ? 'warn' : 'hot'}">${rec.growthSignal}/100</div>
            </div>
          </div>

          <div class="rec-advice">
            <div class="rec-advice-title">◆ 写作建议</div>
            <p>${rec.advice.text}</p>
          </div>

          <div class="rec-tags">
            ${rec.hints.map(h => `<span class="rec-tag">${h}</span>`).join('')}
          </div>
        </div>
      </div>`;
  }).join('');
}

// ── Trend Direction Banners ──
function renderTrendDirection(catMomentum, entryScores) {
  const container = document.getElementById('trendBanners');
  if (!container) return;

  const rising = catMomentum.filter(c => c.cmiNorm > 15).slice(0, 3);
  const falling = catMomentum.filter(c => c.cmiNorm < -15).slice(-3).reverse();
  const topFriendly = entryScores.slice(0, 3);
  const topCompetitive = [...entryScores].sort((a, b) => b.concentration - a.concentration).slice(0, 3);

  const banners = [];

  if (rising.length > 0) {
    banners.push({
      icon: '🔥', title: '上升赛道',
      desc: rising.map(c => `${c.category}(+${c.cmiNorm})`).join(' · ') + ' — 本周热度与书目双增，读者关注度持续攀升。',
    });
  }

  if (topFriendly.length > 0) {
    banners.push({
      icon: '🚪', title: '低门槛赛道',
      desc: topFriendly.map(c => `${c.category}(${c.entryScore})`).join(' · ') + ' — 签约新书活跃、榜单分散，新人突围机会较大。',
    });
  }

  if (topCompetitive.length > 0) {
    banners.push({
      icon: '🏰', title: '高壁垒领域',
      desc: topCompetitive.map(c => `${c.category}(${c.concentration}%)`).join(' · ') + ' — 头部集中度高，大神/白金占据主导，建议差异化切入。',
    });
  }

  if (falling.length > 0) {
    banners.push({
      icon: '📉', title: '降温赛道',
      desc: falling.map(c => `${c.category}(${c.cmiNorm})`).join(' · ') + ' — 热度回落，可能处于题材周期下行阶段。',
    });
  }

  container.innerHTML = banners.map(b => `
    <div class="trend-banner">
      <span class="trend-banner-icon">${b.icon}</span>
      <div class="trend-banner-text">
        <div class="trend-banner-title">${b.title}</div>
        <div class="trend-banner-desc">${b.desc}</div>
      </div>
    </div>
  `).join('');
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

    const currentBooks = currentWeek.books;
    const previousBooks = previousWeek ? previousWeek.books : null;

    // Run algorithms
    const catMomentum = computeCategoryMomentum(currentBooks, previousBooks);
    const entryScores = computeEntryFriendliness(currentBooks);
    const marketGaps = computeMarketGap(currentBooks, catMomentum, entryScores);

    // Render all sections
    renderOverview(index, catMomentum, marketGaps, entryScores);
    renderEntryChart(entryScores);
    renderMomentumChart(catMomentum);
    renderMarketChart(marketGaps);
    renderMarketTable(marketGaps);
    renderRecommendations(marketGaps);
    renderTrendDirection(catMomentum, entryScores);

  } catch (err) {
    console.error('风向分析启动失败:', err);
    document.getElementById('updateTime').textContent = '天机紊乱: ' + err.message;
  }
}

document.addEventListener('DOMContentLoaded', main);
