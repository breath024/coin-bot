"""엑싯 모드 A/B — 같은 실데이터·같은 리스크에서 '청산 방식'만 갈아끼워 비교.

  python compare_exit_mode.py [csv이름] [레버,레버,...]

비교 대상(진입 로직·리스크 전부 동일, 청산만 다름):
  - trail      : 기존 재량 트레일링(지지부진 청산)
  - oco rr=R   : 금붕어 OCO — 진입 시 손절·익절(손익비 R) 동시예약, 재량개입 X

리스크는 risk_per_trade=1.5%로 고정(레버 무관) → 순수하게 '엑싯 효과'만 본다.
강의 맥락: 봇의 진짜 가치 = 엑싯 규율 대행(감정 차단). 트레일이 과최적(장세빨)인지,
고정 OCO가 더 robust한지를 다장세 2만봉으로 확인하는 게 목적.
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
RISK = 0.015                 # 거래당 시드 리스크 고정(트레일·OCO 동일 조건)
HERE = os.path.dirname(os.path.abspath(__file__))


def load_bars(path):
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


def run(bars, lev, exit_mode, rr=None):
    broker = FuturesBroker(leverage=lev, risk_per_trade=RISK, stop_on_margin=0.30,
                           rr=rr, taker_fee=0.0004, slippage=0.0002)
    strat = MomentumDip(SYMBOL, exit_mode=exit_mode)
    eng = FuturesEngine(ListFeed(bars), strat, broker, FuturesAccount(INITIAL)).run()
    return curve_metrics(eng.equity_curve, INITIAL), trade_stats(eng.fills)


def row(label, c, s):
    kinds = s.get("종류별", {})
    return (f"{label:>12} | {c.get('총수익률',0)*100:>8.1f}% | {c.get('MDD',0)*100:>7.1f}% | "
            f"{s.get('승률',0)*100:>5.1f}% | {(s.get('손익비(평균이익/평균손실)') or 0):>6.2f} | "
            f"{s.get('청산(LIQ)횟수',0):>3} | {s.get('청산건수',0):>4} | {kinds}")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT_1m_14d.csv"
    levs = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [10, 100]
    path = os.path.join(HERE, "data", name)
    bars = load_bars(path)
    span_h = (bars[-1].dt - bars[0].dt).total_seconds() / 3600
    chg = (bars[-1].close / bars[0].open - 1) * 100
    print(f"\n데이터: {name}  {bars[0].dt:%m-%d %H:%M}~{bars[-1].dt:%m-%d %H:%M}  "
          f"({len(bars)}봉, {span_h:.0f}h, 변동 {chg:+.1f}%)")
    print(f"조건: 리스크 {RISK*100:.1f}%/거래 고정, 진입로직 동일, 청산만 비교\n")

    for lev in levs:
        print(f"=== {lev}배 ===")
        print(f"{'엑싯':>12} | {'수익률':>9} | {'MDD':>8} | {'승률':>6} | "
              f"{'손익비':>6} | {'LIQ':>3} | {'건수':>4} | 종류별")
        print("-" * 96)
        c, s = run(bars, lev, "trail")
        print(row("trail", c, s))
        for rr in (1.0, 1.5, 2.0, 3.0):
            c, s = run(bars, lev, "oco", rr=rr)
            print(row(f"oco rr={rr}", c, s))
        print()


if __name__ == "__main__":
    main()
