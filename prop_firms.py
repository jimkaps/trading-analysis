"""Preset E through the published rules of Lucid Trading and MyFundedFutures (rules read 23 Nov 2026).

Cycle per plan: buy an evaluation -> trade it until pass or bust (bust = reset) -> trade the funded
account, taking payouts whenever the plan's rules allow -> on a funded bust, or after the plan's last
simulated payout (where the firm moves you to live / reviews you), buy a new evaluation.

Trade model: preset E (07:30-08:30 London range, 1 x ATR14 stop, no TP, flat 15:55 New York), 1 pt
round-trip slippage + $1.24 commission per MNQ. Every drawdown is checked against the worst open loss
during the day. Intraday-trailing plans trail the best open profit minute by minute.
Tier 1 news rule (MFFU Rapid and Pro funded): flat 2 minutes before CPI and jobs reports (08:30 New York)
and FOMC statements (14:00 New York); E's stop orders resume 2 minutes after; one trade a day.

Assumptions where the firms' pages are silent (see FINDINGS_orb_prop.md): resets cost the same as a new
evaluation; MFFU Rapid has no per-payout cap; Builder "qualifying day" = a winning day; daily loss
limits are switched off where optional (Lucid) and liquidate for the day where mandatory (MFFU Builder).

Usage: python prop_firms.py [nq_1m_2012_2026.parquet]
"""
import sys

import numpy as np
import pandas as pd
from numba import njit

import orb_sweep as s
from news_dates import CPI, FOMC, NFP

PTV, COST, COMM = 2.0, 1.0, 1.24
MAXLEN = 800

# ---------------------------------------------------------------- plans
# eval: fee, target, dd, eval consistency (best day <= x * profit; 0 = none), eval min days, dll (0 = none)
# funded: trail (0 EOD, 1 intraday), lock (0 when trail reaches start+100, 1 after first payout),
#   split, min payout, cap first, cap later, buffer (balance above start that must stay), pct cap of profit (0 none),
#   cycle min profit, cycle qualifying days, qualifying-day threshold $, cycle consistency (0 none),
#   min calendar days between payouts, max payouts (0 = unlimited), news rule (0/1)
FIELDS = ["fee", "target", "dd", "econs", "edays", "dll", "trail", "lock", "split", "minpay", "cap1", "cap2",
          "buffer", "pctcap", "cycmin", "qdays", "qthr", "ccons", "gap", "maxpay", "news"]
PLANS = {
    # Lucid Flex: 40% eval consistency, no funded consistency, 5 days >= $150 ($250 on 150K) per cycle,
    # payout max 50% of profit capped $2,000 ($3,000), min $500, no buffer, 90/10, 5 payouts then live.
    "Lucid Flex 50K": dict(fee=88.2, target=3000, dd=2000, econs=0.4, edays=3, dll=0, trail=0, lock=0, split=0.9,
                           minpay=500, cap1=2000, cap2=2000, buffer=0, pctcap=0.5, cycmin=1, qdays=5, qthr=150,
                           ccons=0, gap=0, maxpay=5, news=0),
    "Lucid Flex 150K": dict(fee=226.1, target=9000, dd=4500, econs=0.4, edays=3, dll=0, trail=0, lock=0, split=0.9,
                            minpay=500, cap1=3000, cap2=3000, buffer=0, pctcap=0.5, cycmin=1, qdays=5, qthr=250,
                            ccons=0, gap=0, maxpay=5, news=0),
    # Lucid Pro: no eval consistency, 1-day pass; funded cycle profit >= $500 ($1,000), best day <= 40% of cycle,
    # buffer $2,100 ($4,600), payout max $2,000 then $2,500 ($3,000 then $3,500), min $500, 90/10.
    # Number of payouts before live not published: assume 5 like Flex.
    "Lucid Pro 50K": dict(fee=126, target=3000, dd=2000, econs=0, edays=1, dll=0, trail=0, lock=0, split=0.9,
                          minpay=500, cap1=2000, cap2=2500, buffer=2100, pctcap=0, cycmin=500, qdays=0, qthr=0,
                          ccons=0.4, gap=0, maxpay=5, news=0),
    "Lucid Pro 150K": dict(fee=255.5, target=9000, dd=4500, econs=0, edays=1, dll=0, trail=0, lock=0, split=0.9,
                           minpay=500, cap1=3000, cap2=3500, buffer=4600, pctcap=0, cycmin=1000, qdays=0, qthr=0,
                           ccons=0.4, gap=0, maxpay=5, news=0),
    # MFFU Builder: no eval consistency, 1 day; $1,000 daily loss limit (soft: flat for the day); funded cycle
    # >= $500 profit, 2 winning days, best day <= 50%, every 48 h, buffer $2,100, max $2,000, 80/20, 5 payouts.
    "MFFU Builder 50K": dict(fee=92, target=3000, dd=2000, econs=0, edays=1, dll=1000, trail=0, lock=0, split=0.8,
                             minpay=500, cap1=2000, cap2=2000, buffer=2100, pctcap=0, cycmin=500, qdays=2, qthr=0.01,
                             ccons=0.5, gap=2, maxpay=5, news=0),
    # MFFU Pro: 50% eval consistency, 2 days; funded EOD trail locks at +$100 after first payout; payout every
    # 14 days, buffer $2,100, min $1,000, no cap, 80/20, 3 payouts then live review. Tier 1 news rule.
    "MFFU Pro 50K": dict(fee=159, target=3000, dd=2000, econs=0.5, edays=2, dll=0, trail=0, lock=1, split=0.8,
                         minpay=1000, cap1=1e9, cap2=1e9, buffer=2100, pctcap=0, cycmin=1, qdays=0, qthr=0,
                         ccons=0, gap=14, maxpay=3, news=1),
    # MFFU Rapid: 50% eval consistency, 2 days, EOD in eval; funded INTRADAY trailing $2,000 (locks at +$100),
    # daily payouts, buffer $2,100, min $500, cap not published (none assumed), 90/10. Tier 1 news rule.
    "MFFU Rapid 50K": dict(fee=125, target=3000, dd=2000, econs=0.5, edays=2, dll=0, trail=1, lock=0, split=0.9,
                           minpay=500, cap1=1e9, cap2=1e9, buffer=2100, pctcap=0, cycmin=500, qdays=0, qthr=0,
                           ccons=0, gap=0, maxpay=0, news=1),
}
SIZES = {"50K": [(1, 1), (2, 1), (2, 2), (3, 3)], "150K": [(3, 2), (5, 2), (3, 3), (5, 5)]}
# 2014-19 stops were ~4.5x smaller in $ per MNQ; scale contracts so dollar risk matches today's
SIZES_2014 = {"50K": [(5, 5), (9, 5), (9, 9), (14, 14)], "150K": [(14, 9), (23, 9), (14, 14), (23, 23)]}


# ---------------------------------------------------------------- trade paths
@njit
def paths(O, H, L, C, rs, re_, exm, cut, resume, stop):
    """Per day: gross pts at exit, and per-minute adverse / favourable open pts from entry to exit."""
    nd = O.shape[0]
    fin = np.full(nd, np.nan)
    adv = np.zeros((nd, MAXLEN), dtype=np.float32); fav = np.zeros((nd, MAXLEN), dtype=np.float32)
    nlen = np.zeros(nd, dtype=np.int64)
    for d in range(nd):
        rh = -1e18; rl = 1e18; nbar = 0; nflat = 0
        for m in range(rs, re_):
            h = H[d, m]
            if h == h:
                nbar += 1
                if h > rh: rh = h
                if L[d, m] < rl: rl = L[d, m]
                if h == L[d, m]: nflat += 1
        sp = stop[d]
        if nbar < (re_ - rs) * 0.8 or nflat > nbar * 0.5 or rh <= rl or sp != sp:
            continue
        ex = exm[d]; c = cut[d]
        side = 0; ent = -1; px = 0.0; tend = ex
        for seg in range(2):
            a0 = re_ if seg == 0 else resume[d]
            a1 = (c if c >= 0 else ex) if seg == 0 else ex
            if seg == 1 and c < 0:
                break
            for m in range(a0, a1):
                h = H[d, m]
                if h != h:
                    continue
                o = O[d, m]; ua = h >= rh; db = L[d, m] <= rl
                if ua or db:
                    if o >= rh: side = 1; px = o
                    elif o <= rl: side = -1; px = o
                    elif ua and db:
                        if rh - o <= o - rl: side = 1; px = rh
                        else: side = -1; px = rl
                    elif ua: side = 1; px = rh
                    else: side = -1; px = rl
                    ent = m; tend = a1
                    break
            if ent >= 0:
                break
        if ent < 0:
            continue
        res = np.nan; lastc = px; k = 0
        for m in range(ent, tend):
            h = H[d, m]
            if h != h:
                continue
            lo = L[d, m]; lastc = C[d, m]
            f = (h - px) if side == 1 else (px - lo)
            a = (lo - px) if side == 1 else (px - h)
            if a <= -sp:
                adv[d, k] = -sp; fav[d, k] = f      # stop minute: assume the high came first (harsher for trailing)
                k += 1; res = -sp
                break
            adv[d, k] = a; fav[d, k] = f; k += 1
            if k >= MAXLEN:
                break
        if res != res:
            res = (lastc - px) * side
        fin[d] = res; nlen[d] = k
    return fin, adv, fav, nlen


# ---------------------------------------------------------------- simulator
@njit
def simulate(fin, adv, fav, nlen, cal, start, ne, nf, P):
    (fee, target, dd, econs, edays, dll, trail, lock, split, minpay, cap1, cap2, buffer, pctcap,
     cycmin, qdays, qthr, ccons, gap, maxpay, news) = P
    cpc = COST * PTV + COMM                 # round-trip cost per contract in $
    nd = fin.shape[0]
    cum = -fee; bought = 1; passed = 0; npaid_total = 0; paid = 0.0; fbust = 0; retired = 0
    curve = np.zeros(nd)
    phase = 0; bal = 0.0; peak = 0.0; floor = -dd; locked = False; best = 0.0; days = 0
    npay = 0; cyc_base = 0.0; cyc_best = 0.0; qual = 0; last_pay = -10 ** 6
    for d in range(start, nd):
        g = fin[d]
        if g == g:
            n = ne if phase == 0 else nf
            k = nlen[d]
            bust = False; day = 0.0
            intraday = phase == 1 and trail == 1
            done = False
            for t in range(k):
                a = (adv[d, t] * PTV - cpc) * n           # open P&L if closed now (worst point of the minute)
                if dll > 0 and a <= -dll:
                    day = -dll; done = True
                    if bal + day <= floor: bust = True
                    break
                if bal + a <= floor:
                    bust = True; break
                if intraday:
                    fpk = bal + fav[d, t] * PTV * n
                    if fpk > peak:
                        peak = fpk
                        if not locked:
                            floor = min(peak - dd, 100.0) if lock == 0 else peak - dd
                            if lock == 0 and floor >= 100.0: locked = True
            if not bust and not done:
                day = (g * PTV - cpc) * n
                if dll > 0 and day <= -dll: day = -dll
            if bust:
                if phase == 0:
                    cum -= fee; bought += 1
                else:
                    fbust += 1; cum -= fee; bought += 1
                phase = 0; bal = 0.0; peak = 0.0; floor = -dd; locked = False; best = 0.0; days = 0
                npay = 0; cyc_base = 0.0; cyc_best = 0.0; qual = 0
                curve[d] = cum
                continue
            bal += day; days += 1
            # end-of-day trailing (eval always EOD; funded EOD plans)
            if bal > peak:
                peak = bal
                if not locked:
                    if lock == 0 or phase == 0:
                        floor = min(peak - dd, 100.0)
                        if floor >= 100.0: locked = True
                    else:
                        floor = peak - dd
            if phase == 0:
                if day > best: best = day
                if bal >= target and days >= edays and (econs == 0 or best <= econs * bal):
                    passed += 1
                    phase = 1; bal = 0.0; peak = 0.0; floor = -dd; locked = False
                    npay = 0; cyc_base = 0.0; cyc_best = 0.0; qual = 0; last_pay = cal[d]
            else:
                cp = bal - cyc_base
                if day > cyc_best: cyc_best = day
                if qdays > 0 and day >= qthr: qual += 1
                ok = cp >= cycmin and cp > 0 and qual >= qdays and cal[d] - last_pay >= gap
                if ok and ccons > 0 and cyc_best > ccons * cp: ok = False
                if ok:
                    amt = bal - buffer
                    amt = min(amt, cap1 if npay == 0 else cap2)
                    if pctcap > 0: amt = min(amt, pctcap * bal)
                    if amt >= minpay:
                        bal -= amt; npay += 1; npaid_total += 1; paid += amt * split; cum += amt * split
                        cyc_base = bal; cyc_best = 0.0; qual = 0; last_pay = cal[d]
                        if lock == 1 and not locked:
                            floor = 100.0; locked = True
                        if maxpay > 0 and npay >= maxpay:
                            retired += 1
                            cum -= fee; bought += 1
                            phase = 0; bal = 0.0; peak = 0.0; floor = -dd; locked = False; best = 0.0; days = 0
                            npay = 0; cyc_base = 0.0; cyc_best = 0.0; qual = 0
        curve[d] = cum
    return curve, bought, passed, npaid_total, paid, fbust, retired


def news_cut(days):
    """London minute to be flat by (2 min before release) and to resume (2 min after); -1 = no news."""
    cut = np.full(len(days), -1, dtype=np.int64); res = np.zeros(len(days), dtype=np.int64)
    early = set(CPI) | set(NFP); fomc = set(FOMC)
    for i, d in enumerate(days):
        ds = d.strftime("%Y-%m-%d")
        for hh, mm, ok in ((8, 30, ds in early), (14, 0, ds in fomc)):
            if ok:
                t = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=hh, minutes=mm)
                lm = t.tz_convert("Europe/London"); lm = lm.hour * 60 + lm.minute
                cut[i] = lm - 2; res[i] = lm + 2
                break
    return cut, res


def build(path):
    df = pd.read_parquet(path)
    days, O, H, L, C = s.day_matrix(df, "Europe/London")
    wk = days.day_of_week < 5
    days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
    rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
    atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
    ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                           for d in days]).tz_convert("Europe/London")
    exm = (ny.hour * 60 + ny.minute).to_numpy().astype(np.int64)
    nocut = np.full(len(days), -1, dtype=np.int64)
    cut, res = news_cut(days)
    base = paths(O, H, L, C, 450, 510, exm, nocut, nocut, atr)
    newsp = paths(O, H, L, C, 450, 510, exm, cut, res, atr)
    cal = ((days - days[0]).days).to_numpy().astype(np.int64)
    return days, cal, base, newsp, (cut >= 0)


def run_period(days, cal, base, newsp, a, b, label, sizes=SIZES):
    sel = (days.year >= a) & (days.year <= b)
    i0 = int(np.argmax(sel)); i1 = int(len(sel) - np.argmax(sel[::-1]))
    sl = slice(i0, i1)
    yrs = (i1 - i0) / 252
    rows = []
    for name, p in PLANS.items():
        P = np.array([float(p[f]) for f in FIELDS])
        fin, adv, fav, nlen = newsp if p["news"] else base
        args = (fin[sl], adv[sl], fav[sl], nlen[sl], cal[sl])
        size = "150K" if "150K" in name else "50K"
        for ne, nf in sizes[size]:
            curve, bought, passed, npay, paid, fbust, retired = simulate(*args, 15, ne, nf, P)
            # start-date sensitivity: a new start every 2 months
            finals = []
            for st in range(15, len(curve) - 252, 42):
                c = simulate(*args, st, ne, nf, P)[0]
                finals.append(c[-1] / ((len(c) - st) / 252))
            finals = np.array(finals)
            eq = curve[15:]
            rows.append({"plan": name, "eval/funded MNQ": f"{ne}/{nf}", "evals": bought, "passed": passed,
                         "payouts": npay, "paid out": round(paid), "fees": round(bought * p["fee"]),
                         "NET": round(curve[-1]), "net/yr": round(curve[-1] / yrs),
                         "worst drop": round((np.maximum.accumulate(eq) - eq).max()),
                         "net/yr by start: median": round(np.median(finals)), "worst": round(finals.min()),
                         "% starts > 0": f"{(finals > 0).mean():.0%}"})
    print(f"\n===== {label} =====")
    print(pd.DataFrame(rows).set_index(["plan", "eval/funded MNQ"]).to_string())


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "nq_1m_2012_2026.parquet"
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30)
    days, cal, base, newsp, isnews = build(path)
    b, n = base[0], newsp[0]
    m = (days.year >= 2020) & np.isfinite(b) & np.isfinite(n)
    print(f"News rule, 2020-26: {isnews[days.year >= 2020].sum()} news days; on them E made "
          f"${((b[m & isnews] - 1) * PTV - COMM).sum():,.0f} per MNQ normally vs ${((n[m & isnews] - 1) * PTV - COMM).sum():,.0f} "
          f"flat-for-news (all days: ${((b[m] - 1) * PTV - COMM).sum():,.0f} vs ${((n[m] - 1) * PTV - COMM).sum():,.0f})")
    run_period(days, cal, base, newsp, 2020, 2026, "Jan 2020 - Nov 2026 (where E has its edge)")
    run_period(days, cal, base, newsp, 2014, 2019, "2014-2019 at ~4.5x contracts (same $ risk as today; E had no "
               "edge; no news dates loaded, so news rule not applied)", SIZES_2014)


if __name__ == "__main__":
    main()
