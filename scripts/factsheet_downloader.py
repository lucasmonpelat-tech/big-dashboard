"""
factsheet_downloader.py
=======================
Downloads the latest factsheets from all fund manager websites
and stores them in factsheets/<isin>_<YYYYMMDD>.pdf.

Useful for manual review: you (or future parser) can open the PDF
and verify currency/country/yield numbers against what's in
data/funds_metadata.js.

Usage:
    python factsheet_downloader.py
"""

import requests
import os
import json
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "factsheets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ==============================================================
# Direct PDF links (from FACTSHEET_LINKS in funds_metadata.js)
# Only include those that return a PDF directly (not HTML pages)
# ==============================================================
FACTSHEET_PDFS = {
    "IE00B5BMR087_CSPX": "https://www.blackrock.com/americas-offshore/en/literature/fact-sheet/cspx-ishares-core-s-p-500-ucits-etf-fund-fact-sheet-en-lm.pdf",
    "US4642873909_ILF":  "https://www.ishares.com/us/literature/fact-sheet/ilf-ishares-latin-america-40-etf-fund-fact-sheet-en-us.pdf",
    "LU1985812756_MFS":  "https://www.mfs.com/content/dam/mfs-enterprise/mfscom/products/factsheet/meridian/gg/mer_cvf_fs_gg_en.pdf",
}

# HTML pages where factsheet must be located manually
FACTSHEET_PAGES = {
    "US37950E2596_ARGT":  "https://www.globalxetfs.com/funds/argt",
    "DE000A0Q4R85_4BRZ":  "https://www.blackrock.com/es/profesionales/productos/304304/",
    "IE00BF4KN675_LGLI":  "https://www.lazardassetmanagement.com/",
    "IE00BFMHRK20_NBGMT": "https://www.nb.com/en/latam/products/ucits-funds/global-equity-megatrends-fund",
    "LU2940405447_JHGSC": "https://www.janushenderson.com/en-lu/advisor/product/jhhf-global-smaller-companies-fund/",
    "IE00B87KCF77_PIMCO_INC": "https://www.pimco.com/sg/en/investments/gis/income-fund/",
    "IE00BDT57R20_PIMCO_LD":  "https://www.pimco.com/sg/en/investments/gis/low-duration-income-fund/",
    "IE000OE87WX6_MANIG":     "https://www.man.com/",
    "IE00B29K0P99_PIMCO_EM":  "https://www.pimco.com/gb/en/investments/gis/emerging-local-bond-fund/",
    "IE00BG13YG49_SGCB":      "https://www.schroders.com/en-ch/ch/professional/funds/schroder-gaia-cat-bond/",
    "US78462F1030_THOR":      "https://www.thornburg.com/funds/equity-income-builder-fund/",
}


def download_pdf(key: str, url: str) -> bool:
    stamp = datetime.now().strftime("%Y%m%d")
    fname = OUTPUT_DIR / f"{key}_{stamp}.pdf"
    print(f"  [PDF] {key} ← {url}")
    try:
        r = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if r.status_code != 200:
            print(f"    ✗ HTTP {r.status_code}")
            return False
        if r.headers.get("Content-Type", "").startswith("text/html"):
            print(f"    ✗ Returned HTML (not PDF)")
            return False
        with open(fname, "wb") as f:
            f.write(r.content)
        print(f"    ✓ {fname.name} ({len(r.content)//1024} KB)")
        return True
    except Exception as e:
        print(f"    ✗ {e}")
        return False


def main():
    print(f"[{datetime.now().isoformat()}] Downloading factsheets...")
    print("\n=== Direct PDFs ===")
    success = 0
    for key, url in FACTSHEET_PDFS.items():
        if download_pdf(key, url):
            success += 1

    print("\n=== Factsheet Pages (manual) ===")
    print("These need manual download. Open URL, find latest factsheet PDF link:")
    manifest = {
        "generatedAt": datetime.now().isoformat(),
        "pages": FACTSHEET_PAGES,
    }
    with open(OUTPUT_DIR / "pages_to_review.json", "w") as f:
        json.dump(manifest, f, indent=2)
    for key, url in FACTSHEET_PAGES.items():
        print(f"  → {key}: {url}")

    print(f"\n✓ Downloaded {success} / {len(FACTSHEET_PDFS)} PDFs to {OUTPUT_DIR}")
    print(f"  Plus {len(FACTSHEET_PAGES)} pages listed in pages_to_review.json for manual review.")


if __name__ == "__main__":
    main()
