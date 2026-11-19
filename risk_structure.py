"""Survival vs profit for account/contract structures, same metrics as risk_sim.py (preset E, 15:55 NY exit)."""
import numpy as np
import pandas as pd

import risk_sim as rs

p, a, sd = rs.paths(rs.atr)
rows = []
for acct, dd, tgt, cap, mind, fee, sizes in [("50K", 2000.0, 3000.0, 2000.0, 150.0, 150.0, [(2, 2), (2, 1), (1, 1), (3, 2)]),
                                             ("150K", 4500.0, 9000.0, 5000.0, 250.0, 350.0, [(5, 5), (5, 3), (5, 2), (5, 1), (4, 2), (3, 3)])]:
    rs.DD, rs.TGT, rs.CAP, rs.MIND, rs.FEE = dd, tgt, cap, mind, fee
    for ne, nf in sizes:
        rule = (lambda ne, nf: lambda ph, b, t, pk, s_: ne if ph == 0 else nf)(ne, nf)
        r = rs.evaluate(f"{acct}: eval {ne} MNQ, funded {nf} MNQ (fee ${fee:.0f})", p, a, sd, rule)
        rows.append(r)
r = pd.DataFrame(rows)
pd.set_option("display.width", 280); pd.set_option("display.max_columns", 30)
cols = ["variant", "net/yr median", "net/yr worst start", "evals/yr", "payouts per funded", "funded life (days)",
        "years+ (fresh Jan start, 2020-25)", "worst year", "2026"]
print(r[cols].round(2).to_string(index=False))
