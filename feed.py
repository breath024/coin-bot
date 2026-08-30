"""데이터 피드.

- CsvFeed:        실제 CSV(거래소 다운로드)를 Bar로 변환
- SyntheticFeed:  거래소 키 없이 바로 돌려보기 위한 가짜 15분봉 (추세+노이즈)

CSV 컬럼: timestamp,open,high,low,close,volume
  timestamp = ISO8601 (예: 2024-01-01T00:00:00) 또는 'YYYY-MM-DD HH:MM'
"""
from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta

from core import Bar


class CsvFeed:
    def __init__(self, symbol: str, path: str):
        self.symbol = symbol
        self.path = path

    def stream(self):
        with open(self.path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ts = row["timestamp"].strip().replace("T", " ")
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
                yield Bar(self.symbol, dt,
                          float(row["open"]), float(row["high"]),
                          float(row["low"]), float(row["close"]),
                          float(row.get("volume", 0) or 0))


class _Lcg:
    """결정적 선형합동난수 — 외부 의존성 없이 재현 가능한 시세 생성용."""
    def __init__(self, seed: int):
        self.s = seed & 0x7FFFFFFF

    def next(self) -> float:
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return self.s / 0x7FFFFFFF


class SyntheticFeed:
    """가짜 15분봉. 완만한 상승 사이클 + 작은 노이즈.

    주의: 합성데이터는 '코드가 도는지' 확인용일 뿐, 성과 판단 근거가 아니다.
    100배에선 봉 내부 경로가 결과를 좌우하므로 반드시 실제 1분/틱 데이터로 재검증.
    """
    def __init__(self, symbol: str = "BTCUSDT", bars: int = 5000,
                 start_price: float = 50000, seed: int = 7,
                 minutes: int = 15):
        self.symbol = symbol
        self.bars = bars
        self.start_price = start_price
        self.seed = seed
        self.minutes = minutes

    def stream(self):
        rnd = _Lcg(self.seed)
        price = self.start_price
        dt = datetime(2024, 1, 1)
        for i in range(self.bars):
            drift = math.sin(i / 200) * 0.0015         # 완만한 추세 사이클
            shock = (rnd.next() - 0.5) * 0.008          # 봉당 노이즈(±0.4%대)
            open_p = price
            close_p = max(100.0, price * (1 + drift + shock))
            high = max(open_p, close_p) * (1 + rnd.next() * 0.003)
            low = min(open_p, close_p) * (1 - rnd.next() * 0.003)
            yield Bar(self.symbol, dt, round(open_p, 2), round(high, 2),
                      round(low, 2), round(close_p, 2), 1000.0)
            price = close_p
            dt += timedelta(minutes=self.minutes)
