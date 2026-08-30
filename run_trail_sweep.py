"""트레일 익절 스윕 — trail_pct만 바꿔 손익비가 오르는지 본다.

매매법(진입·방향·스윕깊이)은 한 글자도 안 건드린다. 청산 트레일(승자 끊는 폭)만
0.10%부터 1.00%까지 넓혀가며 같은 데이터로 비교한다.

    python run_trail_sweep.py

근거: 실거래 손익비 0.58 = 승자를 0.1% 되돌림에 너무 일찍 끊음(HANDOFF 5-1/5-3).
가설: 트레일을 넓히면 평균이익↑ → 손익비↑ (대신 승률은 좀 내려갈 수 있음 = 트레이드오프).
※ data/BTCUSDT_1m.csv는 하락 편향 구간이라 '절대수익'이 아니라 '손익비 방향성'만 본다.
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

SYMBOL = "BTCUSDT"
INITIAL = 1_000_000
HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", f"{SYMBOL}_1m.csv")
TRAILS = [0.0010, 0.0015, 0.0020, 0.0030, 0.0040, 0.0050, 0.0070, 0.0100]


def load_all():
    bars = []
    with open(PATH, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or not row[0].isdigit():
                continue
            ot = int(row[0])
            bars.append(Bar(SYMBOL, datetime.fromtimestamp(ot / 1000),
                            float(row[2]), float(row[3]), float(row[4]),
                            float(row[5]), float(row[6])))
    return bars


def run_one(bars, lev, trail):
    broker = FuturesBroker(leverage=lev, margin_fraction=0.05,
                           stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    strat = MomentumDip(SYMBOL, trail_pct=trail)   # ← 트레일만 교체, 나머지 기본값
    eng = FuturesEngine(ListFeed(bars), strat, broker,
                        FuturesAccount(INITIAL)).run()
    return curve_metrics(eng.equity_curve, INITIAL), trade_stats(eng.fills)


def sweep(bars, lev):
    print(f"\n=== 레버 {lev}x — 트레일 익절 스윕 (진입로직 고정, 익절폭만 변경) ===")
    print(f"{'트레일':>6} | {'수익률':>9} | {'승률':>6} | {'손익비':>6} | "
          f"{'평균이익':>9} | {'평균손실':>9} | {'청산':>4} | {'건수':>4}")
    print("-" * 78)
    for t in TRAILS:
        c, s = run_one(bars, lev, t)
        mark = "  ← 현재" if abs(t - 0.0010) < 1e-9 else ""
        print(f"{t * 100:>5.2f}% | {c.get('총수익률', 0) * 100:>8.1f}% | "
              f"{s.get('승률', 0) * 100:>5.1f}% | "
              f"{(s.get('손익비(평균이익/평균손실)') or 0):>6.2f} | "
              f"{(s.get('평균이익') or 0):>9,.0f} | {(s.get('평균손실') or 0):>9,.0f} | "
              f"{s.get('청산(LIQ)횟수', 0):>4} | {s.get('청산건수', 0):>4}{mark}")


def main():
    bars = load_all()
    span_h = (bars[-1].dt - bars[0].dt).total_seconds() / 3600
    print(f"\n구간: {bars[0].dt} ~ {bars[-1].dt}  "
          f"({len(bars)}봉, {span_h:.1f}시간, "
          f"변동 {(bars[-1].close / bars[0].open - 1) * 100:+.1f}%)")
    sweep(bars, 10)    # 손익비 깔끔하게 (청산 거의 없음)
    sweep(bars, 100)   # 호윤 실전 레버 (수수료·청산 노이즈 포함)


if __name__ == "__main__":
    main()
