"""진입 자리 해부 — '길게 갈 자리 vs 짧게 끝날 자리'를 가르는 신호 찾기.

0.1% 기준 진입(10x, 채점과 동일)을 뽑아, 각 진입의 (1)직전 변동성 (2)직전 추세강도
(3)진입 후 60봉 MFE(최대 유리 이동)/MAE(최대 불리)/MFE 도달시간 (4)스윕깊이를 잰다.
#1(길게 정답) vs #2·#8(짧게 정답)이 진입 시점에 뭐가 달랐나 본다.

    python anatomy_entries.py [cutoff_ms]
"""
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from strategy import MomentumDip
from run_window import load_bars, DEFAULT_CUTOFF, INITIAL

SYMBOL = "BTCUSDT"
LEV = 10   # 채점과 동일


def entries(bars):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(ListFeed(bars), MomentumDip(SYMBOL, trail_pct=0.0010),
                        broker, FuturesAccount(INITIAL)).run()
    return [(f.dt, f.side.value, f.price, f.reason)
            for f in eng.fills if f.kind == "ENTRY"]


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    idx = {b.dt: i for i, b in enumerate(bars)}
    ents = entries(bars)

    print(f"\n구간 {bars[0].dt:%m-%d %H:%M} ~ {bars[-1].dt:%m-%d %H:%M}, {LEV}x")
    print("직전변동성=진입 전 15봉 평균(고-저)/종가  ·  직전추세=진입 전 30봉 종가변화")
    print("MFE=진입 후 60봉 최대 유리이동  ·  MFE도달=거기까지 걸린 분  ·  MAE=최대 불리이동\n")
    hdr = (f"{'#':>2} {'진입시각':>11} {'방':>2} {'진입가':>8} | "
           f"{'직전변동성':>9} {'직전추세%':>9} | "
           f"{'MFE%':>6} {'MFE도달':>7} {'MAE%':>6} | {'스윕깊이':>10}")
    print(hdr)
    print("-" * len(hdr))
    for n, (t, side, ep, reason) in enumerate(ents, 1):
        i = idx[t]
        pre = bars[max(0, i - 15):i]
        vol = (sum((b.high - b.low) / b.close for b in pre) / len(pre) * 100) if pre else 0
        j = max(0, i - 30)
        trend = (bars[i].close / bars[j].close - 1) * 100
        post = bars[i + 1:i + 61]
        if not post:
            continue
        if side == "SELL":
            favs = [(ep - b.low) / ep * 100 for b in post]
            mae = max((b.high - ep) / ep * 100 for b in post)
        else:
            favs = [(b.high - ep) / ep * 100 for b in post]
            mae = max((ep - b.low) / ep * 100 for b in post)
        mfe = max(favs)
        ttm = favs.index(mfe) + 1
        sw = reason.split("스윕 ")[1].rstrip(")") if "스윕" in reason else ""
        print(f"{n:>2} {t:%m-%d %H:%M} {side[:1]:>2} {ep:>8,.0f} | "
              f"{vol:>8.3f}% {trend:>+8.2f}% | "
              f"{mfe:>5.2f}% {str(ttm) + 'm':>7} {mae:>5.2f}% | {sw:>10}")


if __name__ == "__main__":
    main()
