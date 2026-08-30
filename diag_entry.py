"""진단: 내 진입 조건이 실데이터에서 '어디서 다 걸러지는지' 깔때기로 확인.

전략 로직을 복제하지 않는다 — 진짜 MomentumDip을 그대로 돌리고,
매 봉마다 내부 상태(_pb, _pb_ref, _pb_ext, _htf_trend)를 들여다봐 단계별로 센다.

  python diag_entry.py [csv경로]

funnel()/print_funnel()은 tick_backtest.py 등에서 재사용한다.
"""
import csv
import os
import sys
from datetime import datetime

from core import Bar
from strategy import MomentumDip

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "data", "BTCUSDT_1m.csv")


def load_bars(path):
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ts = (row.get("datetime") or row.get("timestamp") or "").strip().replace("T", " ")
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
            out.append(Bar("BTCUSDT", dt, float(row["open"]), float(row["high"]),
                           float(row["low"]), float(row["close"]), float(row.get("volume", 0) or 0)))
    return out


class _DummyAccount:
    position = None          # 항상 무포지션 → 매 봉 진입조건이 평가됨


class _RecBroker:
    def __init__(self):
        self.entries = []
    def request_entry(self, side, reason):
        self.entries.append((side, reason))
    def request_exit(self, reason):
        pass


def funnel(bars, strat=None):
    """bars를 MomentumDip에 통과시키며 진입조건 깔때기를 센다 → dict.

    strat 미지정 시 기본 파라미터 MomentumDip 생성.
    전략 로직은 복제하지 않고, 진입이 막힌 '멈춤' 시점의 내부값을 관찰만 한다.
    """
    if strat is None:
        strat = MomentumDip("BTCUSDT")
    acct, brk = _DummyAccount(), _RecBroker()
    n = len(bars)
    trend = {1: 0, -1: 0, 0: 0}
    eligible = spike_start = valid_stop = depth_pass = both_pass = 0
    prev_pb = 0
    for bar in bars:
        strat.on_bar(bar, acct, brk)
        cur_pb, t = strat._pb, strat._htf_trend
        trend[t] = trend.get(t, 0) + 1
        if t != 0 and strat._prev_low is not None:
            eligible += 1
        if prev_pb == 0 and cur_pb >= 1:
            spike_start += 1
        if 1 <= prev_pb <= strat.max_wait and cur_pb == 0:
            valid_stop += 1
            ref, ext = strat._pb_ref, strat._pb_ext
            depth = (ref - ext) / ref if (t == 1 and ref) else ((ext - ref) / ref if ref else 0)
            flat = ((bar.high - bar.low) / bar.close <= strat.flat_pct) if bar.close else False
            if depth >= strat.sweep_pct:
                depth_pass += 1
                if flat:
                    both_pass += 1
        prev_pb = cur_pb
    return {
        "n": n, "strat": strat, "trend": trend, "eligible": eligible,
        "spike_start": spike_start, "valid_stop": valid_stop,
        "depth_pass": depth_pass, "both_pass": both_pass,
        "entries": brk.entries,
        "span": (f"{bars[0].dt:%m-%d %H:%M} ~ {bars[-1].dt:%m-%d %H:%M}" if bars else "-"),
    }


def print_funnel(r):
    s = r["strat"]
    n, vs, dp = r["n"], r["valid_stop"], r["depth_pass"]
    pct = lambda a, b: f"{(a/b*100):5.1f}%" if b else "  -  "
    print(f"데이터: {n}봉  ({r['span']})")
    print(f"파라미터: max_wait={s.max_wait}, sweep≥{s.sweep_pct*100:.2f}%, "
          f"flat≤{s.flat_pct*100:.2f}%, regime_ma={s.regime_ma}, htf={s.htf_group}\n")
    t = r["trend"]
    print("── 흐름(상위 추세) 분포 ──")
    print(f"  상승 {t.get(1,0):6d}봉 ({pct(t.get(1,0),n)})")
    print(f"  하락 {t.get(-1,0):6d}봉 ({pct(t.get(-1,0),n)})")
    print(f"  횡보 {t.get(0,0):6d}봉 ({pct(t.get(0,0),n)})  ← 횡보면 진입 평가 안 함\n")
    print("── 진입 조건 깔때기 ──")
    print(f"  ① 진입평가 도는 봉(흐름≠0)     : {r['eligible']}")
    print(f"  ② 훼이크 스파이크 시작          : {r['spike_start']}")
    print(f"  ③ 1~{s.max_wait}봉 안에 '멈춤'(후보)   : {vs}")
    print(f"  ④ + 스윕깊이 ≥ {s.sweep_pct*100:.2f}%        : {dp}   ({pct(dp,vs)} of ③)")
    print(f"  ⑤ + 그 봉 '고정'(flat) = 진입   : {r['both_pass']}   ({pct(r['both_pass'],dp)} of ④)")
    ok = "OK" if len(r["entries"]) == r["both_pass"] else "불일치!"
    print(f"\n  실제 MomentumDip 진입 호출      : {len(r['entries'])}   (⑤와 같아야 정상 → {ok})")
    for side, reason in r["entries"][:10]:
        print(f"      · {side.value}  «{reason}»")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    print_funnel(funnel(load_bars(path)))


if __name__ == "__main__":
    main()
