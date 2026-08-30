"""실데이터 백테스트 — 진짜 바이낸스 과거 봉으로 레버리지 스윕.

합성데이터가 아니라 실제 BTCUSDT 15분봉을 받아서, 같은 매매법을
레버리지별로 돌려 비교한다. (한 번 받아서 메모리에 두고 재사용)

    실행:  python run_realtest.py

주의: 그래도 '봉' 데이터다. 100배의 ±0.2~0.5% 트리거는 봉 안에서
      어떻게 움직였는지 모르므로 100배 결과는 여전히 과신 금지.
      낮은 레버리지(5~20배) 결과가 상대적으로 더 믿을 만하다.
"""
import os

from account import FuturesAccount
from binance_feed import ListFeed, fetch_klines, klines_to_bars
from broker import FuturesBroker
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip
from trade_log import save

SYMBOL = "BTCUSDT"
INTERVAL = "1m"            # 호윤 실행단위: 1분봉 (15분은 흐름, 진입은 1분에)
BARS = 30000              # 1분봉 3만개 ≈ 21일
INITIAL = 1_000_000
LEVERAGES = [5, 10, 20, 50, 100]


def run_one(bars, lev):
    broker = FuturesBroker(leverage=lev, margin_fraction=0.05,
                           stop_on_margin=0.30,   # 고정익절 없음 → 트레일링(재량) 청산
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(ListFeed(bars), MomentumDip(SYMBOL), broker,
                        FuturesAccount(INITIAL)).run()
    c = curve_metrics(eng.equity_curve, INITIAL)
    s = trade_stats(eng.fills)
    return c, s, eng


def main():
    print(f"\n바이낸스에서 {SYMBOL} {INTERVAL} {BARS}봉 받는 중...")
    kl = fetch_klines(SYMBOL, INTERVAL, BARS)
    bars = klines_to_bars(SYMBOL, kl)
    print(f"  받음: {len(bars)}봉  ({bars[0].dt} ~ {bars[-1].dt})")

    print("\n=== 실데이터 레버리지 스윕 ===")
    print(f"{'레버':>4} | {'수익률':>9} | {'MDD':>8} | {'승률':>6} | "
          f"{'손익비':>5} | {'청산':>4} | {'건수':>4}")
    print("-" * 64)
    last_eng = None
    for lev in LEVERAGES:
        c, s, eng = run_one(bars, lev)
        last_eng = eng
        print(f"{lev:>4} | {c.get('총수익률',0)*100:>8.1f}% | {c.get('MDD',0)*100:>7.1f}% | "
              f"{s.get('승률',0)*100:>5.1f}% | "
              f"{(s.get('손익비(평균이익/평균손실)') or 0):>5.2f} | "
              f"{s.get('청산(LIQ)횟수',0):>4} | {s.get('청산건수',0):>4}")

    # 마지막(100배) 매매내역 저장 — 청산이 어디서 터지는지 보기
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "real_trades_100x.csv")
    save(last_eng.fills, out)
    print(f"\n  100배 매매내역 → {out}")
    print("  ※ 실데이터라도 봉 단위. 낮은 레버리지 결과가 더 신뢰도 높음.")


if __name__ == "__main__":
    main()
