# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A weekly web-scraping pipeline that collects public ranking data (~1000 entries/week) from Qidian (起点中文网) and visualizes it on an Alibaba Cloud VPS static dashboard using ECharts. The scraper uses Playwright to bypass Qidian's `probe.js` anti-bot protection.

**Production URL:** http://47.102.40.95/ (阿里云 VPS, Ubuntu 24.04, nginx)
**VPS SSH:** root@47.102.40.95 (密钥: `~/.ssh/qidian_vps_deploy`)

## Commands

```bash
# Install scraper dependencies + Playwright Chromium
pip install -r scraper/requirements.txt
playwright install chromium

# Dry-run scraper (no data saved, 20 books/rank)
python scraper/crawl.py --dry-run --max-per-rank 20

# Full scrape → data/YYYY-WW.json + data/index.json
python scraper/crawl.py

# Run text mining analysis only (jieba + TF-IDF)
python scraper/analysis/pipeline.py --text-only

# Run LLM analysis only (requires OPENAI_API_KEY env var)
python scraper/analysis/pipeline.py --skip-text-mining

# Run data mining only (forecast, association rules, clustering, anomaly detection)
python scraper/analysis/pipeline.py --data-mining-only

# Run AI Agent analysis only (DeepSeek ReAct agent, requires OPENAI_API_KEY)
python scraper/analysis/pipeline.py --agent-only

# Run all except data mining / agent
python scraper/analysis/pipeline.py --skip-data-mining --skip-agent

# Generate sample data for frontend testing (default 3 weeks)
python scraper/generate_sample.py [weeks]

# Local preview (serve from repo root, then visit docs/index.html)
python -m http.server 8080

# Manually deploy docs/ to VPS (Linux/macOS with rsync)
rsync -avz --delete -e "ssh -i ~/.ssh/qidian_vps_deploy -o StrictHostKeyChecking=accept-new" docs/ root@47.102.40.95:/var/www/qidian-heat-analysis/

# Manually deploy docs/ to VPS (Windows — no rsync, use tar+ssh pipeline)
tar czf - docs/ | ssh -i ~/.ssh/qidian_vps_deploy -o StrictHostKeyChecking=accept-new root@47.102.40.95 "rm -rf /var/www/qidian-heat-analysis/* && tar xzf - -C /var/www/ && mv /var/www/docs/* /var/www/qidian-heat-analysis/ && rm -rf /var/www/docs && nginx -t && systemctl reload nginx"

# SSH into VPS
ssh -i ~/.ssh/qidian_vps_deploy root@47.102.40.95
```

## Architecture

### Data pipeline

```
GitHub Actions (cron: weekly Monday 00:00 UTC)
  → scraper/crawl.py
  → Playwright headless Chromium + --disable-blink-features=AutomationControlled
  → data/YYYY-WW.json + data/index.json
  → scraper/analysis/pipeline.py --text-only (text mining: jieba + TF-IDF)
  → data/analysis/keywords.json, category_keywords.json, genre_tags.json
  → scraper/analysis/pipeline.py --data-mining-only (non-blocking)
  → data/analysis/forecast.json, association_rules.json, clusters.json, anomalies.json
  → scraper/analysis/pipeline.py --skip-text-mining (LLM: DeepSeek API, non-blocking)
  → data/analysis/llm_insights.json, weekly_report.md
  → scraper/analysis/pipeline.py --agent-only (ReAct agent: DeepSeek, non-blocking)
  → data/analysis/agent_insights.json, agent_report.md
  → cp -r data/ docs/data/ (analysis/ subdir included)
  → git commit & push
  → rsync docs/ → root@47.102.40.95:/var/www/qidian-heat-analysis/
  → nginx serves from /var/www/qidian-heat-analysis/
```

### Scraper (`scraper/`)

- **`crawl.py`** — CLI entry. `--dry-run` / `--max-per-rank N` control behavior.
- **`qidian_scraper/rankings.py`** — Playwright async scraper. `scrape_all_rankings()` is the main entry point (sync wrapper around async internals). One browser per crawl, fresh context per ranking page. Selector: `li[data-rid]` (20 items/page, pagination via `?page=N`). Parsing: title from `h2 a`, author from `p.author a.name`, category from `p.author a:not(.name):not(.go-sub-type)`, status from `p.author span`, intro from `p.intro`. Default: 200 books/rank × 8 rankings = 1600 books.
- **`qidian_scraper/storage.py`** — `save_weekly_snapshot()` writes `data/YYYY-WW.json`. `update_index()` rebuilds `data/index.json` scanning all week files for cumulative stats.
- **`generate_sample.py`** — Standalone fake-data generator for UI testing without hitting real Qidian.

**Anti-bot**: Qidian returns a 202 JS probe page for bare `requests`. Playwright with `--disable-blink-features=AutomationControlled` flag is required. No login/cookies needed — all data is public.

The scraper now has three layers of anti-bot defense:
1. **Probe detection** — after navigation, checks if HTML contains `"probe"` (the probe.js page) or if the fallback selector matches no real book items. If detected, retries with a fresh browser context.
2. **Retry with backoff** — up to 3 retries per ranking, with exponential backoff (2s, 4s, 6s).
3. **Random delays** — 2-4s between pages within a ranking, 4-10s between rankings, to avoid triggering rate limits.

⚠️ **Rate limiting**: Running the scraper multiple times in quick succession (e.g., manual re-runs within minutes) will cause Qidian to temporarily block the IP for ~5-10 minutes. The CI cron (weekly, once) never triggers this. If you need to re-scrape manually, wait at least 15 minutes between runs.

### Text Mining & LLM Analysis (`scraper/analysis/`)

- **`text_mining.py`** — jieba Chinese word segmentation + scikit-learn TF-IDF. 87 web-novel domain terms in custom dictionary, ~200 Chinese stop words. `run_text_mining()` outputs three JSON files to `data/analysis/`:
  - `keywords.json` — global TF-IDF keywords (top 50), per-category keywords (top 20 each)
  - `category_keywords.json` — full TF-IDF token/scores per category (background corpus = all intros)
  - `genre_tags.json` — 31 regex-based genre tag patterns (穿越, 重生, 系统, 修炼, 末世, etc.) with co-occurrence matrix
- **`llm_analyzer.py`** — DeepSeek API (OpenAI-compatible, `deepseek-chat` model). `batch_analyze_books()` extracts structured metadata from book intros (genre tags, protagonist archetype, golden finger type, world keywords). `generate_market_report()` produces a Chinese natural-language weekly report. Non-blocking: API failures write fallback JSON, workflow step uses `continue-on-error: true`.
- **`pipeline.py`** — CLI orchestrator with 7 flags: `--text-only`, `--skip-text-mining`, `--data-mining-only`, `--agent-only`, `--skip-data-mining`, `--skip-agent`, `--week YYYY-WNN`. Default mode runs text mining (blocking) → data mining → LLM → agent (all non-blocking). Data mining and agent steps are new since W27.

### Data Mining (`scraper/analysis/data_mining.py`)

Four sub-modules, each independently wrapped in try/except, all writing to `data/analysis/`:

- **Holt-Winters forecast** (`forecast_categories`) — Holt double-exponential smoothing per category (trend only, no seasonality). Requires ≥4 weeks of data, ≥3 positive points per category. Predicts 2 weeks ahead with 95% CI. Output: `forecast.json`.
- **Apriori association rules** (`mine_association_rules`) — mlxtend `apriori` + `association_rules`. One-hot encodes 8-ranking presence per book. Support≥0.05, confidence≥0.50, max 1-consequent. Top 20 by lift. Output: `association_rules.json`. **Important**: bidirectional pairs (A→B, B→A) form cycles — sankey renderer must deduplicate (see frontend notes).
- **K-means clustering** (`cluster_books`) — 8-D normalized-rank feature vector, `StandardScaler`, KMeans k=4 (42 seeds, 20 inits), PCA→2D. Clusters labeled by centroid argmax (e.g. "月票型"). Needs ≥20 books. Output: `clusters.json`.
- **Z-score anomaly detection** (`detect_anomalies`) — within-category rank-change Z-scores between current and previous week. Flags |Z|>2.5, max 50 results. Needs ≥5 data points per category, σ≥0.5. Output: `anomalies.json`.

### AI Agent (`scraper/analysis/agent.py`)

ReAct (Reasoning+Acting) agent named "天机", powered by DeepSeek Chat API. Autonomous data exploration loop with 6 tools:

| Tool | Description |
|------|-------------|
| `get_weekly_stats(week)` | Overview: total books, authors, categories, per-rank distribution |
| `get_category_trend(category)` | Multi-week heat score trend for a category |
| `get_top_books(week, rank_type, n)` | Top N books for a ranking (max 20) |
| `get_keywords(week)` | Top 20 TF-IDF keywords from `keywords.json` |
| `get_genre_distribution(week)` | Genre tag distribution from `genre_tags.json` |
| `compare_weeks(week1, week2)` | Week-over-week diff: churn rate, category heat changes |

Tools read from pre-computed JSON files in `data/` — no external API calls during execution. Max 8 ReAct rounds. Report extracted from `<REPORT>...</REPORT>` tags, FAQ parsed from report or auto-generated (12-15 structured Q&As, merged to max 40). Output: `agent_insights.json` + `agent_report.md`.

**Key constraints**:
- W20-W21 data excluded from analysis (`total < 1000` = placeholder intros, no value)
- Deduplication key: (title, author)
- Per-category TF-IDF requires ≥10 books in category; sparse categories are skipped
- DeepSeek API key via `OPENAI_API_KEY` env var; ~0.14 RMB/1M tokens, ~1 cent per weekly run
- Batch size: 30 books/call, max 120 books total for cost control

### Frontend (`docs/`)

Zero-build static site. ECharts 6.0 + Google Fonts (Noto Serif SC / Noto Sans SC) loaded from CDN with `defer` at end of `<body>` to avoid blocking render. Fonts from `fonts.googleapis.com`, ECharts from `cdn.jsdelivr.net`.

Design aesthetic: **"天榜墨韵"** — dark ink-wash parchment theme with gold accents. CSS variables in `style.css` control the palette (`--ink`, `--parchment`, `--gold`, `--vermillion`).

**Pages:**
- `index.html` + `app.js` + `style.css` — main dashboard (总览)
- `analysis.html` + `analysis.js` + `analysis.css` — algorithmic analysis page (深度分析)
- `trends.html` + `trends.js` + `trends.css` — market trend & writing recommendation page (风向推荐)
- `ai-report.html` + `ai-report.js` + `ai-report.css` — AI-powered text mining insights page (AI洞见)
- All pages share `style.css` and a `.site-nav` component for switching between them

**Dashboard layout (`index.html` / `app.js`):**
1. **Overview marks** — 4 stat cards (weeks, titles, authors, categories)
2. **Rank explorer (榜位巡览)** — pill-tab selector (8 ranking types) + Top 3 highlight cards + horizontal bar chart (Top 30). Bars use a `rankToScore()` conversion (rank → 0–100, bigger = better) for intuitive display. Rank numbers shown without `#` prefix.
3. **Category rose pie** + **Status donut** — side-by-side 2-column grid
4. **Author scatter (笔落惊风)** — ECharts scatter/bubble chart, Top 20 authors by cumulative appearances across all weeks. `symbolSize` proportional to count, `RadialGradient` gives a "star glow" effect. yAxis inverted so most appearances are at top.
5. **Cross-rank leaderboard (霸榜天卷)** — custom HTML cards (not ECharts), Top 12 books by list coverage. Each card shows: rank number (gold/silver/bronze for top 3), title + author + category + status, "霸占 N/8 榜" coverage indicator, colored rank badges sorted best-first per list.
6. **Ranking table (榜单名录)** — filtered by active tab, 125 rows, sticky header, gold/silver/bronze rank coloring

**Analysis page (`analysis.html` / `analysis.js`):**
1. **Overview marks** — weeks count, unique books, heat champion, widest coverage
2. **Heat score table (综合热度总榜)** — Top 50 by weighted algorithm `Σ(weight / √rank)`. Weights: yuepiao 1.0, hotsales 0.95, readindex 0.85, recom 0.8, collect 0.75, signnewbook 0.7, newfans 0.6, vipup 0.5. Shows heat score, list badges, best rank, momentum tag.
3. **Rank changes table (排名异动追踪)** — week-over-week rank delta per list. Pills switch between 8 ranking types. Labels: 新晋 (new), ↑N (improved), ↓N (dropped), — (unchanged). Row backgrounds tinted by change direction. Anomaly entries (|Z|>2.5) get ⚠ marker + row highlight loaded from `anomalies.json`.
4. **Longevity chart (霸榜常青)** — horizontal bar, Top 20 books by cumulative weeks appeared. Green gradient.
5. **Coverage pie (榜单覆盖度)** — rose/radius pie showing distribution of how many lists books appear on (1-8).
6. **Category grid (分类争锋)** — responsive card grid, Top 12 categories by total heat, each showing top 5 books with gold/silver/bronze rank badges.
7. **Association Sankey (榜单关联 — 共现流向)** — ECharts sankey from `association_rules.json`. Nodes = 8 ranking types, links = deduplicated Apriori rules (lift as thickness). **Critical**: bidirectional pairs MUST be deduplicated in renderer (sort antecedent+consequent as canonical key) — sankey requires DAG, "original data has cycle" error otherwise.
8. **K-Means scatter (书籍聚类画像)** — PCA 2D scatter from `clusters.json`. 4 color-coded clusters, hover shows title/author/category/cluster label. Data loads async via `Promise.allSettled` with try/catch per chart.

**Trends page (`trends.html` / `trends.js`):**

Four algorithms, all cross-sectional except CMI:

- **Entry Friendliness Score (EFS / 新人友好度)** — cross-sectional metric using ONLY current-week data. Three factors: ① 签约新书密度 (signnewbook entries per category, the official "new book" signal) × 0.45, ② 竞争分散度 (1 − top-3 Herfindahl heat concentration) × 0.30, ③ 排名可及性 (inverse normalized avg rank, lower avg rank = more accessible) × 0.25. Raw composite normalized to 10-90 range across categories. Does NOT depend on week-over-week overlap, avoiding the "100% everywhere" problem when leaderboard churn is high.
- **Category Momentum Index (CMI)** — `0.6 × tanh(heatΔ/30) + 0.4 × tanh(countΔ/20)`, scaled `×100` to [-100, 100]. Uses tanh damping to prevent extreme swings in sparse categories. No artificial normalization — tanh naturally bounds the output to [-1, 1].
- **Market Gap Score (MGS / 风口指数)** — `demandScore×0.35 + (1−concentration)×0.25 + entryFriendliness×0.25 + growthSignal×0.15`. Demand = yuepiao/hotsales rank quality (real money = real demand). Concentration = Herfindahl top-3 heat share.
- **Writing advice generator** — classifies categories into 5 templates: 强烈推荐 (high demand + low competition), 差异化切入 (high demand + high competition), 新人友好 (high entry score), 风口赛道 (strong growth), 稳健深耕 (stable). Each card includes sub-genre hints based on 2025-2026 market trends.

Sections: overview cards, stacked-bar entry friendliness chart, momentum bars, demand-vs-competition scatter, scoring table, recommendation cards (Top 6 with detailed metrics panels), **Holt-Winters forecast chart** (multi-line, history + fitted trend + 2-week prediction + 95% CI bands, loaded async from `forecast.json`), radar chart (4-D market gap per category, top 6).

**AI Report page (`ai-report.html` / `ai-report.js`):**

Loads analysis files from `data/analysis/` (each with independent try/catch for graceful degradation):
1. **Overview marks** — analyzed books count, keyword count, genre tag count
2. **AI Agent Market Report** — `agent_report.md` rendered as HTML via regex (##→h2, **bold**, - →li). Fallback: `weekly_report.md` from LLM analyzer. 4 sections: 本周概览, 题材风向, 人设趋势, 创作建议.
3. **Global keywords** — horizontal bar, top 40 TF-IDF keywords, gold gradient
4. **Genre tag distribution** — horizontal bar, top 25 genre tags, green gradient
5. **Category keywords** — tabbed bar chart (`.rank-pills` tabs per category), azure gradient. Only categories with ≥10 books shown.
6. **Protagonist archetypes** — rose/area pie chart (9 archetypes from LLM)
7. **Golden finger types** — regular pie chart (7 types from LLM)
8. **World keywords** — horizontal bar chart (purple gradient, top 25 from LLM aggregations)
9. **Genre co-occurrence** — ECharts 6.0 chord diagram. Labels on circumference, curved ribbons between connected sectors.
10. **Smart Q&A Chat (智能问答 — 问问天机)** — client-side FAQ matching from `agent_insights.json`. Tokenizes questions via character-length heuristic, scores via Jaccard-style overlap + keyword bonus (threshold≥0.06). Renders chat bubbles with CSS `msgIn` animation. Fallback suggests checking analysis/trends pages.

**ECharts patterns used across all files:**
- `initChart(domId)` — disposes existing instance, creates SVG renderer, registers for resize
- `darkAxis(name)` / `darkTooltip()` — shared dark-theme base config
- `containLabel: true` on grids; spread order matters: `...darkAxis()` first, then overrides
- Data path auto-detection: JS checks `window.location.pathname.includes('/docs/')` to decide between `../data/` and `./data/`. On VPS and local, uses `./data/`.

**Legacy files** in `docs/css/`, `docs/images/`, `docs/picture/`, `docs/scripts/` — unused, leftover from a prior Bootstrap-based theme.

### GitHub Actions (`.github/workflows/scrape.yml`)

- Triggers: `cron 0 0 * * 1` (Monday UTC) + `workflow_dispatch`
- Steps: checkout → Python 3.12 → pip install → `playwright install chromium` → `python scraper/crawl.py` → `python scraper/analysis/pipeline.py --text-only` → `python scraper/analysis/pipeline.py --data-mining-only` (non-blocking) → `python scraper/analysis/pipeline.py --skip-text-mining` (LLM, non-blocking) → `python scraper/analysis/pipeline.py --agent-only` (ReAct agent, non-blocking) → `cp -r data/ docs/data/` → commit & push `data/` + `docs/data/` → `rsync docs/` to VPS. All three analysis steps use `continue-on-error: true`.
- Secrets required: `VPS_HOST` (47.102.40.95), `VPS_USERNAME` (root), `VPS_SSH_PRIVATE_KEY` (ed25519 deploy key), `OPENAI_API_KEY` (DeepSeek API key — LLM and Agent steps degrade gracefully without it)
- Line endings: CRLF breaks YAML parsing on GitHub; `.gitattributes` enforces `eol=lf` for all text files

### VPS (`47.102.40.95`)

- Ubuntu 24.04, nginx 1.24 serving from `/var/www/qidian-heat-analysis/`
- `gzip` enabled for JSON/CSS/JS; static assets cached 7d, data files 1h
- No domain; access via IP directly (port 80)
- nginx config: `/etc/nginx/sites-available/default`, reload with `nginx -t && systemctl reload nginx`
- Logs: `tail -f /var/log/nginx/access.log` / `error.log`

### Data format

`data/YYYY-WW.json`: `{ week, scraped_at, total, books: [{ rank, title, author, category, status, intro, url, rank_type }] }`
`data/index.json`: `{ updated_at, weeks: [{ week, file, total }], total_weeks, unique_titles, unique_authors, categories }`

## Valid ranking URLs

| Key | URL | Label |
|-----|-----|-------|
| yuepiao | `/rank/yuepiao/` | 月票榜 |
| hotsales | `/rank/hotsales/` | 畅销榜 |
| readindex | `/rank/readindex/` | 阅读指数榜 |
| recom | `/rank/recom/` | 推荐榜 |
| collect | `/rank/collect/` | 收藏榜 |
| newfans | `/rank/newfans/` | 书友榜 |
| vipup | `/rank/vipup/` | 更新榜 |
| signnewbook | `/rank/signnewbook/` | 签约新书榜 |

`/rank/rec/` and `/rank/newbook/` are dead — those were incorrect assumptions.

## Key constraints

- Playwright required; plain `requests` gets 202 probe page
- `word_count` not available on ranking list pages (removed from schema)
- 8 rankings × 200 books = up to 1600/week at default settings (CLI default: `--max-per-rank 200`)
- Pages have 20 `li[data-rid]` items each; pagination uses `?page=N`
- Data lives in `docs/data/` (workflow copies from repo root `data/`). VPS nginx serves directly from `/var/www/qidian-heat-analysis/`.
- For UI redesigns, invoke the `frontend-design` skill (plugin: `frontend-design@claude-plugins-official`)
- ⚠️ Manual re-scrapes within 15 minutes of each other will trigger Qidian IP rate limiting. Single CI cron runs are safe.
- W20-W21 data is excluded from text mining/LM analysis (total < 1000, placeholder intros).
- Each JS file duplicates shared helpers (fetchJSON, initChart, darkAxis, etc.) — no module bundler; keep it self-contained.
- ECharts sankey requires DAG (no cycles). Association rules contain bidirectional pairs (A→B, B→A). Renderer MUST deduplicate by canonical pair key before building sankey links.
- `mlxtend` installation can fail on some platforms (requires C compiler for pandas/NumPy). Data mining step is non-blocking in CI; missing module → silent skip.
- Agent tool calls have 0.3s rate-limit delay. Max 8 ReAct rounds. If model doesn't produce `<REPORT>` tags by max rounds, a forced final report is generated.
- Windows: `rsync` not available by default — use the tar+ssh pipeline for manual deploy.
- Forecast, association rules, clustering, and anomaly detection all write to `data/analysis/` with independent error handling — one failing doesn't block others.
