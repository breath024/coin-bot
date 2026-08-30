"""ML 실험용 라벨 데이터 채굴 — MomentumDip 신호를 '동시다발도 다 기록'(포지션 점유 무관)해서
표본을 최대한 늘리고, 각 신호에 실제 트레일청산 규칙으로 시뮬레이션한 결과(승/패·pnl·R)를 라벨로 붙인다.

기존 run_window/compare_* 는 계좌가 포지션 1개뿐이라 겹치는 신호를 건너뛴다(표본 손실).
여기서는 신호마다 독립 가상계좌로 '그때 그 신호만 잡았으면'을 시뮬레이션한다(near_miss.py 아이디어 확장).

    python ml_dataset.py [csv이름] [출력csv=data/ml_signals.csv]
"""
import csv
import os
import re
import sys
from datetime import datetime

import numpy as np

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from core import Bar, Side
from engine import FuturesEngine
from strategy import MomentumDip

SYMBOL = "BTCUSDT"
LEV = 10
INITIAL = 1_000_000
MAX_HORIZON = 1440   # 라벨 확정까지 최대로 볼 봉수(1일). 이 안에 안 닫히면 표본 제외.
HERE = os.path.dirname(os.path.abspath(__file__))
REASON_RE = re.compile(r"스윕 ([\d.]+)%,(\d+)봉")


def load_bars(path):
    bars = []
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or not row[0].isdigit():
                continue
            ot = int(row[0])
            bars.append(Bar(SYMBOL, datetime.fromtimestamp(ot / 1000),
                            float(row[2]), float(row[3]), float(row[4]),
                            float(row[5]), float(row[6])))
    return bars


class _FakeBroker:
    """스캔 전용 — 신호만 받아 적고 아무 상태도 바꾸지 않는다(포지션 점유 흉내 안 냄)."""
    def __init__(self):
        self.pending = None

    def request_entry(self, side, reason):
        self.pending = (side, reason)

    def request_exit(self, reason):
        pass


class _FakeAccount:
    position = None   # 항상 무포지션으로 보여 전략이 매 봉 진입 재평가하게 만든다


def scan_signals(bars):
    """기본 파라미터(swing·consec·trail) MomentumDip의 전체 진입신호(반사실 포함) 스캔."""
    strat = MomentumDip(SYMBOL)
    fb, fa = _FakeBroker(), _FakeAccount()
    out = []
    for i, bar in enumerate(bars):
        fb.pending = None
        strat.on_bar(bar, fa, fb)
        if fb.pending:
            side, reason = fb.pending
            out.append((i, side, reason))
    return out


class _ForcedTrade:
    """신호 하나를 강제 진입시키고 트레일 청산 규칙만 관리(재진입 없음) — 라벨용 카운터팩추얼."""
    def __init__(self, side, trail_pct=0.0010):
        self.side = side
        self.trail_pct = trail_pct
        self._entered = False
        self._best = None

    def on_bar(self, bar, account, broker):
        if account.position is None:
            if not self._entered:
                self._entered = True
                broker.request_entry(self.side, "ML라벨용 강제진입")
                self._best = bar.high if self.side == Side.BUY else bar.low
            return
        pos = account.position
        if pos.side == Side.BUY:
            self._best = max(self._best, bar.high)
            retrace = (self._best - bar.close) / self._best
            in_profit = bar.close > pos.entry_price
        else:
            self._best = min(self._best, bar.low)
            retrace = (bar.close - self._best) / self._best
            in_profit = bar.close < pos.entry_price
        if in_profit and retrace >= self.trail_pct:
            broker.request_exit("ML라벨용 트레일청산")


def simulate(bars_slice, side):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    strat = _ForcedTrade(side)
    eng = FuturesEngine(ListFeed(bars_slice), strat, broker, FuturesAccount(INITIAL)).run()
    exits = [f for f in eng.fills if f.kind != "ENTRY"]
    if not exits:
        return None   # 지평 안에 못 닫힘 → 라벨 미확정, 표본 제외
    x = exits[0]
    entry_fill = eng.fills[0]
    hold_min = (x.dt - entry_fill.dt).total_seconds() / 60
    return x.pnl, x.r_multiple, x.kind, hold_min


# --- 피처 (신호 시점까지의 정보만 사용, 미래 누출 금지) ---
def build_features(bars):
    n = len(bars)
    closes = np.array([b.close for b in bars])
    highs = np.array([b.high for b in bars])
    lows = np.array([b.low for b in bars])
    vols = np.array([b.volume for b in bars])
    rets = np.diff(closes) / closes[:-1]
    rets = np.concatenate([[0.0], rets])
    return closes, highs, lows, vols, rets


def feat_at(i, closes, highs, lows, vols, rets, side):
    def safe_std(a):
        return float(np.std(a)) if len(a) > 1 else 0.0

    w30 = rets[max(0, i - 30):i + 1]
    vol30 = safe_std(w30) * 100                       # 최근 30분 변동성(%)
    mom30 = (closes[i] - closes[max(0, i - 30)]) / closes[max(0, i - 30)] * 100 if i >= 1 else 0.0
    lo, hi = max(0, i - 240), i + 1
    rng_lo, rng_hi = float(np.min(lows[lo:hi])), float(np.max(highs[lo:hi]))
    rng = rng_hi - rng_lo
    range_pos = (closes[i] - rng_lo) / rng if rng > 0 else 0.5   # 240분 범위 내 위치(0바닥~1천장)
    vw = vols[max(0, i - 60):i + 1]
    vol_z = (vols[i] - float(np.mean(vw))) / float(np.std(vw)) if float(np.std(vw)) > 0 else 0.0
    return {
        "vol30": vol30,
        "mom30": mom30,
        "range_pos": range_pos,
        "vol_z": vol_z,
        "is_long": 1 if side == Side.BUY else 0,
    }


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT_1m.csv"
    out_name = sys.argv[2] if len(sys.argv) > 2 else "ml_signals.csv"
    bars = load_bars(os.path.join(HERE, "data", name))
    print(f"데이터: {name}  {bars[0].dt:%m-%d %H:%M}~{bars[-1].dt:%m-%d %H:%M} ({len(bars):,}봉)")

    print("신호 스캔 중(포지션 점유 무관, 반사실 포함)...")
    sigs = scan_signals(bars)
    print(f"신호 {len(sigs)}건 발견. 각 신호 카운터팩추얼 시뮬레이션(트레일 규칙, 지평 {MAX_HORIZON}분)...")

    closes, highs, lows, vols, rets = build_features(bars)
    rows = []
    skipped = 0
    for i, side, reason in sigs:
        m = REASON_RE.search(reason)
        depth = float(m.group(1)) if m else None
        waited = int(m.group(2)) if m else None
        horizon = bars[i + 1: i + 1 + MAX_HORIZON]
        if len(horizon) < 2:
            skipped += 1
            continue
        res = simulate(horizon, side)
        if res is None:
            skipped += 1
            continue
        pnl, r, kind, hold_min = res
        f = feat_at(i, closes, highs, lows, vols, rets, side)
        rows.append({
            "idx": i, "dt": bars[i].dt.isoformat(), "side": side.value,
            "depth": depth, "waited": waited, "hour": bars[i].dt.hour,
            **f,
            "pnl": round(pnl, 1), "r_multiple": round(r, 3) if r is not None else None,
            "kind": kind, "hold_min": round(hold_min, 1), "win": 1 if pnl > 0 else 0,
        })

    print(f"라벨 확정 {len(rows)}건 (지평 안에 못 닫혀 제외 {skipped}건)")
    win_rate = sum(r["win"] for r in rows) / len(rows) if rows else 0
    print(f"전체 승률(카운터팩추얼): {win_rate*100:.1f}%")

    out_path = os.path.join(HERE, "data", out_name)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
