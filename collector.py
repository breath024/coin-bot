"""[1단계] 상시 데이터 수집기 — 켜놓으면 1분봉을 계속 쌓는다.

  python collector.py        # 상시 수집 시작 (Ctrl+C로 중단). 켜둘수록 데이터 쌓임.
  python collector.py once   # 지금까지 빈 구간만 채우고 종료 (테스트/크론용)

- data/BTCUSDT_1m.csv 에 '마감된' 봉만 누적 (형성 중 봉 제외)
- 재시작하면 꺼져있던 동안의 빈 구간을 자동 백필
- 이게 최적화/학습의 '연료'. 수집부터 깔려야 나머지가 의미 있다.
"""
import csv
import os
import sys
import time
from datetime import datetime

from binance_feed import BASE, _get, fetch_klines

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
POLL = 20
HERE = os.path.dirname(os.path.abspath(__file__))
DATADIR = os.path.join(HERE, "data")
PATH = os.path.join(DATADIR, f"{SYMBOL}_{INTERVAL}.csv")


def last_open_time():
    if not os.path.exists(PATH):
        return None
    last = None
    with open(PATH, encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and row[0].isdigit():
                last = int(row[0])
    return last


def append(rows):
    if not rows:
        return
    new = not os.path.exists(PATH)
    os.makedirs(DATADIR, exist_ok=True)
    with open(PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["open_time", "datetime", "open", "high", "low", "close", "volume"])
        for k in rows:
            w.writerow([k[0], datetime.fromtimestamp(k[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                        k[1], k[2], k[3], k[4], k[5]])


def backfill(since):
    """since(open_time ms) 이후의 봉을 1500개씩 끊어 받아온다."""
    out, start = [], since + 1
    while True:
        kl = _get(f"{BASE}?symbol={SYMBOL}&interval={INTERVAL}&startTime={start}&limit=1500")
        if not kl:
            break
        out += kl
        if len(kl) < 1500:
            break
        start = kl[-1][0] + 1
        time.sleep(0.25)
    return out


def catch_up():
    lot = last_open_time()
    kl = fetch_klines(SYMBOL, INTERVAL, 1500) if lot is None else backfill(lot)
    if kl:
        append(kl[:-1])          # 마지막(형성 중) 봉 제외
    return last_open_time()


def main():
    os.makedirs(DATADIR, exist_ok=True)
    once = len(sys.argv) > 1 and sys.argv[1] == "once"
    lot = catch_up()
    n = (sum(1 for _ in open(PATH, encoding="utf-8")) - 1) if os.path.exists(PATH) else 0
    print(f"데이터 {n:,}봉 보유.  최신 {datetime.fromtimestamp(lot/1000):%Y-%m-%d %H:%M}  → {PATH}")
    if once:
        return
    print("상시 수집 시작 (Ctrl+C 중단)...")
    while True:
        try:
            kl = _get(f"{BASE}?symbol={SYMBOL}&interval={INTERVAL}&limit=5")
        except Exception:
            time.sleep(POLL)
            continue
        closed = [k for k in kl[:-1] if k[0] > lot]
        if closed:
            append(closed)
            lot = closed[-1][0]
            print(f"  +{len(closed)}봉  최신 {datetime.fromtimestamp(lot/1000):%H:%M} 종가 {closed[-1][4]}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
