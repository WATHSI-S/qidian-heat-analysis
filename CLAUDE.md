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
python scraper/crawl.py --max-per-rank 125

# Generate sample data for frontend testing (default 3 weeks)
python scraper/generate_sample.py [weeks]

# Local preview (serve from repo root, then visit docs/index.html)
python -m http.server 8080

# Manually deploy docs/ to VPS
rsync -avz --delete -e "ssh -i ~/.ssh/qidian_vps_deploy -o StrictHostKeyChecking=accept-new" docs/ root@47.102.40.95:/var/www/qidian-heat-analysis/

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
  → cp -r data/ docs/data/
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

### Frontend (`docs/`)

Zero-build static site. ECharts 6.0 + Google Fonts (Noto Serif SC / Noto Sans SC) loaded from CDN with `defer` at end of `<body>` to avoid blocking render. Fonts from `fonts.googleapis.com`, ECharts from `cdn.jsdelivr.net`.

Design aesthetic: **"天榜墨韵"** — dark ink-wash parchment theme with gold accents. CSS variables in `style.css` control the palette (`--ink`, `--parchment`, `--gold`, `--vermillion`).

**Pages:**
- `index.html` + `app.js` + `style.css` — main dashboard
- `analysis.html` + `analysis.js` + `analysis.css` — algorithmic analysis page
- `trends.html` + `trends.js` + `trends.css` — market trend & writing recommendation page
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
3. **Rank changes table (排名异动追踪)** — week-over-week rank delta per list. Pills switch between 8 ranking types. Labels: 新晋 (new), ↑N (improved), ↓N (dropped), — (unchanged). Row backgrounds tinted by change direction.
4. **Longevity chart (霸榜常青)** — horizontal bar, Top 20 books by cumulative weeks appeared. Green gradient.
5. **Coverage pie (榜单覆盖度)** — rose/radius pie showing distribution of how many lists books appear on (1-8).
6. **Category grid (分类争锋)** — responsive card grid, Top 12 categories by total heat, each showing top 5 books with gold/silver/bronze rank badges.

**Trends page (`trends.html` / `trends.js`):**

Four algorithms, all cross-sectional except CMI:

- **Entry Friendliness Score (EFS / 新人友好度)** — cross-sectional metric using ONLY current-week data. Three factors: ① 签约新书密度 (signnewbook entries per category, the official "new book" signal) × 0.45, ② 竞争分散度 (1 − top-3 Herfindahl heat concentration) × 0.30, ③ 排名可及性 (inverse normalized avg rank, lower avg rank = more accessible) × 0.25. Raw composite normalized to 10-90 range across categories. Does NOT depend on week-over-week overlap, avoiding the "100% everywhere" problem when leaderboard churn is high.
- **Category Momentum Index (CMI)** — `0.6 × tanh(heatΔ/30) + 0.4 × tanh(countΔ/20)`, normalized to ±100. Uses tanh damping to prevent extreme swings in sparse categories.
- **Market Gap Score (MGS / 风口指数)** — `demandScore×0.35 + (1−concentration)×0.25 + entryFriendliness×0.25 + growthSignal×0.15`. Demand = yuepiao/hotsales rank quality (real money = real demand). Concentration = Herfindahl top-3 heat share.
- **Writing advice generator** — classifies categories into 5 templates: 强烈推荐 (high demand + low competition), 差异化切入 (high demand + high competition), 新人友好 (high entry score), 风口赛道 (strong growth), 稳健深耕 (stable). Each card includes sub-genre hints based on 2025-2026 market trends.

Sections: overview cards, stacked-bar entry friendliness chart, momentum bars, demand-vs-competition scatter, scoring table, recommendation cards (Top 6), trend direction banners.

**ECharts patterns used across all files:**
- `initChart(domId)` — disposes existing instance, creates SVG renderer, registers for resize
- `darkAxis(name)` / `darkTooltip()` — shared dark-theme base config
- `containLabel: true` on grids; spread order matters: `...darkAxis()` first, then overrides
- Data path auto-detection: JS checks `window.location.pathname.includes('/docs/')` to decide between `../data/` and `./data/`. On VPS and local, uses `./data/`.

**Legacy files** in `docs/css/`, `docs/images/`, `docs/picture/`, `docs/scripts/` — unused, leftover from a prior Bootstrap-based theme.

### GitHub Actions (`.github/workflows/scrape.yml`)

- Triggers: `cron 0 0 * * 1` (Monday UTC) + `workflow_dispatch`
- Steps: checkout → Python 3.12 → pip install → `playwright install chromium` → `python scraper/crawl.py` → `cp -r data/ docs/data/` → commit & push `data/` + `docs/data/` → `rsync docs/` to VPS
- Secrets required: `VPS_HOST` (47.102.40.95), `VPS_USERNAME` (root), `VPS_SSH_PRIVATE_KEY` (ed25519 deploy key)
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
