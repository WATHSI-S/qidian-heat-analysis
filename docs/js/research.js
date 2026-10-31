import {RANK_LABELS,DARK_TEXT,GOLD,esc,rankLabel,initChart,emptyChart,darkAxis,darkTooltip} from './shared.js';
const CLUSTER_COLORS=['#c9a96e','#5b8db8','#27ae60','#e67e22'];
const CHART_COLORS=CLUSTER_COLORS;
function renderAssociationMatrix(data) {
  const chart = initChart('research-chart');
  if (!chart) return;
  if (!data?.rules?.length) { emptyChart('research-chart', '本周没有达到阈值的关联规则'); return; }
  const types = data.rank_types || Object.keys(RANK_LABELS);
  const cells = data.rules.map(rule => ({ value: [types.indexOf(rule.consequent), types.indexOf(rule.antecedent), rule.confidence], rule }));
  chart.setOption({
    tooltip: { ...darkTooltip(), formatter: p => `${rankLabel(p.data.rule.antecedent)} → ${rankLabel(p.data.rule.consequent)}<br/>置信度 ${(p.data.rule.confidence * 100).toFixed(1)}%<br/>支持度 ${(p.data.rule.support * 100).toFixed(1)}%<br/>提升度 ${p.data.rule.lift}` },
    grid: { left: 90, right: 25, top: 20, bottom: 90 },
    xAxis: { type: 'category', data: types.map(rankLabel), ...darkAxis(), axisLabel: { color: DARK_TEXT, rotate: 35, fontSize: 10 } },
    yAxis: { type: 'category', data: types.map(rankLabel), ...darkAxis() },
    visualMap: { min: 0, max: 1, calculable: true, orient: 'horizontal', bottom: 0, left: 'center', textStyle: { color: DARK_TEXT }, inRange: { color: ['#28231c', '#c9a96e'] } },
    series: [{ type: 'heatmap', data: cells, label: { show: true, formatter: p => `${Math.round(p.value[2] * 100)}%` } }],
  }, true);
}


function renderClusterScatter(clusterData) {
  const chart = initChart('research-chart');
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

function renderForecastChart(data) {
  const chart = initChart('research-chart');
  if (!chart) return;
  if (!data?.categories || !Object.keys(data.categories).length) { emptyChart('research-chart'); return; }
  const items = Object.entries(data.categories).sort((a, b) =>
    (b[1].history.findLast(h => h.heat !== null)?.heat || 0) - (a[1].history.findLast(h => h.heat !== null)?.heat || 0)).slice(0, 8);
  const weeks = data.week_labels;
  const series = [];
  for (const [name, value] of items) {
    series.push({ name, type: 'line', data: value.history.map(h => h.heat), connectNulls: false, symbolSize: 5 });
    if (value.reason === 'validated' && value.forecast !== null) {
      series.push({ name: name + '（实验预测）', type: 'line', data: [...Array(weeks.length - 1).fill(null), value.history.at(-1).heat, value.forecast, value.forecast_w2], lineStyle: { type: 'dotted' }, symbol: 'diamond' });
    }
  }
  if (!items.some(([, v]) => v.history.some(h => h.heat !== null))) { emptyChart('research-chart', '历史采集不完整，暂无可展示的同口径序列'); return; }
  chart.setOption({ tooltip: { ...darkTooltip(), trigger: 'axis' }, legend: { type: 'scroll', left: 10, right: 10, bottom: 0, textStyle: { color: DARK_TEXT } }, grid: { left: 15, right: 25, top: 15, bottom: 65, containLabel: true },
    xAxis: { type: 'category', data: [...weeks, '预测+1周', '预测+2周'], ...darkAxis() },
    yAxis: { type: 'value', ...darkAxis('热度') }, series }, true);
}

function renderCooccurrenceChart(data) {
  const chart = initChart('research-chart');
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
        if (p.dataType === 'node') return `${esc(p.name)}<br/>总关联: ${p.value}`;
        return `${esc(p.data.source)} ↔ ${esc(p.data.target)}<br/>共现次数: ${p.data.value}`;
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
        borderColor: '#1e1b15',
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

export const researchRenderers={association_rules:renderAssociationMatrix,clusters:renderClusterScatter,forecast:renderForecastChart,genre_tags:renderCooccurrenceChart};
