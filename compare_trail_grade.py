"""트레일 0.1% vs 0.4% 자리별 대조 — 채점과 '같은 설정'(10x)으로.

grade_entries가 뽑은 진입(10x, trail 0.1%)을 0.4%로 다시 돌려, 같은 자리에서
얼마나 더(덜) 먹었는지 진입시각 기준으로 나란히 본다. 진입 로직은 고정(익절폭만 변경).
청산이 늦어지면 이후 진입 자리가 이동할 수 있어, 어긋난 건 따로 표시한다.

    python compare_trail_grade.py [cutoff_ms]
"""
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from strategy import MomentumDip
from run_window import load_bars, DEFAULT_CUTOFF, INITIAL

SYMBOL = "BTCUSDT"
LEV = 10   # ← grade_entries.py와 동일 (채점이 10x였음)


def run_pairs(bars, trail):
    broker = FuturesBroker(leverage=LEV, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(ListFeed(bars), MomentumDip(SYMBOL, trail_pct=trail),
                        broker, FuturesAccount(INITIAL)).run()
    pairs, cur = [], None
    for f in eng.fills:
        if f.kind == "ENTRY":
            cur = {"t": f.dt, "dir": f.side.value, "ep": f.price}
        elif cur is not None:
            cur.update(xt=f.dt, xp=f.price, pnl=f.pnl, xk=f.kind,
                       hold=int((f.dt - cur["t"]).total_seconds() / 60))
            pairs.append(cur)
            cur = None
    if cur is not None:
        cur.update(xt=None, xp=None, pnl=None, xk="미청산", hold=None)
        pairs.append(cur)
    return pairs


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    a = run_pairs(bars, 0.0010)
    b = run_pairs(bars, 0.0040)
    bmap = {p["t"]: p for p in b}
    a_times = {p["t"] for p in a}

    print(f"\n구간 {bars[0].dt:%m-%d %H:%M} ~ {bars[-1].dt:%m-%d %H:%M}, 레버 {LEV}x (채점과 동일)")
    print(f"진입수: 0.1%={len(a)}건 / 0.4%={len(b)}건  (손익=가상시드 {INITIAL:,}원 기준)\n")
    hdr = (f"{'#':>2} {'진입시각':>11} {'방':>2} {'진입가':>8} | "
           f"{'0.1%청산':>9} {'보유':>5} {'손익':>9} | "
           f"{'0.4%청산':>9} {'보유':>5} {'손익':>9} | {'차이':>9}")
    print(hdr)
    print("-" * len(hdr))
    ta = tb = 0
    matched = 0
    for n, p in enumerate(a, 1):
        pa = 0 if p["pnl"] is None else p["pnl"]
        ta += pa
        hold_a = f"{p['hold']}m" if p["hold"] is not None else "-"
        row = (f"{n:>2} {p['t']:%m-%d %H:%M} {p['dir'][:1]:>2} {p['ep']:>8,.0f} | "
               f"{p['xk']:>9} {hold_a:>5} {pa:>9,.0f} |")
        if p["t"] in bmap:
            q = bmap[p["t"]]
            pb = 0 if q["pnl"] is None else q["pnl"]
            tb += pb
            matched += 1
            hold_b = f"{q['hold']}m" if q["hold"] is not None else "-"
            row += (f" {q['xk']:>9} {hold_b:>5} {pb:>9,.0f} | {pb - pa:>+9,.0f}")
        else:
            row += f" {'(0.4%선 진입 어긋남)':>33}"
        print(row)
    print("-" * len(hdr))
    print(f"합계  0.1%: {ta:>+12,.0f}    0.4%(매칭 {matched}건): {tb:>+12,.0f}    "
          f"차이: {tb - ta:>+12,.0f}")

    extra = [q for q in b if q["t"] not in a_times]
    if extra:
        print(f"\n0.4%에서만 새로 생긴 진입 {len(extra)}건 (청산 늦어지며 자리 이동):")
        for q in extra:
            pb = 0 if q["pnl"] is None else q["pnl"]
            print(f"   {q['t']:%m-%d %H:%M} {q['dir'][:1]} {q['ep']:,.0f} "
                  f"-> {q['xk']} {pb:+,.0f}")


if __name__ == "__main__":
    main()
