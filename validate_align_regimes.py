"""추세정렬 필터 다장세 검증 — 하락장 한 토막이 아닌 여러 장세에서 ON vs OFF.

최근 1분봉 N개를 받아 윈도우로 쪼개고, 각 윈도우의 장세(상승/횡보/하락)와 함께
필터 OFF/ON 수익을 비교한다. 장세별로 집계해 "필터가 장세 안 가리고 이기는가"를 본다.
기존 data/BTCUSDT_1m.csv는 건드리지 않고 새로 받아 메모리에서만 검증.

    python validate_align_regimes.py [봉수=20000] [윈도우봉=1440]
"""
import sys

from account import FuturesAccount
from binance_feed import fetch_klines, klines_to_bars, ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip

SYMBOL = "BTCUSDT"
LEV = 10
TRAIL = 0.0040
INITIAL = 1_000_000


def run(bars, align):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    strat = MomentumDip(SYMBOL, trail_pct=TRAIL, trend_align=align)
    eng = FuturesEngine(ListFeed(bars), strat, broker, FuturesAccount(INITIAL)).run()
    c = curve_metrics(eng.equity_curve, INITIAL)
    s = trade_stats(eng.fills)
    return c.get("총수익률", 0) * 100, s.get("청산건수", 0)


def regime(bars):
    chg = (bars[-1].close / bars[0].open - 1) * 100
    return ("상승" if chg > 1 else "하락" if chg < -1 else "횡보"), chg


def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    win = int(sys.argv[2]) if len(sys.argv) > 2 else 1440   # 1일
    print(f"최근 1분봉 {total:,}개 받는 중... (페이지네이션, 잠깐 걸림)")
    bars = klines_to_bars(SYMBOL, fetch_klines(SYMBOL, "1m", total))
    span_d = (bars[-1].dt - bars[0].dt).total_seconds() / 86400
    print(f"받음: {bars[0].dt:%m-%d %H:%M} ~ {bars[-1].dt:%m-%d %H:%M} "
          f"({len(bars):,}봉, {span_d:.1f}일)\n")

    print(f"{'윈도우(시작)':>13} {'장세':>4} {'변동%':>7} | "
          f"{'OFF수익':>8} {'건':>3} | {'ON수익':>8} {'건':>3} | {'ON-OFF':>7}")
    print("-" * 74)
    agg = {}
    diffs = []
    for i in range(0, len(bars) - win + 1, win):
        w = bars[i:i + win]
        reg, chg = regime(w)
        off_r, off_n = run(w, False)
        on_r, on_n = run(w, True)
        d = on_r - off_r
        diffs.append(d)
        a = agg.setdefault(reg, [0.0, 0.0, 0])
        a[0] += off_r
        a[1] += on_r
        a[2] += 1
        print(f"{w[0].dt:%m-%d %H:%M} {reg:>4} {chg:>+6.1f}% | "
              f"{off_r:>+7.1f}% {off_n:>3} | {on_r:>+7.1f}% {on_n:>3} | {d:>+6.1f}%")

    print("-" * 74)
    print("\n=== 장세별 집계 (윈도우 평균 수익) ===")
    for reg, (o, on, n) in sorted(agg.items()):
        print(f"  {reg}: {n}개 윈도우 | OFF평균 {o / n:+.2f}% | ON평균 {on / n:+.2f}% | "
              f"필터효과 {(on - o) / n:+.2f}%")
    better = sum(1 for d in diffs if d > 1e-9)
    worse = sum(1 for d in diffs if d < -1e-9)
    print(f"\n필터 ON이 더 나은 윈도우: {better} / 더 나쁜: {worse} / "
          f"동률: {len(diffs) - better - worse}  (총 {len(diffs)}개)")


if __name__ == "__main__":
    main()
