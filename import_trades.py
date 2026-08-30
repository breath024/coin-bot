"""바이낸스 '거래 상세' 붙여넣기 → 매매기록 CSV + 분석.

사용법:
  1) 바이낸스에서 청산된 포지션 상세를 복사해 trades_raw.txt에 붙여넣는다 (여러 개 OK)
  2) python import_trades.py
  → 매매기록.csv 갱신 + 통계 출력 (승률·손익비·방향별·수수료부담)

trades_raw.txt를 계속 늘려가면 그게 곧 strategy.py 보정용 데이터셋이 된다.
"""
from __future__ import annotations

import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "trades_raw.txt")
OUT = os.path.join(HERE, "매매기록.csv")


def _num(s: str) -> float:
    return float(s.replace(",", "").replace("USDT", "").replace("%", "").strip())


def _hold_min(s: str) -> int:
    h = re.search(r"(\d+)\s*h", s)
    m = re.search(r"(\d+)\s*m", s)
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def parse(text: str) -> list[dict]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    starts = [i for i, l in enumerate(lines) if re.fullmatch(r"[A-Z0-9]{2,}USDT?", l)]
    starts.append(len(lines))
    out = []
    for a, b in zip(starts, starts[1:]):
        blk = lines[a:b]
        t = {"symbol": blk[0]}
        for i, l in enumerate(blk):
            nxt = blk[i + 1] if i + 1 < len(blk) else ""
            md = re.search(r"Isolated (Long|Short)", l)
            if md:
                t["dir"] = md.group(1)
            if re.fullmatch(r"\d+x", l):
                t["lev"] = int(l[:-1])
            if l.endswith("Opened") and re.match(r"\d\d/\d\d/\d{4}", l):
                t["opened"] = l.replace(" Opened", "")
            if l.endswith("Closed") and re.match(r"\d\d/\d\d/\d{4}", l):
                t["closed"] = l.replace(" Closed", "")
            if "Lasting" in l:
                t["hold"] = _hold_min(l)
            if l == "ROI":
                t["roi"] = _num(nxt)
            if l.startswith("Realized PNL"):
                t["pnl"] = _num(nxt)
            if l == "Entry Price":
                t["entry"] = _num(nxt)
            if l.startswith("Avg. Close"):
                t["close"] = _num(nxt)
            if l.startswith("Closed Vol"):
                t["vol"] = _num(nxt)
        if {"dir", "entry", "close", "roi"} <= t.keys():
            out.append(t)
    return out


def enrich(t: dict) -> dict:
    move = (t["close"] - t["entry"]) / t["entry"]
    dir_move = move if t["dir"] == "Long" else -move          # 방향 반영 가격수익률
    lev = t.get("lev", 100)
    t["price_move%"] = dir_move * 100
    t["gross_roi%"] = dir_move * 100 * lev                     # 수수료 전 (증거금 기준)
    t["fee_drag%"] = t["gross_roi%"] - t["roi"]               # 수수료+슬리피지가 먹은 폭
    return t


def main():
    if not os.path.exists(RAW):
        print(f"{RAW} 없음. 바이낸스 거래 상세를 붙여넣어줘.")
        return
    with open(RAW, encoding="utf-8") as f:
        trades = [enrich(t) for t in parse(f.read())]
    if not trades:
        print("파싱된 거래가 없어. 형식을 확인해줘.")
        return

    # CSV 저장 (전체 덮어쓰기 — raw가 원본)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["진입시각", "심볼", "방향", "레버", "진입가", "청산가",
                    "보유(분)", "ROI%", "가격이동%", "수수료먹은%", "PNL_USDT"])
        for t in trades:
            w.writerow([t.get("opened", ""), t["symbol"], t["dir"], t.get("lev", 100),
                        t["entry"], t["close"], t.get("hold", ""), round(t["roi"], 2),
                        round(t["price_move%"], 3), round(t["fee_drag%"], 1),
                        t.get("pnl", "")])

    wins = [t for t in trades if t["roi"] > 0]
    losses = [t for t in trades if t["roi"] <= 0]
    longs = [t for t in trades if t["dir"] == "Long"]
    shorts = [t for t in trades if t["dir"] == "Short"]
    n = len(trades)
    avg_w = sum(t["roi"] for t in wins) / len(wins) if wins else 0
    avg_l = sum(t["roi"] for t in losses) / len(losses) if losses else 0
    pf = abs(avg_w / avg_l) if avg_l else None

    print(f"\n=== 실거래 분석 ({n}건) ===")
    print(f"  승률      : {len(wins)}/{n} = {len(wins)/n*100:.0f}%")
    print(f"  평균이익  : {avg_w:+.1f}% (ROI)")
    print(f"  평균손실  : {avg_l:+.1f}% (ROI)")
    print(f"  손익비    : {pf:.2f}" if pf else "  손익비    : -")
    print(f"  방향      : 롱 {len(longs)} / 숏 {len(shorts)}")
    holds = [t['hold'] for t in trades if 'hold' in t]
    if holds:
        print(f"  보유시간  : {min(holds)}~{max(holds)}분 (편차 큼 = 재량 청산)")
    print(f"  총 PNL    : {sum(t.get('pnl',0) for t in trades):+.2f} USDT")
    breakeven = 1 / (1 + abs(avg_w / avg_l)) * 100 if avg_l else None
    if breakeven is not None:
        print(f"  손익분기승률: {breakeven:.0f}%  (이 위면 +EV)")

    print("\n  [건별]")
    print(f"  {'진입시각':<20}{'방향':<6}{'보유분':>6}{'ROI%':>9}{'가격%':>9}{'수수료먹은%':>10}")
    for t in trades:
        print(f"  {t.get('opened',''):<20}{t['dir']:<6}{t.get('hold',''):>6}"
              f"{t['roi']:>8.1f}%{t['price_move%']:>8.2f}%{t['fee_drag%']:>9.1f}%")
    print(f"\n  저장 → {OUT}")


if __name__ == "__main__":
    main()
