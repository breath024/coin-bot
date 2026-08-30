"""추세 게이트 속도 스윕 — 가설 검증용.

가설: 봇이 6/5(하락 힘 빠진 횡보)에 계속 숏 친 건 추세판단이 느려서다.
현재 코드 regime_ma=20 = 15분봉 20개 = 5시간 MA. 호윤은 15분 구조로 훨씬 빠르게 봄.
→ regime_ma를 줄여(추세 빠르게) 6/5 진입이 줄어드나 본다. 단 너무 줄이면 6/4도 망가짐(과최적 경계).

같은 구간(run_window와 동일 cutoff), 레버 10x 고정으로 비교.

    python run_regime_sweep.py [cutoff_open_time_ms]
"""
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip
from run_window import load_bars, DEFAULT_CUTOFF, INITIAL

LEV = 10
REGIMES = [20, 12, 8, 6, 4, 3]   # 15분봉 개수 -> 5h, 3h, 2h, 1.5h, 1h, 45m


def pair_trades(fills):
    """ENTRY와 다음 EXIT를 묶어 (진입dt, 방향, 손익). 한 번에 한 포지션이라 순차 페어링."""
    trades, entry = [], None
    for f in fills:
        if f.kind == "ENTRY":
            entry = f
        elif entry is not None:
            trades.append((entry.dt, entry.side.value, f.pnl))
            entry = None
    return trades, entry        # entry != None이면 마지막 진입 미청산


def run(bars, rma):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    return FuturesEngine(ListFeed(bars), MomentumDip("BTCUSDT", regime_ma=rma),
                         broker, FuturesAccount(INITIAL)).run()


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    print(f"\n구간 {bars[0].dt} ~ {bars[-1].dt}  ({len(bars)}봉)  레버 {LEV}x 고정")
    print(f"{'reg_ma':>6} | {'~시간':>5} | {'수익률':>7} | {'건수':>4} | {'승률':>6} | "
          f"{'청산':>4} | {'6/4진입':>6} | {'6/5진입':>6} | {'6/4손익':>9} | {'6/5손익':>9} | {'미청산':>5}")
    print("-" * 100)
    for rma in REGIMES:
        eng = run(bars, rma)
        c = curve_metrics(eng.equity_curve, INITIAL)
        s = trade_stats(eng.fills)
        trades, open_entry = pair_trades(eng.fills)
        d4 = [t for t in trades if t[0].day == 4]
        d5 = [t for t in trades if t[0].day == 5]
        print(f"{rma:>6} | {rma*15/60:>4.1f}h | {c['총수익률']*100:>6.1f}% | "
              f"{s.get('청산건수',0):>4} | {s.get('승률',0)*100:>5.1f}% | "
              f"{s.get('청산(LIQ)횟수',0):>4} | {len(d4):>6} | {len(d5):>6} | "
              f"{sum(t[2] for t in d4):>9,.0f} | {sum(t[2] for t in d5):>9,.0f} | "
              f"{'있음' if open_entry else '-':>5}")
    print("\n(현재 코드 = reg_ma 20 = 5.0h. 위로 갈수록 추세를 느리게, 아래로 갈수록 빠르게 봄.)")


if __name__ == "__main__":
    main()
