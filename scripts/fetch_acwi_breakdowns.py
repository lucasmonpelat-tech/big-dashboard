"""
fetch_acwi_breakdowns.py
========================
Descarga el factsheet PDF oficial de iShares MSCI ACWI ETF (ACWI) y extrae:
  - Fecha del factsheet ("Fact Sheet as of MMMM DD, YYYY")
  - TOP SECTORS (%): 11 sectores GICS con sus pesos
  - GEOGRAPHIC BREAKDOWN (%): hasta 11 paises con sus pesos

ACWI es el benchmark del equity sleeve de BIG. Los breakdowns alimentan los
charts comparativos "BIG vs ACWI" del dashboard (sectorial + regional).

Output:
  data/breakdowns/acwi_iShares.json

Estructura:
  {
    "metadata": {
      "factsheet_date": "March 31, 2026",
      "fetched_at": "2026-06-03T11:00:00Z",
      "source_url": "https://www.ishares.com/..."
    },
    "sectors":    { "Information Technology": 24.5, "Financials": 16.2, ... },
    "geographic": { "United States": 62.4, "Japan": 5.3, ... }
  }

Uso:
    python scripts/fetch_acwi_breakdowns.py
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
OUT_PATH = ROOT / "data" / "breakdowns" / "acwi_iShares.json"

SOURCE_URL = (
    "https://www.ishares.com/us/literature/fact-sheet/"
    "acwi-ishares-msci-acwi-etf-fund-fact-sheet-en-us.pdf"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

# Sectores GICS canonicos que aparecen en el factsheet ACWI
GICS_SECTORS = [
    "Information Technology",
    "Financials",
    "Industrials",
    "Consumer Discretionary",
    "Health Care",
    "Communication",
    "Consumer Staples",
    "Energy",
    "Materials",
    "Utilities",
    "Real Estate",
    "Cash and/or Derivatives",
]


def download_pdf(url: str) -> bytes:
    """Baja el PDF del factsheet con UA de browser (iShares 403ea sin esto)."""
    resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


def extract_full_text(pdf_bytes: bytes) -> str:
    """Extrae texto plano de todas las paginas del PDF."""
    chunks: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            chunks.append(txt)
    return "\n".join(chunks)


def parse_factsheet_date(text: str) -> str | None:
    """Captura el 'Fact Sheet as of MMMM DD, YYYY' del header."""
    # Tolera espacios extra, mayusculas variables
    pattern = re.compile(
        r"Fact\s+Sheet\s+as\s+of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    return m.group(1) if m else None


def parse_sectors(text: str) -> dict[str, float]:
    """
    Extrae el bloque TOP SECTORS (%).
    El formato tipico es:
        TOP SECTORS (%)
        Information Technology 24.50
        Financials             16.20
        ...
    Buscamos cada sector canonico seguido de un numero decimal.
    """
    sectors: dict[str, float] = {}
    # Aislar la seccion entre "TOP SECTORS" y la siguiente seccion mayuscula
    section = _slice_section(
        text,
        start_markers=["TOP SECTORS"],
        end_markers=[
            "GEOGRAPHIC BREAKDOWN",
            "TOP HOLDINGS",
            "TOP COUNTRIES",
            "CHARACTERISTICS",
        ],
    )
    if not section:
        return sectors

    for sector in GICS_SECTORS:
        # Match nombre del sector seguido de un % (ej. "Information Technology  24.50")
        # Algunos PDFs ponen "Communication Services" en lugar de "Communication"
        name_re = re.escape(sector).replace(r"\ ", r"\s+")
        if sector == "Communication":
            name_re = r"Communication(?:\s+Services)?"
        pattern = re.compile(
            rf"{name_re}\s+(\d{{1,3}}\.\d{{1,2}})",
            re.IGNORECASE,
        )
        m = pattern.search(section)
        if m:
            key = "Communication" if sector == "Communication" else sector
            sectors[key] = float(m.group(1))
    return sectors


def parse_geographic(text: str) -> dict[str, float]:
    """
    Extrae el bloque GEOGRAPHIC BREAKDOWN (%).
    Formato tipico:
        GEOGRAPHIC BREAKDOWN (%)
        United States  62.40
        Japan           5.30
        ...
    Tomamos hasta 11 lineas tipo 'Nombre Pais  XX.XX'.
    """
    geo: dict[str, float] = {}
    section = _slice_section(
        text,
        start_markers=["GEOGRAPHIC BREAKDOWN", "GEOGRAPHIC EXPOSURE"],
        end_markers=[
            "TOP SECTORS",
            "TOP HOLDINGS",
            "CHARACTERISTICS",
            "GLOSSARY",
            "WANT TO KNOW MORE",
        ],
    )
    if not section:
        return geo

    # Linea tipo: <country name (letras + espacios + posibles puntos)>  <numero>
    line_re = re.compile(
        r"^\s*([A-Z][A-Za-z\.\-\(\)\s]+?)\s+(\d{1,3}\.\d{1,2})\s*$",
        re.MULTILINE,
    )
    for m in line_re.finditer(section):
        name = m.group(1).strip()
        # Filtrar headers residuales
        if name.upper() in {"GEOGRAPHIC BREAKDOWN", "GEOGRAPHIC EXPOSURE", "COUNTRY"}:
            continue
        if "BREAKDOWN" in name.upper() or "%" in name:
            continue
        geo[name] = float(m.group(2))
        if len(geo) >= 11:
            break
    return geo


def _slice_section(
    text: str, start_markers: list[str], end_markers: list[str]
) -> str | None:
    """Devuelve el sub-string entre el primer start_marker y el primer end_marker."""
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


def main() -> int:
    print(f"[acwi] Descargando factsheet: {SOURCE_URL}")
    try:
        pdf_bytes = download_pdf(SOURCE_URL)
    except requests.RequestException as e:
        print(f"[acwi] ERROR descargando PDF: {e}", file=sys.stderr)
        return 1
    print(f"[acwi] PDF size: {len(pdf_bytes):,} bytes")

    text = extract_full_text(pdf_bytes)
    if not text.strip():
        print("[acwi] ERROR: PDF sin texto extraible", file=sys.stderr)
        return 1

    factsheet_date = parse_factsheet_date(text)
    sectors = parse_sectors(text)
    geographic = parse_geographic(text)

    print(f"[acwi] Fecha factsheet: {factsheet_date or '(no encontrada)'}")
    print(f"[acwi] Sectores parseados: {len(sectors)}")
    print(f"[acwi] Paises parseados:   {len(geographic)}")

    if not sectors or not geographic:
        print(
            "[acwi] WARN: parseo incompleto — revisar estructura del factsheet",
            file=sys.stderr,
        )

    payload = {
        "metadata": {
            "factsheet_date": factsheet_date,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_url": SOURCE_URL,
        },
        "sectors": sectors,
        "geographic": geographic,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[acwi] OK -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
