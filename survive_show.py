"""Display survive_search.parquet with correct precision."""
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)
r = pd.read_parquet("survive_search.parquet")
YR = [f"s{y}" for y in range(2020, 2026)]
num = ["pass %", "survive 1yr %", "worst start-yr %", "median eval days", "payouts in yr $", "trades/yr",
       "1-MNQ total $", "1-MNQ maxDD $"] + YR
r[num] = r[num].round(0)
u = r.drop_duplicates(["stop xATR", "skip if stop >$"])[["stop xATR", "skip if stop >$", "trades/yr", "1-MNQ total $",
                                                         "1-MNQ maxDD $"]].copy()
u["total/DD"] = (u["1-MNQ total $"] / u["1-MNQ maxDD $"]).round(1)
print("Underlying strategy per stop / skip rule (1 MNQ, 2020 - Nov 2026):")
print(u.to_string(index=False))
cols = ["stop xATR", "skip if stop >$", "account", "eval MNQ", "funded MNQ", "pass %", "survive 1yr %",
        "worst start-yr %", "median eval days", "payouts in yr $"] + YR
print("\nTop 25 by 1-year survival:")
print(r.sort_values("survive 1yr %", ascending=False).head(25)[cols].to_string(index=False))
print("\nBest per account:")
print(r.sort_values("survive 1yr %", ascending=False).groupby("account").head(2)[cols].to_string(index=False))
