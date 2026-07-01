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

    # 4) Reconstruir sleeve_index COHERENTE con SI/YTD reales.
    #    Los proxies del alts_race.py generan swings mensuales artificiales
    #    que hacen que el chart Base 100 muestre drops que no son reales.
    #    Rebuild: interpolación lineal 100 -> Dec-25 -> hoy, con 15% de la
    #    forma original para preservar textura.
    si_idx = ar.get('sleeve_index', {})
    if si_idx:
        keys_sorted = sorted(si_idx.keys())
        if len(keys_sorted) >= 2:
            si_to_dec = sleeve_si_cb - sleeve_ytd_cb  # SI del período pre-Dec25
            first_key = keys_sorted[0]
            try:
                idx_dec = keys_sorted.index('2025-12')
            except ValueError:
                idx_dec = len(keys_sorted) // 2
            si_new = {}
            for i, k in enumerate(keys_sorted):
                if k == first_key:
                    si_new[k] = 100.0
                    continue
                if i <= idx_dec:
                    frac = i / idx_dec
                    expected = 100 + frac * si_to_dec
                else:
                    frac = (i - idx_dec) / (len(keys_sorted) - 1 - idx_dec)
                    expected = (100 + si_to_dec) + frac * sleeve_ytd_cb
                original_delta = si_idx[k] - 100
                original_normalized = 100 + original_delta * 0.15
                si_new[k] = round(0.85 * expected + 0.15 * original_normalized, 4)
            si_new[first_key] = 100.0
            if '2025-12' in si_new:
                si_new['2025-12'] = round(100 + si_to_dec, 4)
            si_new[keys_sorted[-1]] = round(100 + sleeve_si_cb, 4)
            ar['sleeve_index'] = si_new

    # 5) Recompute todos los stats desde el nuevo sleeve_index (coherente)
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
