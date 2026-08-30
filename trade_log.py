"""매매내역 CSV 저장. (엑셀 한글 깨짐 방지: utf-8-sig)

진입/청산을 한 줄씩, 실현손익(pnl)과 종류(kind)까지 남긴다.
이 파일이 곧 '감 파라미터 보정'과 '실거래 전 검증'의 1차 데이터다.
"""
from __future__ import annotations

import csv


def save(fills: list, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["일시", "심볼", "방향", "종류", "수량", "가격",
                    "수수료", "실현손익", "R배수", "사유"])
        for x in fills:
            w.writerow([
                x.dt.strftime("%Y-%m-%d %H:%M"), x.symbol, x.side.value, x.kind,
                round(x.qty, 6), round(x.price, 2), round(x.fee, 2),
                round(x.pnl, 2),
                round(x.r_multiple, 2) if x.r_multiple is not None else "",
                x.reason,
            ])
