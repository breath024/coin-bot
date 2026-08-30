"""지금 시장 한 컷 — 이전 고점/저점(저항·지지) 대비 현재가 + 최근 봉 구조(힘 빠짐 여부).

    실행:  python live_look.py

호윤이 "지금 이 자리 어때?" 할 때 객관적 숫자(흐름·레벨·거리·모멘텀)를 보여준다.
※ 매수/매도 지시가 아니라 '데이터로 본 현재 상태'다. 판단은 호윤이 한다.
"""
import json
import urllib.request
from datetime import datetime

BASE = "https://fapi.binance.com/fapi/v1/klines"
SYMBOL = "BTCUSDT"


def kl(interval, limit):
    url = f"{BASE}?symbol={SYMBOL}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "coinbot/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    m15 = kl("15m", 50)
    m1 = kl("1m", 30)
    highs15 = [float(k[2]) for k in m15]
    lows15 = [float(k[3]) for k in m15]
    closes15 = [float(k[4]) for k in m15]
    price = float(m1[-1][4])

    recent_high = max(highs15[-20:-1])   # 최근 20봉 저항(현재 형성봉 제외)
    recent_low = min(lows15[-20:-1])     # 최근 20봉 지지
    ma_s = sum(closes15[-5:]) / 5
    ma_l = sum(closes15[-20:]) / 20
    trend = "상승흐름" if ma_s > ma_l else ("하락흐름" if ma_s < ma_l else "횡보")

    print(f"\n=== {SYMBOL} 현재 ({datetime.fromtimestamp(m1[-1][0]/1000):%m-%d %H:%M} KST) ===")
    print(f"  현재가     : {price:,.1f}")
    print(f"  15분 흐름  : {trend}  (MA5 {ma_s:,.0f} / MA20 {ma_l:,.0f})")
    print(f"  저항(고점) : {recent_high:,.1f}  → 현재가까지 {(recent_high-price)/price*100:+.2f}%")
    print(f"  지지(저점) : {recent_low:,.1f}  → 현재가까지 {(recent_low-price)/price*100:+.2f}%")

    print("\n  [최근 15분봉 6개]")
    for k in m15[-6:]:
        o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        print(f"   {datetime.fromtimestamp(k[0]/1000):%H:%M} {'▲' if c>=o else '▼'} "
              f"종가 {c:,.0f}  레인지 {(h-l)/c*100:.2f}%")

    print("\n  [최근 1분봉 8개]  ← 레인지 줄면 '힘 빠짐'")
    for k in m1[-8:]:
        o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        print(f"   {datetime.fromtimestamp(k[0]/1000):%H:%M} {'▲' if c>=o else '▼'} "
              f"종가 {c:,.1f}  레인지 {(h-l)/c*100:.3f}%")

    # 수렴(코일) 감지: 최근 10개 1분봉을 앞5/뒤5로 나눠 고점↓·저점↑ 인지
    last = m1[-10:]
    h = [float(k[2]) for k in last]
    l = [float(k[3]) for k in last]
    eh, lh = max(h[:5]), max(h[5:])      # 앞5/뒤5 고점
    el, ll = min(l[:5]), min(l[5:])      # 앞5/뒤5 저점
    lower_highs = lh < eh
    higher_lows = ll > el
    rng0 = (eh - el) / price * 100
    rng1 = (lh - ll) / price * 100
    print("\n  [수렴(코일) 체크 — 최근 10분]")
    print(f"   고점: {eh:,.0f} → {lh:,.0f}  ({'낮아짐 ✅' if lower_highs else '안 낮아짐'})")
    print(f"   저점: {el:,.0f} → {ll:,.0f}  ({'높아짐 ✅' if higher_lows else '안 높아짐'})")
    print(f"   변동폭: {rng0:.2f}% → {rng1:.2f}%  ({'좁혀짐(수렴)' if rng1 < rng0 else '벌어짐'})")
    if lower_highs and higher_lows:
        verdict = "삼각수렴 형성 = 힘 빠지는 중 (네 진입각 자리)"
    elif rng1 < rng0:
        verdict = "변동폭 축소 중 (수렴 초기)"
    else:
        verdict = "아직 수렴 아님 (힘 살아있음)"
    print(f"   → {verdict}")


if __name__ == "__main__":
    main()
