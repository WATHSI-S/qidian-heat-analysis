/** Shared loading, safe formatting and bounded ECharts lifecycle. */
export const DATA_BASE = new URL('../data/', import.meta.url);
export const RANK_LABELS = { yuepiao: '月票榜', hotsales: '畅销榜', readindex: '阅读指数榜', recom: '推荐榜', collect: '收藏榜', newfans: '书友榜', vipup: '更新榜', signnewbook: '签约新书榜' };
export const DARK_TEXT = '#9a8e7e';
export const DARK_AXIS = '#362f26';
export const GOLD = '#c9a96e';
export const VERMILLION = '#c0392b';
export const JADE = '#27ae60';
export const AZURE = '#5b8db8';
const requests = new Map();
const charts = new Map();

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
export function rankLabel(key) { return RANK_LABELS[key] || key; }
export function bookKey(book) { return JSON.stringify([book.title, book.author]); }
export function safeBookURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'www.qidian.com' && !url.username && !url.password && !url.port && /^\/book\/\d+\/$/.test(url.pathname) ? url.href : null;
  } catch { return null; }
}
export function bookLink(book, className = '') {
  const url = safeBookURL(book.url);
  const attrs = `class="${esc(className)}" title="${esc(book.intro || '')}"`;
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener" ${attrs}>${esc(book.title)}</a>` : `<span ${attrs}>${esc(book.title)}</span>`;
}
export function markdownHTML(text) {
  const inline = value => esc(value).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  let list = false;
  const html = [];
  for (const line of String(text || '').split('\n')) {
    if (!line.startsWith('- ') && list) { html.push('</ul>'); list = false; }
    if (line.startsWith('- ')) {
      if (!list) { html.push('<ul>'); list = true; }
      html.push(`<li>${inline(line.slice(2))}</li>`);
    } else if (line.startsWith('## ')) html.push(`<h2>${inline(line.slice(3))}</h2>`);
    else if (line.trim()) html.push(`<p>${inline(line)}</p>`);
  }
  if (list) html.push('</ul>');
  return html.join('');
}
export function fetchJSON(path) {
  const url = String(path);
  if (!requests.has(url)) {
    const read = async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        let response;
        try {
          response = await fetch(url, { cache: 'no-cache', signal: AbortSignal.timeout(60000) });
          if (response.ok) return await response.json();
        } catch (error) {
          if (attempt === 0) continue;
          throw error;
        }
        throw new Error(`HTTP ${response.status}: ${url}`);
      }
    };
    requests.set(url, read().catch(error => {
      requests.delete(url);
      throw error;
    }));
  }
  return requests.get(url);
}
export const loadIndex = () => fetchJSON(new URL('index.json', DATA_BASE));
export const loadWeekData = file => fetchJSON(new URL(file, DATA_BASE));
export async function loadAnalysisFile(filename, week, allowStale = false, required = false) {
  try {
    const index = await loadIndex();
    const target = week || index.weeks.at(-1)?.week;
    const manifest = await fetchJSON(new URL('analysis/index.json', DATA_BASE));
    const entry = manifest.artifacts[filename];
    if (!entry?.path || (!allowStale && entry.week !== target)) return null;
    const result = await fetchJSON(new URL('analysis/' + entry.path, DATA_BASE));
    if (result.week !== entry.week) return null;
    return { ...result, stale: result.week !== target, attempt_status: entry.attempt_status, attempt_week: entry.attempt_week };
  } catch (error) {
    if (required) throw new Error(`汇总数据加载失败：${['TimeoutError', 'AbortError'].includes(error.name) ? '网络读取超时，请重试' : error.message}`);
    return null;
  }
}
export async function loadDashboard() {
  const index = await loadIndex();
  const latest = index.weeks.at(-1);
  if (!latest) throw new Error('暂无真实采集数据');
  const [snapshot, summary] = await Promise.all([loadWeekData(latest.file), loadAnalysisFile('summary.json', latest.week, false, true)]);
  if (!summary) throw new Error('本周汇总与数据周不匹配，请检查发布产物');
  Object.assign(RANK_LABELS, index.rank_labels || {});
  return { index, snapshot, summary };
}
export function showContext(snapshot, summary, artifacts = []) {
  const time = document.getElementById('updateTime');
  if (!time) return;
  time.textContent = `数据周：${snapshot.week} · 采集时间：${snapshot.scraped_at || '未知'}`;
  let notice = document.getElementById('dataStatus');
  if (!notice) { notice = document.createElement('p'); notice.id = 'dataStatus'; notice.className = 'data-status'; time.after(notice); }
  const missing = Object.entries(snapshot.quality?.rankings || {}).filter(([, q]) => q.status !== 'complete').map(([rt]) => rankLabel(rt));
  const depths = summary?.comparison?.depths || {};
  const comparisons = Object.entries(depths).map(([rt, depth]) => `${rankLabel(rt)} Top ${depth}`).join('、');
  const status = artifacts.map(([label, result]) => result ? `${label}：${result.week}${result.stale ? '（历史结果）' : ''}${result.status === 'partial' ? '（部分可用）' : ''}${['error', 'unavailable'].includes(result.attempt_status) ? '；最近尝试失败，保留有效结果' : ''}` : `${label}：本周不可用`);
  const links = snapshot.quality?.invalid_urls ? `${snapshot.quality.invalid_urls} 条历史书籍链接不可恢复，已显示为纯文本` : '';
  notice.textContent = [`采集${missing.length ? '不完整：' + missing.join('、') : '完整'}`, comparisons ? `与 ${summary.comparison.previous_week} 比较：` + comparisons : '暂无可比周数据', links, ...status].filter(Boolean).join(' · ');
}
export function initChart(domId) {
  const dom = document.getElementById(domId);
  if (!dom) return null;
  if (!globalThis.echarts) { const library = document.querySelector('#chartLibrary'); dom.textContent = !library ? '图表库不可用' : library.dataset.failed ? '图表库加载失败，请刷新重试' : '图表库正在加载…'; return null; }
  const existing = charts.get(domId);
  if (existing && !existing.isDisposed()) return existing;
  const chart = globalThis.echarts.getInstanceByDom(dom) || globalThis.echarts.init(dom, null, { renderer: 'svg' });
  charts.set(domId, chart);
  return chart;
}
export function chartCount() { return charts.size; }
export function disposeCharts() { charts.forEach(chart => chart.dispose()); charts.clear(); }
if (typeof window !== 'undefined') {
  window.addEventListener('resize', () => charts.forEach(chart => { if (!chart.isDisposed()) chart.resize(); }));
  window.addEventListener('pagehide', disposeCharts);
}
export function darkAxis(name = '') {
  return { axisLine: { lineStyle: { color: DARK_AXIS } }, axisTick: { show: false }, axisLabel: { color: DARK_TEXT, fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(54,47,38,0.3)' } }, name, nameTextStyle: { color: DARK_TEXT, fontSize: 11 } };
}
export function darkTooltip() {
  return { backgroundColor: '#2a2218', borderColor: '#5a4a30', textStyle: { color: '#e0d6c2', fontSize: 12, fontFamily: 'Noto Sans SC' } };
}
export function emptyChart(id, message = '数据不足或本周分析不可用') {
  initChart(id)?.setOption({ title: { text: message, left: 'center', top: 'center', textStyle: { color: DARK_TEXT, fontSize: 13 } } }, true);
}

export function disposeChart(id) { const chart=charts.get(id); if(chart){chart.dispose();charts.delete(id);} }
