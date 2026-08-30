"""ml_dataset.py가 뽑은 라벨(data/ml_signals.csv)로 '수익모델' 5개를 학습·검증.

시간순 분할(과거=학습, 미래=테스트 — 셔플 금지, 미래정보 누출 방지). 표본이 워낙 적어서
(76건) 결과를 곧이곧대로 "엣지"라 읽으면 안 됨 — 테스트셋 n이 20여 건이면 정확도 하나
튀어도 이항분포 신뢰구간이 넓어 우연과 구분 안 됨. 그 폭도 같이 찍는다.

    python ml_models.py [csv=data/ml_signals.csv] [테스트비율=0.3]
"""
import csv
import math
import os
import sys

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier

HERE = os.path.dirname(os.path.abspath(__file__))
FEATURES = ["depth", "waited", "hour", "vol30", "mom30", "range_pos", "vol_z", "is_long"]


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    rows.sort(key=lambda r: r["idx"])   # 시간순 보장
    X = np.array([[float(r[k]) for k in FEATURES] for r in rows])
    y = np.array([int(r["win"]) for r in rows])
    pnl = np.array([float(r["pnl"]) for r in rows])
    return X, y, pnl


def binom_ci95(k, n):
    """정확도의 95% 근사 신뢰구간(정규근사, Wilson 아님·간단 버전) — '이 숫자 믿어도 되나' 감 잡기용."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    se = math.sqrt(p * (1 - p) / n)
    return max(0, p - 1.96 * se), min(1, p + 1.96 * se)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "ml_signals.csv"
    test_ratio = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    X, y, pnl = load(os.path.join(HERE, "data", name))
    n = len(y)
    n_test = max(1, int(n * test_ratio))
    n_train = n - n_test
    Xtr, Xte = X[:n_train], X[n_train:]
    ytr, yte = y[:n_train], y[n_train:]
    pnl_te = pnl[n_train:]

    print(f"전체 {n}건 → 학습 {n_train}건 / 테스트 {n_test}건 (시간순 분할, 테스트=최근 구간)")
    print(f"학습셋 승률 {ytr.mean()*100:.1f}% / 테스트셋 승률 {yte.mean()*100:.1f}%")
    print(f"베이스라인(전 신호 다 잡기) 테스트기간 총손익: {pnl_te.sum():+,.0f}\n")

    models = {
        "LogReg":  LogisticRegression(max_iter=1000, class_weight="balanced"),
        "DTree(d3)": DecisionTreeClassifier(max_depth=3, min_samples_leaf=5, random_state=0),
        "RandForest": RandomForestClassifier(n_estimators=200, max_depth=4,
                                             min_samples_leaf=3, random_state=0),
        "GBoost": GradientBoostingClassifier(n_estimators=100, max_depth=2,
                                             learning_rate=0.05, random_state=0),
        "KNN(5)": KNeighborsClassifier(n_neighbors=5),
    }

    hdr = (f"{'모델':>11} | {'학습acc':>7} | {'테스트acc':>8} | {'95%CI':>13} | "
           f"{'예측승 건':>7} | {'그중 실제승':>8} | {'모델선별 손익':>10}")
    print(hdr)
    print("-" * len(hdr))
    for name_, model in models.items():
        model.fit(Xtr, ytr)
        acc_tr = model.score(Xtr, ytr)
        pred_te = model.predict(Xte)
        acc_te = (pred_te == yte).mean()
        lo, hi = binom_ci95(int((pred_te == yte).sum()), len(yte))
        picked = pred_te == 1
        n_picked = int(picked.sum())
        n_picked_win = int(yte[picked].sum()) if n_picked else 0
        picked_pnl = pnl_te[picked].sum() if n_picked else 0.0
        print(f"{name_:>11} | {acc_tr*100:>6.1f}% | {acc_te*100:>7.1f}% | "
              f"[{lo*100:>4.0f}%,{hi*100:>4.0f}%] | {n_picked:>7} | {n_picked_win:>8} | {picked_pnl:>+10,.0f}")

    print(f"\n(참고) 테스트 n={n_test}건 — 정확도 하나가 이 정도 표본에선 신뢰구간이 "
          f"{(binom_ci95(int(n_test*0.5), n_test)[1]-binom_ci95(int(n_test*0.5), n_test)[0])*100:.0f}%p "
          f"폭까지 벌어짐. 모델간 몇 %p 차이는 우연과 구분 불가.")


if __name__ == "__main__":
    main()
