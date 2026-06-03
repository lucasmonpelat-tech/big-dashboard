"""
fetch_agg_breakdowns.py
=======================
Descarga el factsheet PDF oficial de iShares Core U.S. Aggregate Bond ETF (AGG) y extrae:
  - Fecha del factsheet ("Fact Sheet as of MMMM DD, YYYY")
  - CREDIT RATINGS (%): AAA, AA, A, BBB, BB, NR, Cash
  - TOP SECTORS (%): Treasury, MBS Pass-Through, Industrial, Financial, etc.
  - MATURITY BREAKDOWN (%): buckets 0-1, 1-2, 2-3, 3-5, 5-7, 7-10, 10-15, 15-20, 20+

AGG es el benchmark del FI sleeve de BIG. Estos breakdowns alimentan los charts
comparativos "BIG FI vs AGG" del dashboard (credit quality + maturity).

Output:
  data/breakdowns/agg_iShares.json

Estructura:
  {
    "metadata": {
      "factsheet_date": "March 31, 2026",
      "fetched_at": "2026-06-03T11:00:00Z",
      "source_url": "https://www.ishares.com/..."
    },
    "credit_ratings": { "AAA": 71.5, "AA": 3.1, "A": 11.8, "BBB": 13.4, ... },
    "sectors":        { "Treasury": 43.2, "MBS Pass-Through": 27.8, ... },
    "maturity":       { "0-1": 1.2, "1-2": 6.5, "2-3": 7.1, "3-5": 14.3, ... }
  }

Uso:
    python scripts/fetch_agg_breakdowns.py
"""

import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "breakdowns" / "agg_iShares.json"

SOURCE_URL = (
    "https://www.ishares.com/us/literature/fact-sheet/"
    "agg-ishares-core-u-s-aggregate-bond-etf-fund-fact-sheet-en-us.pdf"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

# Buckets canonicos del breakdown de credit ratings AGG
CREDIT_BUCKETS = ["AAA", "AA", "A", "BBB", "BB", "B", "NR", "Cash"]

# Sectores tipicos del breakdown AGG
AGG_SECTORS = [
    "Treasury",
    "MBS Pass-Through",
    "Industrial",
    "Financial Institutions",
    "Financial",
    "Government-Related",
    "Agency",
    "Utility",
    "CMBS",
    "ABS",
    "Cash and/or Derivatives",
]

# Buckets de maturity canonicos
MATURITY_BUCKETS = [
    ("0-1", r"0\s*-\s*1\s*Year[s]?"),
    ("1-2", r"1\s*-\s*2\s*Year[s]?"),
    ("2-3", r"2\s*-\s*3\s*Year[s]?"),
    ("3-5", r"3\s*-\s*5\s*Year[s]?"),
    ("5-7", r"5\s*-\s*7\s*Year[s]?"),
    ("7-10", r"7\s*-\s*10\s*Year[s]?"),
    ("10-15", r"10\s*-\s*15\s*Year[s]?"),
    ("15-20", r"15\s*-\s*20\s*Year[s]?"),
    ("20+", r"20\+?\s*Year[s]?"),
]


def download_pdf(url: str) -> bytes:
    """Baja el PDF con UA de browser (iShares 403ea sin User-Agent)."""
    resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


def extract_full_text(pdf_bytes: bytes) -> str:
    """Texto plano de todas las paginas."""
    chunks: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            chunks.append(txt)
    return "\n".join(chunks)


def parse_factsheet_date(text: str) -> str | None:
    pattern = re.compile(
        r"Fact\s+Sheet\s+as\s+of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    return m.group(1) if m else None


def _slice_section(
    text: str, start_markers: list[str], end_markers: list[str]
) -> str | None:
    upper = text.upper()
    start_idx = -1
    for m in start_markers:
        i = upper.find(m.upper())
        if i != -1:
            start_idx = i
            break
    if start_idx == -1:
        return None
    end_idx = len(text)
    for m in end_markers:
        i = upper.find(m.upper(), start_idx + 1)
        if i != -1 and i < end_idx:
            end_idx = i
    return text[start_idx:end_idx]


def parse_credit_ratings(text: str) -> dict[str, float]:
    """
    Extrae el bloque CREDIT RATINGS (%).
    Formato tipico:
        CREDIT RATINGS (%)
        AAA   71.50
        AA     3.10
        A     11.80
        BBB   13.40
        ...
    """
    out: dict[str, float] = {}
    section = _slice_section(
        text,
        start_markers=["CREDIT RATINGS", "CREDIT QUALITY"],
        end_markers=[
            "TOP SECTORS",
            "MATURITY",
            "CHARACTERISTICS",
            "TOP HOLDINGS",
            "GLOSSARY",
        ],
    )
    if not section:
        return out

    for bucket in CREDIT_BUCKETS:
        # Match al inicio de linea: 'AAA   71.50'
        pattern = re.compile(
            rf"^\s*{re.escape(bucket)}\s+(\d{{1,3}}\.\d{{1,2}})\s*$",
            re.MULTILINE,
        )
        m = pattern.search(section)
        if m:
            out[bucket] = float(m.group(1))
    return out


def parse_sectors(text: str) -> dict[str, float]:
    """Extrae TOP SECTORS (%) del factsheet de AGG."""
    out: dict[str, float] = {}
    section = _slice_section(
        text,
        start_markers=["TOP SECTORS", "SECTOR BREAKDOWN", "SECTOR EXPOSURE"],
        end_markers=[
            "CREDIT RATINGS",
            "CREDIT QUALITY",
            "MATURITY",
            "CHARACTERISTICS",
            "TOP HOLDINGS",
            "GLOSSARY",
        ],
    )
    if not section:
        return out

    for sector in AGG_SECTORS:
        name_re = re.escape(sector).replace(r"\ ", r"\s+")
        pattern = re.compile(
            rf"{name_re}\s+(\d{{1,3}}\.\d{{1,2}})",
            re.IGNORECASE,
        )
        m = pattern.search(section)
        if m:
            out[sector] = float(m.group(1))
    return out


def parse_maturity(text: str) -> dict[str, float]:
    """
    Extrae MATURITY BREAKDOWN (%).
    Formato tipico:
        MATURITY BREAKDOWN (%)
        0-1 Years    1.20
        1-2 Years    6.50
        ...
        20+ Years    18.40
    """
    out: dict[str, float] = {}
    section = _slice_section(
        text,
        start_markers=["MATURITY BREAKDOWN", "MATURITY EXPOSURE", "MATURITY"],
        end_markers=[
            "TOP SECTORS",
            "CREDIT RATINGS",
            "CREDIT QUALITY",
            "CHARACTERISTICS",
            "TOP HOLDINGS",
            "GLOSSARY",
        ],
    )
    if not section:
        return out

    for label, regex in MATURITY_BUCKETS:
        pattern = re.compile(
            rf"{regex}\s+(\d{{1,3}}\.\d{{1,2}})",
            re.IGNORECASE,
        )
        m = pattern.search(section)
        if m:
            out[label] = float(m.group(1))
    return out


def main() -> int:
    print(f"[agg] Descargando factsheet: {SOURCE_URL}")
    try:
        pdf_bytes = download_pdf(SOURCE_URL)
    except requests.RequestException as e:
        print(f"[agg] ERROR descargando PDF: {e}", file=sys.stderr)
        return 1
    print(f"[agg] PDF size: {len(pdf_bytes):,} bytes")

    text = extract_full_text(pdf_bytes)
    if not text.strip():
        print("[agg] ERROR: PDF sin texto extraible", file=sys.stderr)
        return 1

    factsheet_date = parse_factsheet_date(text)
    credit = parse_credit_ratings(text)
    sectors = parse_sectors(text)
    maturity = parse_maturity(text)

    print(f"[agg] Fecha factsheet:  {factsheet_date or '(no encontrada)'}")
    print(f"[agg] Credit buckets:   {len(credit)}")
    print(f"[agg] Sectores:         {len(sectors)}")
    print(f"[agg] Maturity buckets: {len(maturity)}")

    if not credit or not sectors or not maturity:
        print(
            "[agg] WARN: parseo incompleto — revisar estructura del factsheet",
            file=sys.stderr,
        )

    payload = {
        "metadata": {
            "factsheet_date": factsheet_date,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_url": SOURCE_URL,
        },
        "credit_ratings": credit,
        "sectors": sectors,
        "maturity": maturity,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[agg] OK -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
