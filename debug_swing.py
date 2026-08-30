"""#10(6/5 16:30 미청산 숏) 디버그 — swing이 왜 아직 하락(숏)으로 보나.

strategy와 동일하게 1분봉을 15개씩 흐름봉으로 묶고, 각 흐름봉에서
최근 swing_n개 저점/고점 시퀀스를 그대로 찍는다.
호윤 눈("저점 쭉 올라감")과 코드 판정(higher_lows/lower_highs)이 어디서 갈리나.

    python debug_swing.py [cutoff] [--from 6/5 10:00]
"""
import sys
from run_window import load_bars, DEFAULT_CUTOFF

GROUP = 15        # strategy.htf_group
SWING_N = 3       # strategy.swing_n


def build_htf(bars):
    htf = []
    n = len(bars) - len(bars) % GROUP
    for i in range(0, n, GROUP):
        g = bars[i:i + GROUP]
        htf.append((g[-1].dt, max(b.high for b in g), min(b.low for b in g), g[-1].close))
    return htf


def main():
    cutoff = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    htf = build_htf(bars)
    print(f"\n흐름봉 {len(htf)}개 (1분봉 {GROUP}개 묶음, strategy와 동일 경계).  swing_n={SWING_N}")
    print(f"진입 #10 = 6/5 16:30 숏.  그 직전 흐름봉들의 저/고점 구조를 본다.\n")
    print(f"{'흐름봉끝(=15분)':>15} | {'저점3 (오래된→최근)':>30} | {'고점3 (오래된→최근)':>30} | {'판정':>7}")
    print("-" * 95)
    for k in range(len(htf)):
        dt, hi, lo, cl = htf[k]
        if not (dt.day == 5 and dt.hour >= 12):      # 16:30 진입 주변만
            continue
        verdict = "데이터부족"
        lseq = hseq = ""
        if k >= SWING_N - 1:
            lows = [htf[j][2] for j in range(k - SWING_N + 1, k + 1)]
            highs = [htf[j][1] for j in range(k - SWING_N + 1, k + 1)]
            hl = all(lows[m] > lows[m - 1] for m in range(1, len(lows)))
            lh = all(highs[m] < highs[m - 1] for m in range(1, len(highs)))
            verdict = "롱 +1" if (hl and not lh) else ("숏 -1" if (lh and not hl) else "횡 0")
            lseq = " > ".join(f"{v:,.0f}" for v in lows) + ("  (저점상승)" if hl else "  (아님)")
            hseq = " > ".join(f"{v:,.0f}" for v in highs) + ("  (고점하락)" if lh else "  (아님)")
        mark = "  <- #10 진입 직전" if (dt.hour == 16 and 15 <= dt.minute <= 35) else ""
        print(f"{dt:%m/%d %H:%M} | {lseq:>30} | {hseq:>30} | {verdict:>7}{mark}")


if __name__ == "__main__":
    main()
