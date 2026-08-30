"""코인 선물 백테스트 진입점 (기본 틀).

    실행:  python run_backtest.py

지금은 합성데이터로 '코드가 제대로 도는지'만 확인하는 단계다.
성과 숫자는 의미 없음 — 실제 1분/틱 CSV로 바꿔야 진짜 검증 시작.

⚠ 100배 핵심 경고 두 가지 (broker.py 상단에도 적어둠):
  1) 왕복 수수료 ≈ 증거금의 8% (fee 0.04%·100배 기준) → 익절폭이 작으면 수수료가 다 먹음
  2) 손절/익절 폭(~0.2~0.5%)이 15분봉 한 개보다 작을 수 있음 → 봉데이터론 한계
"""
from account import FuturesAccount
from broker import FuturesBroker
from engine import FuturesEngine
from feed import SyntheticFeed
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip
from trade_log import save

import os

SYMBOL = "BTCUSDT"
INITIAL = 1_000_000        # 시드 (단위 무관: USDT든 원이든)
LEVERAGE = 100
RISK_PER_TRADE = 0.01      # ★ 거래당 시드 리스크 = 1% (강의: 리스크=상수, "1%씩만 잃기")
STOP_ON_MARGIN = 0.30      # -30% 증거금 손절 (이 지점 도달 시 손실 = 시드의 RISK_PER_TRADE)
RR = 1.0                   # ★ 손익비 1:1 = 강의의 금붕어 실험(손절·익절 동시예약)
TAKER_FEE = 0.0004         # 0.04% (바이낸스 선물 taker 대략치 — 실제값으로 교체)
SLIPPAGE = 0.0002


def main():
    feed = SyntheticFeed(symbol=SYMBOL, bars=5000, start_price=50000, seed=7)
    strat = MomentumDip(SYMBOL, exit_mode="oco")   # 금붕어: 재량개입 X, 손절·익절만
    broker = FuturesBroker(leverage=LEVERAGE, risk_per_trade=RISK_PER_TRADE,
                           stop_on_margin=STOP_ON_MARGIN, rr=RR,
                           taker_fee=TAKER_FEE, slippage=SLIPPAGE)
    acct = FuturesAccount(INITIAL)

    eng = FuturesEngine(feed, strat, broker, acct).run()

    curve = curve_metrics(eng.equity_curve, INITIAL)
    stats = trade_stats(eng.fills)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crypto_trades.csv")
    save(eng.fills, out)

    rt_fee_pct = 2 * TAKER_FEE * LEVERAGE * 100   # 왕복 수수료가 증거금의 몇 %인지

    print("\n=== 코인 선물 백테스트 (합성데이터 5000봉 · 검증용) ===")
    print(f"  설정: {LEVERAGE}배 / ★리스크 {broker.risk_per_trade_pct()*100:.1f}%/거래 / "
          f"손절 -{STOP_ON_MARGIN*100:.0f}% / 손익비 {RR:.1f} (금붕어 OCO)")
    print(f"  [주의] 왕복 수수료 = 증거금의 {rt_fee_pct:.1f}%  (이게 손익비를 깎는 핵심 비용)")
    print(f"  초기시드: {INITIAL:,}")
    print("\n  [자산곡선]")
    for k, v in curve.items():
        if k in ("총수익률", "MDD"):
            print(f"    {k}: {v*100:.2f}%")
        elif k == "최종자산":
            print(f"    {k}: {v:,.0f}")
        else:
            print(f"    {k}: {v}")
    print("\n  [매매통계]  ← '내 90% 승률이 진짜냐'를 보는 곳")
    for k, v in stats.items():
        if k == "승률":
            print(f"    {k}: {v*100:.1f}%")
        else:
            print(f"    {k}: {v}")
    print(f"\n  매매내역 저장 → {out}")
    if stats.get("청산(LIQ)횟수", 0) > 0:
        print("  ※ 청산(LIQ)이 찍혔다 = 손절보다 빠른 급락에 증거금 전소된 케이스. 꼬리리스크 신호.")


if __name__ == "__main__":
    main()
