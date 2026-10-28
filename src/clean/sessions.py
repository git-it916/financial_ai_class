"""Common time axis for every source.

fx_date rolls at 17:00 New York (06:00 KST in US summer time, 07:00 otherwise), the same day the
24h Seoul market and ECOS use from P2. Run `python -m src.clean.sessions` for the self-check.
"""
from __future__ import annotations

import pandas as pd
import yaml

from ..collect.common import ROOT

REGIMES = yaml.safe_load((ROOT / "config" / "events.yaml").read_text(encoding="utf-8"))["regimes"]
SAMPLE_END = pd.Timestamp("2026-10-09")  # last fx_date in the main sample (analysis_decisions.md v0)
NY = "America/New_York"


def fx_date(ts_utc: pd.Series) -> pd.Series:
    wall = ts_utc.dt.tz_convert(NY).dt.tz_localize(None)  # NY wall clock, so DST shifts the roll
    return (wall + pd.Timedelta(hours=7)).dt.normalize()


def us_dst(ts_utc: pd.Series) -> pd.Series:
    offset = ts_utc.dt.tz_convert(NY).dt.tz_localize(None) - ts_utc.dt.tz_localize(None)
    return offset == pd.Timedelta(hours=-4)


def us_dst_on(dates: pd.Series) -> pd.Series:
    """DST flag for a daily date (taken at noon New York)."""
    noon = pd.to_datetime(dates).dt.normalize() + pd.Timedelta(hours=12)
    return us_dst(noon.dt.tz_localize(NY).dt.tz_convert("UTC"))


def session(ts_utc: pd.Series) -> pd.Series:
    """KST session: day 09:00-15:30, A 15:30-02:00, B 02:00-NY close, C NY close-09:00."""
    kst = ts_utc.dt.tz_convert("Asia/Seoul")
    m = kst.dt.hour * 60 + kst.dt.minute
    close = us_dst(ts_utc).map({True: 6 * 60, False: 7 * 60})
    out = pd.Series("A", index=ts_utc.index)
    out[(m >= 9 * 60) & (m < 15 * 60 + 30)] = "day"
    out[(m >= 2 * 60) & (m < close)] = "B"
    out[(m >= close) & (m < 9 * 60)] = "C"
    return out


def period(dates: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates)
    out = pd.Series(pd.NA, index=d.index, dtype="string")
    for name in ["P_pre", "P0", "P1", "P2"]:
        r = REGIMES[name]
        end = pd.Timestamp(r["end"]) if r.get("end") else SAMPLE_END
        out[(d >= pd.Timestamp(r["start"])) & (d <= end)] = name
    return out


def p1_late(dates: pd.Series) -> pd.Series:
    r = REGIMES["P1_late"]
    d = pd.to_datetime(dates)
    return (d >= pd.Timestamp(r["start"])) & (d <= pd.Timestamp(r["end"]))


def tag(ts_utc: pd.Series) -> pd.DataFrame:
    """All time columns for intraday rows."""
    fd = fx_date(ts_utc)
    return pd.DataFrame({
        "ts_kst": ts_utc.dt.tz_convert("Asia/Seoul"),
        "fx_date": fd,
        "session": session(ts_utc),
        "period": period(fd),
        "p1_late": p1_late(fd),
        "us_dst": us_dst(ts_utc),
    })


def _check() -> None:
    ts = pd.Series(pd.to_datetime([
        "2026-10-30 05:59", "2026-10-30 06:00", "2026-11-02 06:30", "2026-11-02 07:00",
        "2026-10-29 15:00", "2026-10-29 20:00", "2026-10-29 03:00",
    ]).tz_localize("Asia/Seoul").tz_convert("UTC"))
    t = tag(ts)
    assert list(t.fx_date.dt.strftime("%m-%d")) == ["10-29", "10-30", "11-01", "11-02", "10-29", "10-29", "10-28"]  # Mon 06:30 KST in winter is pre-open -> Sunday
    assert list(t.session) == ["B", "C", "B", "C", "day", "A", "B"]
    assert list(t.us_dst) == [True, True, False, False, True, True, True]
    p = period(pd.Series(["2022-06-30", "2022-07-01", "2026-07-03", "2026-07-06", "2026-10-10"]))
    assert list(p.fillna("-")) == ["P_pre", "P0", "P1", "P2", "-"]
    assert list(us_dst_on(pd.Series(["2026-10-30", "2026-11-02"]))) == [True, False]
    print("sessions ok")


if __name__ == "__main__":
    _check()
