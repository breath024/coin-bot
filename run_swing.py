"""방향판정 ma vs swing 비교 — 채점에서 나온 'swing 구조' 가설 검증.

같은 구간(run_window 동일), 10x 고정으로 기존 5h-MA 방식과
새 swing(저점높아짐/고점낮아짐) 방식을 나란히 돌려:
  - 수익률·롱/숏 분포·6/4 vs 6/5 손익·미청산
  - 각 방식의 진입 목록(시각·방향·손익)을 찍어 채점 10자리와 대조
swing이 #5·#7·#10(호윤이 '롱쳤어야/위험'이라 본 자리)에서 숏을 안 치고
롱으로 돌거나 스킵하면 = 가설 적중.

    python run_swing.py [cutoff_open_time_ms]
"""
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip
from run_window import load_bars, DEFAULT_CUTOFF, INITIAL
from run_regime_sweep import pair_trades

LEV = 10


def run(bars, mode):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    return FuturesEngine(ListFeed(bars), MomentumDip("BTCUSDT", trend_mode=mode),
                         broker, FuturesAccount(INITIAL)).run()


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    print(f"\n구간 {bars[0].dt} ~ {bars[-1].dt} ({len(bars)}봉)  10x  ma vs swing")
    print(f"{'방식':>5} | {'수익률':>7} | {'건수':>4} | {'롱':>3} | {'숏':>3} | {'승률':>6} | "
          f"{'6/4손익':>9} | {'6/5손익':>9} | {'미청산':>5}")
    print("-" * 80)
    saved = {}
    for mode in ["ma", "swing"]:
        eng = run(bars, mode)
        c = curve_metrics(eng.equity_curve, INITIAL)
        s = trade_stats(eng.fills)
        trades, op = pair_trades(eng.fills)
        saved[mode] = (trades, op)
        longs = sum(1 for t in trades if t[1] == "BUY")
        shorts = sum(1 for t in trades if t[1] == "SELL")
        d4 = sum(t[2] for t in trades if t[0].day == 4)
        d5 = sum(t[2] for t in trades if t[0].day == 5)
        print(f"{mode:>5} | {c['총수익률']*100:>6.2f}% | {s.get('청산건수',0):>4} | "
              f"{longs:>3} | {shorts:>3} | {s.get('승률',0)*100:>5.1f}% | "
              f"{d4:>9,.0f} | {d5:>9,.0f} | {'있음' if op else '-':>5}")

    for mode in ["ma", "swing"]:
        trades, op = saved[mode]
        print(f"\n[{mode}] 진입 {len(trades)}건:")
        for t in trades:
            print(f"  {t[0]:%m/%d %H:%M}  {'롱' if t[1]=='BUY' else '숏'}  {t[2]:>+9,.0f}")
        if op:
            print(f"  {op.dt:%m/%d %H:%M}  {'롱' if op.side.value=='BUY' else '숏'}  (미청산)")


if __name__ == "__main__":
    main()
