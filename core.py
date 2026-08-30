"""코인 선물 봇이 주고받는 기본 데이터 타입 (외부 의존성 없음).

전략·브로커·계좌가 모두 이 타입들로만 소통한다.
거래소가 바이낸스든 바이비트든 여기 구조는 안 바뀐다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"     # 롱 진입 / (현물 의미의)매수
    SELL = "SELL"   # 청산


@dataclass
class Bar:
    """하나의 봉(15분봉 등). 데이터피드가 흘려보내는 단위."""
    symbol: str
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class FuturesPosition:
    """현재 보유 중인 선물 포지션 (격리)."""
    symbol: str
    side: Side          # 현재는 BUY(롱)만 사용 — 호윤 매매법 = 매수만
    qty: float          # 코인 수량 (소수 가능)
    entry_price: float
    margin: float       # 격리 증거금 = 이 포지션이 잃을 수 있는 최대치
    leverage: float
    liq_price: float    # 청산가
    stop_price: float   # 손절가 (-stop_on_margin 지점)
    tp_price: float | None  # 고정 익절가(옵션). None이면 재량(트레일링) 청산만 사용
    open_dt: datetime
    reason: str = ""


@dataclass
class FuturesFill:
    """진입/청산 한 건. 실현손익(pnl)과 종류(kind)를 남긴다.

    이 기록이 쌓이면 '눌림/지지부진' 같은 감(感) 파라미터를 보정하는 근거가 된다.
    """
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    dt: datetime
    reason: str
    pnl: float          # 청산 시 실현손익(수수료 차감 후). 진입은 0.
    kind: str           # ENTRY / STOP / TP / LIQ / STALL
    r_multiple: float | None = None  # ★메타인지: 실현손익 ÷ 계획리스크. 손절=-1R, 익절=+rr R.
                                     #   R<-1 = 이상치(갭/청산/슬리피지로 계획보다 더 잃음). 진입은 None.
