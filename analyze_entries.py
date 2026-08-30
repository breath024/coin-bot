"""진입 자리 역추적 — '호윤이 들어간 자리'의 공통점을 숫자로 뽑는다.

trades_raw.txt의 각 거래 진입시각으로 바이낸스 1분봉을 다시 받아와,
진입 순간의 맥락(직전 눌림%·직전 추세·진입 후 최대유리/불리 이동)을 계산한다.
거래가 쌓일수록 "내 먹을 자리"의 공통 조건이 선명해진다 → strategy.py 진입필터로.

시간대(TZ)는 진입가격이 그 봉의 [저가,고가] 안에 드는 오프셋을 자동으로 찾는다.

    실행:  python analyze_entries.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime

from import_trades import RAW, parse

BASE = "https://fapi.binance.com/fapi/v1/klines"
MIN = 60_000
CANDIDATE_TZ = [9, 0, -4, -5, 8]   # KST, UTC, ET, ... 자동탐지 후보


def _klines(symbol, start=None, end=None, limit=None):
    url = f"{BASE}?symbol={symbol}&interval=1m"
    if start is not None:
        url += f"&startTime={start}"
    if end is not None:
        url += f"&endTime={end}"
    if limit:
        url += f"&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "coinbot/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _to_ms(dt_str, offset_h):
    dt = datetime.strptime(dt_str, "%m/%d/%Y %H:%M:%S")
    epoch = (dt - datetime(1970, 1, 1)).total_seconds()
    return int((epoch - offset_h * 3600) * 1000)


def detect_tz_and_ms(symbol, opened, entry_price):
    """진입가가 그 1분봉 범위 안에 드는 시간대 오프셋을 찾는다."""
    best = None
    for off in CANDIDATE_TZ:
        ms = _to_ms(opened, off)
        try:
            k = _klines(symbol, start=ms, limit=1)
        except Exception:
            continue
        if not k:
            continue
        lo, hi = float(k[0][3]), float(k[0][2])
        if lo <= entry_price <= hi:
            return off, ms                      # 정확히 일치
        # 근접도 백업
        mid = (lo + hi) / 2
        d = abs(mid - entry_price) / entry_price
        if best is None or d < best[2]:
            best = (off, ms, d)
    return (best[0], best[1]) if best else (None, None)


def features(symbol, t):
    off, ms = detect_tz_and_ms(symbol, t["opened"], t["entry"])
    if ms is None:
        return None
    win = _klines(symbol, start=ms - 120 * MIN, end=ms + 60 * MIN)
    # 진입 봉 인덱스
    i = next((j for j, k in enumerate(win) if k[0] <= ms < k[0] + MIN), None)
    if i is None or i < 20:
        return None
    highs = [float(k[2]) for k in win]
    lows = [float(k[3]) for k in win]
    closes = [float(k[4]) for k in win]
    entry = t["entry"]
    is_long = t["dir"] == "Long"

    prior_high = max(highs[i - 20:i])
    prior_low = min(lows[i - 20:i])
    pullback = ((prior_high - entry) / prior_high * 100) if is_long else ((entry - prior_low) / prior_low * 100)
    runup = (entry - closes[i - 60]) / closes[i - 60] * 100 if i >= 60 else float("nan")

    after_h = highs[i:i + 60]
    after_l = lows[i:i + 60]
    if is_long:
        mfe = (max(after_h) - entry) / entry * 100
        mae = (entry - min(after_l)) / entry * 100
    else:
        mfe = (entry - min(after_l)) / entry * 100
        mae = (max(after_h) - entry) / entry * 100
    return {"tz": off, "pullback": pullback, "runup": runup, "mfe": mfe, "mae": mae,
            "dir": t["dir"], "opened": t["opened"], "roi": t["roi"]}


def main():
    with open(RAW, encoding="utf-8") as f:
        trades = parse(f.read())
    rows = []
    for t in trades:
        try:
            r = features(t["symbol"], t)
        except Exception as e:
            r = None
        if r:
            rows.append(r)

    if not rows:
        print("역추적 실패 — 시간대/형식 확인 필요.")
        return

    print(f"\n=== 진입 자리 역추적 ({len(rows)}건) ===")
    print("  (pullback=직전20분 고/저점 대비 진입 눌림%, runup=직전60분 가격변화%,")
    print("   MFE=진입후 최대유리이동%, MAE=진입후 최대불리이동%)\n")
    print(f"  {'진입시각':<20}{'방향':<6}{'눌림%':>8}{'직전60분%':>10}{'MFE%':>8}{'MAE%':>8}{'TZ':>5}")
    for r in rows:
        ru = f"{r['runup']:+.2f}" if r["runup"] == r["runup"] else "  n/a"
        print(f"  {r['opened']:<20}{r['dir']:<6}{r['pullback']:>7.2f}%{ru:>10}"
              f"{r['mfe']:>7.2f}%{r['mae']:>7.2f}%{('+'+str(r['tz'])) if r['tz']>=0 else r['tz']:>5}")

    n = len(rows)
    avg = lambda key: sum(r[key] for r in rows) / n
    print("\n  [공통점 평균]")
    print(f"    진입 눌림      : {avg('pullback'):.2f}%   ← '내린다 싶으면'의 실제 크기")
    print(f"    진입 후 MFE    : {avg('mfe'):.2f}%   ← 들어가면 평균 이만큼 먹을 자리였음")
    print(f"    진입 후 MAE    : {avg('mae'):.2f}%   ← 근데 그 전에 이만큼은 출렁임(손절 견뎌야 하는 폭)")
    print(f"\n  ※ 표본 {n}건 — 거래 더 모으면 이 숫자가 진짜 진입 조건식이 된다.")


if __name__ == "__main__":
    main()
