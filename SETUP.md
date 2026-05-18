# BIG Fund Dashboard — Setup & Operations

Full architecture:
```
                        ┌──────────────────┐
                        │  Pershing export │  (manual, from Maximus/Pershing portal)
                        └────────┬─────────┘
                                 │
                                 ▼
                     ┌──────────────────────┐
                     │ Google Sheet (main)  │  ← Edit this when positions change
                     │ BIG_Live_View_FINAL  │
                     └──────────┬───────────┘
                                │
                                │ (published as CSV)
                                ▼
                     ┌──────────────────────────────────┐
                     │ data/funds_metadata.js (fallback)│  ← Mirrors Sheet, source of
                     │                                  │    truth for factsheet data
                     └────────────────┬─────────────────┘
                                      │
    ┌─────────────────┬───────────────┼──────────────────┐
    ▼                 ▼               ▼                  ▼
┌─────────┐     ┌──────────┐    ┌──────────┐     ┌───────────────┐
│ Stooq   │     │  Lynk    │    │ Factsheet│     │  Dashboard    │
│ prices  │─── ▶│ scraper  │───▶│ downloader│───▶ │  HTML + JS   │
│ (ETFs)  │     │ (NAV)    │    │   (PDFs)  │     │  Plotly viz   │
└─────────┘     └──────────┘    └──────────┘     └───────┬───────┘
                                                          │
                                                          ▼
                                             ┌───────────────────────┐
                                             │ GitHub Pages (public) │
                                             │ big-dashboard URL     │
                                             └───────────────────────┘
```

## Installed Structure

```
big-dashboard/
├── index.html               Main dashboard UI
├── dashboard.js             Rendering logic (tabs, KPIs, charts)
├── data/
│   ├── funds_metadata.js    Source of truth (positions, currency, yield, RF)
│   ├── live_prices.js       Stooq fetch module (client-side JS)
│   ├── live_prices.json     Output from price_refresher.py (cached prices)
│   └── lynk_data.json       Output from lynk_refresher.py (cached NAV)
├── scripts/
│   ├── price_refresher.py   Fetches Stooq quotes, writes live_prices.json
│   ├── lynk_refresher.py    Scrapes Lynk with Playwright, writes lynk_data.json
│   ├── download_factsheets.py   Downloads manager PDFs (URLs en data/factsheet_urls.json)
│   └── refresh_all.py       Runs all 3 in sequence
├── factsheets/              Downloaded PDFs per run
├── .claude/
│   └── launch.json          Local dev server config
├── SETUP.md                 This file
└── README.md                Project overview
```

## First-time Setup

### 1. Install Python dependencies

```bash
pip install requests playwright
playwright install chromium
```

### 2. Refresh data (first pass)

```bash
cd big-dashboard
python scripts/refresh_all.py
```

This populates:
- `data/live_prices.json` with today's ETF closes
- `data/lynk_data.json` with current NAV/AUM/returns
- `factsheets/` with manager PDFs

### 3. View locally

Start a local HTTP server (needed for JSON fetches to work):

```bash
cd big-dashboard
python -m http.server 8000
# Or: npx serve
```

Open: http://localhost:8000/

### 4. Publish to GitHub Pages

```bash
cd big-dashboard
git init
git add .
git commit -m "Initial commit — BIG dashboard v1"
git branch -M main
git remote add origin https://github.com/lucasmonpelat-tech/big-dashboard.git
git push -u origin main
```

Then: GitHub → Repo Settings → Pages → Source: `main` branch → Save.

**Dashboard URL:** `https://lucasmonpelat-tech.github.io/big-dashboard/`

Share this link with Fer for read-only access.

## Daily / Weekly Workflow

### Every morning (~30 sec)

```bash
cd big-dashboard
python scripts/price_refresher.py   # refresh ETF prices
git add data/live_prices.json
git commit -m "Daily price refresh $(date +%Y-%m-%d)"
git push
```

### Every week (Lynk NAV + factsheets)

```bash
python scripts/refresh_all.py        # runs all 3 scripts
git add data/ factsheets/
git commit -m "Weekly data refresh"
git push
```

### When a trade executes

1. Update `data/funds_metadata.js`:
   - `BIG_POSITIONS` array (add/remove/resize position)
2. Open `index.html` `#tab-trades` section:
   - Add row to trade log
3. Commit + push

## Data Sources

| Sleeve | Source | Frequency | Script |
|---|---|---|---|
| ETFs (CSPX, 4BRZ, ILF, ARGT, GLD, IBIT) | Stooq CSV | Daily | `price_refresher.py` |
| UCITS funds (PIMCO, MFS, NB, Man, Schroder) | Factsheets | Monthly | `download_factsheets.py` + manual NAV update |
| Private Alts (Carlyle, NB PE, HLEND, BPCC, Golub, Flex) | Manager emails | Quarterly | Manual |
| Lynk NAV (BIG fund product) | app.lynkmarkets.com | Daily | `lynk_refresher.py` |
| Maximus performance data | Maximus/LATAM ConsultUs | Monthly | Manual (update PORT_PERF_DETAIL in metadata) |

## Tabs Overview

| Tab | What it shows |
|---|---|
| 📊 Overview | KPIs (NAV, AUM, YTD, SI, Vol, Sharpe), Allocation donut, NAV chart |
| 💼 Positions | Full instrument list, live NAVs, TER, factsheet links |
| 💱 Currency | Underlying currency exposure aggregated (not share class) |
| 🌍 Geography | Country-level exposure from factsheets |
| 💰 Yield | Current/distribution yield, portfolio weighted vs 60/40 bmk |
| 📈 YTM / FI | Fixed income sleeve YTM, Duration, Maturity breakdown |
| 📉 Performance | Multi-period returns, risk metrics, capture ratios |
| 📝 Trade Log | History of executed and proposed trades |

## Known Limitations (to solve later)

1. **NAV chart is synthetic** — Real inception-to-date NAV series needs to be
   extracted from Lynk (chart data is behind React chunks).
2. **UCITS pricing is manual** — No public API for most UCITS. Options:
   - Refinitiv/Bloomberg terminal (if available at Pampa)
   - Morningstar API (free tier limited)
   - Manual weekly refresh from factsheet NAV
3. **Private Alts are quarterly-priced** — No way to get daily NAV. Last
   received value stays until new statement.
4. **Stooq CORS** — Works from Python but not always from browser. The Python
   refresher solves this (fetch happens server-side, dashboard reads JSON).

## Troubleshooting

### "All positions show N/A"
→ `data/live_prices.json` missing. Run `python scripts/price_refresher.py`

### "Lynk numbers look old"
→ Run `python scripts/lynk_refresher.py --email lucas.monpelat@pampa-capital.com`

### "Dashboard opens but shows static data"
→ Need local HTTP server for JSON fetches. Run `python -m http.server 8000` instead of opening `index.html` directly.

### "Factsheet download fails for X"
→ Some managers lock factsheets behind login. Edit the entry in
`data/factsheet_urls.json` and change `factsheet_url` to `"MANUAL_DROP — ..."`
so the script skipea ese fondo y se baja manual.
