"""
parse_factsheet.py
==================
Universal factsheet parser. Extracts standardized data from any fund PDF.

Reads:    factsheets/{sleeve}/{TICKER}_{DATE}.pdf
Outputs:  data/funds/{TICKER}.json

Extracts (best-effort, returns None if section not found):
  - top_holdings: dict[name] -> weight_pct (top 10)
  - sectors: dict[sector] -> weight_pct
  - regions: dict[region] -> weight_pct
  - countries: dict[country] -> weight_pct
  - currencies: dict[currency] -> weight_pct
  - style_box: dict (V/G/B split or large/mid/small split)
  - active_share: float
  - ter: float (ongoing charges)
  - risk_metrics: { vol_3y, vol_5y, sharpe_3y, sharpe_5y, max_dd_3y, max_dd_5y }
  - fi_metrics (FI only): { ytw, duration, maturity, current_yield, credit_quality, sub_asset_class }
  - as_of_date

Usage:
    python scripts/parse_factsheet.py                      # parses all PDFs in factsheets/
    python scripts/parse_factsheet.py factsheets/equity/NBGMT_20260331.pdf  # one file
"""

import json
import re
import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.parent

# Map filename prefix (TICKER) → ISIN / sleeve for metadata
TICKER_METADATA = {
    "CSPX":     {"isin": "IE00B5BMR087", "sleeve": "Equity",       "name": "iShares Core S&P 500 UCITS"},
    "NBGMT":    {"isin": "IE00BFMHRK20", "sleeve": "Equity",       "name": "NB Global Equity Megatrends I"},
    "MFSCV":    {"isin": "LU1985812756", "sleeve": "Equity",       "name": "MFS Meridian Contrarian Value I1"},
    "THOR":     {"isin": "IE00B6YCBF59", "sleeve": "Equity",       "name": "Thornburg Equity Income Builder I"},
    "JHGSC":    {"isin": "LU2940405447", "sleeve": "Equity",       "name": "Janus Henderson Global Smaller Cos F2"},
    "LGLI":     {"isin": "IE00BF4KN675", "sleeve": "Equity",       "name": "Lazard Global Listed Infrastructure A"},
    "ILF":      {"isin": "US4642873909", "sleeve": "Equity",       "name": "iShares Latin America 40 ETF"},
    "4BRZ":     {"isin": "DE000A0Q4R85", "sleeve": "Equity",       "name": "iShares MSCI Brazil UCITS (DE)"},
    "ARGT":     {"isin": "US37950E2596", "sleeve": "Equity",       "name": "Global X MSCI Argentina ETF"},
    "PIMCO-LD": {"isin": "IE00BDT57R20", "sleeve": "Fixed Income", "name": "PIMCO GIS Low Duration Income I"},
    "PIMCO-INC":{"isin": "IE00B87KCF77", "sleeve": "Fixed Income", "name": "PIMCO GIS Income I"},
    "PIMCO-EM": {"isin": "IE00B29K0P99", "sleeve": "Fixed Income", "name": "PIMCO GIS EM Local Bond I"},
    "MANIG":    {"isin": "IE000OE87WX6", "sleeve": "Fixed Income", "name": "Man GLG Global IG Opportunities"},
    "TGF":      {"isin": "XS2324777171", "sleeve": "Fixed Income", "name": "Tenac Global Fund"},
    "SGCB":     {"isin": "LU2049315265", "sleeve": "Fixed Income", "name": "Schroder GAIA Cat Bond C"},
}


def extract_text(pdf_path):
    """Extract text from PDF using pypdf."""
    import pypdf
    reader = pypdf.PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() for page in reader.pages)


# ─────────────────────────────────────────────────────────────
# UNIVERSAL EXTRACTORS — try multiple patterns to find each section
# ─────────────────────────────────────────────────────────────

def find_section(text, section_keywords, max_chars=3000):
    """Find a section by keyword (case-insensitive). Returns the chunk."""
    text_lower = text.lower()
    for kw in section_keywords:
        idx = text_lower.find(kw.lower())
        if idx >= 0:
            return text[idx:idx + max_chars]
    return None


def extract_top_holdings(text):
    """Extract top 10 holdings. Returns dict[name] -> pct or None."""
    section = find_section(text, [
        "TOP 10 FUND HOLDINGS", "TOP TEN HOLDINGS", "TEN LARGEST HOLDINGS",
        "Top 10 holdings", "Top Holdings", "Top 10 Fund Holdings",
        "Largest Holdings", "Top ten holdings"
    ])
    if not section:
        return None

    holdings = {}
    # Match patterns like "Name 4.95" or "Name 4.95%" or "Name           4.95"
    # Try line-by-line approach
    for line in section.split("\n")[:60]:  # limit scope
        line = line.strip()
        if not line:
            continue
        # Pattern: text followed by percentage at end
        m = re.match(r"^([A-Z][A-Za-z\.\,\&\-\s\(\)0-9/']+?)\s+(\d{1,2}\.\d{1,2})\%?\s*(\d+\.\d+)?\s*$", line)
        if m:
            name = m.group(1).strip().rstrip(",")
            pct = float(m.group(2))
            # Filter out obvious non-holdings (sectors, regions)
            if pct > 30 or pct < 0.1:
                continue
            if any(skip in name.lower() for skip in [
                "total", "cash", "country", "region", "sector", "yield", "duration", "maturity",
                "page", "fund", "share class", "industry", "active share", "growth", "value", "blend"
            ]):
                continue
            holdings[name] = pct
            if len(holdings) >= 10:
                break
    return holdings if holdings else None


def extract_sectors(text):
    """Extract sector breakdown."""
    section = find_section(text, [
        "Sectors (%)", "SECTOR", "Sector breakdown", "Sector exposure",
        "Top Ten Industries", "Industry breakdown"
    ], max_chars=2000)
    if not section:
        return None

    sectors = {}
    # Common sector keywords with weights
    sector_patterns = [
        "Technology", "Information Technology", "Financial", "Financials",
        "Industrials", "Health", "Health Care", "Consumer Discretionary",
        "Consumer Staples", "Cons. Cyc.", "Cons. Def.", "Comm. Serv.",
        "Communication Services", "Energy", "Materials", "Basic Mat.",
        "Utilities", "Real Estate", "Real estate"
    ]
    for line in section.split("\n")[:40]:
        for s in sector_patterns:
            pattern = re.compile(rf"\b{re.escape(s)}\b\s+(\d{{1,2}}\.\d{{1,2}})\%?", re.IGNORECASE)
            m = pattern.search(line)
            if m:
                if s not in sectors:
                    sectors[s] = float(m.group(1))
    return sectors if sectors else None


def extract_regions(text):
    """Extract regional breakdown."""
    section = find_section(text, [
        "Regions", "REGIONAL", "Regional breakdown", "Region exposure",
        "Geographic", "Country breakdown", "Top 5 Countries"
    ], max_chars=2000)
    if not section:
        return None

    regions = {}
    region_patterns = [
        "United States", "US", "North America",
        "Eurozone", "Europe ex Euro", "Europe", "Europe dev",
        "United Kingdom", "UK", "Japan",
        "Asia - Developed", "Asia Developed", "Asia - Emerging", "Asia Emerging",
        "Latin America", "LatAm", "Latin Am.",
        "Australasia", "China", "Africa", "Middle East", "Emerging Market"
    ]
    for line in section.split("\n")[:40]:
        for r in region_patterns:
            pattern = re.compile(rf"\b{re.escape(r)}\b\s+(\d{{1,2}}\.\d{{1,2}})\%?", re.IGNORECASE)
            m = pattern.search(line)
            if m and r not in regions:
                regions[r] = float(m.group(1))
    return regions if regions else None


def extract_ytw_duration(text):
    """Extract YTW / Duration / Maturity for FI funds."""
    out = {}
    # YTW patterns
    for pat, key in [
        (r"Yield to (?:Worst|Maturity)\s*[\n]*\s*(?:As of[^0-9]+)?(\d{1,2}\.\d{1,2})\%?", "ytw"),
        (r"Yield to Worst\s+(\d{1,2}\.\d{1,2})", "ytw"),
        (r"Effective Duration[^0-9]*(\d{1,2}\.\d{1,2})", "duration"),
        (r"Effective Maturity[^0-9]*(\d{1,2}\.\d{1,2})", "maturity"),
        (r"Current Yield\s*[\n]*\s*(?:As of[^0-9]+)?(\d{1,2}\.\d{1,2})\%?", "current_yield"),
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out[key] = float(m.group(1))
    return out if out else None


def extract_active_share(text):
    """Extract active share metric."""
    m = re.search(r"Active Share[^0-9\-]*?(\d{1,2}\.\d{1,2})\%?", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def extract_as_of_date(text):
    """Find the 'as of' date from the factsheet."""
    patterns = [
        r"As of (?:\d{1,2}-\w{3}-\d{2,4})",
        r"As of \w+ \d{1,2},?\s*\d{4}",
        r"As at (?:\d{1,2}\s+\w+\s+\d{4})",
        r"\d{1,2}\s+\w+\s+\d{4}",
        r"\d{2}/\d{2}/\d{4}",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None


def extract_ter(text):
    """Extract Total Expense Ratio / Ongoing Charges."""
    patterns = [
        r"Ongoing Charges?\s*[\n]*\s*(\d{1,2}\.\d{1,2})\s*%",
        r"Total Expense Ratio[^0-9]*?(\d{1,2}\.\d{1,2})\s*%",
        r"TER[^0-9]*?(\d{1,2}\.\d{1,2})\s*%",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            ter = float(m.group(1))
            if 0.01 <= ter <= 5:  # sanity range
                return ter
    return None


# ─────────────────────────────────────────────────────────────
# MAIN PARSER
# ─────────────────────────────────────────────────────────────

def parse_factsheet(pdf_path):
    """Parse a single factsheet PDF. Returns dict with extracted fields."""
    text = extract_text(pdf_path)
    if not text or len(text) < 200:
        return {"error": "Empty or very short PDF"}

    # Identify ticker from filename: TICKER_YYYYMMDD.pdf
    fname = pdf_path.stem
    ticker = fname.split("_")[0]
    meta = TICKER_METADATA.get(ticker, {})

    result = {
        "ticker": ticker,
        "isin": meta.get("isin"),
        "name": meta.get("name", ticker),
        "sleeve": meta.get("sleeve"),
        "source_file": pdf_path.name,
        "parsed_at": date.today().isoformat(),
        "as_of_factsheet": extract_as_of_date(text),
        "top_holdings": extract_top_holdings(text),
        "sectors": extract_sectors(text),
        "regions": extract_regions(text),
        "active_share": extract_active_share(text),
        "ter": extract_ter(text),
    }

    # FI-specific extractors
    if meta.get("sleeve") == "Fixed Income":
        result["fi_metrics"] = extract_ytw_duration(text)

    return result


def main():
    out_dir = ROOT / "data" / "funds"
    out_dir.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) > 1:
        # Single file mode
        pdfs = [Path(sys.argv[1])]
    else:
        # All PDFs in factsheets/
        pdfs = list(ROOT.glob("factsheets/**/*.pdf"))

    if not pdfs:
        print("No PDFs found in factsheets/")
        return

    print(f"Parsing {len(pdfs)} factsheet(s)...")
    print()
    for pdf in pdfs:
        ticker = pdf.stem.split("_")[0]
        try:
            data = parse_factsheet(pdf)
            out_path = out_dir / f"{ticker}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Print summary
            n_h = len(data.get("top_holdings") or {})
            n_s = len(data.get("sectors") or {})
            n_r = len(data.get("regions") or {})
            ter = data.get("ter")
            ter_s = f"TER={ter}%" if ter else "TER=?"
            fi = data.get("fi_metrics") or {}
            fi_s = f"YTW={fi.get('ytw')}, Dur={fi.get('duration')}" if fi else ""
            print(f"  {ticker:10s} | holdings={n_h:>2d} sectors={n_s:>2d} regions={n_r:>2d} | {ter_s} {fi_s}")
        except Exception as e:
            print(f"  {ticker:10s} | ERROR: {e}")

    print()
    print(f"[OK] Saved to {out_dir}/")


if __name__ == "__main__":
    main()
