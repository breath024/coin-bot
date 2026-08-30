"""레버리지 스윕 — 같은 전략·같은 데이터, 레버리지만 바꿔 비교.

레버리지가 '수익 배수'가 아니라 '청산 빈도 다이얼'이라는 걸 눈으로 보기 위함.
(합성데이터라 절대수치는 의미 없음. 레버리지에 따른 '변화'만 본다.)

    실행:  python run_sweep.py
"""
from account import FuturesAccount
from broker import FuturesBroker
from engine import FuturesEngine
from feed import SyntheticFeed
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip

INITIAL = 1_000_000
LEVERAGES = [5, 10, 20, 50, 100]


def run_one(lev: int) -> dict:
    feed = SyntheticFeed(symbol="BTCUSDT", bars=5000, start_price=50000, seed=7)
    broker = FuturesBroker(leverage=lev, margin_fraction=0.05,
                           stop_on_margin=0.30, tp_on_margin=0.20,
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(feed, MomentumDip("BTCUSDT"), broker, FuturesAccount(INITIAL)).run()
    c = curve_metrics(eng.equity_curve, INITIAL)
    s = trade_stats(eng.fills)
    return {
        "lev": lev,
        "수익률": c.get("총수익률", 0) * 100,
        "MDD": c.get("MDD", 0) * 100,
        "승률": s.get("승률", 0) * 100,
        "손익비": s.get("손익비(평균이익/평균손실)") or 0,
        "청산": s.get("청산(LIQ)횟수", 0),
        "건수": s.get("청산건수", 0),
        "수수료%증거금": 2 * 0.0004 * lev * 100,
    }


def main():
    print("\n=== 레버리지 스윕 (합성데이터 · 상대비교용) ===")
    print(f"{'레버':>4} | {'수익률':>9} | {'MDD':>8} | {'승률':>6} | "
          f"{'손익비':>5} | {'청산':>4} | {'건수':>4} | {'왕복수수료(증거금%)':>16}")
    print("-" * 86)
    for lev in LEVERAGES:
        r = run_one(lev)
        print(f"{r['lev']:>4} | {r['수익률']:>8.1f}% | {r['MDD']:>7.1f}% | "
              f"{r['승률']:>5.1f}% | {r['손익비']:>5.2f} | {r['청산']:>4} | "
              f"{r['건수']:>4} | {r['수수료%증거금']:>15.1f}%")
    print("\n  → 레버리지 올릴수록: 손절/익절 폭이 노이즈에 묻혀 청산↑, 수수료부담↑.")
    print("    같은 매매법인데 '레버리지 다이얼' 하나로 생존이 갈린다.")


if __name__ == "__main__":
    main()
