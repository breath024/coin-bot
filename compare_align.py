"""추세정렬 필터 효과 — 역행 숏을 거르면 손익비가 사는가.

같은 구간을 (필터 OFF/ON) x (트레일 0.1%/0.4%)로 돌려 비교한다.
진입 '타이밍'(훼이크페이드 스윕)은 그대로, '역행 방향'만 옵션으로 거른다.
한 구간만 보면 과최적이므로 두 구간(전체 / 채점구간)에서 함께 본다.

    python compare_align.py
"""
import csv
import os
from datetime import datetime

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from core import Bar
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip
from run_window import DEFAULT_CUTOFF, INITIAL

SYMBOL = "BTCUSDT"
LEV = 10
HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", f"{SYMBOL}_1m.csv")


def load(cutoff=0):
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


def run(bars, align, trail):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    strat = MomentumDip(SYMBOL, trail_pct=trail, trend_align=align)
    eng = FuturesEngine(ListFeed(bars), strat, broker,
                        FuturesAccount(INITIAL)).run()
    return curve_metrics(eng.equity_curve, INITIAL), trade_stats(eng.fills)


def block(name, bars):
    span = (bars[-1].dt - bars[0].dt).total_seconds() / 3600
    print(f"\n=== {name}: {bars[0].dt:%m-%d %H:%M} ~ {bars[-1].dt:%m-%d %H:%M} "
          f"({len(bars)}봉 {span:.0f}h, 변동 {(bars[-1].close / bars[0].open - 1) * 100:+.1f}%) ===")
    print(f"{'필터':>5} {'트레일':>6} | {'수익률':>8} {'승률':>6} {'손익비':>6} "
          f"{'평균이익':>8} {'평균손실':>8} {'청산':>4} {'건수':>4}")
    print("-" * 70)
    for align in (False, True):
        for trail in (0.0010, 0.0040):
            c, s = run(bars, align, trail)
            tag = "ON" if align else "OFF"
            print(f"{tag:>5} {trail * 100:>5.2f}% | "
                  f"{c.get('총수익률', 0) * 100:>7.1f}% {s.get('승률', 0) * 100:>5.1f}% "
                  f"{(s.get('손익비(평균이익/평균손실)') or 0):>6.2f} "
                  f"{(s.get('평균이익') or 0):>8,.0f} {(s.get('평균손실') or 0):>8,.0f} "
                  f"{s.get('청산(LIQ)횟수', 0):>4} {s.get('청산건수', 0):>4}")


def main():
    block("전체구간", load(0))
    block("채점구간", load(DEFAULT_CUTOFF))


if __name__ == "__main__":
    main()
