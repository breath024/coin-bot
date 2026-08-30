"""[훈련/수집] 백데이터 결정 훈련기 — 미래를 가린 채 '롱/숏/스킵'을 묻는다.

요즘 거래 감이 떨어졌을 때, 봇이 못 가진 '방향 판단'을 연습하면서
동시에 그 판단을 라벨 데이터로 적재한다(=진짜 필요한 표본 수집).

흐름:
  1. data/BTCUSDT_1m.csv에서 결정 지점을 뽑는다
     - 봇이 실제 진입한 자리(방향 동의?) + 봇이 안 들어간 통제 자리(들어갔어야?)
  2. 그 시점까지의 차트 맥락만 보여준다(미래는 가림)
  3. 너에게 묻는다: 롱(l) / 숏(s) / 스킵(n)  [확신 1~3 붙이려면 l2]
  4. 답하면 → 이후 60분 실제 움직임 + 봇이 뭘 했는지 공개 + 채점
  5. 네 판단을 drill_log.csv에 적재(=라벨)

    python drill.py [문제수]     # 기본 10

콘솔 한글 안 깨지면 그대로, 깨지면 Windows Terminal에서 실행 권장.
"""
import csv
import os
import random
import sys
from datetime import datetime

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from core import Side
from engine import FuturesEngine
from strategy import MomentumDip
from run_window import load_bars, INITIAL

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "drill_log.csv")
CTX = 60          # 보여줄 과거 봉 수
H = 60            # 미래 공개 지평(분)
THR = 0.003       # 방향 정답 판정 문턱 0.3% (호윤 평균 눌림/엣지 크기)
SPARK = "▁▂▃▄▅▆▇█"


def bot_entries(bars):
    """봇(MomentumDip swing 기본)이 실제 진입한 (봉인덱스 → 방향)."""
    broker = FuturesBroker(leverage=10, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(ListFeed(bars), MomentumDip("BTCUSDT"), broker,
                        FuturesAccount(INITIAL)).run()
    idx = {b.dt: i for i, b in enumerate(bars)}
    out = {}
    for f in eng.fills:
        if f.kind == "ENTRY" and f.dt in idx:
            out[idx[f.dt]] = f.side.value
    return out


def sparkline(vals):
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return SPARK[0] * len(vals)
    return "".join(SPARK[int((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in vals)


def show_context(bars, i):
    win = bars[i - CTX:i + 1]
    closes = [b.close for b in win]
    cur = bars[i].close
    hi = max(b.high for b in win)
    lo = min(b.low for b in win)
    pos = (cur - lo) / (hi - lo) * 100 if hi > lo else 50
    r30 = (cur / bars[i - 30].close - 1) * 100
    r60 = (cur / bars[i - 60].close - 1) * 100
    print(f"\n{'='*64}")
    print(f"  [{bars[i].dt:%m/%d %H:%M}]  현재가 {cur:,.1f}")
    print(f"  최근60분 {sparkline(closes)}")
    print(f"  60분변화 {r60:+.2f}%  |  30분변화 {r30:+.2f}%  |  "
          f"범위내 위치 {pos:.0f}% (0=바닥 100=천장)")
    print(f"  최근60봉 고 {hi:,.1f} / 저 {lo:,.1f}  (폭 {(hi/lo-1)*100:.2f}%)")
    print(f"  직전 6봉:")
    for b in win[-6:]:
        arr = "▲" if b.close >= b.open else "▼"
        print(f"     {b.dt:%H:%M} {arr} O{b.open:,.0f} H{b.high:,.0f} "
              f"L{b.low:,.0f} C{b.close:,.0f}")


def reveal(bars, i):
    """이후 H봉 실제 움직임 → 방향 정답 라벨 + 주요 수치."""
    cur = bars[i].close
    fut = bars[i + 1:i + 1 + H]
    up = (max(b.high for b in fut) - cur) / cur          # 최대 상승폭(MFE 롱)
    dn = (cur - min(b.low for b in fut)) / cur           # 최대 하락폭(MFE 숏)
    f15 = (bars[i + 15].close / cur - 1) * 100
    f30 = (bars[i + 30].close / cur - 1) * 100
    f60 = (bars[i + 60].close / cur - 1) * 100
    if up >= THR and up > dn * 1.5:
        label = "BUY"
    elif dn >= THR and dn > up * 1.5:
        label = "SELL"
    else:
        label = "SKIP"
    return label, up * 100, dn * 100, f15, f30, f60


def parse(s):
    s = s.strip().lower()
    conf = next((c for c in s if c.isdigit()), "")
    head = s[0] if s else "n"
    if head in ("l", "롱", "b"):
        return "BUY", conf
    if head in ("s", "숏"):
        return "SELL", conf
    return "SKIP", conf


def kor(call):
    return {"BUY": "롱", "SELL": "숏", "SKIP": "스킵"}[call]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    bars = load_bars(0)
    if len(bars) < CTX + H + 10:
        print("데이터 부족.")
        return
    ent = bot_entries(bars)
    valid = lambda j: CTX <= j <= len(bars) - H - 2
    ent_pts = [(i, d) for i, d in ent.items() if valid(i)]
    # 통제군: 봇이 안 들어간 무작위 자리(엔트리 근처 제외)
    near = set()
    for e in ent:
        near.update(range(e - 10, e + 10))
    pool = [j for j in range(CTX, len(bars) - H - 2) if j not in near]
    ctrl = [(j, None) for j in random.sample(pool, min(len(ent_pts), len(pool)))]
    probs = ent_pts + ctrl
    random.shuffle(probs)
    probs = probs[:n]

    print(f"\n백데이터 훈련 — {len(probs)}문제. 미래는 가려져 있다. 롱(l)/숏(s)/스킵(n).")
    print(f"데이터: {bars[0].dt:%m/%d} ~ {bars[-1].dt:%m/%d}  (봇진입 {len(ent_pts)} + 통제 섞음)")

    rows, hit, bot_hit = [], 0, 0
    for k, (i, bot_dir) in enumerate(probs, 1):
        print(f"\n────────── 문제 {k}/{len(probs)} ──────────")
        show_context(bars, i)
        try:
            ans = input("  네 판단 (l/s/n): ")
        except EOFError:
            break
        call, conf = parse(ans)
        label, up, dn, f15, f30, f60 = reveal(bars, i)
        botc = bot_dir or "SKIP"
        ok = call == label
        bok = botc == label
        hit += ok
        bot_hit += bok
        print(f"  ── 정답: {kor(label)}  (이후 최대 상승 {up:.2f}% / 하락 {dn:.2f}%, "
              f"+15분 {f15:+.2f}% +30분 {f30:+.2f}% +60분 {f60:+.2f}%)")
        print(f"  ── 너: {kor(call)} {'✓ 맞음' if ok else '✗ 틀림'}   |   "
              f"봇: {kor(botc)} {'✓' if bok else '✗'}")
        rows.append([f"{bars[i].dt:%Y-%m-%d %H:%M}", f"{bars[i].close:.1f}",
                     call, conf, botc, label, int(ok),
                     f"{up:.3f}", f"{dn:.3f}", f"{f60:.3f}"])

    if not rows:
        return
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["dt", "price", "my_call", "conf", "bot_call",
                        "outcome", "correct", "peak_up%", "peak_dn%", "fwd60%"])
        w.writerows(rows)

    nn = len(rows)
    print(f"\n{'='*64}")
    print(f"  결과: 너 {hit}/{nn} ({hit/nn*100:.0f}%)   봇 {bot_hit}/{nn} ({bot_hit/nn*100:.0f}%)")
    print(f"  {nn}건 → drill_log.csv 적재(라벨 데이터). 쌓일수록 '봇 vs 나' 패턴이 보인다.")


if __name__ == "__main__":
    main()
