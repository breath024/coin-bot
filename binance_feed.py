"""바이낸스 선물 시세 피드 (공개 API · API키 불필요 · 표준 라이브러리만).

- fetch_klines:    과거 봉을 페이지네이션으로 N개 받아온다
- ListFeed:        받아둔 봉을 그대로 흘려보낸다 (한 번 받아 여러 번 백테스트용)
- BinanceHistFeed: 과거 봉을 받아 스트리밍 (실데이터 백테스트)
- BinanceLiveFeed: 워밍업 후 새로 마감된 봉을 실시간으로 흘려보낸다 (모의투자)

엔드포인트: https://fapi.binance.com/fapi/v1/klines
kline 배열: [openTime, open, high, low, close, volume, closeTime, ...]
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime

from core import Bar

BASE = "https://fapi.binance.com/fapi/v1/klines"


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "coinbot/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def fetch_klines(symbol: str, interval: str, total: int) -> list:
    """가장 최근 마감봉 total개를 받아온다 (1500개씩 끊어서 과거로 페이지네이션)."""
    out: list = []
    end_time = None
    while len(out) < total:
        limit = min(1500, total - len(out))
        url = f"{BASE}?symbol={symbol}&interval={interval}&limit={limit}"
        if end_time is not None:
            url += f"&endTime={end_time}"
        data = _get(url)
        if not data:
            break
        out = data + out
        end_time = data[0][0] - 1      # 가장 이른 봉 직전으로 커서 이동
        if len(data) < limit:
            break
        time.sleep(0.25)               # 레이트리밋 예의
    return out[-total:]


def klines_to_bars(symbol: str, klines: list) -> list:
    return [
        Bar(symbol, datetime.fromtimestamp(k[0] / 1000),
            float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
        for k in klines
    ]


class ListFeed:
    """미리 받아둔 Bar 리스트를 그대로 흘려보낸다."""
    def __init__(self, bars: list):
        self.bars = bars

    def stream(self):
        yield from self.bars


class BinanceHistFeed:
    """과거 봉을 받아 스트리밍 (실데이터 백테스트)."""
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", bars: int = 5000):
        self.symbol = symbol
        self.interval = interval
        self.bars = bars

    def stream(self):
        kl = fetch_klines(self.symbol, self.interval, self.bars)
        yield from klines_to_bars(self.symbol, kl)


class BinanceLiveFeed:
    """모의투자용 실시간 피드.

    1) 워밍업: 직전 마감봉 warmup개를 먼저 흘려보낸다(지표 시드용)
    2) 라이브: poll_seconds마다 확인해 '새로 마감된 봉'이 생기면 흘려보낸다
    """
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m",
                 warmup: int = 200, poll_seconds: int = 15):
        self.symbol = symbol
        self.interval = interval
        self.warmup = warmup
        self.poll_seconds = poll_seconds

    def stream(self):
        # 1) 워밍업 — 마지막 봉(아직 형성 중)은 빼고 마감봉만
        hist = fetch_klines(self.symbol, self.interval, self.warmup + 1)[:-1]
        last_open = None
        for k in hist:
            last_open = k[0]
            yield Bar(self.symbol, datetime.fromtimestamp(k[0] / 1000),
                      float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
        # 2) 라이브 — 새 마감봉 폴링
        while True:
            time.sleep(self.poll_seconds)
            try:
                kl = _get(f"{BASE}?symbol={self.symbol}&interval={self.interval}&limit=2")
            except Exception:
                continue                      # 일시적 네트워크 오류는 무시하고 재시도
            closed = kl[-2]                    # [-1]은 형성 중인 봉
            if last_open is None or closed[0] != last_open:
                last_open = closed[0]
                yield Bar(self.symbol, datetime.fromtimestamp(closed[0] / 1000),
                          float(closed[1]), float(closed[2]), float(closed[3]),
                          float(closed[4]), float(closed[5]))
