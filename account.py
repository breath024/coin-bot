"""선물 계좌 — 격리 마진 + 청산 (롱/숏 양방향).

핵심:
- 증거금(margin)만 잡고 레버리지로 명목(notional)을 키운다
- 격리(isolated): 한 포지션 최대 손실 = 그 포지션 증거금
- 손실이 증거금에 근접하면 청산(liquidation)된다
- 롱: 가격 오르면 이익 / 숏: 가격 내리면 이익

단순화(기본 틀 단계): 심볼당 1포지션, 펀딩비 미반영.
  TODO: 펀딩비(8h마다 명목의 ±0.01% 내외). 보유시간 길면 누적 영향 큼.
"""
from __future__ import annotations

from core import FuturesPosition, Side


def _sign(side: Side) -> float:
    """롱 +1 / 숏 -1. 손익·청산 방향 계산에 쓴다."""
    return 1.0 if side == Side.BUY else -1.0


class FuturesAccount:
    def __init__(self, initial_balance: float, maintenance_rate: float = 0.005):
        self.initial_balance = initial_balance
        self.balance = initial_balance      # 증거금으로 잠기지 않은 가용 잔고
        self.maintenance_rate = maintenance_rate
        self.position: FuturesPosition | None = None
        self.last_price: float = 0.0

    def mark(self, price: float) -> None:
        self.last_price = price

    @staticmethod
    def liquidation_price(entry: float, leverage: float,
                          maintenance_rate: float, side: Side) -> float:
        """격리 청산가.
        롱:  entry * (1 - 1/lev + maint)  → 가격 하락 시 청산
        숏:  entry * (1 + 1/lev - maint)  → 가격 상승 시 청산"""
        if side == Side.BUY:
            return entry * (1 - 1 / leverage + maintenance_rate)
        return entry * (1 + 1 / leverage - maintenance_rate)

    def unrealized(self, price: float | None = None) -> float:
        if not self.position:
            return 0.0
        p = self.last_price if price is None else price
        return self.position.qty * (p - self.position.entry_price) * _sign(self.position.side)

    def equity(self) -> float:
        if not self.position:
            return self.balance
        u = max(self.unrealized(), -self.position.margin)   # 격리: 증거금까지만
        return self.balance + self.position.margin + u

    def open(self, pos: FuturesPosition, open_fee: float) -> None:
        self.balance -= pos.margin + open_fee
        self.position = pos

    def close(self, exit_price: float, close_fee: float) -> float:
        """포지션 청산 → 실현손익 반환(수수료 차감, 격리 손실 캡)."""
        pos = self.position
        pnl = pos.qty * (exit_price - pos.entry_price) * _sign(pos.side) - close_fee
        pnl = max(pnl, -pos.margin)
        self.balance += pos.margin + pnl
        self.position = None
        return pnl
