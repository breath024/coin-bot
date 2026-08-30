"""스윕 측정 모드 비교 — consec(연속 신저점) vs path(창 내 최대낙폭).

path가 지그재그 눌림을 잡아 진입수를 늘리는지 + 품질(수익/승률/손익비)이 유지되는지.
진입 '정의'를 바꾸는 거라(매매법 핵심) 14일 다장세 데이터로 본다. 채택은 검증 통과 후.
trail 0.4% 고정, 정렬필터 OFF/ON 둘 다.

    python compare_sweep_mode.py [csv경로]
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
LEV = 10
TRAIL = 0.0040
INITIAL = 1_000_000
HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    bars = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if not row or not row[0].isdigit():
                continue
            ot = int(row[0])
            bars.append(Bar(SYMBOL, datetime.fromtimestamp(ot / 1000),
                            float(row[2]), float(row[3]), float(row[4]),
                            float(row[5]), float(row[6])))
    return bars


def run(bars, mode, align):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    strat = MomentumDip(SYMBOL, trail_pct=TRAIL, sweep_mode=mode, trend_align=align)
    eng = FuturesEngine(ListFeed(bars), strat, broker, FuturesAccount(INITIAL)).run()
    return curve_metrics(eng.equity_curve, INITIAL), trade_stats(eng.fills)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "BTCUSDT_1m_14d.csv")
    bars = load(path)
    print(f"\n데이터 {os.path.basename(path)}: {bars[0].dt:%m-%d %H:%M} ~ {bars[-1].dt:%m-%d %H:%M} "
          f"({len(bars):,}봉, 변동 {(bars[-1].close / bars[0].open - 1) * 100:+.1f}%)")
    print(f"{'모드':>7} {'정렬':>4} | {'수익률':>8} {'승률':>6} {'손익비':>6} "
          f"{'평균이익':>8} {'평균손실':>8} {'청산':>4} {'진입':>4}")
    print("-" * 74)
    for mode in ("consec", "path"):
        for align in (False, True):
            c, s = run(bars, mode, align)
            print(f"{mode:>7} {'ON' if align else 'OFF':>4} | "
                  f"{c.get('총수익률', 0) * 100:>7.1f}% {s.get('승률', 0) * 100:>5.1f}% "
                  f"{(s.get('손익비(평균이익/평균손실)') or 0):>6.2f} "
                  f"{(s.get('평균이익') or 0):>8,.0f} {(s.get('평균손실') or 0):>8,.0f} "
                  f"{s.get('청산(LIQ)횟수', 0):>4} {s.get('청산건수', 0):>4}")


if __name__ == "__main__":
    main()
