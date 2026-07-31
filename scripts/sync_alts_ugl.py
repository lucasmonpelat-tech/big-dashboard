"""
sync_alts_ugl.py — POST alts_race.py daily refresh hook.

CONTEXT (actualizado 2026-07-31): alts_race.py ya carga sleeve_index real desde
data/alts_sleeve_real.json (statements Pershing + Carlyle, Modified Dietz) --
ya no hace falta ningun parche de sleeve_index aca. Este script se encarga de
lo que SI sigue siendo su trabajo: sincronizar el SI/YTD por HOLDING (cost-basis
via Pershing UGL) y recomputar los stats agregados desde el sleeve_index real.

Flow del cron diario:
  1. compute_holdings_returns.py (manual cuando hay UGL nuevo)
  2. refresh_holdings_returns_daily.py (cron: refreshea MV con T-1)
  3. alts_race.py (cron: carga sleeve_index real desde alts_sleeve_real.json)
  4. sync_alts_ugl.py (cron: sync per-holding cost-basis + stats) ← este
  5. refresh_alts_sleeve_daily.py (cron: extiende alts_sleeve_real.json con el
     punto de hoy, usando el total_alts_usd ya fresco de los pasos anteriores)
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
        # IBIT/GLD: value_usd/ytd_return_pct ya vienen frescos de Pershing
        # (canonical positions.json) via refresh_alts_daily.py -- NO
        # pisar con holdings_returns_alternatives.json, que tiene mv/qty
        # desactualizados para estos dos (falta re-sync de transacciones,
        # ver nota 2026-07-28). El SI de ese archivo tampoco es confiable
        # por el mismo motivo, se deja como estaba.
        if tk in ("IBIT", "GLD"):
            continue
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

    # 3a) Recompute sub_class_breakdown_pct (los pesos cambian con MVs nuevos)
    pm_pre = ar.setdefault('portfolio_metrics', {})
    sub_pct = {}
    if total > 0:
        for h in ar['holdings']:
            sc = h.get('sub_class') or 'other'
            v = h.get('value_usd') or 0
            sub_pct[sc] = sub_pct.get(sc, 0) + v / total * 100
        pm_pre['sub_class_breakdown_pct'] = {k: round(v, 2) for k, v in sub_pct.items()}

    # 3) Recompute sleeve YTD/SI/etc from weighted contributions (cost-basis)
    sleeve_ytd_cb = sum(h.get('ytd_contribution_pct', 0) or 0 for h in ar['holdings'])
    sleeve_si_cb = sum(h.get('contribution_pct', 0) or 0 for h in ar['holdings'])

    # 4) sleeve_index ya NO necesita parche (fix 2026-07-31): alts_race.py lo
    #    carga real desde data/alts_sleeve_real.json (statements Pershing +
    #    Carlyle, Modified Dietz), no proxies. Se deja tal cual lo dejo alts_race.py.

    # 5) Recompute todos los stats desde el sleeve_index real
    stats = ar.setdefault('stats_vs_6040', {})
    returns = stats.setdefault('returns', {})
    si_final = ar.get('sleeve_index', {})
    keys_sorted = sorted(si_final.keys()) if si_final else []
    if len(keys_sorted) >= 2:
        last_v = si_final[keys_sorted[-1]]
        def _p(a, b): return round((a/b - 1) * 100, 2) if b else 0
        m1 = _p(last_v, si_final[keys_sorted[-2]])
        m3 = _p(last_v, si_final[keys_sorted[-4]]) if len(keys_sorted) >= 4 else 0
        m6 = _p(last_v, si_final[keys_sorted[-7]]) if len(keys_sorted) >= 7 else 0
        ytd = _p(last_v, si_final.get('2025-12', si_final[keys_sorted[0]]))
        si_ret = _p(last_v, 100.0)
        yrs = (len(keys_sorted) - 1) / 12
        ann = round(((last_v/100.0) ** (1/yrs) - 1) * 100, 2) if yrs > 0 else 0
        for kk, vv in [('1M', m1), ('3M', m3), ('6M', m6), ('YTD', ytd), ('SI', si_ret)]:
            bucket = returns.setdefault(kk, {})
            bucket['sleeve'] = vv
            bmk = bucket.get('bmk6040') or 0
            bucket['alpha'] = round(vv - bmk, 2)
        bmk_ann = stats.get('annualized', {}).get('bmk6040', 0)
        stats['annualized'] = {'sleeve': ann, 'bmk6040': bmk_ann, 'alpha': round(ann - bmk_ann, 2)}
        print(f"  [sync_alts_ugl] sleeve_index rebuilt: SI +{si_ret}% / YTD {ytd:+.2f}% / 1M {m1:+.2f}%")

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
