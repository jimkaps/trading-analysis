"""Risk controls for preset E on a 50K prop account (buy $150 eval -> pass -> payouts -> bust -> repeat).

Each variant = (stop rule, sizing rule). Judged on 48 start months, cycles to end of 2025 (2026 shown separately).
Rules: $2,000 EOD trailing drawdown (checked against open loss), $3,000 target, best day <= 50% of profit,
funded: payout after 5 days >= $150 and balance >= $2,500, withdraw to $2,000 above start (max $2,000),
90% split, max 6 payouts per account.

Usage: python risk_sim.py
"""
import numpy as np
import pandas as pd

import orb_sweep as s
from prop_paths import path_block
from extra_test import gen_block

DD, TGT, CAP, MIND, FEE, SPLIT, MAXPAY = 2000.0, 3000.0, 2000.0, 150.0, 150.0, 0.90, 6

df = pd.read_parquet("nq_1m.parquet")
days, O, H, L, C = s.day_matrix(df, "Europe/London")
wk = days.weekday < 5
days, O, H, L, C = days[wk], O[wk], H[wk], L[wk], C[wk]
rng = np.nanmax(H[:, :1260], axis=1) - np.nanmin(L[:, :1260], axis=1)
atr = pd.Series(rng).rolling(14, min_periods=10).mean().shift(1).to_numpy()
ny = pd.DatetimeIndex([pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=55)
                       for d in days]).tz_convert("Europe/London")
EXM = (ny.hour * 60 + ny.minute).to_numpy()
YEARS = days.year.to_numpy()


def paths(stop_pts, be=0.0):
    """Per-day $ P&L, worst open $ and full-stop $ for 1 MNQ, 15:55 NY exit."""
    pnl = np.full(len(days), np.nan); mae = np.full(len(days), np.nan)
    for ex in np.unique(EXM):
        sel = EXM == ex
        p, a, f = path_block(O, H, L, C, 450, 510, int(ex), stop_pts, 1.0, 1.0)
        if be > 0:
            p = gen_block(O, H, L, C, 450, 510, int(ex), 0.0, 0, stop_pts, 1.0, be, 0, 1.0)
        pnl[sel] = p[sel] * 2 - 1.24; mae[sel] = a[sel] * 2 - 1.24
    return pnl, mae, stop_pts * 2 + 3.24


def cycle(pnl, mae, stopd, start, end, size_rule):
    """Real-life cycle. size_rule(phase, bal, thr, peak, stop_usd) -> contracts (0 = skip day)."""
    cum = 0.0 - FEE; buys = 1; passes = 0; npays = 0; funded_days = []; f_start = None
    phase, bal, thr, best, qual, npay, peak = 0, 0.0, -DD, 0.0, 0, 0, 0.0
    for d in range(start, end):
        p = pnl[d]
        if p != p:
            continue
        n = size_rule(phase, bal, thr, peak, stopd[d])
        if n <= 0:
            continue
        a, p = mae[d] * n, p * n
        if bal + a <= thr or bal + p <= thr:
            if phase == 1:
                funded_days.append(d - f_start)
            phase, bal, thr, best, qual, npay, peak = 0, 0.0, -DD, 0.0, 0, 0, 0.0
            cum -= FEE; buys += 1
            continue
        bal += p; peak = max(peak, bal)
        t2 = bal - DD
        if t2 > thr:
            thr = min(t2, 0.0) if thr < 0 else thr
        if phase == 0:
            best = max(best, p)
            if bal >= TGT and best <= 0.5 * bal:
                phase, bal, thr, qual, npay, peak = 1, 0.0, -DD, 0, 0, 0.0
                passes += 1; f_start = d
        else:
            if p >= MIND:
                qual += 1
            if qual >= 5 and bal >= DD + 500:
                w = min(CAP, bal - DD)
                bal -= w; qual = 0; npay += 1; npays += 1
                cum += w * SPLIT
                if npay >= MAXPAY:
                    funded_days.append(d - f_start)
                    phase, bal, thr, best, qual, npay, peak = 0, 0.0, -DD, 0.0, 0, 0, 0.0
                    cum -= FEE; buys += 1
    return cum, buys, passes, npays, funded_days


def evaluate(name, pnl, mae, stopd, rule):
    end25 = int(np.searchsorted(days, pd.Timestamp("2026-01-01")))
    nets, buys, passes, pays, life = [], [], [], [], []
    for m in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
        s0 = int(np.searchsorted(days, m))
        c, b, ps, py, fd = cycle(pnl, mae, stopd, s0, end25, rule)
        yrs = (end25 - s0) / 252
        nets.append(c / yrs); buys.append(b / yrs); passes.append(ps); pays.append(py); life += fd
    s0 = int(np.searchsorted(days, pd.Timestamp("2020-01-20")))
    yr_net = []
    for y in range(2020, 2027):
        a = int(np.searchsorted(days, pd.Timestamp(f"{y}-01-01"))); b = int(np.searchsorted(days, pd.Timestamp(f"{y + 1}-01-01")))
        c, *_ = cycle(pnl, mae, stopd, max(a, s0), b, rule)   # fresh start each Jan: is each year profitable on its own?
        yr_net.append(c)
    return {"variant": name, "net/yr median": np.median(nets), "net/yr worst start": np.min(nets),
            "evals/yr": np.mean(buys), "pass rate": np.sum(passes) / np.sum([b * ((end25 - int(np.searchsorted(days, m))) / 252) for b, m in zip(buys, pd.date_range("2020-02-01", "2023-11-01", freq="MS"))]),
            "payouts per funded": np.sum(pays) / max(np.sum(passes), 1),
            "funded life (days)": np.median(life) if life else 0,
            "years+ (fresh Jan start, 2020-25)": sum(v > 0 for v in yr_net[:6]), "worst year": min(yr_net[:6]),
            "2026": yr_net[6], **{str(2020 + i): round(v) for i, v in enumerate(yr_net)}}


def main():
    base = paths(atr)
    variants = []
    fixed = lambda n: (lambda ph, bal, thr, pk, sd: n)
    variants += [(f"E, fixed {n} MNQ", base, fixed(n)) for n in (1, 2, 3)]
    # fixed-dollar risk: contracts = floor(R / full-stop $); skip if 0 (or min 1)
    for R in (500, 700, 900, 1100, 1300):
        variants.append((f"E, risk ${R}/trade (skip if <1)", base, (lambda R: lambda ph, b, t, pk, sd: int(R // sd))(R)))
        variants.append((f"E, risk ${R}/trade (min 1)", base, (lambda R: lambda ph, b, t, pk, sd: max(1, int(R // sd)))(R)))
    # cushion-based: 2 MNQ if room above threshold >= C, else 1
    for Cc in (800, 1200, 1600, 2000):
        variants.append((f"E, 2 MNQ, 1 MNQ when room < ${Cc}", base,
                         (lambda Cc: lambda ph, b, t, pk, sd: 2 if (b - t) >= Cc else 1)(Cc)))
    # risk a share of the remaining room: contracts = floor(f * room / stop$), min 1
    for f in (0.3, 0.45, 0.6):
        variants.append((f"E, risk {int(f * 100)}% of room (min 1)", base,
                         (lambda f: lambda ph, b, t, pk, sd: max(1, int(f * (b - t) // sd)))(f)))
    # size down after a drop from the account high
    for X in (500, 1000):
        variants.append((f"E, 2 MNQ, 1 MNQ after ${X} drop from high", base,
                         (lambda X: lambda ph, b, t, pk, sd: 1 if (pk - b) >= X else 2)(X)))
    # capped stop ($ per MNQ) and narrower ATR stops, at 2 MNQ
    for cap in (400, 600, 800):
        stop_pts = np.minimum(atr, cap / 2.0)
        variants.append((f"Stop capped at ${cap}/MNQ, 2 MNQ", paths(stop_pts), fixed(2)))
    for k in (0.6, 0.8):
        variants.append((f"Stop {k} x ATR, 2 MNQ", paths(k * atr), fixed(2)))
    variants.append(("E + break-even at +1%, 2 MNQ", paths(atr, be=1.0), fixed(2)))
    rows = []
    for name, (p, a, sd), rule in variants:
        rows.append(evaluate(name, p, a, sd, rule))
        print(f"done: {name}", flush=True)
    r = pd.DataFrame(rows).sort_values("net/yr median", ascending=False)
    pd.set_option("display.width", 280); pd.set_option("display.max_columns", 30)
    cols = ["variant", "net/yr median", "net/yr worst start", "evals/yr", "pass rate", "payouts per funded",
            "funded life (days)", "years+ (fresh Jan start, 2020-25)", "worst year", "2026"]
    print(r[cols].round(2).to_string(index=False))
    r.to_csv("risk_sim_results.csv", index=False)


if __name__ == "__main__":
    main()
