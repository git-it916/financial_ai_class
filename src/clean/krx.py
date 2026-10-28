"""KRX USD futures -> data/processed/krx_usd.parquet (one row per fx_date x session x contract).

Night rows dated D belong to the session that ended 06:00 KST on D, so their fx_date is the previous
KRX trading day (analysis_decisions.md v0). Spreads ('SP') are dropped.
python -m src.clean.krx
"""
from __future__ import annotations

import pandas as pd

from ..collect.common import INTERIM, ROOT
from . import cleanlog
from .sessions import p1_late, period, us_dst_on

OUT = ROOT / "data" / "processed" / "krx_usd.parquet"
NUM = {"TDD_OPNPRC": "open", "TDD_HGPRC": "high", "TDD_LWPRC": "low", "TDD_CLSPRC": "close",
       "SETL_PRC": "settle", "SPOT_PRC": "spot", "ACC_TRDVOL": "volume", "ACC_OPNINT_QTY": "oi"}
MIN_DAYS = 10  # ponytail: provisional roll rule, fixed in E2 (analysis_decisions.md)


def third_monday(month: pd.Timestamp) -> pd.Timestamp:
    first = month.replace(day=1)
    return first + pd.Timedelta(days=(7 - first.weekday()) % 7 + 14)


def load() -> pd.DataFrame:
    raw = pd.read_parquet(INTERIM / "krx_usd_futures.parquet")
    keep = (raw.PROD_NM == "미국달러 선물") & ~raw.ISU_NM.str.contains("SP")
    cleanlog.record("krx", "01_product", "drop", len(raw), int(keep.sum()),
                    "kept PROD_NM='미국달러 선물' outright contracts; calendar spreads ('SP') out", rows=raw[~keep])
    k = raw[keep].copy()
    out = pd.DataFrame({
        "bas_dd": pd.to_datetime(k.BAS_DD),
        "session": k.MKT_NM.map({"정규": "day", "야간": "night"}),
        "contract": pd.to_datetime(k.ISU_NM.str.extract(r"F (\d{6})")[0], format="%Y%m"),
    })
    for src, dst in NUM.items():
        out[dst] = pd.to_numeric(k[src].astype(str).str.replace(",", ""), errors="coerce")
    novol = out.volume.fillna(0) == 0
    cleanlog.record("krx", "02_zero_volume", "change", len(out), len(out),
                    "no trades that day: open/high/low/close set to missing (KRX fills them with blanks or stale values)",
                    rows=out[novol & out[["open", "high", "low", "close"]].notna().any(axis=1)], affected=int(novol.sum()))
    out.loc[novol, ["open", "high", "low", "close"]] = pd.NA
    dup = out.duplicated()
    cleanlog.record("krx", "03_duplicates", "drop", len(out), len(out) - int(dup.sum()), "exact duplicate rows", rows=out[dup])
    return out[~dup]


def build() -> pd.DataFrame:
    k = load()
    cal = pd.DatetimeIndex(sorted(k.bas_dd.unique()))  # KRX trading days
    prev = pd.Series(cal[:-1], index=cal[1:])
    k["fx_date"] = k.bas_dd.where(k.session == "day", k.bas_dd.map(prev))
    # last trade = 3rd Monday, or the trading day before it if that is a holiday; settle = 2 trading days later
    # (checked against the data: 191 contracts on the 3rd Monday, 10 moved earlier by holidays)
    def last_trade(c: pd.Timestamp) -> pd.Timestamp:
        m = third_monday(c)
        return cal[cal <= m][-1] if m <= cal[-1] else m

    def settle(d: pd.Timestamp) -> pd.Timestamp:
        nxt = cal[cal > d]
        return nxt[1] if len(nxt) >= 2 else d + pd.offsets.BDay(2)

    lt = {c: last_trade(c) for c in k.contract.unique()}
    st = {d: settle(d) for d in set(lt.values())}
    k["last_trade"] = k.contract.map(lt)
    k["settle_date"] = k.last_trade.map(st)
    k["days"] = (k.settle_date - k.fx_date).dt.days
    live = k[k.days >= MIN_DAYS]
    front = live.groupby(["fx_date", "session"]).contract.min().rename("front")
    k = k.join(front, on=["fx_date", "session"])
    k["is_front"] = k.contract == k.front
    k["period"] = period(k.fx_date)
    k["p1_late"] = p1_late(k.fx_date)
    k["us_dst"] = us_dst_on(k.fx_date)
    return k.drop(columns="front").sort_values(["fx_date", "session", "contract"]).reset_index(drop=True)


def main() -> None:
    cleanlog.reset("krx")
    k = build()
    for name, mask, why in [("no_front_night", (k.session == "night") & k.is_front & k.close.isna(),
                             "front-month night session with no trades (close missing)"),
                            ("cme_link_night", (k.session == "night") & (k.fx_date < "2021-01-01"),
                             "night rows 2014-12~2020 (KRX-CME link era, hours to be confirmed; kept, not used in main test)")]:
        cleanlog.record("krx", f"04_flag_{name}", "flag", len(k), len(k), why, affected=int(mask.sum()))
    # rule check: an expired contract's last day-session trade should equal the computed last_trade
    seen = k[(k.session == "day") & (k.volume > 0)].groupby("contract").bas_dd.max()
    rule = k.drop_duplicates("contract").set_index("contract").last_trade
    exp = seen.index[seen.index < k.fx_date.max().to_period("M").to_timestamp()]
    off = (seen[exp] != rule[exp]).sum()
    print(f"last_trade rule mismatches: {off} of {len(exp)} expired contracts")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    k.to_parquet(OUT, index=False)
    f = k[k.is_front]
    cleanlog.record("krx", "99_saved", "info", len(k), len(k), f"saved {OUT.relative_to(ROOT)}", affected=0)
    print(f.groupby("session").agg(first=("fx_date", "min"), last=("fx_date", "max"), days=("fx_date", "nunique"),
                                    med_days=("days", "median"), zero_vol=("close", lambda s: s.isna().mean())))


if __name__ == "__main__":
    main()
