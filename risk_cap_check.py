"""Robustness of the stop cap: nearby $ caps, and caps as a % of price (scale with NQ's price), at 2 MNQ on 50K."""
import numpy as np
import pandas as pd

import risk_sim as rs

price = np.nanmean(rs.C[:, 450:510], axis=1)
fixed2 = lambda ph, b, t, pk, sd: 2
rows = [rs.evaluate("E, no cap (current)", *rs.paths(rs.atr), fixed2)]
for cap in (500, 550, 600, 650, 700, 800, 1000):
    rows.append(rs.evaluate(f"cap ${cap}/MNQ", *rs.paths(np.minimum(rs.atr, cap / 2.0)), fixed2))
for pct in (0.8, 0.9, 1.0, 1.1, 1.2, 1.4):
    rows.append(rs.evaluate(f"cap {pct}% of price", *rs.paths(np.minimum(rs.atr, price * pct / 100)), fixed2))
r = pd.DataFrame(rows)
pd.set_option("display.width", 280); pd.set_option("display.max_columns", 30)
cols = ["variant", "net/yr median", "net/yr worst start", "evals/yr", "payouts per funded", "funded life (days)",
        "years+ (fresh Jan start, 2020-25)", "worst year", "2026"] + [str(y) for y in range(2020, 2026)]
print(r[cols].round(2).to_string(index=False))
share = (rs.atr > price * 0.01)
print(f"\nShare of days where 1% of price is tighter than the ATR stop: {np.nanmean(share):.0%} overall, "
      f"{np.nanmean(share[rs.YEARS == 2026]):.0%} in 2026")
print(f"Share of days where $600 cap binds: {np.nanmean(rs.atr > 300):.0%} overall, {np.nanmean((rs.atr > 300)[rs.YEARS == 2026]):.0%} in 2026")
