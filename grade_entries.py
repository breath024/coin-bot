"""진입 채점 도구 — 봇이 친 자리를 호윤이 직접 ✓/✗/? 매긴다.

봇(10x, reg_ma 20)이 이번 구간에 친 진입들을 뽑아, 각 자리의 전후 봉을
캔들차트로 그려 단일 HTML로 만든다. 호윤이 차트만 보고
  ✓ = 나도 들어갔다 / ✗ = 난 안 친다 / ? = 애매
를 매기면, 그 갭이 곧 '봇 vs 나' 보정 목록 = 80% 승률의 숨은 규칙.

    python grade_entries.py [cutoff_open_time_ms]
→ grade_entries.html 생성 (더블클릭). 채점 후 '결과 복사'로 떠서 붙여넣으면 분석.
"""
import json
import os
import sys

from account import FuturesAccount
from binance_feed import ListFeed
from broker import FuturesBroker
from engine import FuturesEngine
from strategy import MomentumDip
from run_window import load_bars, DEFAULT_CUTOFF, INITIAL

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "grade_entries.html")
BEFORE, AFTER = 30, 12          # 진입 전 30봉 ~ 청산 후 12봉(미청산이면 진입+40봉)


def collect(bars, mode="consec"):
    idx = {b.dt: i for i, b in enumerate(bars)}
    broker = FuturesBroker(leverage=10, margin_fraction=0.05, stop_on_margin=0.30,
                           taker_fee=0.0004, slippage=0.0002)
    eng = FuturesEngine(ListFeed(bars), MomentumDip("BTCUSDT", sweep_mode=mode), broker,
                        FuturesAccount(INITIAL)).run()
    # ENTRY ↔ 다음 EXIT 페어링 (한 번에 한 포지션)
    pairs, cur = [], None
    for f in eng.fills:
        if f.kind == "ENTRY":
            cur = {"t": f.dt, "dir": f.side.value, "reason": f.reason, "ep": f.price}
        elif cur is not None:
            cur.update(xt=f.dt, xp=f.price, pnl=f.pnl, xk=f.kind)
            pairs.append(cur)
            cur = None
    if cur is not None:
        cur.update(xt=None, xp=None, pnl=None, xk="미청산")
        pairs.append(cur)

    out = []
    for n, e in enumerate(pairs):
        ei = idx.get(e["t"])
        if ei is None:
            continue
        xi = idx.get(e["xt"]) if e["xt"] else None
        end = (xi + AFTER) if xi is not None else (ei + 40)
        s, en = max(0, ei - BEFORE), min(len(bars), end)
        sl = bars[s:en]
        out.append({
            "id": n + 1,
            "time": e["t"].strftime("%m/%d %H:%M"),
            "dir": e["dir"],
            "reason": e["reason"],
            "ep": e["ep"],
            "xtime": e["xt"].strftime("%m/%d %H:%M") if e["xt"] else None,
            "xp": e["xp"],
            "xk": e["xk"],
            "pnl": round(e["pnl"]) if e["pnl"] is not None else None,
            "ei": ei - s,
            "xi": (xi - s) if xi is not None else None,
            "bars": [{"t": b.dt.strftime("%H:%M"), "o": b.open, "h": b.high,
                      "l": b.low, "c": b.close} for b in sl],
        })
    return out


def main():
    argv = sys.argv[1:]
    mode = "path" if "path" in argv else "consec"
    nums = [a for a in argv if a.isdigit()]
    cutoff = int(nums[0]) if nums else DEFAULT_CUTOFF
    bars = load_bars(cutoff)
    data = collect(bars, mode)
    print(f"(스윕 모드: {mode})")
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__SPAN__", f"{bars[0].dt:%m/%d %H:%M} ~ {bars[-1].dt:%m/%d %H:%M}")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n진입 {len(data)}자리 -> {OUT}")
    print("더블클릭해서 열고, 각 자리마다 차트 보고 [나도 들어감]/[난 안 침]/[애매] 채점.")
    print("키보드: 1=들어감  2=애매  3=안침  화살표=이동.  다 하면 '결과 복사' 눌러 붙여넣기.")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>봇 진입 채점 — 봇 vs 나</title>
<style>
  :root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--mut:#8b949e;
        --up:#26a69a;--dn:#ef5350;--yel:#f5c518;--ok:#2ea043;--no:#da3633;--may:#9e6a03;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,sans-serif}
  .wrap{max-width:960px;margin:0 auto;padding:20px}
  h1{font-size:18px;margin:0 0 4px}
  .sub{color:var(--mut);font-size:13px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:14px}
  .meta{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;margin-bottom:10px}
  .dir{font-weight:700;padding:2px 10px;border-radius:6px}
  .long{background:rgba(38,166,154,.18);color:var(--up)}
  .short{background:rgba(239,83,80,.18);color:var(--dn)}
  .reason{color:var(--mut);font-size:13px}
  .pnl-pos{color:var(--up);font-weight:600}.pnl-neg{color:var(--dn);font-weight:600}
  .pnl-open{color:var(--yel);font-weight:600}
  canvas{width:100%;height:380px;display:block;background:#0a0e14;border-radius:8px}
  .btns{display:flex;gap:10px;margin-top:14px}
  .btns button{flex:1;padding:12px;border:1px solid var(--line);border-radius:8px;
        background:#21262d;color:var(--fg);font-size:15px;font-weight:600;cursor:pointer}
  .btns button:hover{filter:brightness(1.2)}
  .btns .sel.ok{background:var(--ok);border-color:var(--ok)}
  .btns .sel.no{background:var(--no);border-color:var(--no)}
  .btns .sel.may{background:var(--may);border-color:var(--may)}
  .nav{display:flex;justify-content:space-between;align-items:center;margin-top:16px}
  .nav button{padding:9px 18px;border:1px solid var(--line);border-radius:8px;background:#21262d;color:var(--fg);cursor:pointer}
  .prog{color:var(--mut)}
  textarea{width:100%;height:120px;background:#0a0e14;color:var(--fg);border:1px solid var(--line);
        border-radius:8px;padding:10px;font-family:monospace;font-size:12px;margin-top:8px;display:none}
  .tools{display:flex;gap:10px;margin-top:14px}
  .tools button{padding:9px 16px;border:1px solid var(--line);border-radius:8px;background:#21262d;color:var(--fg);cursor:pointer}
  .tally{color:var(--mut);font-size:13px;margin-left:auto;align-self:center}
  .memo{width:100%;margin-top:10px;background:#0a0e14;color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px;font-size:13px}
</style></head>
<body><div class="wrap">
  <h1>봇 진입 채점 — 봇 vs 나</h1>
  <div class="sub">구간 __SPAN__ · 봇(10x)이 친 자리를 차트만 보고 매겨줘. <b>1</b>=나도 들어감 · <b>2</b>=애매 · <b>3</b>=난 안 침 · ←/→ 이동</div>
  <div class="card" id="card">
    <div class="meta" id="meta"></div>
    <canvas id="cv" width="1840" height="760"></canvas>
    <div class="btns">
      <button id="b1" onclick="grade('ok')">✓ 나도 들어감 (1)</button>
      <button id="b2" onclick="grade('may')">? 애매 (2)</button>
      <button id="b3" onclick="grade('no')">✗ 난 안 침 (3)</button>
    </div>
    <input class="memo" id="memo" placeholder="메모(선택): 왜 안 치는지 / 어디서 끊을지 — 적으면 보정에 큰 도움">
    <div class="nav">
      <button onclick="go(-1)">← 이전</button>
      <span class="prog" id="prog"></span>
      <button onclick="go(1)">다음 →</button>
    </div>
  </div>
  <div class="tools">
    <button onclick="exportRes()">결과 복사</button>
    <button onclick="if(confirm('채점 초기화?')){localStorage.removeItem(KEY);location.reload()}">초기화</button>
    <span class="tally" id="tally"></span>
  </div>
  <textarea id="out" readonly></textarea>
</div>
<script>
const DATA = __DATA__;
const KEY = "grade_v1";
let i = 0;
let res = JSON.parse(localStorage.getItem(KEY) || "{}");

function save(){ localStorage.setItem(KEY, JSON.stringify(res)); }
function rec(id){ return res[id] || {v:null, memo:""}; }
function stashMemo(){ const e=DATA[i]; if(!e)return; const r=rec(e.id);
  r.memo=document.getElementById("memo").value; res[e.id]=r; save(); }

function draw(e){
  const cv = document.getElementById("cv"), x = cv.getContext("2d");
  const W = cv.width, H = cv.height, padL=70, padR=20, padT=20, padB=28;
  x.clearRect(0,0,W,H);
  const bs = e.bars, n = bs.length;
  let lo=Infinity, hi=-Infinity;
  bs.forEach(b=>{lo=Math.min(lo,b.l);hi=Math.max(hi,b.h)});
  const pad=(hi-lo)*0.08; lo-=pad; hi+=pad;
  const px=i2=>padL+(W-padL-padR)*(i2+0.5)/n;
  const py=p=>padT+(H-padT-padB)*(hi-p)/(hi-lo);
  // grid + price labels
  x.strokeStyle="#1c2330"; x.fillStyle="#8b949e"; x.font="20px monospace"; x.textAlign="right";
  for(let k=0;k<=4;k++){const p=lo+(hi-lo)*k/4, y=py(p);
    x.beginPath();x.moveTo(padL,y);x.lineTo(W-padR,y);x.stroke();
    x.fillText(p.toFixed(0), padL-8, y+6);}
  // entry / exit markers
  function vline(idx,col,lbl,top){ if(idx==null)return;
    const xx=px(idx); x.strokeStyle=col; x.setLineDash([6,5]);
    x.beginPath();x.moveTo(xx,padT);x.lineTo(xx,H-padB);x.stroke(); x.setLineDash([]);
    x.fillStyle=col; x.textAlign="center"; x.font="bold 22px sans-serif";
    x.fillText(lbl, xx, top?padT+22:H-padB-8); }
  vline(e.ei, "#f5c518", "진입", true);
  vline(e.xi, "#8b949e", "청산", false);
  // candles
  const cw = Math.max(2, (W-padL-padR)/n*0.6);
  bs.forEach((b,k)=>{
    const up=b.c>=b.o, col=up?"#26a69a":"#ef5350", xx=px(k);
    x.strokeStyle=col; x.fillStyle=col; x.lineWidth=1;
    x.beginPath();x.moveTo(xx,py(b.h));x.lineTo(xx,py(b.l));x.stroke();
    const yo=py(b.o), yc=py(b.c);
    x.fillRect(xx-cw/2, Math.min(yo,yc), cw, Math.max(2,Math.abs(yc-yo)));
  });
}

function render(){
  const e = DATA[i];
  if(!e){document.getElementById("meta").innerHTML="채점할 진입이 없음";return;}
  let pnl;
  if(e.pnl==null) pnl=`<span class="pnl-open">미청산(열린 채 끝)</span>`;
  else pnl=`<span class="${e.pnl>=0?'pnl-pos':'pnl-neg'}">${e.pnl>=0?'+':''}${e.pnl.toLocaleString()}원 (${e.xk})</span>`;
  document.getElementById("meta").innerHTML =
    `<span class="dir ${e.dir=='BUY'?'long':'short'}">${e.dir=='BUY'?'롱':'숏'}</span>`+
    `<b>#${e.id}</b> 진입 ${e.time} @ ${e.ep.toLocaleString()}`+
    (e.xtime?` → 청산 ${e.xtime} @ ${e.xp.toLocaleString()}`:``)+
    ` · ${pnl} · <span class="reason">${e.reason}</span>`;
  draw(e);
  const r = rec(e.id);
  document.getElementById("memo").value = r.memo||"";
  for(const [bid,v] of [["b1","ok"],["b2","may"],["b3","no"]]){
    const el=document.getElementById(bid);
    el.className = (r.v===v)?("sel "+v):"";
  }
  document.getElementById("prog").textContent = `${i+1} / ${DATA.length}`;
  tally();
}
function grade(v){
  stashMemo();
  const e=DATA[i]; const r=rec(e.id); r.v=v; res[e.id]=r; save(); render();
  setTimeout(()=>{ if(i<DATA.length-1) go(1); },180);
}
function go(d){ stashMemo(); i=Math.max(0,Math.min(DATA.length-1,i+d)); render(); }
function tally(){
  let ok=0,no=0,may=0,done=0;
  DATA.forEach(e=>{const v=rec(e.id).v; if(v){done++; if(v=='ok')ok++; else if(v=='no')no++; else may++;}});
  document.getElementById("tally").textContent=`채점 ${done}/${DATA.length} · ✓${ok} ?${may} ✗${no}`;
}
function exportRes(){
  const rows=[["id","진입시각","방향","손익","봇사유","판정","메모"]];
  const map={ok:"나도들어감",no:"난안침",may:"애매"};
  DATA.forEach(e=>{const r=rec(e.id);
    rows.push([e.id,e.time,e.dir=='BUY'?'롱':'숏',e.pnl==null?'미청산':e.pnl,
      e.reason, r.v?map[r.v]:"미채점", (r.memo||"").replace(/\t/g," ")]);});
  const txt=rows.map(r=>r.join("\t")).join("\n");
  const ta=document.getElementById("out"); ta.style.display="block"; ta.value=txt;
  ta.select(); try{document.execCommand("copy");}catch(_){}
  alert("결과가 복사됐어 (아래 표에도 떴음). 클로드한테 붙여넣으면 분석해줌.");
}
document.addEventListener("keydown",ev=>{
  if(ev.target.tagName==="INPUT")return;
  if(ev.key=="1")grade("ok"); else if(ev.key=="2")grade("may"); else if(ev.key=="3")grade("no");
  else if(ev.key=="ArrowLeft")go(-1); else if(ev.key=="ArrowRight")go(1);
});
document.getElementById("memo").addEventListener("input", stashMemo);  // 타이핑 즉시 저장
window.addEventListener("beforeunload", stashMemo);                    // 닫기/새로고침 직전에도
render();
</script></body></html>
"""

if __name__ == "__main__":
    main()
