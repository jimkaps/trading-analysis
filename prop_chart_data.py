"""Mean cumulative payouts and survival per funded account, sampled every 5 trading days, for the chart."""
import json

import numpy as np
import pandas as pd

from prop_detail import run_eval, run_funded

df = pd.read_parquet("prop_days.parquet")
pnl = df["E_pnl"].to_numpy(); mae = df["E_mae"].to_numpy()
OPTS = {"50K, 2 MNQ": (2, 2, 2000.0, 3000.0, 2000.0, 150.0),
        "150K, 5 MNQ": (5, 5, 4500.0, 9000.0, 5000.0, 250.0),
        "150K, eval 5 then funded 1 MNQ": (5, 1, 4500.0, 9000.0, 5000.0, 250.0)}
out = {"x": list(range(0, 252, 5)) + [251]}
for name, (ne, nf, dd, tgt, cap, mind) in OPTS.items():
    res = np.array([run_eval(pnl, mae, s0, ne, dd, tgt, 0.5) for s0 in range(15, len(pnl) - 60)])
    starts = np.unique(res[res[:, 0] == 1, 2]) + 1
    starts = starts[starts < len(pnl) - 20]
    C, L = [], []
    for s0 in starts:
        c, b, k, n_p = run_funded(pnl, mae, s0, nf, dd, cap, mind, 252, 0.9)
        if k == -2:
            continue
        c = pd.Series(c).ffill().fillna(0).to_numpy()
        C.append(c); L.append(k)
    C = np.array(C); L = np.array(L)
    # accounts with too little future data are kept but only counted while data exists
    mean = np.nanmean(C, axis=0)
    alive = np.array([((L == -1) | (L > k)).mean() for k in range(252)])
    out[name] = {"mean": [round(float(mean[i])) for i in out["x"]],
                 "alive": [round(float(alive[i]) * 100, 1) for i in out["x"]]}
json.dump(out, open("prop_chart.json", "w"), separators=(",", ":"))
print(json.dumps(out))
