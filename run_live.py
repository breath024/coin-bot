"""[라이브] 내 매매법으로 자동 모의매매 + 로그 — 켜놓는 진짜 봇.

  python run_live.py

실시간 1분봉(BinanceLiveFeed) → 내 매매법(MomentumDip) → 가상 체결/계좌(돈 안 걸림)
→ 진입/청산 생길 때마다 live_paper_log.csv 에 자동 기록.

※ 원시 시세는 언제든 다시 받을 수 있지만, '봇이 내 매매법으로 내린 라이브 결정'은
   지금 켜놔야만 쌓인다. 그래서 collector(원시가격)보다 이게 의미 있다.
※ 가상매매(페이퍼)다. 손익은 '돈'이 아니라 '데이터'. 코드매매법 성능 측정용 +
   네 실제 손매매(import_trades)와 비교용.
"""
import csv
import os

from account import FuturesAccount
from binance_feed import BinanceLiveFeed
from broker import FuturesBroker
from strategy import MomentumDip

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "live_paper_log.csv")
SYMBOL = "BTCUSDT"
INITIAL = 100_000
WARMUP = 400               # 흐름(15분*20) 감지에 충분한 워밍업 봉


class _Dummy:              # 워밍업 동안 신호 무시 (지표만 시드)
    def request_entry(self, *a):
        pass

    def request_exit(self, *a):
        pass


def log_fill(f, equity):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        if new:
            w.writerow(["시각", "종류", "방향", "가격", "수량", "수수료", "실현손익", "R배수", "자산", "사유"])
        w.writerow([f.dt.strftime("%Y-%m-%d %H:%M"), f.kind, f.side.value,
                    round(f.price, 2), round(f.qty, 6), round(f.fee, 4),
                    round(f.pnl, 2),
                    round(f.r_multiple, 2) if f.r_multiple is not None else "",
                    round(equity, 2), f.reason])


def main():
    feed = BinanceLiveFeed(symbol=SYMBOL, interval="1m", warmup=WARMUP, poll_seconds=15)
    strat = MomentumDip(SYMBOL)
    broker = FuturesBroker(leverage=100, risk_per_trade=0.015, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    acct = FuturesAccount(INITIAL)
    dummy = _Dummy()

    print(f"라이브 모의매매 — {SYMBOL} 1분봉, 내 매매법.  (Ctrl+C 중단)")
    print(f"리스크 = 거래당 시드 {broker.risk_per_trade_pct()*100:.1f}% 고정(상수)")
    print(f"워밍업 {WARMUP}봉 받는 중...")
    i = 0
    for bar in feed.stream():
        acct.mark(bar.close)
        live = i >= WARMUP
        if live:
            for f in broker.execute_pending(bar, acct):
                log_fill(f, acct.equity())
                extra = "" if f.kind == "ENTRY" else f"  실현 {f.pnl:+.2f} → 자산 {acct.equity():,.0f}"
                print(f"  [{bar.dt:%m-%d %H:%M}] {f.kind} {f.side.value} @ {f.price:,.1f}{extra}  «{f.reason}»")
            for f in broker.check_protective_exits(bar, acct):
                log_fill(f, acct.equity())
                print(f"  [{bar.dt:%m-%d %H:%M}] {f.kind} @ {f.price:,.1f}  실현 {f.pnl:+.2f} → 자산 {acct.equity():,.0f}")
        strat.on_bar(bar, acct, broker if live else dummy)
        if i == WARMUP:
            t = acct.position
            print(f"워밍업 완료. 흐름 보며 '먹을 자리' 대기 중... (현재가 {bar.close:,.1f})")
        if live and (i - WARMUP) % 5 == 0 and i != WARMUP:
            pos = acct.position
            ps = f"보유 {pos.side.value}@{pos.entry_price:,.0f}" if pos else "무포지션"
            print(f"  …{bar.dt:%H:%M} 대기중  현재가 {bar.close:,.1f}  ({ps}, 자산 {acct.equity():,.0f})")
        i += 1


if __name__ == "__main__":
    main()
