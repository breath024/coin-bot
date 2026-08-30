"""최소 유지시간(min_hold_bars) 검증 — 다장세 일단위 윈도우로 baseline(0) vs 후보값.

0-B에서 확정한 원인: trail_pct=0.10%가 1분봉 노이즈 폭과 겹쳐 조기청산 다발
(10x 33건 중 25건이 진입 후 1시간 내 청산). 후보안②는 "진입 후 N분은 트레일 평가
자체를 안 함"으로 순수 노이즈성 즉시청산을 차단하는 것. trail_pct는 손대지 않고
min_hold_bars만 켠다(변수 하나만 바꿔 순수 효과만 본다).

기존 data/BTCUSDT_1m.csv(6/2~7/10, 하락+횡보 다장세)를 일단위(1440봉)로 쪼개
윈도우별 장세(상승/횡보/하락) 태그와 함께 baseline vs 후보 min_hold_bars를 비교한다.
validate_align_regimes.py와 같은 패턴(한 구간 통짜 결과의 착시를 막기 위해).

    python compare_min_hold.py [csv이름] [레버] [후보목록=5,10,15,20,30] [윈도우봉=1440]
"""
import os
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from core import Bar
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip

SYMBOL = "BTCUSDT"
INITIAL = 1_000_000
HERE = os.path.dirname(os.path.abspath(__file__))


def load_bars(path):
    import csv
    from datetime import datetime
    bars = []
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or not row[0].isdigit():
                continue
            ot = int(row[0])
            bars.append(Bar(SYMBOL, datetime.fromtimestamp(ot / 1000),
                            float(row[2]), float(row[3]), float(row[4]),
                            float(row[5]), float(row[6])))
    return bars


def regime(bars):
    chg = (bars[-1].close / bars[0].open - 1) * 100
    return ("상승" if chg > 1 else "하락" if chg < -1 else "횡보"), chg


def hold_stats(fills):
    """ENTRY-청산 짝지어 평균 보유시간(분)·15분 이내 청산 비율을 낸다."""
    holds = []
    cur = None
    for f in fills:
        if f.kind == "ENTRY":
            cur = f.dt
        elif cur is not None:
            holds.append((f.dt - cur).total_seconds() / 60)
            cur = None
    if not holds:
        return 0.0, 0.0
    avg = sum(holds) / len(holds)
    quick = sum(1 for h in holds if h <= 15) / len(holds)
    return avg, quick


def run(bars, lev, min_hold):
    broker = FuturesBroker(leverage=lev, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    strat = MomentumDip(SYMBOL, min_hold_bars=min_hold)
    eng = FuturesEngine(ListFeed(bars), strat, broker, FuturesAccount(INITIAL)).run()
    c = curve_metrics(eng.equity_curve, INITIAL)
    s = trade_stats(eng.fills)
    avg_hold, quick = hold_stats(eng.fills)
    ret = c.get("총수익률", 0) * 100
    n = s.get("청산건수", 0)
    payoff = s.get("손익비(평균이익/평균손실)") or 0.0
    liq = s.get("청산(LIQ)횟수", 0)
    return ret, n, payoff, avg_hold, quick, liq


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT_1m.csv"
    lev = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    cands = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [5, 10, 15, 20, 30]
    win = int(sys.argv[4]) if len(sys.argv) > 4 else 1440   # 1일

    path = os.path.join(HERE, "data", name)
    bars = load_bars(path)
    span_d = (bars[-1].dt - bars[0].dt).total_seconds() / 86400
    print(f"데이터: {name}  {bars[0].dt:%m-%d %H:%M}~{bars[-1].dt:%m-%d %H:%M} "
          f"({len(bars):,}봉, {span_d:.1f}일)  레버 {lev}x, 후보 min_hold_bars={cands}\n")

    windows = [bars[i:i + win] for i in range(0, len(bars) - win + 1, win)]

    hdr_cands = " | ".join(f"{f'{m}분':>7}수익 {'건':>3}" for m in cands)
    print(f"{'윈도우(시작)':>13} {'장세':>4} {'변동%':>7} | {'0(base)':>7} {'건':>3} | {hdr_cands}")
    print("-" * (36 + 14 * len(cands)))

    agg = {}          # regime -> {0: [sum_ret,n], cand: [...]}
    win_diff = {c: [] for c in cands}   # 후보-baseline 수익차, 윈도우별 (승/패 집계용)
    detail = {0: [], **{c: [] for c in cands}}  # 전체 집계용 (avg_hold, quick, payoff, liq)

    for w in windows:
        reg, chg = regime(w)
        base = run(w, lev, 0)
        row = f"{w[0].dt:%m-%d %H:%M} {reg:>4} {chg:>+6.1f}% | {base[0]:>+6.1f}% {base[1]:>3} |"
        a = agg.setdefault(reg, {})
        a.setdefault(0, [0.0, 0])
        a[0][0] += base[0]; a[0][1] += 1
        detail[0].append(base)
        for c in cands:
            r = run(w, lev, c)
            row += f" {r[0]:>+6.1f}% {r[1]:>3} |"
            a.setdefault(c, [0.0, 0])
            a[c][0] += r[0]; a[c][1] += 1
            win_diff[c].append(r[0] - base[0])
            detail[c].append(r)
        print(row)

    print("-" * (36 + 14 * len(cands)))
    print("\n=== 장세별 평균 수익 (윈도우 평균) ===")
    for reg in sorted(agg):
        line = f"  {reg}: base {agg[reg][0][0]/agg[reg][0][1]:+.2f}%"
        for c in cands:
            s, n = agg[reg][c]
            line += f"  | {c}분 {s/n:+.2f}%"
        print(line)

    print("\n=== 후보별 전체 집계 (전체 윈도우 합산 평균 보유시간·15분내청산비율·손익비·청산) ===")

    def summarize(label, rows):
        n_total = sum(r[1] for r in rows)
        avg_hold = sum(r[3] * r[1] for r in rows) / n_total if n_total else 0
        quick = sum(r[4] * r[1] for r in rows) / n_total if n_total else 0
        payoff_vals = [r[2] for r in rows if r[2]]
        payoff = sum(payoff_vals) / len(payoff_vals) if payoff_vals else 0
        liq = sum(r[5] for r in rows)
        print(f"  {label:>10}: 총건수 {n_total:>4} | 평균보유 {avg_hold:>6.1f}분 | "
              f"15분내청산 {quick*100:>5.1f}% | 손익비평균 {payoff:>5.2f} | LIQ {liq}")

    summarize("base(0)", detail[0])
    for c in cands:
        summarize(f"{c}분", detail[c])

    print("\n=== 후보가 baseline보다 나은/나쁜 윈도우 수 (수익률 기준) ===")
    for c in cands:
        d = win_diff[c]
        better = sum(1 for x in d if x > 1e-9)
        worse = sum(1 for x in d if x < -1e-9)
        tie = len(d) - better - worse
        print(f"  min_hold={c}분: 나음 {better} / 나쁨 {worse} / 동률 {tie}  (총 {len(d)}개 윈도우)")


if __name__ == "__main__":
    main()
