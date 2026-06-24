"""
sync_alts_ugl.py — POST alts_race.py daily refresh hook.

CONTEXT: alts_race.py construye la serie mensual con PROXIES (PSP, carry%
hardcoded por sub-class). Eso funciona para charts históricos pero NO refleja
los returns reales de los privates que sí trackeamos en Pershing UGL.

Este script SOBREESCRIBE el último punto del sleeve_index + stats con los
datos REALES de holdings_returns_alternatives.json (que vienen de Pershing
UGL via refresh_holdings_returns_daily.py).

Flow del cron diario:
  1. compute_holdings_returns.py (manual cuando hay UGL nuevo)
  2. refresh_holdings_returns_daily.py (cron: refreshea MV con T-1)
  3. alts_race.py (cron: construye serie histórica con proxies)
  4. sync_alts_ugl.py (cron: pisa último punto + stats con datos reales) ← este
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
ALTS_RACE = ROOT / "data" / "alts_race.json"
HOLDINGS_ALTS = ROOT / "data" / "holdings_returns_alternatives.json"
CARLYLE_STMT = ROOT / "data" / "alts_carlyle_statement.json"


def main():
    if not ALTS_RACE.exists() or not HOLDINGS_ALTS.exists():
        print(f"  [sync_alts_ugl] SKIP: archivos faltantes")
        return

    ar = json.load(open(ALTS_RACE, encoding='utf-8'))
    ha = json.load(open(HOLDINGS_ALTS, encoding='utf-8'))
    ha_by_tk = {h['ticker']: h for h in ha.get('holdings', [])}

    # CALP comes from Carlyle statement (external, no Pershing). Build pseudo-entry.
    if CARLYLE_STMT.exists():
        carlyle = json.load(open(CARLYLE_STMT, encoding='utf-8'))
        stmts = carlyle.get('statements', {}).get('CALP', [])
        if stmts:
            # Latest by as_of
            last = max(stmts, key=lambda s: s.get('as_of', ''))
            ha_by_tk['CALP'] = {
                'ticker': 'CALP',
                'return_pct': last.get('si_return_pct'),
                'ytd_pct': last.get('ytd_return_pct_pct') or last.get('ytd_return_pct'),
                'mv_usd': last.get('mv_usd'),
                'period_end': last.get('as_of'),
            }

    # 1) Sync per-holding SI/YTD/contribs from UGL data
    updates = 0
    for h in ar.get('holdings', []):
        tk = h['ticker']
        if tk not in ha_by_tk:
            continue
        pers = ha_by_tk[tk]
        si = pers.get('return_pct')
        ytd = pers.get('ytd_pct')
        if si is None:
            continue
        h['si_return_pct'] = round(si, 2)
        h['value_usd'] = round(pers.get('mv_usd') or h.get('value_usd', 0), 2)
        if ytd is not None:
            h['ytd_return_pct'] = round(ytd, 2)
        h['source'] = 'Pershing UGL via sync_alts_ugl.py'
        h['valuation_date'] = ha.get('period_end', datetime.now().date().isoformat())
        h['days_since_valuation'] = 0
        updates += 1

    # 2) Recompute weights (positions might have changed)
    total = sum((h.get('value_usd') or 0) for h in ar['holdings'])
    if total > 0:
        for h in ar['holdings']:
            w = (h.get('value_usd') or 0) / total * 100
            h['weight_pct'] = round(w, 2)
            si = h.get('si_return_pct')
            ytd = h.get('ytd_return_pct')
            if si is not None:
                h['contribution_pct'] = round(w * si / 100, 2)
            if ytd is not None:
                h['ytd_contribution_pct'] = round(w * ytd / 100, 2)

    # 3) Recompute sleeve YTD/SI/etc from weighted contributions (cost-basis)
    sleeve_ytd_cb = sum(h.get('ytd_contribution_pct', 0) or 0 for h in ar['holdings'])
    sleeve_si_cb = sum(h.get('contribution_pct', 0) or 0 for h in ar['holdings'])

    # 4) Override stats_vs_6040 YTD/SI (mantener bench y alpha existentes)
    stats = ar.setdefault('stats_vs_6040', {})
    returns = stats.setdefault('returns', {})
    for k, v in [('YTD', sleeve_ytd_cb), ('SI', sleeve_si_cb)]:
        bucket = returns.setdefault(k, {})
        old_sleeve = bucket.get('sleeve')
        bucket['sleeve'] = round(v, 2)
        bmk = bucket.get('bmk6040') or 0
        bucket['alpha'] = round(v - bmk, 2)
        if old_sleeve is not None and abs((old_sleeve or 0) - v) > 0.5:
            print(f"  [sync_alts_ugl] Sleeve {k}: {old_sleeve:+.2f}% -> {v:+.2f}% (cost-basis weighted)")

    # 5) Same for portfolio_metrics
    pm = ar.setdefault('portfolio_metrics', {})
    pm['total_alts_usd'] = round(total)
    pm['ytd_return_pct'] = round(sleeve_ytd_cb, 2)
    pm['si_return_pct'] = round(sleeve_si_cb, 2)
    pm['n_holdings'] = len(ar['holdings'])

    # 6) Note
    ar['_sync_alts_ugl_at'] = datetime.now().isoformat()
    ar['_sync_alts_ugl_note'] = (
        'Returns y sleeve YTD/SI sobreescritos con Pershing UGL (cost-basis weighted). '
        'sleeve_index mensual sigue siendo time-weighted con proxies (para charts históricos).'
    )

    with open(ALTS_RACE, 'w', encoding='utf-8') as f:
        json.dump(ar, f, indent=2, ensure_ascii=False)
    print(f"  [sync_alts_ugl] {updates} holdings sync'd. Sleeve YTD: {sleeve_ytd_cb:+.2f}% / SI: {sleeve_si_cb:+.2f}%")


if __name__ == '__main__':
    main()
