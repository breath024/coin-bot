"""선물 모의 체결 — 진입/청산 + 격리 청산·손절·익절 (롱/숏 양방향).

- 레버리지로 명목 계산, 증거금만 차감
- 매 봉 high/low로 청산/손절/(옵션)고정익절 트리거 검사
- 재량 익절(트레일링)은 strategy가 판단해 request_exit로 넘긴다

⚠ 100배 수수료: 왕복 taker ≈ 증거금의 (2*fee*lev)배. 0.04%·100배 → 증거금 8%.
⚠ 봉 데이터 한계: 100배 트리거폭(~0.2~0.5%)이 봉보다 작을 수 있음.
   한 봉에서 손절·익절 동시 터치 시 '불리한 쪽 먼저(청산>손절>익절)'로 보수 가정.
"""
from __future__ import annotations

from account import FuturesAccount
from core import Bar, FuturesFill, FuturesPosition, Side


class FuturesBroker:
    """리스크 = 상수(강의 핵심). 거래당 잃을 시드 비율을 *직접* 정하고 거기서 포지션을 역산한다.

    - risk_per_trade: 손절 도달 시 잃을 시드 비율(예 0.01 = 1%). 설정되면 이게 1급.
      증거금 = 자산 × (risk_per_trade / stop_on_margin)  → 손절 손실 = 자산 × risk_per_trade 로 고정.
      미설정(None)이면 기존 margin_fraction(증거금 비율)로 폴백(분석 스크립트 호환).
    - rr: 손익비(reward:risk). 설정되면 익절폭 = rr × 손절폭 으로 고정익절을 건다.
      rr=1 이면 강의의 금붕어 실험(손절·익절 동시예약, 손익비 1:1) 그대로.
    """
    def __init__(self, leverage: float = 100.0, margin_fraction: float = 0.05,
                 risk_per_trade: float | None = None,
                 stop_on_margin: float = 0.30, tp_on_margin: float | None = None,
                 rr: float | None = None,
                 taker_fee: float = 0.0004, slippage: float = 0.0002):
        self.leverage = leverage
        self.margin_fraction = margin_fraction   # 폴백용 증거금 비율(risk_per_trade 미설정 시)
        self.risk_per_trade = risk_per_trade     # ★ 거래당 시드 대비 리스크(1급). None이면 폴백
        self.stop_on_margin = stop_on_margin     # 증거금의 -30%에서 손절
        self.rr = rr                             # 손익비. 설정 시 tp_on_margin 자동 유도
        if rr is not None:
            tp_on_margin = rr * stop_on_margin   # 익절폭 = 손익비 × 손절폭
        self.tp_on_margin = tp_on_margin         # 고정 익절(옵션). None이면 재량청산만
        self.taker_fee = taker_fee
        self.slippage = slippage
        self._pending_entry: tuple[Side, str] | None = None
        self._pending_exit: str | None = None

    def risk_per_trade_pct(self) -> float:
        """거래당 시드 대비 실효 리스크(손절 도달 시 잃는 비율). 정직한 리포팅용."""
        if self.risk_per_trade is not None:
            return self.risk_per_trade
        return self.margin_fraction * self.stop_on_margin

    # --- 전략이 호출 ---
    def request_entry(self, side: Side, reason: str) -> None:
        self._pending_entry = (side, reason)

    def request_exit(self, reason: str) -> None:
        self._pending_exit = reason

    # --- 엔진이 호출 ---
    def execute_pending(self, bar: Bar, account: FuturesAccount) -> list[FuturesFill]:
        """직전 봉 신호(진입/재량청산)를 '이번 봉 시가'에 체결 (룩어헤드 방지)."""
        fills: list[FuturesFill] = []

        if self._pending_exit and account.position is not None:
            price = self._exit_price(account.position.side, bar.open)
            fills.append(self._close(account, price, bar, kind="STALL", reason=self._pending_exit))
        self._pending_exit = None

        if self._pending_entry and account.position is None:
            side, reason = self._pending_entry
            price = self._entry_price(side, bar.open)
            f = self._open(account, side, price, bar, reason)
            if f:
                fills.append(f)
        self._pending_entry = None
        return fills

    def check_protective_exits(self, bar: Bar, account: FuturesAccount) -> list[FuturesFill]:
        """이번 봉 범위로 청산/손절/(고정)익절 검사. 보수적 순서."""
        pos = account.position
        if not pos:
            return []
        if pos.side == Side.BUY:
            if bar.low <= pos.liq_price:
                return [self._close(account, pos.liq_price, bar, "LIQ", "청산")]
            if bar.low <= pos.stop_price:
                return [self._close(account, pos.stop_price, bar, "STOP",
                                    f"손절 -{self.stop_on_margin*100:.0f}%")]
            if pos.tp_price is not None and bar.high >= pos.tp_price:
                return [self._close(account, pos.tp_price, bar, "TP", "고정익절")]
        else:  # SHORT — 가격 상승이 손실
            if bar.high >= pos.liq_price:
                return [self._close(account, pos.liq_price, bar, "LIQ", "청산")]
            if bar.high >= pos.stop_price:
                return [self._close(account, pos.stop_price, bar, "STOP",
                                    f"손절 -{self.stop_on_margin*100:.0f}%")]
            if pos.tp_price is not None and bar.low <= pos.tp_price:
                return [self._close(account, pos.tp_price, bar, "TP", "고정익절")]
        return []

    # --- 내부 ---
    def _entry_price(self, side: Side, open_px: float) -> float:
        return open_px * (1 + self.slippage) if side == Side.BUY else open_px * (1 - self.slippage)

    def _exit_price(self, side: Side, open_px: float) -> float:
        # 롱 청산=매도(불리하게 낮게), 숏 청산=매수(불리하게 높게)
        return open_px * (1 - self.slippage) if side == Side.BUY else open_px * (1 + self.slippage)

    def _open(self, account: FuturesAccount, side: Side, price: float, bar: Bar, reason: str):
        eq = account.equity()
        if self.risk_per_trade is not None:
            # 리스크 우선: 손절 손실(= margin × stop_on_margin)이 자산 × risk_per_trade가 되도록 역산
            margin = eq * (self.risk_per_trade / self.stop_on_margin)
        else:
            margin = eq * self.margin_fraction
        margin = min(margin, eq)        # 가용 자산 초과 금지(안전 캡)
        if margin <= 0:
            return None
        notional = margin * self.leverage
        qty = notional / price
        open_fee = notional * self.taker_fee
        liq = account.liquidation_price(price, self.leverage, account.maintenance_rate, side)
        if side == Side.BUY:
            stop = price * (1 - self.stop_on_margin / self.leverage)
            tp = price * (1 + self.tp_on_margin / self.leverage) if self.tp_on_margin else None
        else:
            stop = price * (1 + self.stop_on_margin / self.leverage)
            tp = price * (1 - self.tp_on_margin / self.leverage) if self.tp_on_margin else None
        pos = FuturesPosition(bar.symbol, side, qty, price, margin,
                              self.leverage, liq, stop, tp, bar.dt, reason)
        account.open(pos, open_fee)
        return FuturesFill(bar.symbol, side, qty, price, open_fee, bar.dt,
                           reason, pnl=0.0, kind="ENTRY")

    def _close(self, account: FuturesAccount, price: float, bar: Bar, kind: str, reason: str):
        pos = account.position
        close_fee = pos.qty * price * self.taker_fee
        # 청산 체결 방향(반대매매): 롱 청산=SELL, 숏 청산=BUY
        close_side = Side.SELL if pos.side == Side.BUY else Side.BUY
        # ★메타인지: 계획리스크(= 증거금 × 손절폭) 대비 R배수. 손절이면 -1R 부근이 정상.
        planned_risk = pos.margin * self.stop_on_margin
        pnl = account.close(price, close_fee)
        r = pnl / planned_risk if planned_risk else None
        return FuturesFill(bar.symbol, close_side, pos.qty, price, close_fee, bar.dt,
                           reason, pnl=pnl, kind=kind, r_multiple=r)
