# BIG Fund Dashboard — Pampa Capital

Live portfolio dashboard for the **Balanced Income & Growth (BIG)** fund.
Mirrors the architecture of [pampa-dashboard](https://lucasmonpelat-tech.github.io/pampa-dashboard/) (Allaria) but adapted to a multi-asset USD-denominated strategy.

## Live URL

Will be published at: `https://lucasmonpelat-tech.github.io/big-dashboard/`

## 8 Tabs

1. **📊 Overview** — KPIs + Asset Allocation donut + NAV Evolution chart
2. **💼 Positions** — All 24 holdings with live NAVs, TER, and factsheet links
3. **💱 Currency** — Underlying currency exposure (weighted portfolio)
4. **🌍 Geography** — Country exposure from factsheets
5. **💰 Yield** — Current/Distribution yield vs 60/40 benchmark
6. **📈 YTM / FI** — Fixed income sleeve YTM, Duration, Maturity
7. **📉 Performance** — Multi-period returns, risk, capture ratios
8. **📝 Trade Log** — Executed and proposed trades

## Data Flow

- **Live prices (ETFs):** Stooq CSV (daily refresh via `price_refresher.py`)
- **UCITS NAVs:** Manual from factsheets (monthly refresh)
- **Private Alts:** Manual from manager statements (quarterly)
- **Lynk NAV:** Scraped from `app.lynkmarkets.com` (daily via `lynk_refresher.py`)
- **Performance:** Maximus data (monthly manual input)

See [`SETUP.md`](SETUP.md) for full setup instructions.

## Quick Start

```bash
# Install
pip install requests playwright
playwright install chromium

# Refresh all data
python scripts/refresh_all.py

# View locally
python -m http.server 8000
# → http://localhost:8000/
```

## Design Language

Navy + Gold ("Midnight Executive" palette) to differentiate from Allaria's Navy + Blue/Green:

- Background: `#0D1B2A`
- Cards: `#1A2A3D`
- Headers: `#1F3864`
- Primary accent: `#D4AF37` (gold) for BIG
- Secondary accents: `#64B5F6` (Equity), `#FFA726` (Alts), `#81C784` (FI), `#CE93D8` (Cash)
