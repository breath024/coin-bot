"""로그 → 단일 HTML 대시보드 + (서브모드) 버튼식 모의매매 기록.

  python report.py          # dashboard.html 생성 (읽기전용, 더블클릭으로 열기)
  python report.py --serve  # ★ 브라우저에 띄우고 진입/청산 버튼까지 (localhost)

읽는 로그(있는 것만):
  - live_paper_log.csv   : 봇 라이브 모의매매 (run_live.py)
  - 매매기록.csv          : 내 실거래 (import_trades.py)
  - paper_trades_log.csv : 내 수동 모의매매 (paper_trade.py / 이 화면 버튼)

브라우저는 로컬 CSV를 직접 못 쓰므로, 버튼 기록은 --serve(작은 로컬 서버)에서만 동작.
그냥 더블클릭해 연 dashboard.html은 예전처럼 읽기전용.
"""
from __future__ import annotations

import csv
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# 모의매매 기록은 paper_trade.py와 같은 파일/로직 공유 (단일 출처)
from paper_trade import LOG, RT_FEE, STATE, STOP_ON_MARGIN, SYMBOL, LEV, price, roi
# 차트/흐름 판정은 live_look.py와 같은 로직 공유 (콘솔 텍스트 → 웹 차트로 옮김)
from live_look import kl
# AI 신호(보조도구) = MomentumDip이 '지금' 진입신호를 내는지, 포지션 점유 무관하게 스캔
from binance_feed import klines_to_bars
from ml_dataset import scan_signals

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8790   # 8765는 이 PC에서 다른(정체불명) 서버가 이미 물고있어 충돌 → 안 겹치는 포트로 변경


def read_csv(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").replace("USDT", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def stats_from(values):
    if not values:
        return {"n": 0}
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v <= 0]
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    return {
        "n": len(values),
        "winrate": round(len(wins) / len(values) * 100, 1),
        "avg_win": round(aw, 2),
        "avg_loss": round(al, 2),
        "pf": round(abs(aw / al), 2) if al else None,
        "total": round(sum(values), 2),
    }


def _epoch(dt_str, fmt):
    """차트 리뷰용 — 문자열 시각을 epoch ms로. 파싱 실패 시 None(리뷰 버튼만 비활성)."""
    try:
        return int(datetime.strptime(dt_str, fmt).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


GRADE_LOG = os.path.join(HERE, "trade_grades.csv")


def load_grades():
    """소스+진입시각(et)별 '가장 최근' 채점만 남긴다(재채점 시 덮어쓰기 취급)."""
    out = {}
    if not os.path.exists(GRADE_LOG):
        return out
    with open(GRADE_LOG, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = f"{row.get('소스')}|{row.get('et')}"
            out[key] = row.get("등급")
    return out


def save_grade(payload):
    """grade_entries.py와 같은 채점 어휘(ok=나도 들어감 / may=애매 / no=난 안 침)."""
    new = not os.path.exists(GRADE_LOG)
    with open(GRADE_LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["기록시각", "소스", "et", "방향", "진입가", "청산가", "등급", "메모"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payload.get("source", ""),
                    payload.get("et", ""), payload.get("side", ""), payload.get("ep", ""),
                    payload.get("xp", ""), payload.get("grade", ""), payload.get("label", "")])


def build():
    data = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "sources": []}
    grades = load_grades()

    def tag(trade, source, side):
        if trade is None:
            return None
        trade["source"] = source
        trade["side"] = side
        trade["grade"] = grades.get(f"{source}|{trade['et']}")
        return trade

    bot = read_csv("live_paper_log.csv")
    exits = [r for r in bot if r.get("종류") in ("STOP", "TP", "STALL", "LIQ")]
    eq = [[r.get("시각", ""), fnum(r.get("자산"))] for r in bot if r.get("자산")]
    # ENTRY-청산 짝지어 리뷰차트용(진입가/청산가/시각) — 표는 기존처럼 낱건 그대로 보여줌
    bot_trades, cur_entry = [], None
    for r in bot[-60:]:
        if r.get("종류") == "ENTRY":
            cur_entry = r
            bot_trades.append(None)     # ENTRY 자체 행은 리뷰 대상 아님(짝인 청산행에서 클릭)
        elif cur_entry is not None:
            et = _epoch(cur_entry.get("시각", ""), "%Y-%m-%d %H:%M")
            xt = _epoch(r.get("시각", ""), "%Y-%m-%d %H:%M")
            trade = ({"et": et, "ep": fnum(cur_entry.get("가격")), "xt": xt, "xp": fnum(r.get("가격")),
                     "label": f"봇 {cur_entry.get('방향','')} {cur_entry.get('시각','')}"}
                     if (et and xt) else None)
            bot_trades.append(tag(trade, "bot", cur_entry.get("방향", "")))
            cur_entry = None
        else:
            bot_trades.append(None)
    data["sources"].append({
        "key": "bot", "title": "🤖 봇 라이브 모의 (내 매매법 자동)",
        "stats": stats_from([fnum(r.get("실현손익")) for r in exits]),
        "unit": "원", "equity": eq,
        "rows": [[r.get("시각", ""), r.get("종류", ""), r.get("방향", ""),
                  r.get("가격", ""), r.get("실현손익", ""), r.get("사유", "")] for r in bot[-60:]],
        "cols": ["시각", "종류", "방향", "가격", "실현손익", "사유"],
        "trades": bot_trades,
    })

    real = read_csv("매매기록.csv")
    real_trades = []
    for r in real:
        et = _epoch(r.get("진입시각", ""), "%m/%d/%Y %H:%M:%S")
        hold = fnum(r.get("보유(분)"))
        xt = et + int(hold * 60000) if et is not None else None
        trade = ({"et": et, "ep": fnum(r.get("진입가")), "xt": xt, "xp": fnum(r.get("청산가")),
                 "label": f"실거래 {r.get('방향','')} {r.get('진입시각','')}"} if et else None)
        real_trades.append(tag(trade, "real", r.get("방향", "")))
    data["sources"].append({
        "key": "real", "title": "💰 내 실거래 (바이낸스)",
        "stats": stats_from([fnum(r.get("ROI%")) for r in real]),
        "unit": "% ROI", "equity": [],
        "rows": [[r.get("진입시각", ""), r.get("방향", ""), r.get("진입가", ""),
                  r.get("청산가", ""), r.get("ROI%", ""), r.get("보유(분)", "")] for r in real],
        "cols": ["진입시각", "방향", "진입가", "청산가", "ROI%", "보유(분)"],
        "trades": real_trades,
    })

    mp = read_csv("paper_trades_log.csv")
    manual_trades = []
    for r in mp:
        et = _epoch(r.get("진입시각", ""), "%Y-%m-%d %H:%M:%S")
        xt = _epoch(r.get("청산시각", ""), "%Y-%m-%d %H:%M:%S")
        trade = ({"et": et, "ep": fnum(r.get("진입가")), "xt": xt, "xp": fnum(r.get("청산가")),
                 "label": f"수동 {r.get('방향','')} {r.get('진입시각','')}"} if et and xt else None)
        manual_trades.append(tag(trade, "manual", r.get("방향", "")))
    data["sources"].append({
        "key": "manual", "title": "✋ 내 수동 모의 (버튼 기록)",
        "stats": stats_from([fnum(r.get("실현ROI%")) for r in mp]),
        "unit": "% ROI", "equity": [],
        "rows": [[r.get("진입시각", ""), r.get("방향", ""), r.get("진입가", ""),
                  r.get("청산가", ""), r.get("실현ROI%", "")] for r in mp],
        "cols": ["진입시각", "방향", "진입가", "청산가", "실현ROI%"],
        "trades": manual_trades,
    })
    return data


def history_candles(center_ms, mins):
    """리뷰차트용 — 로컬 누적 데이터(data/BTCUSDT_1m.csv)에서 center 전후 mins분 캔들.
    실시간 바이낸스 호출 없이 이미 쌓아둔 과거 데이터만 씀(범위 밖이면 빈 배열)."""
    half = mins * 60000 // 2
    lo, hi = center_ms - half, center_ms + half
    path = os.path.join(HERE, "data", "BTCUSDT_1m.csv")
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if not row or not row[0].isdigit():
                continue
            ot = int(row[0])
            if ot < lo:
                continue
            if ot > hi:
                break
            out.append({"t": ot, "o": float(row[2]), "h": float(row[3]),
                        "l": float(row[4]), "c": float(row[5])})
    return out


# ───────────────────────── 모의매매 동작 (서버 전용) ─────────────────────────
def pos_state():
    """현재가 + 열린 포지션 손익. 버튼 화면이 4초마다 부른다."""
    p = price()
    out = {"price": p}
    if os.path.exists(STATE):
        st = json.load(open(STATE))
        st["peak"] = max(st["peak"], p) if st["side"] == "long" else min(st["peak"], p)
        json.dump(st, open(STATE, "w"))
        _, n = roi(st["side"], st["entry"], p)
        _, npk = roi(st["side"], st["entry"], st["peak"])
        stop = (st["entry"] * (1 + STOP_ON_MARGIN / LEV) if st["side"] == "short"
                else st["entry"] * (1 - STOP_ON_MARGIN / LEV))
        hit = (st["side"] == "short" and p >= stop) or (st["side"] == "long" and p <= stop)
        out["pos"] = {"side": st["side"], "entry": st["entry"], "roi": round(n, 1),
                      "peak_roi": round(npk, 1), "retrace": round(npk - n, 1),
                      "stop": round(stop, 1), "hit": hit, "rt_fee": round(RT_FEE),
                      "entry_time_ms": _epoch(st.get("time", ""), "%Y-%m-%d %H:%M:%S")}
    return out


def chart_data():
    """live_look.py와 같은 판정(흐름·저항/지지·코일)을 웹 차트용 JSON으로."""
    m15 = kl("15m", 50)
    m1 = kl("1m", 120)
    highs15 = [float(k[2]) for k in m15]
    lows15 = [float(k[3]) for k in m15]
    closes15 = [float(k[4]) for k in m15]
    recent_high = max(highs15[-20:-1])   # 최근 20봉 저항(형성중 봉 제외)
    recent_low = min(lows15[-20:-1])     # 최근 20봉 지지
    ma_s = sum(closes15[-5:]) / 5
    ma_l = sum(closes15[-20:]) / 20
    trend = "상승흐름" if ma_s > ma_l else ("하락흐름" if ma_s < ma_l else "횡보")

    last = m1[-10:]                      # 코일(수렴) 체크 — 최근 10분을 앞5/뒤5로
    h = [float(k[2]) for k in last]
    l = [float(k[3]) for k in last]
    lower_highs = max(h[5:]) < max(h[:5])
    higher_lows = min(l[5:]) > min(l[:5])
    coil = lower_highs and higher_lows

    candles = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                "l": float(k[3]), "c": float(k[4])} for k in m1]
    return {
        "candles": candles, "recent_high": round(recent_high, 1), "recent_low": round(recent_low, 1),
        "trend": trend, "ma_s": round(ma_s, 1), "ma_l": round(ma_l, 1), "coil": coil,
    }


AI_SIG_LOG = os.path.join(HERE, "ai_signal_log.csv")


def live_signal():
    """지금 이 순간(가장 최근 마감봉)에 MomentumDip이 진입신호를 내는가 — AI=보조도구, 사람이 실행할 걸 가정.
    포지션 점유와 무관하게 스캔(ml_dataset.scan_signals)해서 '마지막 봉'에 신호가 있었는지만 본다."""
    m1 = kl("1m", 400)   # swing 추세 판정 워밍업용으로 넉넉히
    bars = klines_to_bars(SYMBOL, m1)
    sigs = scan_signals(bars)
    last_idx = len(bars) - 1
    fired = [s for s in sigs if s[0] == last_idx]
    if not fired:
        return {"signal": False}
    _, side, reason = fired[0]
    return {"signal": True, "side": side.value, "reason": reason,
            "price": bars[-1].close, "time": bars[-1].dt.isoformat()}


def log_signal_if_new(sig):
    """같은 봉의 신호를 매 폴링(20초)마다 중복 기록하지 않도록 마지막 기록 시각과 대조."""
    if not sig.get("signal"):
        return
    last_seen = None
    if os.path.exists(AI_SIG_LOG):
        with open(AI_SIG_LOG, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
            if rows:
                last_seen = rows[-1]["시각"]
    if sig["time"] == last_seen:
        return
    new = not os.path.exists(AI_SIG_LOG)
    with open(AI_SIG_LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["시각", "방향", "가격", "사유"])
        w.writerow([sig["time"], sig["side"], sig["price"], sig["reason"]])


def enter_trade(side):
    if os.path.exists(STATE):
        return {"ok": False, "msg": "이미 포지션 있음"}
    p = price()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json.dump({"side": side, "entry": p, "time": now, "peak": p}, open(STATE, "w"))
    return {"ok": True, "msg": f"{side.upper()} 진입 @ {p:,.1f}"}


def close_trade():
    if not os.path.exists(STATE):
        return {"ok": False, "msg": "열린 포지션 없음"}
    st = json.load(open(STATE))
    p = price()
    _, n = roi(st["side"], st["entry"], p)
    new = not os.path.exists(LOG)
    with open(LOG, "a", encoding="utf-8-sig") as f:
        if new:
            f.write("진입시각,청산시각,심볼,방향,진입가,청산가,실현ROI%\n")
        f.write(f"{st['time']},{datetime.now():%Y-%m-%d %H:%M:%S},{SYMBOL},"
                f"{st['side']},{st['entry']},{p},{n:.1f}\n")
    os.remove(STATE)
    return {"ok": True, "msg": f"청산 {st['side'].upper()} {st['entry']:,.1f}→{p:,.1f}  실현 {n:+.1f}%"}


# ───────────────────────── HTML ─────────────────────────
HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>코인봇 대시보드</title>
<style>
  :root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--tx:#e6edf3;--mut:#8b949e;--up:#3fb950;--dn:#f85149;--ac:#58a6ff}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--tx);
    font-family:'Segoe UI',-apple-system,'Malgun Gothic',sans-serif;padding:24px}
  h1{font-size:20px;margin:0 0 2px} .gen{color:var(--mut);font-size:12px;margin-bottom:20px}
  .sec{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:18px;margin-bottom:18px}
  .sec h2{font-size:15px;margin:0 0 14px}
  .cards{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
  .c{background:var(--bg);border:1px solid var(--bd);border-radius:9px;padding:10px 14px;min-width:96px}
  .c .l{color:var(--mut);font-size:11px} .c .v{font-size:19px;font-weight:700;margin-top:3px}
  .up{color:var(--up)} .dn{color:var(--dn)} .mut{color:var(--mut)}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th,td{text-align:right;padding:6px 9px;border-bottom:1px solid var(--bd);white-space:nowrap}
  th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
  th{color:var(--mut);font-weight:600} td:last-child{color:var(--mut);text-align:left;white-space:normal}
  .empty{color:var(--mut);padding:18px;text-align:center}
  .clkrow{cursor:pointer} .clkrow:hover td{background:rgba(88,166,255,.08)}
  svg{width:100%;height:120px;display:block;margin-bottom:10px}
  /* 버튼식 모의매매 */
  .chartbox{background:var(--bg);border:1px solid var(--bd);border-radius:9px;padding:8px;margin-bottom:8px;
    height:280px;resize:vertical;overflow:hidden;min-height:160px;max-height:80vh}
  #chartsvg,#reviewsvg{width:100%;height:100%;display:block}
  .cinfo{font-size:12px;color:var(--mut);margin-bottom:14px;line-height:1.6}
  .aisig{font-size:13px;margin-bottom:14px;padding:9px 12px;border-radius:8px;
    background:var(--bg);border:1px solid var(--bd);transition:background .3s,border-color .3s}
  #trade .px{font-size:30px;font-weight:800;margin:2px 0 10px}
  #trade .st{font-family:Consolas,monospace;font-size:13px;line-height:1.7;margin-bottom:14px;white-space:pre}
  .btns{display:flex;gap:10px;flex-wrap:wrap}
  .btn{flex:1;min-width:90px;border:0;border-radius:9px;color:#fff;font-size:15px;font-weight:700;
    padding:16px 0;cursor:pointer}
  .btn:disabled{opacity:.35;cursor:default}
  .bl{background:#238636} .bs{background:#da3633} .bc{background:#373e47}
  #tmsg{margin-top:10px;color:var(--mut);font-size:12px;min-height:16px}
</style></head>
<body>
  <h1>🪙 코인봇 대시보드</h1>
  <div class="gen" id="gen"></div>

  <div class="sec" id="reviewbox" style="display:none">
    <h2>🔍 과거 매매 리뷰 — 표에서 행 클릭. 채점(1/2/3)하면 자동으로 다음 것 · ←/→ 수동이동
      <span class="mut" id="reviewprog" style="font-size:12px;font-weight:400"></span></h2>
    <div class="chartbox"><svg id="reviewsvg" viewBox="0 0 900 260"></svg></div>
    <div class="cinfo" id="reviewinfo"></div>
    <div class="btns" id="gradebtns" style="display:none">
      <button class="btn bl" onclick="grade('ok')">✓ 나도 들어감 (1)</button>
      <button class="btn bc" onclick="grade('may')">? 애매 (2)</button>
      <button class="btn bs" onclick="grade('no')">✗ 난 안 침 (3)</button>
    </div>
    <div class="btns" id="navbtns" style="display:none;margin-top:8px">
      <button class="btn bc" onclick="goReview(-1)">← 이전</button>
      <button class="btn bc" onclick="goReview(1)">다음 →</button>
    </div>
    <div id="gmsg" class="mut" style="font-size:12px;margin-top:8px"></div>
  </div>

  <div class="sec" id="trade" style="display:none">
    <h2>✋ 모의매매 (버튼) — 차트 보고 진입/청산 누르면 기록됨</h2>
    <div class="chartbox"><svg id="chartsvg" viewBox="0 0 900 260"></svg></div>
    <div class="cinfo" id="cinfo">차트 불러오는 중…</div>
    <div class="aisig mut" id="aisig">🔔 AI 신호 확인 중…</div>
    <div class="px" id="tpx">현재가 …</div>
    <div class="st mut" id="tst">무포지션</div>
    <div class="btns">
      <button class="btn bl" id="bl" onclick="enter('long')">롱 진입</button>
      <button class="btn bs" id="bs" onclick="enter('short')">숏 진입</button>
      <button class="btn bc" id="bc" onclick="closeT()">청산 (기록)</button>
    </div>
    <div id="tmsg"></div>
  </div>

  <div id="app"></div>
<script>
const DATA = __DATA__;
const LIVE = __LIVE__;
document.getElementById('gen').textContent = '생성: ' + DATA.generated
  + (LIVE ? ' · 라이브(버튼 기록 가능)' : ' · 새로고침은 python report.py 다시');

function sign(v){return v>0?'up':(v<0?'dn':'')}
function spark(pts){
  if(!pts || pts.length<2) return '';
  const ys=pts.map(p=>p[1]), mn=Math.min(...ys), mx=Math.max(...ys), rng=(mx-mn)||1, w=800,h=120,st=w/(pts.length-1);
  const d=pts.map((p,i)=>`${(i*st).toFixed(1)},${(h-((p[1]-mn)/rng)*h).toFixed(1)}`).join(' ');
  const up=ys[ys.length-1]>=ys[0];
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${d}" fill="none" stroke="${up?'#3fb950':'#f85149'}" stroke-width="2"/></svg>`;
}
function card(l,v,cls){return `<div class="c"><div class="l">${l}</div><div class="v ${cls||''}">${v}</div></div>`}
function gradeIcon(g){return g==='ok'?'✓ ':g==='no'?'✗ ':g==='may'?'? ':'';}
function reviewClick(tr){
  const t=JSON.parse(tr.dataset.trade);
  reviewIndex = reviewQueue.findIndex(x=>x.source===t.source && x.et===t.et);
  reviewTrade(t);
}

function render(){
  const app=document.getElementById('app');
  app.innerHTML = DATA.sources.map(s=>{
    const st=s.stats;
    let cards='';
    if(!st.n){ cards=`<div class="empty">아직 데이터 없음 — 쌓이면 여기 채워져요</div>`; }
    else{
      const u = s.unit;
      cards = '<div class="cards">'
        + card('거래수', st.n)
        + card('승률', st.winrate+'%', st.winrate>=60?'up':(st.winrate<50?'dn':''))
        + card('평균이익', st.avg_win+u, 'up')
        + card('평균손실', st.avg_loss+u, 'dn')
        + card('손익비', st.pf??'-', (st.pf&&st.pf>=1)?'up':'dn')
        + card('누적', st.total+u, sign(st.total))
        + '</div>';
    }
    const eq = s.equity && s.equity.length>1 ? spark(s.equity) : '';
    let table='';
    if(s.rows && s.rows.length){
      const trades = s.trades || [];
      table = '<table><thead><tr>'+s.cols.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'
        + s.rows.map((r,i)=>({r,t:trades[i]})).slice().reverse().map(({r,t})=>{
            const clickable = t && t.et!=null;
            const attrs = clickable ? ` class="clkrow" data-trade='${JSON.stringify(t)}' onclick="reviewClick(this)"` : '';
            return '<tr'+attrs+'>'+r.map((c,i)=>{
              let cls=''; const cn=s.cols[i];
              if(cn&&(cn.includes('ROI')||cn.includes('손익'))){const n=parseFloat(String(c).replace(/[,%]/g,''));cls=sign(n);}
              const badge = (i===0 && t && t.grade) ? gradeIcon(t.grade) : '';
              return `<td class="${cls}">${badge}${c}</td>`;
            }).join('')+'</tr>';
          }).join('')
        + '</tbody></table>';
    }
    return `<div class="sec"><h2>${s.title}</h2>${eq}${cards}${table}</div>`;
  }).join('');
}
render();

// 채점 큐 — 소스 구분 없이 클릭 가능한 매매를 시간순으로 모아, 채점 후 '다음 것'으로 바로 넘어가게(grade_entries.py와 같은 흐름)
let reviewQueue = DATA.sources.flatMap(s=>(s.trades||[]).filter(t=>t && t.et!=null))
  .sort((a,b)=>a.et-b.et);
let reviewIndex = -1;

// ── 차트 (live_look.py 판정을 그대로 그림) ──
let lastChart=null, lastPrice=null, lastEntry=null, lastEntryTime=null;

// 캔들+수평선+핀(진입/청산 정확한 위치) 그리기 — 라이브차트/리뷰차트 공용
// pins: [{t: 캔들 시각(ms), price, color, label, dir:'up'|'down'(라벨을 점 위/아래 어느 쪽에 둘지)}]
function drawCandles(svg, candles, lines, pins){
  if(!svg || !candles || !candles.length){ if(svg) svg.innerHTML=''; return; }
  pins = pins || [];
  // viewBox를 실제 렌더 픽셀크기에 맞춤(=스케일 1:1) — 안 맞으면(예: preserveAspectRatio=none으로
  // 비율 다른 화면에 강제로 늘림) 글자가 가로로 뭉개져 보임. 화면 폭이 바뀔 때마다 다시 계산.
  const W = svg.clientWidth || 900, H = svg.clientHeight || 260, PAD=14;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const vals=[...candles.map(c=>c.l), ...candles.map(c=>c.h), ...lines.map(l=>l.price), ...pins.map(p=>p.price)];
  const lo=Math.min(...vals), hi=Math.max(...vals), rng=(hi-lo)||1;
  const y=p=>H-PAD-((p-lo)/rng)*(H-2*PAD);
  const cw=W/candles.length;
  const parts=[];
  candles.forEach((c,i)=>{
    const x=i*cw+cw/2, up=c.c>=c.o, col=up?'#3fb950':'#f85149';
    parts.push(`<line x1="${x}" x2="${x}" y1="${y(c.h).toFixed(1)}" y2="${y(c.l).toFixed(1)}" stroke="${col}" stroke-width="1"/>`);
    const yo=y(c.o), yc=y(c.c), top=Math.min(yo,yc), hgt=Math.max(1,Math.abs(yo-yc));
    parts.push(`<rect x="${(x-cw*0.32).toFixed(1)}" y="${top.toFixed(1)}" width="${(cw*0.64).toFixed(1)}" height="${hgt.toFixed(1)}" fill="${col}"/>`);
  });
  lines.forEach(l=>{
    const yy=y(l.price).toFixed(1);
    parts.push(`<line x1="0" x2="${W}" y1="${yy}" y2="${yy}" stroke="${l.color}" stroke-width="1" stroke-dasharray="${l.dash??'4,3'}" opacity="0.85"/>`);
    if(l.label){
      const right = l.align==='right';
      parts.push(`<text x="${right?W-4:4}" y="${(y(l.price)+(right?-3:11)).toFixed(1)}" fill="${l.color}" font-size="10" text-anchor="${right?'end':'start'}">${l.label}</text>`);
    }
  });
  // 핀 — 진입/청산이 실제로 일어난 그 캔들 위치에 점 찍고 라벨 붙임(가격라인만으론 '어디서'가 안 보여서)
  pins.forEach(p=>{
    let idx=0, best=Infinity;
    candles.forEach((c,i)=>{ const diff=Math.abs(c.t-p.t); if(diff<best){best=diff; idx=i;} });
    const x=(idx*cw+cw/2).toFixed(1), py=y(p.price);
    const up = p.dir!=='down';
    const stemY=(up? py-16 : py+16).toFixed(1);
    parts.push(`<line x1="${x}" x2="${x}" y1="${py.toFixed(1)}" y2="${stemY}" stroke="${p.color}" stroke-width="1.5"/>`);
    parts.push(`<circle cx="${x}" cy="${py.toFixed(1)}" r="4.5" fill="${p.color}" stroke="#0d1117" stroke-width="1.5"/>`);
    parts.push(`<text x="${x}" y="${(up? py-20 : py+28).toFixed(1)}" fill="${p.color}" font-size="10.5" font-weight="700" text-anchor="middle">${p.label}</text>`);
  });
  svg.innerHTML=parts.join('');
}

function renderChart(d, curPrice, entryPrice, entryTime){
  if(!d || !d.candles) return;
  const lines=[
    {price:d.recent_high, color:'#f85149', label:'저항 '+d.recent_high.toLocaleString()},
    {price:d.recent_low, color:'#3fb950', label:'지지 '+d.recent_low.toLocaleString()},
  ];
  if(curPrice) lines.push({price:curPrice, color:'#58a6ff', dash:'0'});
  const pins=[];
  if(entryPrice && entryTime){
    pins.push({t:entryTime, price:entryPrice, color:'#d29922', label:'진입 '+entryPrice.toLocaleString(), dir:'up'});
  }else if(entryPrice){
    // 진입시각을 못 구했을 때 폴백(핀 위치 못 잡음) — 가격 라인만이라도 표시
    lines.push({price:entryPrice, color:'#d29922', dash:'2,2', label:'진입 '+entryPrice.toLocaleString(), align:'right'});
  }
  drawCandles(document.getElementById('chartsvg'), d.candles, lines, pins);
}

// ── 과거 매매 리뷰(표 행 클릭) + 채점(grade_entries.py와 같은 어휘: ok/may/no) ──
let currentReview=null, lastReview=null;

async function reviewTrade(t){
  currentReview=t;
  const box=document.getElementById('reviewbox');
  box.style.display='';
  box.scrollIntoView({behavior:'smooth', block:'start'});
  const info=document.getElementById('reviewinfo');
  const gmsg=document.getElementById('gmsg');
  gmsg.textContent = t.grade ? `기존 채점: ${gradeLabel(t.grade)} (다시 누르면 갱신)` : '';
  document.getElementById('gradebtns').style.display='';
  document.getElementById('navbtns').style.display='';
  document.getElementById('reviewprog').textContent =
    reviewIndex>=0 ? `· ${reviewIndex+1} / ${reviewQueue.length}` : '';
  info.textContent='불러오는 중…';
  const {et, ep, xt, xp, label} = t;
  const hasExit = xt!=null;
  const center = hasExit ? Math.round((et+xt)/2) : et;
  const spanMin = hasExit ? Math.max(180, Math.round((xt-et)/60000)*3+60) : 240;
  let d; try{ d=await (await fetch(`/api/history?center=${center}&mins=${spanMin}`)).json(); }
  catch(e){ info.textContent='불러오기 실패'; return; }
  if(!d.candles || !d.candles.length){
    document.getElementById('reviewsvg').innerHTML='';
    info.textContent=`${label} — 로컬에 쌓인 데이터 범위 밖(그 시점 캔들 없음)`;
    return;
  }
  const pins=[{t:et, price:ep, color:'#d29922', label:'진입 '+Number(ep).toLocaleString(), dir:'up'}];
  if(hasExit) pins.push({t:xt, price:xp, color:'#58a6ff', label:'청산 '+Number(xp).toLocaleString(), dir:'down'});
  lastReview={candles:d.candles, lines:[], pins};
  drawCandles(document.getElementById('reviewsvg'), d.candles, [], pins);
  info.innerHTML = `<b>${label}</b>`;
}

// 차트 박스 크기 바뀔 때(모서리 드래그로 직접 리사이즈 · 창 리사이즈 · 회전) 재요청 없이
// 캐시된 데이터로 다시 그림(ResizeObserver라 element 자체의 resize 핸들 조작도 잡힘)
let resizeTimer=null;
const chartResizeObserver = new ResizeObserver(()=>{
  clearTimeout(resizeTimer);
  resizeTimer=setTimeout(()=>{
    if(lastChart) renderChart(lastChart, lastPrice, lastEntry, lastEntryTime);
    if(lastReview) drawCandles(document.getElementById('reviewsvg'), lastReview.candles, lastReview.lines, lastReview.pins);
  }, 100);
});
chartResizeObserver.observe(document.getElementById('chartsvg'));
chartResizeObserver.observe(document.getElementById('reviewsvg'));

function gradeLabel(g){ return g==='ok' ? '✓ 나도 들어감' : g==='no' ? '✗ 난 안 침' : '? 애매'; }

function goReview(delta){
  const ni = reviewIndex + delta;
  if(ni<0 || ni>=reviewQueue.length) return;
  reviewIndex = ni;
  reviewTrade(reviewQueue[reviewIndex]);
}

async function grade(g){
  if(!currentReview) return;
  const t=currentReview;
  const gmsg=document.getElementById('gmsg');
  gmsg.textContent='기록 중…';
  try{
    await fetch('/api/grade', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({source:t.source, et:t.et, side:t.side, ep:t.ep, xp:t.xp, label:t.label, grade:g})});
    t.grade=g;
    if(reviewIndex>=0 && reviewIndex<reviewQueue.length-1){
      gmsg.textContent=`채점 완료: ${gradeLabel(g)} — 다음으로 이동…`;
      setTimeout(()=>goReview(1), 180);   // grade_entries.py와 같은 자동 다음이동
    }else{
      gmsg.textContent=`채점 완료: ${gradeLabel(g)} — 마지막까지 다 봤음`;
    }
  }catch(e){ gmsg.textContent='기록 실패'; }
}

document.addEventListener('keydown', e=>{
  if(!currentReview) return;
  if(e.key==='1') grade('ok'); else if(e.key==='2') grade('may'); else if(e.key==='3') grade('no');
  else if(e.key==='ArrowLeft') goReview(-1); else if(e.key==='ArrowRight') goReview(1);
});

function updateChartInfo(d){
  document.getElementById('cinfo').innerHTML =
    `<b>${d.trend}</b> (MA5 ${d.ma_s.toLocaleString()} / MA20 ${d.ma_l.toLocaleString()}) · `+
    (d.coil ? '<b style="color:#3fb950">삼각수렴 — 힘 빠지는 중</b>' : '수렴 아님(힘 살아있음)');
}

async function loadChart(){
  if(!LIVE) return;
  let d; try{ d=await (await fetch('/api/chart')).json(); }catch(e){ return; }
  lastChart=d; updateChartInfo(d); renderChart(d, lastPrice, lastEntry, lastEntryTime);
}

// ── AI 신호(보조도구) — 사람이 보고 판단, 실행은 사람 몫 ──
async function loadSignal(){
  if(!LIVE) return;
  let d; try{ d=await (await fetch('/api/signal')).json(); }catch(e){ return; }
  const el=document.getElementById('aisig');
  if(d.signal){
    const long = d.side==='BUY';
    el.style.background = long ? 'rgba(63,185,80,.15)' : 'rgba(248,81,73,.15)';
    el.style.borderColor = long ? '#3fb950' : '#f85149';
    el.innerHTML = `🔔 <b>AI 신호: ${long?'롱':'숏'}</b> — ${d.reason} (판단·실행은 사람)`;
  }else{
    el.style.background=''; el.style.borderColor='';
    el.textContent = '지금은 신호 없음 — 기다리는 중';
  }
}

// ── 버튼식 모의매매 (LIVE에서만) ──
async function refresh(){
  if(!LIVE) return;
  let d; try{ d=await (await fetch('/api/price')).json(); }catch(e){ return; }
  document.getElementById('tpx').textContent = Number(d.price).toLocaleString();
  lastPrice = d.price; lastEntry = d.pos ? d.pos.entry : null;
  lastEntryTime = d.pos ? d.pos.entry_time_ms : null;
  if(lastChart) renderChart(lastChart, lastPrice, lastEntry, lastEntryTime);
  const st=document.getElementById('tst'), bl=document.getElementById('bl'),
        bs=document.getElementById('bs'), bc=document.getElementById('bc');
  if(d.pos){
    const p=d.pos, col=p.roi>0?'up':(p.roi<0?'dn':'mut');
    st.className='st '+col;
    st.textContent =
      `${p.side.toUpperCase()}  진입 ${Number(p.entry).toLocaleString()}\n`+
      `ROI(수수료후) : ${p.roi>0?'+':''}${p.roi}%\n`+
      `피크 ROI      : ${p.peak_roi>0?'+':''}${p.peak_roi}%\n`+
      `피크대비 되돌림: ${p.retrace}%p\n`+
      `손절가(-30%)  : ${Number(p.stop).toLocaleString()}  ${p.hit?'⚠ 도달':''}\n`+
      `왕복수수료    : 증거금 ${p.rt_fee}%`;
    bl.disabled=true; bs.disabled=true; bc.disabled=false;
  }else{
    st.className='st mut'; st.textContent='무포지션 — 진입 자리 오면 [롱]/[숏]';
    bl.disabled=false; bs.disabled=false; bc.disabled=true;
  }
}
async function enter(side){
  const r=await (await fetch('/api/enter?side='+side,{method:'POST'})).json();
  document.getElementById('tmsg').textContent=r.msg; refresh();
}
async function closeT(){
  const r=await (await fetch('/api/close',{method:'POST'})).json();
  document.getElementById('tmsg').textContent=r.msg+'  (새로고침하면 표에 반영)';
  refresh();
}
if(LIVE){ document.getElementById('trade').style.display=''; refresh(); loadChart(); loadSignal();
  setInterval(refresh,4000); setInterval(loadChart,20000); setInterval(loadSignal,20000); }
</script>
</body></html>
"""


def page_html(live: bool) -> str:
    data = build()
    return (HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
                .replace("__LIVE__", "true" if live else "false"))


# ───────────────────────── 서버 ─────────────────────────
def _lan_ip():
    """이 PC의 LAN IP(같은 와이파이에서 접속용). 외부연결 시도 없이 라우팅 테이블만 이용."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def _tailscale_ip():
    """테일스케일 IP(다른 네트워크에서도 접속용, COMET과 동일 방식). 없으면 None."""
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=3)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None


def serve():
    class H(BaseHTTPRequestHandler):
        def _send(self, body, ctype="application/json"):
            b = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    self._send(page_html(True), "text/html")
                elif path == "/api/price":
                    self._send(json.dumps(pos_state()))
                elif path == "/api/chart":
                    self._send(json.dumps(chart_data()))
                elif path == "/api/signal":
                    sig = live_signal()
                    log_signal_if_new(sig)
                    self._send(json.dumps(sig))
                elif path == "/api/history":
                    qs = parse_qs(urlparse(self.path).query)
                    center = int(qs.get("center", ["0"])[0])
                    mins = int(qs.get("mins", ["180"])[0])
                    self._send(json.dumps({"candles": history_candles(center, mins)}))
                else:
                    self.send_error(404)
            except Exception as e:
                self._send(json.dumps({"error": str(e)}))

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/api/enter":
                    side = parse_qs(u.query).get("side", ["long"])[0]
                    self._send(json.dumps(enter_trade("short" if side == "short" else "long")))
                elif u.path == "/api/close":
                    self._send(json.dumps(close_trade()))
                elif u.path == "/api/grade":
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length)) if length else {}
                    save_grade(payload)
                    self._send(json.dumps({"ok": True}))
                else:
                    self.send_error(404)
            except Exception as e:
                self._send(json.dumps({"ok": False, "msg": str(e)}))

        def log_message(self, *a):
            pass

    class Srv(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = None
    for port in range(PORT, PORT + 10):       # 점유 시 다음 빈 포트로
        try:
            srv = Srv(("0.0.0.0", port), H)   # 0.0.0.0 = 맥북 등 다른 기기에서도 접속 가능
            break
        except OSError:
            continue
    if srv is None:
        print(f"  빈 포트가 없음 ({PORT}~{PORT+9}). 다른 서버 끄고 다시 시도.")
        return
    lan, ts = _lan_ip(), _tailscale_ip()
    print(f"\n  대시보드 + 실시간차트 + AI신호 + 버튼 모의매매")
    print(f"  이 PC에서        : http://127.0.0.1:{port}/")
    if lan:
        print(f"  같은 와이파이에서(맥북 등): http://{lan}:{port}/")
    if ts:
        print(f"  테일스케일로(다른 네트워크에서도): http://{ts}:{port}/")
    print("  안 열리면 윈도우 방화벽이 python.exe 연결을 막았는지 확인(처음엔 허용 팝업 뜰 수 있음)")
    print("  멈추려면 Ctrl+C\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  종료.")


def main():
    if "--serve" in sys.argv:
        serve()
        return
    out = os.path.join(HERE, "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page_html(False))
    data = build()
    total = sum(s["stats"].get("n", 0) for s in data["sources"])
    print(f"대시보드 생성 → {out}")
    print(f"  로그 합계 {total}건 반영.  더블클릭으로 열기 (읽기전용).")
    print(f"  버튼으로 기록하려면: python report.py --serve")


if __name__ == "__main__":
    main()
