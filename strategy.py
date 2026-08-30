"""정호윤 매매법 (코인 선물, 롱/숏, 멀티 타임프레임) — 4차: 눌림 소진(exhaustion) 진입.

호윤 본인 설명(원문):
  "추세봉 보고 반대 방향 봉이 나오면, 2~3봉 지켜보다가 그 반대움직임의 '힘이 빠지는
   순간'에 추세 방향으로 진입하고 기다린다. 아무리 세도 한탕이라 힘은 언젠가 빠진다."

번역(입력 = 1분봉):
  - 흐름(방향): 1분봉 15개를 묶은 15분 흐름의 추세 → 롱/숏 방향
  - 진입: 추세 반대 눌림이 시작되고(신저점/신고점 갱신), 그게 2~3봉 안에 '멈추는 순간'
          (= 힘 빠짐)에 추세 방향으로 진입
  - 청산: 1분 트레일링(승자 길게, 되돌리면 컷) + 브로커 -30% 손절/청산

  ★ = 보정 대상(max_wait 등). import_trades/analyze_entries로 실거래에 맞춤.
"""
from collections import deque

from account import FuturesAccount
from broker import FuturesBroker
from core import Bar, Side


class MomentumDip:
    def __init__(self, symbol: str,
                 htf_group: int = 15,       # 1분봉 몇 개 = 상위 흐름봉
                 regime_ma: int = 20,       # 15분 흐름 추세 이평 (trend_mode="ma"일 때)
                 trend_mode: str = "swing", # "swing"(저점높아짐·고점낮아짐 구조, 기본) / "ma"(5h 이평)  ★
                 swing_n: int = 3,          # swing 판정: 흐름봉 저/고점을 몇 개 연속 보는가  ★
                 max_wait: int = 3,         # 훼이크 스파이크가 진행되는 최대 봉수(2~3봉)  ★
                 sweep_pct: float = 0.004,  # 훼이크 스파이크 최소 깊이 0.4% (청산사냥 크기)  ★
                 flat_pct: float = 0.0015,  # '거의 고정' 판정: 멈춤봉 범위 ≤ 0.15%          ★
                 trail_pct: float = 0.0010, # 1분 트레일링 청산 0.10%                      ★
                 min_hold_bars: int = 0,    # 진입 후 최소 유지 봉수(=분) — 이전엔 트레일 평가 안 함 ★
                 exit_mode: str = "trail",  # "trail"(재량 트레일링) / "oco"(손절·익절 동시예약, 재량개입 X=금붕어) ★
                 sweep_mode: str = "consec",# "consec"(연속 신저점 누적) / "path"(창 내 최대낙폭=지그재그 허용) ★
                 path_win: int = 6,         # path 모드 스윕 측정 창(봉)                    ★
                 trend_align: bool = False, # True=직전 align_lb봉 추세와 같은 방향만 진입(역행 거름) ★
                 align_lb: int = 30,        # 추세정렬 판정 룩백(1분봉 수)                  ★
                 sr_filter: bool = False,   # True=S/R 레벨 필터: 천장권 롱·바닥권 숏 거부   ★
                 sr_lookback: int = 240,    # S/R 범위 탐색 1분봉 수(직전 N분 고저)          ★
                 sr_room: float = 0.15,     # 범위 끝 금지대 비율(0.15=상/하단 15%선 진입금지)★
                 allow_short: bool = True):
        self.symbol = symbol
        self.htf_group = htf_group
        self.regime_ma = regime_ma
        self.trend_mode = trend_mode
        self.swing_n = swing_n
        self.max_wait = max_wait
        self.sweep_pct = sweep_pct
        self.flat_pct = flat_pct
        self.trail_pct = trail_pct
        self.min_hold_bars = min_hold_bars
        self.exit_mode = exit_mode
        self.sweep_mode = sweep_mode
        self.path_win = path_win
        self.trend_align = trend_align
        self.align_lb = align_lb
        self.sr_filter = sr_filter
        self.sr_lookback = sr_lookback
        self.sr_room = sr_room
        self.allow_short = allow_short

        keep = max(regime_ma, swing_n) + 1
        self.htf_closes: deque = deque(maxlen=keep)
        self.htf_highs: deque = deque(maxlen=keep)   # swing용: 흐름봉 고점 시퀀스
        self.htf_lows: deque = deque(maxlen=keep)    # swing용: 흐름봉 저점 시퀀스
        self._htf_n = 0
        self._htf_close = 0.0
        self._htf_high = float("-inf")    # 형성 중 흐름봉의 고점
        self._htf_low = float("inf")      # 형성 중 흐름봉의 저점
        self._htf_ma_prev: float | None = None
        self._htf_trend = 0           # +1 상승흐름 / -1 하락흐름 / 0 횡보
        self._prev_low: float | None = None
        self._prev_high: float | None = None
        self._pb = 0                  # 훼이크 스파이크가 신극값 갱신을 이어간 봉 수
        self._pb_ref = 0.0            # 스파이크 시작 기준가(직전 극값)
        self._pb_ext = 0.0            # 스파이크 극값(롱=최저, 숏=최고)
        self._best = 0.0              # 진입 후 가장 유리했던 가격
        self._closes: deque = deque(maxlen=align_lb + 1)  # 추세정렬용 1분 종가 버퍼
        self._win: deque = deque(maxlen=path_win + 1)     # path 스윕용 (고,저) 창
        self._sr: deque = deque(maxlen=sr_lookback + 1)   # S/R 레벨용 (고,저) 창
        self._n = 0                   # 봉 카운터 (path 디바운스용)
        self._last_entry_n = -10 ** 9  # 마지막 진입 봉 인덱스
        self._pos_entry_n: int | None = None  # 현재 포지션이 '체결된' 봉 인덱스(min_hold_bars용)

    def _update_htf(self, bar: Bar) -> None:
        self._htf_close = bar.close
        self._htf_high = max(self._htf_high, bar.high)
        self._htf_low = min(self._htf_low, bar.low)
        self._htf_n += 1
        if self._htf_n < self.htf_group:
            return
        # 흐름봉 하나 완성 → 시퀀스에 적재하고 형성중 고저점 리셋
        self._htf_n = 0
        self.htf_closes.append(self._htf_close)
        self.htf_highs.append(self._htf_high)
        self.htf_lows.append(self._htf_low)
        self._htf_high, self._htf_low = float("-inf"), float("inf")
        if self.trend_mode == "swing":
            self._trend_swing()
        else:
            self._trend_ma()

    def _trend_ma(self) -> None:
        if len(self.htf_closes) < self.regime_ma:
            return
        ma = sum(list(self.htf_closes)[-self.regime_ma:]) / self.regime_ma
        if self._htf_ma_prev is not None:
            if self._htf_close > ma and ma > self._htf_ma_prev:
                self._htf_trend = 1
            elif self._htf_close < ma and ma < self._htf_ma_prev:
                self._htf_trend = -1
            else:
                self._htf_trend = 0
        self._htf_ma_prev = ma

    def _trend_swing(self) -> None:
        """호윤 방향규칙: 흐름봉 저점이 연속 높아지면(higher lows) 상승=롱편향,
        고점이 연속 낮아지면(lower highs) 하락=숏편향, 혼조는 횡보(0)→진입 안 함.
        '저점이 점점 높아지니까 롱', '고점 낮아짐' 메모를 그대로 옮긴 것."""
        if len(self.htf_lows) < self.swing_n:
            return
        lows = list(self.htf_lows)[-self.swing_n:]
        highs = list(self.htf_highs)[-self.swing_n:]
        higher_lows = all(lows[i] > lows[i - 1] for i in range(1, len(lows)))
        lower_highs = all(highs[i] < highs[i - 1] for i in range(1, len(highs)))
        if higher_lows and not lower_highs:
            self._htf_trend = 1
        elif lower_highs and not higher_lows:
            self._htf_trend = -1
        else:
            self._htf_trend = 0

    def _entry_consec(self, bar, prev_low, prev_high):
        """원래 방식: 연속 신저점/신고점 갱신을 누적해 스파이크 깊이를 잰다.
        지그재그로 갱신이 한 번 끊기면 _pb=0으로 리셋 → 눌림을 놓치는 빡빡함."""
        enter, waited, depth = None, 0, 0.0
        flat = ((bar.high - bar.low) / bar.close <= self.flat_pct) if bar.close else False
        if self._htf_trend == 1:                 # 상승흐름 → 하락 훼이크 스파이크 페이드 롱
            if bar.low < prev_low:               # 스파이크 신저점 갱신 중(힘 살아있음)
                if self._pb == 0:
                    self._pb_ref = prev_high     # 스파이크 시작 기준(직전 고점)
                    self._pb_ext = bar.low
                else:
                    self._pb_ext = min(self._pb_ext, bar.low)
                self._pb += 1
            else:                                # 신저점 갱신 멈춤 = 힘 빠짐
                if 1 <= self._pb <= self.max_wait:
                    depth = (self._pb_ref - self._pb_ext) / self._pb_ref
                    if depth >= self.sweep_pct and flat:   # 0.4%+ 스윕 후 고정
                        enter, waited = Side.BUY, self._pb
                self._pb = 0
        elif self._htf_trend == -1 and self.allow_short:   # 하락흐름 → 상승 훼이크 페이드 숏
            if bar.high > prev_high:             # 스파이크 신고점 갱신 중
                if self._pb == 0:
                    self._pb_ref = prev_low
                    self._pb_ext = bar.high
                else:
                    self._pb_ext = max(self._pb_ext, bar.high)
                self._pb += 1
            else:                                # 신고점 갱신 멈춤 = 힘 빠짐
                if 1 <= self._pb <= self.max_wait:
                    depth = (self._pb_ext - self._pb_ref) / self._pb_ref
                    if depth >= self.sweep_pct and flat:
                        enter, waited = Side.SELL, self._pb
                self._pb = 0
        return enter, waited, depth

    def _entry_path(self, bar, prev_low, prev_high):
        """창 내 최대낙폭으로 깊이 측정(연속 갱신 불요 = 지그재그 눌림 허용).
        직전봉 대비 신극값을 더는 안 만들면 '힘 빠짐'으로 본다. near_miss.py 완화판 이식."""
        if len(self._win) <= self.path_win:
            return None, 0, 0.0
        if self._n - self._last_entry_n <= self.path_win:   # 청산 직후 즉시 재진입 디바운스
            return None, 0, 0.0
        wb = list(self._win)[:-1]                # 현재봉 제외, 직전 path_win개 창
        highs = [h for h, _ in wb]
        lows = [l for _, l in wb]
        if self._htf_trend == 1:                 # 상승흐름 → 창 내 최대낙폭 = 페이드 롱
            ref, trough = max(highs), min(lows)
            depth = (ref - trough) / ref if ref else 0.0
            if depth >= self.sweep_pct and bar.low >= prev_low:   # 더는 신저점 안 만듦
                self._last_entry_n = self._n
                return Side.BUY, len(wb), depth
        elif self._htf_trend == -1 and self.allow_short:          # 하락흐름 → 창 내 최대상승폭 = 페이드 숏
            ref, peak = min(lows), max(highs)
            depth = (peak - ref) / ref if ref else 0.0
            if depth >= self.sweep_pct and bar.high <= prev_high:  # 더는 신고점 안 만듦
                self._last_entry_n = self._n
                return Side.SELL, len(wb), depth
        return None, 0, 0.0

    def on_bar(self, bar: Bar, account: FuturesAccount, broker: FuturesBroker) -> None:
        if bar.symbol != self.symbol:
            return
        self._n += 1
        self._closes.append(bar.close)   # 추세정렬용 종가 적재(보유 중에도 연속 유지)
        self._win.append((bar.high, bar.low))  # path 스윕용 창(보유 중에도 연속 유지)
        self._sr.append((bar.high, bar.low))   # S/R 레벨용 창(보유 중에도 연속 유지)
        self._update_htf(bar)
        prev_low, prev_high = self._prev_low, self._prev_high
        self._prev_low, self._prev_high = bar.low, bar.high   # 다음 봉을 위해 항상 갱신

        # === 보유 중: 청산 ===
        if account.position is not None:
            if self._pos_entry_n is None:
                self._pos_entry_n = self._n   # 포지션이 처음 관측된 봉 = 체결봉
            if self.exit_mode == "oco":
                return   # 금붕어 모드: 진입 시 건 손절·익절(broker)만 작동, 재량개입 금지
            # 1분 트레일링(지지부진) 청산
            pos = account.position
            if pos.side == Side.BUY:
                self._best = max(self._best, bar.high)
                retrace = (self._best - bar.close) / self._best
                in_profit = bar.close > pos.entry_price
            else:
                self._best = min(self._best, bar.low)
                retrace = (bar.close - self._best) / self._best
                in_profit = bar.close < pos.entry_price
            held = self._n - self._pos_entry_n   # 체결 후 경과 봉수(=분)
            if held >= self.min_hold_bars and in_profit and retrace >= self.trail_pct:
                broker.request_exit(f"지지부진 청산(되돌림 {retrace*100:.2f}%, 보유{held}분)")
            return

        # === 무포지션: 눌림 소진 진입 ===
        self._pos_entry_n = None   # 포지션 없음 → 다음 진입을 위해 리셋
        if prev_low is None or self._htf_trend == 0:
            self._pb = 0
            return

        if self.sweep_mode == "path":
            enter, waited, depth = self._entry_path(bar, prev_low, prev_high)
        else:
            enter, waited, depth = self._entry_consec(bar, prev_low, prev_high)

        # 추세정렬 필터(옵션): 직전 align_lb봉 추세와 같은 방향만 — 반등 중 숏/조정 중 롱(역행) 거름
        if enter is not None and self.trend_align and len(self._closes) > self.align_lb:
            past = self._closes[-1 - self.align_lb]
            tr = (bar.close - past) / past if past else 0.0
            if (enter == Side.BUY and tr <= 0) or (enter == Side.SELL and tr >= 0):
                enter = None

        # S/R 레벨 필터(옵션): 직전 sr_lookback분 범위의 천장권에선 롱, 바닥권에선 숏 거부.
        # 호윤 "이전 고점/저점 중시" — 6/9형 끝물 진입(저항 밑 롱)을 거른다.
        if enter is not None and self.sr_filter and len(self._sr) > self.htf_group:
            hl = list(self._sr)[:-1]                 # 현재봉 제외
            sup = min(l for _, l in hl)              # 지지 = 범위 최저
            res = max(h for h, _ in hl)              # 저항 = 범위 최고
            rng = res - sup
            if rng > 0:
                pos = (bar.close - sup) / rng        # 0=지지바닥, 1=저항천장
                if enter == Side.BUY and pos > 1 - self.sr_room:
                    enter = None                      # 천장권 롱 거부
                elif enter == Side.SELL and pos < self.sr_room:
                    enter = None                      # 바닥권 숏 거부

        if enter == Side.BUY:
            self._best = bar.high
            broker.request_entry(Side.BUY, f"상승흐름 훼이크페이드 롱(스윕 {depth*100:.2f}%,{waited}봉)")
        elif enter == Side.SELL:
            self._best = bar.low
            broker.request_entry(Side.SELL, f"하락흐름 훼이크페이드 숏(스윕 {depth*100:.2f}%,{waited}봉)")
