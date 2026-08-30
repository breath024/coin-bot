"""near-miss 진단: '들어갈 자리였는데 코드가 안 들어간' 곳을 KST로 뽑는다.

두 가지를 본다:
  A) 공식 룰(MomentumDip)이 ③'멈춤'까지 갔다가 떨군 자리 + 사유(깊이부족/고정실패)
  B) '완화판'(연속 신저점 갱신을 요구하지 않고, 시간창 안 최대낙폭=path로 측정)이면
     잡았을 자리 → 공식 룰이 통째로 놓친 후보. ※진단·비교용, 채택 아님.

시간은 open_time(ms epoch) + tz시간으로 표시 → 타임존 모호함 없음(기본 KST +9).

  python near_miss.py [csv경로] [--tz 9] [--win 6]
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import deque
from datetime import datetime, timedelta, timezone

from core import Bar
from strategy import MomentumDip

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "data", "BTCUSDT_1m.csv")


def load_bars(path, tz_hours):
    """open_time(ms, UTC)에 tz를 더해 KST 등으로 라벨링. 없으면 datetime 문자열 사용."""
    out = []
    off = timedelta(hours=tz_hours)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("open_time"):
                ms = int(row["open_time"])
                dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None) + off
            else:
                ts = (row.get("datetime") or row.get("timestamp") or "").strip().replace("T", " ")
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
            out.append(Bar("BTCUSDT", dt, float(row["open"]), float(row["high"]),
                           float(row["low"]), float(row["close"]), float(row.get("volume", 0) or 0)))
    return out


class _Acct:
    position = None


class _Brk:
    def __init__(self):
        self.entries = []      # (dt, side, reason)
    def request_entry(self, side, reason):
        self.entries.append((self._dt, side, reason))
    def request_exit(self, reason):
        pass


def main():
    ap = argparse.ArgumentParser(description="near-miss 진단 (KST)")
    ap.add_argument("path", nargs="?", default=DEFAULT)
    ap.add_argument("--tz", type=float, default=9.0, help="표시 타임존 오프셋(시간). 기본 9=KST")
    ap.add_argument("--win", type=int, default=6, help="완화판 path 측정 창(봉). 기본 6")
    args = ap.parse_args()

    bars = load_bars(args.path, args.tz)
    strat = MomentumDip("BTCUSDT")
    acct, brk = _Acct(), _Brk()
    sweep, mw = strat.sweep_pct, strat.max_wait

    near = []                  # A) ③까지 갔다 떨군 자리
    relaxed = []               # B) 완화판 후보
    win = deque(maxlen=args.win)
    prev_pb = 0
    last_relaxed_i = -99

    for i, bar in enumerate(bars):
        brk._dt = bar.dt
        strat.on_bar(bar, acct, brk)
        cur_pb, t = strat._pb, strat._htf_trend

        # --- A) 공식 룰 near-miss: 멈춤(③) 했는데 진입 안 된 경우 ---
        if 1 <= prev_pb <= mw and cur_pb == 0:
            ref, ext = strat._pb_ref, strat._pb_ext
            depth = (ref - ext) / ref if (t == 1 and ref) else ((ext - ref) / ref if ref else 0)
            flat = ((bar.high - bar.low) / bar.close <= strat.flat_pct) if bar.close else False
            if not (depth >= sweep and flat):     # 진입된 건 제외
                reason = "깊이부족" if depth < sweep else "고정실패"
                near.append((bar.dt, t, depth, prev_pb, flat, reason))

        # --- B) 완화판: 창 안 최대낙폭(연속 무시) + 신극값 멈춤 ---
        if t != 0 and len(win) == win.maxlen:
            highs = [h for h, l in win]; lows = [l for h, l in win]
            if t == 1:
                ref = max(highs); trough = min(lows)
                pdepth = (ref - trough) / ref if ref else 0
                stopped = bar.low >= bars[i - 1].low      # 더는 신저점 안 만듦
            else:
                ref = min(lows); peak = max(highs)
                pdepth = (peak - ref) / ref if ref else 0
                stopped = bar.high <= bars[i - 1].high
            if pdepth >= sweep and stopped and (i - last_relaxed_i) > args.win:
                relaxed.append((bar.dt, t, pdepth))
                last_relaxed_i = i

        win.append((bar.high, bar.low))
        prev_pb = cur_pb

    # 공식 진입과 겹치지 않는 완화판 = '통째로 놓친 자리'
    entry_times = [e[0] for e in brk.entries]
    def near_entry(dt):
        return any(abs((dt - et).total_seconds()) <= 120 for et in entry_times)
    missed = [r for r in relaxed if not near_entry(r[0])]

    span = f"{bars[0].dt:%m-%d %H:%M} ~ {bars[-1].dt:%m-%d %H:%M}" if bars else "-"
    dirs = lambda t: "롱" if t == 1 else "숏"
    print(f"\n데이터: {len(bars)}봉  ({span} · UTC{args.tz:+g} 표시)")
    print(f"기준: sweep≥{sweep*100:.2f}%, max_wait={mw}, 완화창={args.win}봉\n")

    print(f"=== 공식 진입 ({len(brk.entries)}건) ===")
    for dt, side, reason in brk.entries:
        print(f"  {dt:%m-%d %H:%M}  {side.value}  «{reason}»")

    print(f"\n=== A) ③까지 갔다 떨군 자리 ({len(near)}건, 깊은 순 top 15) ===")
    print(f"  {'시각':<12} {'방향':<3} {'스윕깊이':>7} {'봉':>3} {'고정':>4}  사유")
    for dt, t, depth, pb, flat, reason in sorted(near, key=lambda x: -x[2])[:15]:
        print(f"  {dt:%m-%d %H:%M}  {dirs(t):<3} {depth*100:>6.2f}% {pb:>3} {('O' if flat else 'X'):>4}  {reason}")

    print(f"\n=== B) 완화판이면 잡았을 '통째로 놓친' 자리 ({len(missed)}건, 깊은 순 top 20) ===")
    print("  (연속 신저점 갱신을 요구 안 하고 창 안 최대낙폭으로 측정 — 네 눈에 보이는 그 자리)")
    print(f"  {'시각':<12} {'방향':<3} {'path깊이':>7}")
    for dt, t, pdepth in sorted(missed, key=lambda x: -x[2])[:20]:
        print(f"  {dt:%m-%d %H:%M}  {dirs(t):<3} {pdepth*100:>6.2f}%")

    print(f"\n해석: B가 A·공식진입보다 훨씬 많으면 → 범인 = '연속 신저점 갱신' 정의가 빡빡함")
    print("      (지그재그 눌림을 못 봄). ※완화판은 진단용 — 바로 채택 X, 사례로 검증 후 결정.")


if __name__ == "__main__":
    main()
