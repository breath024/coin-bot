"""실시간 모의매매 추적기 (호윤 재량 트레이드용).

  python paper_trade.py short   # 현재가에 숏 진입(기록)
  python paper_trade.py long    # 롱 진입
  python paper_trade.py status  # 현재 손익 / 스탑거리 / 피크대비 되돌림
  python paper_trade.py close   # 현재가에 청산 + paper_trades_log.csv 기록

100배 ROI 기준으로 보여준다(바이낸스 표시 감각과 동일). 청산 판단은 호윤이.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "paper_state.json")
LOG = os.path.join(HERE, "paper_trades_log.csv")
SYMBOL = "BTCUSDT"
LEV = 100
STOP_ON_MARGIN = 0.30
TAKER_FEE = 0.0004
MAINT = 0.005
RT_FEE = 2 * TAKER_FEE * LEV * 100      # 왕복 수수료(증거금 %)


def price():
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={SYMBOL}"
    req = urllib.request.Request(url, headers={"User-Agent": "coinbot/0.1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return float(json.load(r)["price"])


def roi(side, entry, p):
    move = (p - entry) / entry if side == "long" else (entry - p) / entry
    gross = move * LEV * 100
    return gross, gross - RT_FEE        # (수수료전, 수수료후)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd in ("short", "long"):
        p = price()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        json.dump({"side": cmd, "entry": p, "time": now, "peak": p}, open(STATE, "w"))
        stop = p * (1 + STOP_ON_MARGIN / LEV) if cmd == "short" else p * (1 - STOP_ON_MARGIN / LEV)
        liq = p * (1 + 1 / LEV - MAINT) if cmd == "short" else p * (1 - 1 / LEV + MAINT)
        print(f"\n■ {cmd.upper()} 진입 기록  {SYMBOL} @ {p:,.1f}  ({now})")
        print(f"  손절가(-30%): {stop:,.1f}    청산가: {liq:,.1f}")
        print(f"  왕복 수수료: 증거금 {RT_FEE:.0f}%  → 이거 넘게 먹어야 실익")
        print("  모니터: python paper_trade.py status   청산: python paper_trade.py close")
        return

    if not os.path.exists(STATE):
        print("진입 기록 없음. 먼저: python paper_trade.py short|long")
        return

    st = json.load(open(STATE))
    p = price()
    st["peak"] = max(st["peak"], p) if st["side"] == "long" else min(st["peak"], p)
    json.dump(st, open(STATE, "w"))
    _, n = roi(st["side"], st["entry"], p)
    _, npk = roi(st["side"], st["entry"], st["peak"])
    stop = st["entry"] * (1 + STOP_ON_MARGIN / LEV) if st["side"] == "short" else st["entry"] * (1 - STOP_ON_MARGIN / LEV)

    if cmd == "close":
        new = not os.path.exists(LOG)
        with open(LOG, "a", encoding="utf-8-sig") as f:
            if new:
                f.write("진입시각,청산시각,심볼,방향,진입가,청산가,실현ROI%\n")
            f.write(f"{st['time']},{datetime.now():%Y-%m-%d %H:%M:%S},{SYMBOL},"
                    f"{st['side']},{st['entry']},{p},{n:.1f}\n")
        os.remove(STATE)
        print(f"\n● 청산  {SYMBOL} {st['side'].upper()}  {st['entry']:,.1f} → {p:,.1f}")
        print(f"  실현 ROI(수수료후): {n:+.1f}%    기록 → {LOG}")
        return

    print(f"\n▷ {st['side'].upper()} {SYMBOL}  진입 {st['entry']:,.1f} → 현재 {p:,.1f}")
    print(f"  ROI(수수료후): {n:+.1f}%")
    print(f"  피크 ROI: {npk:+.1f}%   피크대비 되돌림: {npk - n:.1f}%p")
    print(f"  손절가(-30%): {stop:,.1f}")
    if (st["side"] == "short" and p >= stop) or (st["side"] == "long" and p <= stop):
        print("  ⚠ 손절선 도달")


if __name__ == "__main__":
    main()
