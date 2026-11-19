"""Funded-account survival and payouts when trading smaller after passing the evaluation."""
import numpy as np
import pandas as pd

from prop_detail import run_eval, run_funded

df = pd.read_parquet("prop_days.parquet")
pnl = df["E_pnl"].to_numpy(); mae = df["E_mae"].to_numpy()
CASES = {"50K (eval at 2 MNQ)": (2, 2000.0, 3000.0, 2000.0, 150.0, [1, 2]),
         "150K (eval at 5 MNQ)": (5, 4500.0, 9000.0, 5000.0, 250.0, [1, 2, 3, 4, 5])}
for name, (ne, dd, tgt, cap, mind, sizes) in CASES.items():
    res = np.array([run_eval(pnl, mae, s0, ne, dd, tgt, 0.5) for s0 in range(15, len(pnl) - 60)])
    starts = np.unique(res[res[:, 0] == 1, 2]) + 1
    starts = starts[starts < len(pnl) - 20]
    print(name)
    for nf in sizes:
        tot, life, npay = [], [], []
        for s0 in starts:
            c, b, k, n_p = run_funded(pnl, mae, s0, nf, dd, cap, mind, 252, 0.9)
            if k == -2:
                continue
            tot.append(np.nanmax(np.nan_to_num(c))); life.append(k); npay.append(n_p)
        tot = np.array(tot); life = np.array(life); npay = np.array(npay)
        alive = lambda m: ((life == -1) | (life > m)).mean()
        print(f"  funded at {nf} MNQ: alive after 1/3/6/12 months {alive(20):.0%}/{alive(62):.0%}/{alive(125):.0%}/"
              f"{alive(251):.0%} | got a payout {(npay > 0).mean():.0%} | 12-month payouts: median ${np.median(tot):,.0f}, "
              f"mean ${tot.mean():,.0f}, top quarter ${np.percentile(tot, 75):,.0f}+, top 10% ${np.percentile(tot, 90):,.0f}+")
