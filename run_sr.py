"""S/R 레벨 필터 검증 — 천장권 롱·바닥권 숏 거부가 6/9형 손실을 거르나, 대가는?

같은 CSV 전체(cutoff 0), swing 기본, 10x 고정으로 sr_filter OFF vs ON(sr_room 스윕).
각 설정에서 ①수익률·건수·롱숏·승률 ②6/9 07:03 롱(-15,400 재앙)을 걸렀는지 출력.
핵심 질문 = "6/9는 거르되 멀쩡한 거래는 안 죽이나"(과최적 경계).

    python run_sr.py [cutoff_open_time_ms]   # 생략시 0 = CSV 전체
"""
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip
from run_window import load_bars, INITIAL
from run_regime_sweep import pair_trades

LEV = 10
ROOMS = [0.10, 0.15, 0.20, 0.25, 0.30]


def run(bars, sr_filter, sr_room, sr_lb=240):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    strat = MomentumDip("BTCUSDT", sr_filter=sr_filter, sr_room=sr_room,
                        sr_lookback=sr_lb)  # swing 기본
    eng = FuturesEngine(ListFeed(bars), strat, broker, FuturesAccount(INITIAL)).run()
    return eng


def find_0609_long(trades):
    """6/9 롱(재앙 트레이드) 잡힘 여부 + 손익."""
    for t in trades:
        if t[0].month == 6 and t[0].day == 9 and t[1] == "BUY":
            return t[2]
    return None


def summarize(label, eng):
    c = curve_metrics(eng.equity_curve, INITIAL)
    s = trade_stats(eng.fills)
    trades, op = pair_trades(eng.fills)
    longs = sum(1 for t in trades if t[1] == "BUY")
    shorts = sum(1 for t in trades if t[1] == "SELL")
    d609 = find_0609_long(trades)
    tag = f"들어감({d609:+,.0f})" if d609 is not None else "거름 ✓"
    print(f"{label:>14} | {c['총수익률']*100:>6.2f}% | {s.get('청산건수',0):>4} | "
          f"{longs:>3} | {shorts:>3} | {s.get('승률',0)*100:>5.1f}% | "
          f"{(s.get('손익비(평균이익/평균손실)') or 0):>5.2f} | {tag}")
    return trades, op


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    bars = load_bars(cutoff)
    print(f"\n구간 {bars[0].dt} ~ {bars[-1].dt} ({len(bars)}봉)  10x swing  S/R 필터 검증")
    print(f"{'설정':>14} | {'수익률':>7} | {'건수':>4} | {'롱':>3} | {'숏':>3} | "
          f"{'승률':>6} | {'손익비':>5} | 6/9 롱")
    print("-" * 80)
    base_trades, _ = summarize("OFF(기준)", run(bars, False, 0.15))
    # 룩백 길이별 (6/9가 '주간 천장권 롱'으로 잡히려면 룩백이 길어야)
    for lb, hrs in [(240, 4), (720, 12), (1440, 24), (2880, 48)]:
        print(f"-- 룩백 {lb}봉({hrs}h) --")
        for r in [0.15, 0.20, 0.25]:
            summarize(f"lb{hrs}h room={r:.2f}", run(bars, True, r, lb))

    # 기준 진입목록(거른 자리 대조용)
    print("\n[OFF] 진입 전체:")
    for t in base_trades:
        print(f"  {t[0]:%m/%d %H:%M}  {'롱' if t[1]=='BUY' else '숏'}  {t[2]:>+9,.0f}")


if __name__ == "__main__":
    main()
