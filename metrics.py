"""성과 지표 + 매매 통계.

총수익률·MDD·샤프 같은 곡선 지표와, 호윤 검증에 핵심인 매매 통계
(승률·평균손익·청산횟수·수수료 부담)를 따로 계산한다.
"""
from __future__ import annotations

import math

# 15분봉 기준 연환산 계수 (1년 ≈ 96봉 * 365일)
PERIODS_PER_YEAR_15M = 96 * 365


def curve_metrics(equity_curve: list[tuple], initial: float,
                  periods_per_year: int = PERIODS_PER_YEAR_15M) -> dict:
    if not equity_curve:
        return {}
    eq = [e for _, e in equity_curve]
    final = eq[-1]
    total_return = final / initial - 1

    peak, mdd = -float("inf"), 0.0
    for e in eq:
        peak = max(peak, e)
        if peak > 0:
            mdd = min(mdd, e / peak - 1)

    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(periods_per_year) if std > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "최종자산": round(final, 2),
        "총수익률": total_return,
        "MDD": mdd,
        "샤프": round(sharpe, 2),
    }


def trade_stats(fills: list) -> dict:
    """청산 건 기준 매매 통계. 호윤이 제일 궁금해하던 '90% 진짜냐'를 본다."""
    exits = [f for f in fills if f.kind in ("STOP", "TP", "LIQ", "STALL")]
    n = len(exits)
    if n == 0:
        return {"청산건수": 0}
    wins = [f for f in exits if f.pnl > 0]
    losses = [f for f in exits if f.pnl <= 0]
    by_kind = {}
    for f in exits:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    avg_win = sum(f.pnl for f in wins) / len(wins) if wins else 0.0
    avg_loss = sum(f.pnl for f in losses) / len(losses) if losses else 0.0
    out = {
        "청산건수": n,
        "승률": len(wins) / n,
        "평균이익": round(avg_win, 2),
        "평균손실": round(avg_loss, 2),
        "손익비(평균이익/평균손실)": round(abs(avg_win / avg_loss), 2) if avg_loss else None,
        "총실현손익": round(sum(f.pnl for f in exits), 2),
        "종류별": by_kind,                      # STOP/TP/LIQ/STALL 각각 몇 번
        "청산(LIQ)횟수": by_kind.get("LIQ", 0),  # 0이어야 건강함
    }
    out.update(_meta_cognition(exits))
    return out


def _meta_cognition(exits: list, anomaly_at: float = -1.05) -> dict:
    """★메타인지(강의): 잃었을 때 '시스템 결함'인지 '정상 확률'인지 구분.

    각 청산의 R배수(=실현손익÷계획리스크)를 본다.
      - 기대값(R): 평균 R. >0 이면 '돈복사기'(반복하면 우상향). 시스템 자체의 엣지.
      - 이상치손실: R < -1.05 (계획보다 더 잃음 = 갭/청산/슬리피지). 이게 적으면 연속손실도
        그냥 확률(복사기 부수지 마라), 많으면 실행/꼬리리스크 = 진짜 손볼 곳.
    """
    rs = [f.r_multiple for f in exits if f.r_multiple is not None]
    if not rs:
        return {}
    anomalies = [r for r in rs if r < anomaly_at]
    return {
        "기대값(R)": round(sum(rs) / len(rs), 2),       # 거래당 평균 R = 시스템 엣지
        "최악R": round(min(rs), 2),                      # 가장 크게 벗어난 손실
        "이상치손실(R<-1)": len(anomalies),               # 계획초과 손실 건수(실행/꼬리 신호)
        "이상치비율": round(len(anomalies) / len(rs), 2),
    }
