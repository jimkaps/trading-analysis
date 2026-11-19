"""50K account: pass the evaluation at 2 MNQ, then trade 1 MNQ once funded. Same rules as prop_detail.py."""
import json

import numpy as np
import pandas as pd

from prop_detail import run_eval, run_funded

df = pd.read_parquet("prop_days.parquet")
pnl = df["E_pnl"].to_numpy(); mae = df["E_mae"].to_numpy()
DD, TGT, CAP, MIND = 2000.0, 3000.0, 2000.0, 150.0
res = np.array([run_eval(pnl, mae, s0, 2, DD, TGT, 0.5) for s0 in range(15, len(pnl) - 60)])
starts = np.unique(res[res[:, 0] == 1, 2]) + 1
starts = starts[starts < len(pnl) - 20]
C, L, NP, FIRST = [], [], [], []
for s0 in starts:
    c, b, k, n_p = run_funded(pnl, mae, s0, 1, DD, CAP, MIND, 252, 0.9)
    if k == -2:
        continue
    cc = pd.Series(c).ffill().fillna(0).to_numpy()
    C.append(cc); L.append(k); NP.append(n_p)
    nz = np.where(cc > 0)[0]
    if len(nz): FIRST.append(nz[0] + 1)
C = np.array(C); L = np.array(L); NP = np.array(NP); tot = C[:, -1]
alive = np.array([((L == -1) | (L > k)).mean() for k in range(252)])
bk = L[L >= 0]
print(f"Funded accounts simulated: {len(C)}")
print(f"Alive after 1/3/6/12 months: {alive[20]:.0%} / {alive[62]:.0%} / {alive[125]:.0%} / {alive[251]:.0%}")
print(f"Busted accounts: median life {np.median(bk):.0f} trading days")
print(f"Got at least one payout: {(NP > 0).mean():.0%}; average number of payouts {NP.mean():.1f}")
print(f"Days to first payout (if any): median {np.median(FIRST):.0f}")
q = np.percentile(tot, [10, 25, 50, 75, 90])
print(f"12-month payouts: median ${q[2]:,.0f}, mean ${tot.mean():,.0f}, 25-75% ${q[1]:,.0f}-${q[3]:,.0f}, top 10% ${q[4]:,.0f}+")
x = list(range(0, 252, 5)) + [251]
json.dump({"mean": [round(float(C[:, i].mean())) for i in x], "alive": [round(float(alive[i]) * 100, 1) for i in x]},
          open("prop_50k_1mnq.json", "w"), separators=(",", ":"))
print(json.dumps({"mean": [round(float(C[:, i].mean())) for i in x], "alive": [round(float(alive[i]) * 100, 1) for i in x]}))
