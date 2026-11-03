from bt_helpers import DATE, flat_rows, listing, make_frame, trending_rows
from backtest.signals import DayResult, Signal, daily_picks, evaluate, generate_signals, trading_dates
from strategy import analyze_stock_for_swing

RAW = ["open", "high", "low", "close", "volume"]


def test_evaluate_matches_the_app_function_on_the_same_window():
    f = make_frame(trending_rows(90))
    d = f.index[-1]
    st = {"code": "X", "name": "X", "current_price": int(f["close"].iloc[-1])}
    app = analyze_stock_for_swing(st, f[RAW].tail(60))
    sig = evaluate(f, "X", d, 100_000)
    assert app is not None and sig is not None and sig.score == app["score"]       # trending_rows 는 앱 점수 60 이상이어야 의미가 있다


def test_only_the_last_sixty_rows_matter():
    f = make_frame(trending_rows(90))
    d = f.index[-1]
    g = f.copy()
    g.iloc[5, g.columns.get_loc("close")] = 99_999                                   # 60봉 밖의 오래된 봉
    assert evaluate(f, "X", d, 100_000) == evaluate(g, "X", d, 100_000)


def test_analyze_is_injectable_and_called_with_the_close_as_current_price():
    f = make_frame(trending_rows(90))
    d = f.index[-1]
    seen = []
    evaluate(f, "X", d, 100_000, analyze=lambda st, df: (seen.append((st["current_price"], len(df))), None)[1])
    assert seen == [(int(f["close"].iloc[-1]), 60)]


def test_vol_break_and_halt_days_are_skipped_without_calling_analyze():
    f = make_frame(trending_rows(90))
    d = f.index[-1]
    calls = []
    spy = lambda st, df: calls.append(1)
    f.loc[d, "vol_break"] = True
    assert evaluate(f, "X", d, 100_000, analyze=spy) is None
    f.loc[d, ["vol_break", "halt"]] = [False, True]
    assert evaluate(f, "X", d, 100_000, analyze=spy) is None
    assert calls == []


def test_short_history_gives_no_signal_and_does_not_crash():
    for n in (3, 24, 40):                                  # 25봉 미만은 앱 함수가 None, 그 이상은 예외 없이 동작
        f = make_frame(trending_rows(n))
        evaluate(f, "X", f.index[-1], 100_000)
    f = make_frame(flat_rows(24))
    assert evaluate(f, "X", f.index[-1], 100_000) is None


def test_daily_picks_sorted_by_score_then_risk_reward_and_top_n():
    mk = lambda code, score: Signal(code, DATE, score, 2.17, 100_000)
    day = DayResult(DATE, list("ABCD"), sorted([mk("A", 65), mk("B", 70), mk("C", 60), mk("D", 70)], key=lambda s: (-s.score, -s.risk_reward)))
    assert [s.code for s in daily_picks(day)] == ["B", "D", "A"] and len(daily_picks(day, None)) == 4


def test_generate_signals_uses_the_pool_and_reports_it():
    frames = {c: make_frame(flat_rows(90, volume=300_000)) for c in "ABC"}
    only_b = lambda st, df: {"score": 70} if st["code"] == "B" else None
    days = generate_signals(listing("ABC"), frames, 100_000, [frames["A"].index[-1]], analyze=only_b)
    assert days[0].pool == ["A", "B", "C"] and [s.code for s in days[0].signals] == ["B"]


def test_trading_dates_drops_the_warmup():
    frames = {"A": make_frame(flat_rows(70)), "B": make_frame(flat_rows(75), start="2026-01-05")}
    dates = trading_dates(frames, warmup=60)
    assert len(dates) == 75 - 60 and dates == sorted(dates)
