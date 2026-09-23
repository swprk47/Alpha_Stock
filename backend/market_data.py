"""
market_data.py
한국 주식 시장(KOSPI, KOSDAQ) 실시간 시세 및 캔들 데이터 수집 모듈
네이버 증권 공식 모바일 API 및 차트 API 연동
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://m.stock.naver.com/"
}

def get_market_candidate_stocks(max_price=50000, min_price=1000, min_trading_value_m=2000):
    """
    KOSPI 및 KOSDAQ에서 10만원 시드에 적합한 가격대와 충분한 거래대금을 갖춘 종목군을 수집합니다.
    - max_price: 최대 단가 (기본 50,000원 -> 10만원으로 최소 2종목 분산 가능)
    - min_price: 최소 단가 (기본 1,000원 -> 동전주 배제)
    - min_trading_value_m: 최소 거래대금 (기본 2,000백만원 = 20억원 -> 거래량 없는 소외주 배제)
    """
    candidates = []
    seen_codes = set()

    for market in ["KOSPI", "KOSDAQ"]:
        # 시총 및 유동성 상위 150개씩 탐색 (페이지당 50개 x 3페이지)
        for page in range(1, 4):
            url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=50"
            try:
                res = requests.get(url, headers=HEADERS, timeout=5)
                if res.status_code != 200:
                    continue
                data = res.json()
                stocks = data.get("stocks", [])
                for s in stocks:
                    code = s.get("itemCode")
                    if not code or code in seen_codes:
                        continue

                    # 거래정지 종목 제외
                    trade_status = s.get("tradableStatus", "")
                    if trade_status != "tradable":
                        continue

                    def safe_int(val, default=0):
                        if isinstance(val, (int, float)):
                            return int(val)
                        if isinstance(val, str):
                            cleaned = val.replace(",", "").strip()
                            if cleaned.isdigit() or (cleaned.startswith('-') and cleaned[1:].isdigit()):
                                return int(cleaned)
                        return default

                    price = safe_int(s.get("closePriceRaw", 0))
                    if price == 0:
                        price = safe_int(s.get("closePrice", "0"))

                    trading_value_raw = safe_int(s.get("accumulatedTradingValueRaw", 0))
                    trading_value_m = trading_value_raw // 1_000_000 if trading_value_raw else 0

                    try:
                        change_rate = float(str(s.get("fluctuationsRatio", 0.0)).replace(",", ""))
                    except Exception:
                        change_rate = 0.0

                    # 10만원 예산 필터 및 거래대금 필터
                    if min_price <= price <= max_price and trading_value_m >= min_trading_value_m:
                        seen_codes.add(code)
                        candidates.append({
                            "code": code,
                            "name": s.get("stockName", ""),
                            "current_price": price,
                            "change_rate": change_rate,
                            "trading_value_m": trading_value_m,
                            "volume": s.get("accumulatedTradingVolumeRaw", 0),
                            "market": market,
                            "logo_url": s.get("itemLogoPngUrl", "") or s.get("itemLogoUrl", "")
                        })
            except Exception as e:
                print(f"Error fetching {market} page {page}: {e}")

    return candidates

def get_stock_daily_candles(code, count=60):
    """
    네이버 차트 API를 통해 종목의 최근 일봉 캔들 데이터(count일)를 수집하여
    이동평균선 및 보조지표 계산용 DataFrame으로 반환합니다.
    """
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        soup = BeautifulSoup(res.text, "xml")
        chartdata = soup.find("chartdata")
        if not chartdata:
            return None

        items = chartdata.find_all("item")
        records = []
        for item in items:
            data = item["data"].split("|")
            if len(data) >= 6:
                records.append({
                    "date": data[0],
                    "open": int(data[1]),
                    "high": int(data[2]),
                    "low": int(data[3]),
                    "close": int(data[4]),
                    "volume": int(data[5])
                })

        df = pd.DataFrame(records)
        if len(df) > 0:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
        return None
    except Exception as e:
        print(f"Error fetching daily candles for {code}: {e}")
        return None

def get_realtime_stock_info(code):
    """
    단일 종목 실시간 상세 시세 정보 조회
    """
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    try:
        res = requests.get(url, headers=HEADERS, timeout=4)
        if res.status_code == 200:
            data = res.json()
            return {
                "code": code,
                "name": data.get("stockName", ""),
                "current_price": int(data.get("closePrice", "0").replace(",", "")),
                "change_rate": float(data.get("fluctuationsRatio", 0.0)),
                "high_price": int(data.get("highPrice", "0").replace(",", "")),
                "low_price": int(data.get("lowPrice", "0").replace(",", "")),
                "volume": int(data.get("accumulatedTradingVolume", "0").replace(",", ""))
            }
    except Exception:
        pass
    return None

def search_stocks(query: str):
    """
    네이버 증권 공식 자동완성 API(ac.stock.naver.com)를 활용하여
    코스피/코스닥 종목을 실시간으로 검색합니다.
    """
    if not query or len(query.strip()) < 1:
        return []

    url = f"https://ac.stock.naver.com/ac?q={query.strip()}&target=stock"
    try:
        res = requests.get(url, headers=HEADERS, timeout=4)
        if res.status_code != 200:
            return []

        data = res.json()
        items = data.get("items", [])
        results = []

        for item in items[:6]:  # 상위 6개 결과
            code = item.get("code")
            name = item.get("name")
            market = item.get("typeCode", "KOSPI")

            # 실시간 현재가 및 등락률 조회
            info = get_realtime_stock_info(code)
            current_price = info["current_price"] if info else 0
            change_rate = info["change_rate"] if info else 0.0

            # 10만원 예산 적합성 진단
            # 5만원 이하: 분산 매수 적합 (FIT_SPLIT)
            # 10만원 이하: 1주 단일 매수 가능 (FIT_SINGLE)
            # 10만원 초과: 시드 머니 초과 (OVER_BUDGET)
            if current_price <= 50000:
                budget_status = "FIT_SPLIT"
                budget_desc = "분산 매수 적합"
            elif current_price <= 100000:
                budget_status = "FIT_SINGLE"
                budget_desc = "1주 매수 가능"
            else:
                budget_status = "OVER_BUDGET"
                budget_desc = "10만원 초과"

            results.append({
                "code": code,
                "name": name,
                "market": market,
                "current_price": current_price,
                "change_rate": change_rate,
                "budget_status": budget_status,
                "budget_desc": budget_desc,
                "logo_url": f"https://ssl.pstatic.net/imgstock/fn/real/logo/png/stock/Stock{code}.png"
            })

        return results
    except Exception as e:
        print(f"Search error: {e}")
        return []

def is_stock_fractional_tradable(code: str) -> tuple[bool, str]:
    """
    한국예탁결제원 신탁 방식 기준, 증권사 소수점 거래 가능 종목 여부를 판별합니다.
    - 대상: KOSPI/KOSDAQ 상장 주식 중 시가총액 약 3,000억 원 이상 우량주
    - 제외: ETF/ETN, 관리종목, 정리매매, 동전주(1,000원 미만)
    """
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        res = requests.get(url, headers=HEADERS, timeout=3)
        if res.status_code != 200:
            return False, "정보 조회 실패"
        data = res.json()
        end_type = data.get("stockEndType", "stock")
        if end_type != "stock":
            return False, "ETF/ETN 파생상품은 소수점 거래 미지원"

        market_cap_str = ""
        for item in data.get("totalInfos", []):
            if item.get("key") == "시총":
                market_cap_str = item.get("value", "")
                break

        # '조' 단위는 무조건 가능
        if "조" in market_cap_str:
            return True, f"소수점 매수 가능 (시총 {market_cap_str})"

        # '억' 단위는 3,000억 이상 판별
        if "억" in market_cap_str:
            import re
            m = re.search(r"([\d,]+)억", market_cap_str)
            if m:
                val = int(m.group(1).replace(",", ""))
                if val >= 3000:
                    return True, f"소수점 매수 가능 (시총 {market_cap_str})"
                else:
                    return False, f"소수점 미지원 (시총 3,000억 미만: {market_cap_str})"

        return False, "소수점 거래 미지원 종목"
    except Exception as e:
        return False, f"판별 오류: {e}"

def get_stock_detail_with_chart(code: str, budget: int = 100000):
    """
    종목의 실시간 상세 정보와 30일 시계열 차트 데이터를 함께 반환합니다.
    스윙 등급(S/A/B/C) 및 소수점 매수 가능 여부도 함께 계산하여 반환합니다.
    """
    from strategy import get_stock_grade

    info = get_realtime_stock_info(code)
    if not info:
        return None

    # 소수점 매수 가능 여부 판별
    is_fractional, fractional_desc = is_stock_fractional_tradable(code)

    candles = get_stock_daily_candles(code, count=60)
    chart_data = {"dates": [], "prices": []}
    if candles is not None and len(candles) > 0:
        recent = candles.tail(30)
        chart_data = {
            "dates": recent["date"].dt.strftime("%m.%d").tolist(),
            "prices": recent["close"].tolist(),
            "min_price": int(recent["close"].min()),
            "max_price": int(recent["close"].max())
        }

    # 등급 산출 (데이터 충분할 때만)
    grade_result = {"grade": "N/A", "score": 0, "grade_reasons": ["데이터 부족"]}
    if candles is not None and len(candles) >= 25:
        grade_result = get_stock_grade(info, candles, budget=budget, is_fractional=is_fractional)

    return {
        "code": code,
        "name": info["name"],
        "current_price": info["current_price"],
        "change_rate": info["change_rate"],
        "high_price": info.get("high_price", 0),
        "low_price": info.get("low_price", 0),
        "volume": info.get("volume", 0),
        "chart_data": chart_data,
        "is_fractional": is_fractional,
        "fractional_desc": fractional_desc,
        "grade": grade_result["grade"],
        "grade_score": grade_result["score"],
        "grade_reasons": grade_result["grade_reasons"]
    }


if __name__ == "__main__":
    print("Testing market_data.py...")
    stocks = get_market_candidate_stocks(max_price=50000, min_price=1000, min_trading_value_m=2000)
    print(f"총 {len(stocks)}개 후보 종목 발굴 완료 (1주 5만원 이하 & 거래대금 20억 이상).")
    if stocks:
        print("\n[상위 5개 후보 샘플]")
        for s in stocks[:5]:
            print(f"- {s['name']}({s['code']}) [{s['market']}]: 현재가 {s['current_price']:,}원 | 전일대비 {s['change_rate']}% | 거래대금 {s['trading_value_m']:,}백만원")
        
        sample_code = stocks[0]["code"]
        candles = get_stock_daily_candles(sample_code, count=30)
        print(f"\n{stocks[0]['name']}({sample_code}) 일봉 데이터 수집 성공: {len(candles)}일치")
