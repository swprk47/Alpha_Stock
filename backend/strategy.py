"""
strategy.py
10만원 시드머니 맞춤형 한국 주식 스윙(Swing) 매매 추천 엔진
- 1주당 단가 필터 (1,000원 ~ 50,000원)
- 기술적 분석: 5일/20일 이평선, RSI 눌림목, 거래량 모멘텀
- 자금 관리: 10만원 한도 내 분할 매수 수량 및 비중 산출
- 매수가, 목표가(익절), 손절가, 최대 보유 기한(Time-Stop) 제시
"""
import pandas as pd
import numpy as np
from datetime import datetime
import sys

# 콘솔 출력 시 한글 및 이모지 인코딩 보호
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def calculate_technical_indicators(df):
    """
    일봉 데이터프레임에 보조지표(MA5, MA20, MA60, RSI14, 볼린저밴드)를 계산하여 추가합니다.
    """
    if df is None or len(df) < 25:
        return None

    df = df.copy()

    # 1. 이동평균선 (5일, 20일, 60일)
    df["ma5"] = df["close"].rolling(window=5).mean()
    df["ma20"] = df["close"].rolling(window=20).mean()
    if len(df) >= 60:
        df["ma60"] = df["close"].rolling(window=60).mean()
    else:
        df["ma60"] = df["ma20"]

    # 2. 거래량 이동평균선 (5일)
    df["vol_ma5"] = df["volume"].rolling(window=5).mean()

    # 3. RSI (14일)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi14"] = 100 - (100 / (1 + rs))

    # 4. 볼린저 밴드 (20일, 2표준편차)
    std = df["close"].rolling(window=20).std()
    df["bb_upper"] = df["ma20"] + (std * 2)
    df["bb_lower"] = df["ma20"] - (std * 2)

    return df

def analyze_stock_for_swing(stock_info, candles_df):
    """
    개별 종목의 차트 패턴을 스윙 전략 관점에서 채점하고 매수 시그널을 분석합니다.
    - 골든크로스 / 5일선 > 20일선 정배열
    - RSI 35~65 사이의 눌림목 / 안정권
    - 최근 거래량 유입 여부
    """
    df = calculate_technical_indicators(candles_df)
    if df is None or len(df) < 20:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    current_price = stock_info["current_price"]
    ma5 = latest["ma5"]
    ma20 = latest["ma20"]
    rsi = latest["rsi14"]
    vol_ratio = (latest["volume"] / (latest["vol_ma5"] + 1)) if latest["vol_ma5"] > 0 else 1.0

    score = 0
    signals = []

    # 1. 이동평균선 정배열 및 지지
    if current_price >= ma20:
        score += 25
        signals.append("20일 중기 이평선 위 안정적 지지")
    
    if ma5 > ma20:
        score += 20
        signals.append("단기(5일)-중기(20일) 이평선 정배열")
    elif prev["ma5"] <= prev["ma20"] and ma5 > ma20:
        score += 30
        signals.append("🔥 5일/20일 골든크로스 발생")

    # 2. RSI 모멘텀 & 눌림목
    if 40 <= rsi <= 60:
        score += 25
        signals.append(f"RSI {rsi:.1f} - 과열 없는 이상적 눌림목 구간")
    elif 30 <= rsi < 40:
        score += 20
        signals.append(f"RSI {rsi:.1f} - 과매도 반등 기대 구간")
    elif rsi > 70:
        score -= 20  # 단기 과열 리스크

    # 3. 거래량 수급
    if vol_ratio >= 1.2:
        score += 20
        signals.append(f"거래량 급증 (5일 평균 대비 {vol_ratio*100:.0f}%)")
    elif vol_ratio >= 0.8:
        score += 10

    # 4. 볼린저 밴드 위치 (하단에서 반등하여 중심선 근처)
    if latest["bb_lower"] <= current_price <= latest["ma20"]:
        score += 10
        signals.append("볼린저 밴드 하단 지지 후 반등 진행")

    # 60점 이상이면 매수 추천 대상
    if score >= 60:
        return {
            "score": score,
            "rsi": round(rsi, 1),
            "vol_ratio": round(vol_ratio, 2),
            "signals": signals,
            "ma5": int(ma5),
            "ma20": int(ma20),
            "bb_upper": int(latest["bb_upper"]),
            "bb_lower": int(latest["bb_lower"])
        }
    return None

def get_stock_grade(stock_info, candles_df, budget=100000, is_fractional=False):
    """
    종목의 스윙 적합도를 S/A/B/C 4단계 등급으로 판정합니다.
    점수와 무관하게 항상 등급을 반환합니다 (검색 시 표시용).
    - S (≥80): 강력 매수 추천
    - A (≥60): 매수 추천
    - B (≥35): 중립 / 관망
    - C (<35): 비추천
    소수점 매수가 불가능하고 단가가 설정 예산을 초과하면 C로 지정.
    """
    current_price = stock_info.get("current_price", 0)

    # 소수점 매수가 불가능한데 주가가 예산(시드머니)을 초과하는 경우
    if not is_fractional and current_price > budget:
        return {
            "grade": "C",
            "score": 0,
            "grade_reasons": [f"단가({current_price:,}원) 예산 초과 — 소수점 미지원으로 매수 불가"]
        }

    df = calculate_technical_indicators(candles_df)
    if df is None or len(df) < 20:
        return {
            "grade": "N/A",
            "score": 0,
            "grade_reasons": ["데이터 부족으로 분석 불가"]
        }

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    ma5 = latest["ma5"]
    ma20 = latest["ma20"]
    rsi = latest["rsi14"]
    vol_ratio = (latest["volume"] / (latest["vol_ma5"] + 1)) if latest["vol_ma5"] > 0 else 1.0

    score = 0
    reasons = []
    negatives = []

    # ── 이동평균선 ──────────────────────────────────────
    if current_price >= ma20:
        score += 25
        reasons.append("20일 이평선 위 안정 지지")

    golden_cross = (prev["ma5"] <= prev["ma20"]) and (ma5 > ma20)
    if golden_cross:
        score += 30
        reasons.append("골든크로스 발생 🔥")
    elif ma5 > ma20:
        score += 20
        reasons.append("5일/20일 정배열")
    else:
        negatives.append("역배열 하락 구간")

    # ── RSI ────────────────────────────────────────────
    if 40 <= rsi <= 55:
        score += 25
        reasons.append(f"RSI {rsi:.0f} — 이상적 눌림목")
    elif 55 < rsi <= 65:
        score += 15
        reasons.append(f"RSI {rsi:.0f} — 안정권")
    elif 30 <= rsi < 40:
        score += 20
        reasons.append(f"RSI {rsi:.0f} — 과매도 반등 기대")
    elif rsi > 70:
        score -= 20
        negatives.append(f"RSI {rsi:.0f} — 단기 과열 ⚠️")
    elif rsi < 30:
        score += 10
        reasons.append(f"RSI {rsi:.0f} — 극단 과매도")

    # ── 거래량 ─────────────────────────────────────────
    if vol_ratio >= 1.2:
        score += 20
        reasons.append(f"거래량 급증 ({vol_ratio*100:.0f}%)")
    elif vol_ratio >= 0.8:
        score += 10
    else:
        negatives.append("거래량 감소 수급 약세")

    # ── 볼린저 밴드 ────────────────────────────────────
    if latest["bb_lower"] <= current_price <= latest["ma20"]:
        score += 10
        reasons.append("볼린저 하단 지지 반등")

    # ── 등급 판정 ──────────────────────────────────────
    if score >= 80:
        grade = "S"
    elif score >= 60:
        grade = "A"
    elif score >= 35:
        grade = "B"
    else:
        grade = "C"

    # 이유 문구 조립 (긍정 우선, C등급엔 부정 이유도 포함)
    display_reasons = reasons[:2]
    if grade == "C" and negatives:
        display_reasons = negatives[:1] + reasons[:1]
    elif grade == "B" and not display_reasons:
        display_reasons = negatives[:1] if negatives else ["횡보 구간"]

    return {
        "grade": grade,
        "score": score,
        "grade_reasons": display_reasons if display_reasons else ["분석 데이터 부족"]
    }

def calculate_position_sizing(stock_info, budget=100000, max_allocation_ratio=0.5):
    """
    10만원 시드머니 기준으로 포트폴리오 비중 및 매수 수량을 계산합니다.
    - 기본 2종목 분산 (종목당 최대 50,000원 배정)
    - 단가가 5만원 초과면 1종목 몰빵 대신 제외
    - 목표가: +5% ~ +8% (스윙 목표)
    - 손절가: -3.0% (단기 손절선)
    - 최대 보유 기간: 5영업일 (Time-Stop)
    """
    price = stock_info["current_price"]
    if price > budget * max_allocation_ratio:
        # 단가가 5만원을 넘으면 단일 종목 한도 초과
        # 단, 10만원 이하이면 1주 매수 허용할 수도 있으나 리스크 분산을 위해 기본 5만원 기준
        allocated_budget = min(budget, price)
    else:
        allocated_budget = int(budget * max_allocation_ratio)

    quantity = allocated_budget // price
    if quantity < 1:
        quantity = 1  # 최소 1주

    total_cost = price * quantity
    if total_cost > budget:
        return None

    # 가격 전략 산출
    target_return_pct = 6.5  # 평균 목표 수익률 (+6.5%)
    stop_loss_pct = -3.0     # 손절 기준 (-3.0%)

    target_price = int(price * (1 + target_return_pct / 100))
    stop_loss_price = int(price * (1 + stop_loss_pct / 100))

    # 예상 순수익금 (거래세 0.18% 및 수수료 약 0.03% 차감 반영)
    expected_gain_krw = int(total_cost * ((target_return_pct - 0.21) / 100))
    expected_loss_krw = int(total_cost * ((abs(stop_loss_pct) + 0.21) / 100))
    risk_reward_ratio = round(abs(target_return_pct / stop_loss_pct), 2)

    return {
        "recommended_quantity": quantity,
        "total_cost": total_cost,
        "budget_ratio_pct": round((total_cost / budget) * 100, 1),
        "target_price": target_price,
        "target_return_pct": target_return_pct,
        "stop_loss_price": stop_loss_price,
        "stop_loss_pct": stop_loss_pct,
        "expected_gain_krw": expected_gain_krw,
        "expected_loss_krw": expected_loss_krw,
        "risk_reward_ratio": risk_reward_ratio,
        "max_hold_days": 5, # 최대 보유 5영업일 (대학생 라이프스타일 맞춤)
    }

def get_recommendations(candidate_stocks, candles_provider, budget=100000, top_n=3):
    """
    후보 종목들을 분석하여 10만원 시드에 가장 적합한 TOP N 추천 종목 리스트를 생성합니다.
    """
    recommendations = []

    for stock in candidate_stocks:
        candles_df = candles_provider(stock["code"])
        if candles_df is None:
            continue

        analysis = analyze_stock_for_swing(stock, candles_df)
        if analysis is None:
            continue

        sizing = calculate_position_sizing(stock, budget=budget)
        if sizing is None:
            continue

        # 최근 30일 종가 시계열 데이터 추출 (카카오페이/애플 스타일 인터랙티브 차트용)
        recent_candles = candles_df.tail(30)
        chart_data = {
            "dates": recent_candles["date"].dt.strftime("%m.%d").tolist(),
            "prices": recent_candles["close"].tolist(),
            "min_price": int(recent_candles["close"].min()),
            "max_price": int(recent_candles["close"].max()),
        }

        recommendations.append({
            "code": stock["code"],
            "name": stock["name"],
            "market": stock["market"],
            "current_price": stock["current_price"],
            "change_rate": stock["change_rate"],
            "trading_value_m": stock["trading_value_m"],
            "logo_url": stock.get("logo_url", ""),
            "score": analysis["score"],
            "rsi": analysis["rsi"],
            "signals": analysis["signals"],
            "chart_data": chart_data,
            "sizing": sizing
        })

    # 종합 스코어 및 손익비 순으로 정렬
    recommendations.sort(key=lambda x: (x["score"], x["sizing"]["risk_reward_ratio"]), reverse=True)
    return recommendations[:top_n]

if __name__ == "__main__":
    from market_data import get_market_candidate_stocks, get_stock_daily_candles

    print("Running recommendation engine test...")
    candidates = get_market_candidate_stocks(max_price=50000, min_trading_value_m=3000)
    print(f"Analyzing {len(candidates)} candidates...")

    # 상위 25개 종목을 대상으로 분석 실행
    recs = get_recommendations(candidates[:25], get_stock_daily_candles, budget=100000, top_n=3)

    print(f"\n🎯 [10만원 맞춤 실시간 스윙 추천 TOP {len(recs)}]")
    for i, r in enumerate(recs, 1):
        s = r["sizing"]
        print(f"\n{i}. {r['name']} ({r['code']}) - 점수: {r['score']}점")
        print(f"   현재가: {r['current_price']:,}원 ({r['change_rate']}%) | RSI: {r['rsi']}")
        print(f"   추천 매수: {s['recommended_quantity']}주 ({s['total_cost']:,}원, 예산의 {s['budget_ratio_pct']}%)")
        print(f"   익절 목표가: {s['target_price']:,}원 (+{s['target_return_pct']}%) -> 예상 순수익 +{s['expected_gain_krw']:,}원")
        print(f"   손절 기준가: {s['stop_loss_price']:,}원 ({s['stop_loss_pct']}%) -> 예상 손실 -{s['expected_loss_krw']:,}원")
        print(f"   최대 보유 기간: {s['max_hold_days']}영업일 (스윙)")
        print(f"   핵심 근거: {', '.join(r['signals'][:2])}")
