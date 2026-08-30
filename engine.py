"""백테스트/모의투자 공용 실행 루프.

데이터피드와 브로커만 교체하면 같은 전략이 백테스트·실시간에서 그대로 돈다.
핵심 순서(룩어헤드 방지):
  신호는 '이번 봉 종가' 기준으로 내고, 진입/청산 체결은 '다음 봉 시가'에 한다.
  단, 보호청산(청산/손절/익절)은 봉 내부에서 일어나므로 매 봉 high/low로 검사한다.
"""
from __future__ import annotations

from account import FuturesAccount
from broker import FuturesBroker


class FuturesEngine:
    def __init__(self, feed, strategy, broker: FuturesBroker, account: FuturesAccount):
        self.feed = feed
        self.strategy = strategy
        self.broker = broker
        self.account = account
        self.equity_curve: list[tuple] = []
        self.fills: list = []

    def run(self) -> "FuturesEngine":
        for bar in self.feed.stream():
            self.account.mark(bar.close)

            # 1) 직전 봉 신호(진입/지지부진 청산)를 이번 봉 시가에 체결
            self.fills.extend(self.broker.execute_pending(bar, self.account))

            # 2) 이번 봉 범위로 보호청산(청산 > 손절 > 익절)
            self.fills.extend(self.broker.check_protective_exits(bar, self.account))

            # 3) 전략 판단 (이번 봉 종가 기준 → 다음 봉에서 체결)
            self.strategy.on_bar(bar, self.account, self.broker)

            # 4) 자산곡선 기록
            self.equity_curve.append((bar.dt, self.account.equity()))
        return self
