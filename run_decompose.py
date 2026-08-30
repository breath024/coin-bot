"""본전 분해 — 이 구간 수익률이 왜 본전이 됐나 범인 가리기.

전체수익률(평가포함)을 ①실현손익만 ②미청산 평가손 ③수수료로 쪼갠다.
+ 수수료 0으로 한 번 더 돌려 '수수료가 살인자인가'를 직접 본다.
reg_ma 20(현재 코드) 고정. run_window와 동일 구간.

    python run_decompose.py [cutoff_open_time_ms]
"""
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from metrics import curve_metrics
from strategy import MomentumDip
from run_window import load_bars, DEFAULT_CUTOFF, INITIAL

LEVS = [5, 10, 20, 100]


def run(bars, lev, fee):
    broker = FuturesBroker(leverage=lev, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=fee, slippage=0.0002)
    return FuturesEngine(ListFeed(bars), MomentumDip("BTCUSDT"), broker,
                         FuturesAccount(INITIAL)).run()


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    print(f"\n구간 {bars[0].dt} ~ {bars[-1].dt} ({len(bars)}봉)  본전 분해 (reg_ma 20)")
    print(f"{'레버':>4} | {'전체%':>7} | {'실현만%':>8} | {'미청산%':>8} | {'수수료%':>8} | {'수수료0_전체%':>11}")
    print("-" * 66)
    for lev in LEVS:
        eng = run(bars, lev, 0.0004)
        c = curve_metrics(eng.equity_curve, INITIAL)
        exits = [f for f in eng.fills if f.kind in ("STOP", "TP", "LIQ", "STALL")]
        realized = sum(f.pnl for f in exits)
        fees = sum(f.fee for f in eng.fills)
        total = c["총수익률"] * INITIAL
        unreal = total - realized               # 전체 - 실현 ≈ 미청산 평가손익
        c0 = curve_metrics(run(bars, lev, 0.0).equity_curve, INITIAL)
        print(f"{lev:>4} | {c['총수익률']*100:>6.2f}% | {realized/INITIAL*100:>7.2f}% | "
              f"{unreal/INITIAL*100:>7.2f}% | {fees/INITIAL*100:>7.2f}% | "
              f"{c0['총수익률']*100:>10.2f}%")
    print("\n실현만 = 끝낸 거래 성적 / 미청산 = 마지막 열린 포지션 평가손(측정 끝점 영향)")
    print("수수료0_전체 = 수수료 빼면 수익률이 얼마나 오르나 (수수료가 범인인지)")


if __name__ == "__main__":
    main()
