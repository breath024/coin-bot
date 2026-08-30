"""틱(체결) 데이터로 정밀 백테스트 — 바이낸스 공개 덤프(data.binance.vision) 사용.

왜 틱이냐: 100x 트리거(0.4% 스윕)가 1분봉보다 작다. 1분봉은 봉 안에서
'찔렀다 복귀'한 청산사냥을 종가/저가로 뭉개버린다. 진짜 체결 기록으로
원하는 해상도(초봉)로 재생하면, 그 스윕이 보이는지 직접 확인할 수 있다.

  python tick_backtest.py                      # 어제(UTC) 하루, 1분봉 재구성
  python tick_backtest.py 2026-06-02           # 특정 날짜
  python tick_backtest.py 2026-06-02 --secs 5  # 5초봉(고해상도)
  python tick_backtest.py 2026-06-01 2026-06-02  # 여러 날 이어붙임

표준 라이브러리만 사용(urllib·zipfile·csv). 받은 원본 zip은 data/ticks/에 캐시
→ 다시 돌릴 땐 재다운 안 함.

⚠ 해상도 주의 (--secs < 60):
  봉을 잘게 쪼개면 전략의 시간의미를 맞추려고 htf_group·max_wait를 자동 스케일하지만
  (15분 흐름·~3분 스파이크 유지), flat(고정)은 봉이 작을수록 쉽게 충족돼 ⑤가 헐거워진다.
  → 고해상도 결과의 **PnL은 신뢰하지 말 것.** 용도는 "④ 스윕깊이 통과가
     1분봉(diag_entry) 대비 늘어나는가" = 1분봉이 놓친 스윕을 잡는지 보는 것.
"""
from __future__ import annotations

import argparse
import io
import os
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from core import Bar
from diag_entry import funnel, print_funnel
from engine import FuturesEngine
from metrics import curve_metrics, trade_stats
from strategy import MomentumDip
from trade_log import save

SYMBOL = "BTCUSDT"
INITIAL = 1_000_000
LEVERAGES = [5, 10, 20, 50, 100]
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "ticks")
# USD-M 선물 일별 aggTrades 덤프
BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades/{sym}/{sym}-aggTrades-{date}.zip"


# ───────────────────────── 틱 받기/읽기 ─────────────────────────
def download_day(date: str) -> str:
    """하루치 aggTrades zip을 받아 캐시 경로 반환 (이미 있으면 그대로)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{SYMBOL}-aggTrades-{date}.zip")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"  캐시 사용: {os.path.basename(path)} ({os.path.getsize(path)/1e6:.1f}MB)")
        return path
    url = BASE.format(sym=SYMBOL, date=date)
    print(f"  다운로드: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "coinbot/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
            f.write(r.read())
    except Exception as e:
        if os.path.exists(path):
            os.remove(path)
        raise SystemExit(f"  ✗ {date} 다운로드 실패: {e}\n"
                         f"    (완료된 과거 날짜만 있음. 오늘/미래 날짜는 아직 없음)")
    print(f"  받음: {os.path.getsize(path)/1e6:.1f}MB")
    return path


def iter_ticks(zip_path: str):
    """zip 안 CSV에서 (timestamp_ms, price, qty)를 시간순으로 흘려보낸다.

    aggTrades 컬럼: agg_id, price, qty, first_id, last_id, transact_time, is_buyer_maker
    헤더 유무·시간단위(ms/us) 자동 판별.
    """
    with zipfile.ZipFile(zip_path) as z:
        name = z.namelist()[0]
        with z.open(name) as raw:
            for i, line in enumerate(io.TextIOWrapper(raw, encoding="utf-8")):
                parts = line.rstrip("\n").split(",")
                if len(parts) < 6:
                    continue
                if i == 0 and not parts[0].lstrip("-").isdigit():
                    continue                      # 헤더 행 skip
                try:
                    price = float(parts[1]); qty = float(parts[2]); t = int(parts[5])
                except ValueError:
                    continue
                if t > 1e14:                      # 마이크로초면 ms로
                    t //= 1000
                yield t, price, qty


def ticks_to_bars(zip_paths: list[str], secs: int) -> list[Bar]:
    """틱들을 secs초 봉(OHLCV)으로 묶는다. 빈 구간은 건너뛴다(거래 없는 초는 봉 없음)."""
    bars: list[Bar] = []
    cur_bucket = None
    o = h = l = c = 0.0
    v = 0.0
    width = secs * 1000
    n_ticks = 0
    for zp in zip_paths:
        for t, price, qty in iter_ticks(zp):
            n_ticks += 1
            bucket = t // width
            if bucket != cur_bucket:
                if cur_bucket is not None:
                    dt = datetime.fromtimestamp(cur_bucket * secs, tz=timezone.utc).replace(tzinfo=None)
                    bars.append(Bar(SYMBOL, dt, o, h, l, c, v))
                cur_bucket = bucket
                o = h = l = c = price
                v = qty
            else:
                h = max(h, price); l = min(l, price); c = price; v += qty
    if cur_bucket is not None:
        dt = datetime.fromtimestamp(cur_bucket * secs, tz=timezone.utc).replace(tzinfo=None)
        bars.append(Bar(SYMBOL, dt, o, h, l, c, v))
    print(f"  틱 {n_ticks:,}개 → {secs}초봉 {len(bars):,}개")
    return bars


# ───────────────────────── 전략 파라미터 스케일 ─────────────────────────
def scaled_strategy(secs: int) -> MomentumDip:
    """봉 크기가 바뀌어도 '시간 의미'를 유지: 흐름≈15분, 스파이크≈3분.

    secs=60이면 기본값(htf_group=15, max_wait=3)과 동일.
    """
    htf = max(1, round(900 / secs))    # 15분 흐름
    mw = max(1, round(180 / secs))     # ~3분 스파이크 창
    return MomentumDip(SYMBOL, htf_group=htf, max_wait=mw)


def run_one(bars, lev, secs):
    broker = FuturesBroker(leverage=lev, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(ListFeed(bars), scaled_strategy(secs), broker,
                        FuturesAccount(INITIAL)).run()
    return curve_metrics(eng.equity_curve, INITIAL), trade_stats(eng.fills), eng


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="틱 데이터 정밀 백테스트")
    ap.add_argument("dates", nargs="*", help="YYYY-MM-DD (여러 개 가능; 기본=어제 UTC)")
    ap.add_argument("--secs", type=int, default=60, help="봉 길이(초). 기본 60(=1분봉)")
    args = ap.parse_args()

    dates = args.dates
    if not dates:
        y = datetime.now(timezone.utc) - timedelta(days=1)
        dates = [y.strftime("%Y-%m-%d")]
    secs = args.secs

    print(f"\n=== 틱 백테스트 {SYMBOL}  {secs}초봉  {', '.join(dates)} ===")
    zips = [download_day(d) for d in dates]
    bars = ticks_to_bars(zips, secs)
    if len(bars) < 500:
        raise SystemExit("  봉이 너무 적음 — 날짜/네트워크 확인.")

    st = scaled_strategy(secs)
    print(f"  스케일된 파라미터: htf_group={st.htf_group}(≈15분), max_wait={st.max_wait}(≈3분)")
    if secs != 60:
        print("  ⚠ 1분봉 아님 → PnL 신뢰 말 것. ④ 스윕깊이 통과율만 1분봉과 비교.")

    # 1) 진입조건 깔때기 (diag_entry와 같은 잣대)
    print("\n" + "─" * 64)
    print_funnel(funnel(bars, scaled_strategy(secs)))

    # 2) 레버리지 스윕
    print("\n" + "─" * 64)
    print("=== 레버리지 스윕 ===")
    print(f"{'레버':>4} | {'수익률':>9} | {'MDD':>8} | {'승률':>6} | "
          f"{'손익비':>5} | {'청산':>4} | {'건수':>4}")
    print("-" * 64)
    last_eng = None
    for lev in LEVERAGES:
        c, s, eng = run_one(bars, lev, secs)
        last_eng = eng
        print(f"{lev:>4} | {c.get('총수익률',0)*100:>8.1f}% | {c.get('MDD',0)*100:>7.1f}% | "
              f"{s.get('승률',0)*100:>5.1f}% | "
              f"{(s.get('손익비(평균이익/평균손실)') or 0):>5.2f} | "
              f"{s.get('청산(LIQ)횟수',0):>4} | {s.get('청산건수',0):>4}")

    out = os.path.join(HERE, f"tick_trades_{secs}s_100x.csv")
    save(last_eng.fills, out)
    print(f"\n  100배 매매내역 → {out}")
    print("  ※ 다음: 같은 날을 --secs 60 / 10 / 5 로 돌려 ④ 통과율 비교 = 1분봉이 놓친 스윕 확인.")


if __name__ == "__main__":
    main()
