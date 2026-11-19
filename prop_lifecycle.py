"""Real-life sequence on one 50K account at a time, Jan 2020 - Nov 2026:
buy evaluation ($150) -> trade it until pass or bust -> if passed, trade funded account, take payouts
until it busts -> buy the next evaluation the next trading day. Repeat.

Rules: end-of-day trailing $2,000 drawdown (checked against open loss), $3,000 target, best day <= 50%
of profit to pass; funded has no consistency rule, payout once there are 5 days >= $150 since the last
payout and balance >= $2,500 above start, withdraw down to $2,000 above start (max $2,000), 90% split.

Usage: python prop_lifecycle.py
"""
import json

import numpy as np
import pandas as pd

FEE = 150.0
DD, TGT, CAP, MIND, SPLIT = 2000.0, 3000.0, 2000.0, 150.0, 0.90
MAXPAY = 10 ** 9   # payouts allowed per funded account before it is closed (e.g. 6 at Apex)


def lifecycle(pnl, mae, dates, start, n_eval, n_funded):
    cum = 0.0
    events = []      # (date, kind, amount)
    curve = np.zeros(len(pnl))
    phase, bal, thr, best, qual, npay = 0, 0.0, -DD, 0.0, 0, 0
    cum -= FEE; events.append((dates[start], "buy", -FEE))
    for d in range(start, len(pnl)):
        p = pnl[d]
        if p == p:
            n = n_eval if phase == 0 else n_funded
            a, p = mae[d] * n, p * n
            if bal + a <= thr or bal + p <= thr:
                events.append((dates[d], "bust eval" if phase == 0 else "bust funded", 0.0))
                phase, bal, thr, best, qual, npay = 0, 0.0, -DD, 0.0, 0, 0
                if d + 1 < len(pnl):
                    cum -= FEE; events.append((dates[d + 1], "buy", -FEE))
                curve[d] = cum
                continue
            bal += p
            t2 = bal - DD
            if t2 > thr:
                thr = min(t2, 0.0) if thr < 0 else thr
            if phase == 0:
                best = max(best, p)
                if bal >= TGT and best <= 0.5 * bal:
                    events.append((dates[d], "pass", 0.0))
                    phase, bal, thr, qual, npay = 1, 0.0, -DD, 0, 0
            else:
                if p >= MIND:
                    qual += 1
                if qual >= 5 and bal >= DD + 500:
                    w = min(CAP, bal - DD)
                    bal -= w; qual = 0; npay += 1
                    cum += w * SPLIT; events.append((dates[d], "payout", w * SPLIT))
                    if npay >= MAXPAY:   # account retired after the payout cap: start a new evaluation
                        events.append((dates[d], "capped", 0.0))
                        phase, bal, thr, best, qual, npay = 0, 0.0, -DD, 0.0, 0, 0
                        if d + 1 < len(pnl):
                            cum -= FEE; events.append((dates[d + 1], "buy", -FEE))
        curve[d] = cum
    curve[:start] = 0.0
    return curve, events


def summarise(events, label):
    ev = pd.DataFrame(events, columns=["date", "kind", "amount"])
    ev["year"] = pd.to_datetime(ev.date).dt.year
    bought = (ev.kind == "buy").sum(); passed = (ev.kind == "pass").sum()
    pays = ev[ev.kind == "payout"]
    print(f"\n===== {label} =====")
    print(f"Evaluations bought: {bought}  (fees ${bought * FEE:,.0f})")
    print(f"Passed: {passed} ({passed / bought:.0%})   Funded accounts busted: {(ev.kind == 'bust funded').sum()}")
    print(f"Payouts: {len(pays)} totalling ${pays.amount.sum():,.0f} (average ${pays.amount.mean() if len(pays) else 0:,.0f})")
    print(f"NET P&L: ${ev.amount.sum():,.0f}")
    yr = ev.groupby("year").agg(bought=("kind", lambda k: (k == "buy").sum()),
                                passed=("kind", lambda k: (k == "pass").sum()),
                                payouts=("kind", lambda k: (k == "payout").sum()),
                                paid=("amount", lambda a: a[a > 0].sum()),
                                net=("amount", "sum"))
    yr["fees"] = -yr.bought * FEE
    print(yr[["bought", "passed", "payouts", "fees", "paid", "net"]].round(0).to_string())
    return ev


def main():
    df = pd.read_parquet("prop_days.parquet")
    pnl = df["E_pnl"].to_numpy(); mae = df["E_mae"].to_numpy(); dates = df.index
    start = int(np.searchsorted(dates, pd.Timestamp("2020-01-20")))   # needs 14 days of ATR history
    out = {"d": [x.strftime("%Y-%m-%d") for x in dates[start:]]}
    for label, ne, nf in [("Eval at 2 MNQ, funded at 1 MNQ", 2, 1), ("Eval at 2 MNQ, funded at 2 MNQ", 2, 2),
                          ("Eval at 1 MNQ, funded at 1 MNQ", 1, 1)]:
        curve, events = lifecycle(pnl, mae, dates, start, ne, nf)
        ev = summarise(events, label)
        out[label] = {"c": curve[start:].round(0).astype(int).tolist(),
                      "pay": [(e[0].strftime("%Y-%m-%d"), round(e[2])) for e in events if e[1] == "payout"]}
        # start-date sensitivity: begin on the first trading day of each month 2020-2023
        finals = []
        for m in pd.date_range("2020-02-01", "2023-11-01", freq="MS"):
            s0 = int(np.searchsorted(dates, m))
            c, e = lifecycle(pnl, mae, dates, s0, ne, nf)
            yrs = (len(pnl) - s0) / 252
            finals.append(c[-1] / yrs)
        finals = np.array(finals)
        print(f"Start-date check (48 different start months, 2020-2023): net per year median ${np.median(finals):,.0f}, "
              f"range ${finals.min():,.0f} to ${finals.max():,.0f}; positive in {(finals > 0).mean():.0%} of starts")
    json.dump(out, open("prop_lifecycle.json", "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
