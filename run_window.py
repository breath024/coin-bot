"""구간 백테스트 — '마지막에 본 봉' 이후부터 최신까지만 모의투자.

CSV(data/BTCUSDT_1m.csv)에서 지정한 open_time(ms) 이후 봉만 잘라
같은 매매법(MomentumDip)을 레버리지별로 돌린다.

    python run_window.py [cutoff_open_time_ms]

cutoff 생략 시 1780477440000 (= 2026-06-03 18:04, 직전 세션 마지막 봉).
"""
import csv
import os
import sys
from datetime import datetime

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from core import Bar
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip

SYMBOL = "BTCUSDT"
INITIAL = 1_000_000
LEVERAGES = [5, 10, 20, 100]
HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", f"{SYMBOL}_1m.csv")
DEFAULT_CUTOFF = 1780477440000   # 2026-06-03 18:04 (직전 세션 마지막 봉)


def load_bars(cutoff):
    bars = []
    with open(PATH, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or not row[0].isdigit():
                continue
            ot = int(row[0])
            if ot <= cutoff:
                continue
            bars.append(Bar(SYMBOL, datetime.fromtimestamp(ot / 1000),
                            float(row[2]), float(row[3]), float(row[4]),
                            float(row[5]), float(row[6])))
    return bars


def run_one(bars, lev):
    broker = FuturesBroker(leverage=lev, margin_fraction=0.05,
                           stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(ListFeed(bars), MomentumDip(SYMBOL), broker,
                        FuturesAccount(INITIAL)).run()
    return curve_metrics(eng.equity_curve, INITIAL), trade_stats(eng.fills), eng


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    if not bars:
        print("구간에 봉이 없음. cutoff 확인.")
        return
    span_h = (bars[-1].dt - bars[0].dt).total_seconds() / 3600
    print(f"\n구간: {bars[0].dt} ~ {bars[-1].dt}  ({len(bars)}봉, {span_h:.1f}시간)")
    lo = min(b.low for b in bars)
    hi = max(b.high for b in bars)
    print(f"시세: {bars[0].open:,.1f} → {bars[-1].close:,.1f}  "
          f"(구간 저 {lo:,.1f} / 고 {hi:,.1f}, 변동 {(bars[-1].close/bars[0].open-1)*100:+.1f}%)")

    print("\n=== 레버리지 스윕 (시드 5%, -30% 손절, 트레일 청산) ===")
    print(f"{'레버':>4} | {'수익률':>9} | {'MDD':>8} | {'승률':>6} | "
          f"{'손익비':>6} | {'청산':>4} | {'건수':>4}")
    print("-" * 62)
    engines = {}
    for lev in LEVERAGES:
        c, s, eng = run_one(bars, lev)
        engines[lev] = (c, s, eng)
        print(f"{lev:>4} | {c.get('총수익률',0)*100:>8.1f}% | {c.get('MDD',0)*100:>7.1f}% | "
              f"{s.get('승률',0)*100:>5.1f}% | "
              f"{(s.get('손익비(평균이익/평균손실)') or 0):>6.2f} | "
              f"{s.get('청산(LIQ)횟수',0):>4} | {s.get('청산건수',0):>4}")

    # 대표로 10배 매매내역 상세
    c, s, eng = engines[10]
    print(f"\n=== 10배 매매내역 (종류별: {s.get('종류별')}) ===")
    print(f"{'시각':>16} | {'종류':>6} | {'방향':>4} | {'가격':>10} | {'손익':>12} | 사유")
    print("-" * 90)
    for f in eng.fills:
        print(f"{f.dt:%m-%d %H:%M} | {f.kind:>6} | {f.side.value:>4} | "
              f"{f.price:>10,.1f} | {f.pnl:>12,.0f} | {f.reason}")


if __name__ == "__main__":
    main()
