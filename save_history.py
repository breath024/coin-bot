"""과거 1분봉을 받아 기존 포맷으로 data/ 에 저장 (검증 재사용용).

기존 data/BTCUSDT_1m.csv는 건드리지 않고 별도 파일로 저장한다.
포맷: open_time,datetime,open,high,low,close,volume (run_window.load_bars 호환)

    python save_history.py [봉수=20000] [파일명]
"""
import csv
import os
import sys
from datetime import datetime

from binance_feed import fetch_klines

SYMBOL = "BTCUSDT"
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    name = sys.argv[2] if len(sys.argv) > 2 else f"{SYMBOL}_1m_14d.csv"
    path = os.path.join(HERE, "data", name)
    print(f"최근 1분봉 {total:,}개 받는 중... (잠깐 걸림)")
    kl = fetch_klines(SYMBOL, "1m", total)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "datetime", "open", "high", "low", "close", "volume"])
        for k in kl:
            ot = int(k[0])
            dt = datetime.fromtimestamp(ot / 1000).strftime("%Y-%m-%d %H:%M")
            # 바이낸스 kline: [openTime, open, high, low, close, volume, ...]
            w.writerow([ot, dt, k[1], k[2], k[3], k[4], k[5]])
    print(f"저장: {path} ({len(kl):,}봉)")
    print(f"기간: {datetime.fromtimestamp(int(kl[0][0]) / 1000):%Y-%m-%d %H:%M} ~ "
          f"{datetime.fromtimestamp(int(kl[-1][0]) / 1000):%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
