"""
market_data.py
한국 주식 시장(KOSPI, KOSDAQ) 실시간 시세 및 캔들 데이터 수집 모듈
네이버 증권 공식 모바일 API 및 차트 API 연동
"""
import re
import requests
from symbol_index import MAX_QUERY_LEN, symbol_index
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
                            "logo_url": s.get("itemLogoPngUrl", "") or s.get("itemLogoUrl", ""),
                            "security_type": safe_security_type(s.get("stockEndType"))
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

LOGO_URL_PREFIX = "https://ssl.pstatic.net/imgstock/"
_LOGO_URL_RE = re.compile(r"https://ssl\.pstatic\.net/imgstock/[A-Za-z0-9._/-]+")  # 프론트 LOGO_URL_PATTERN 과 같은 규칙


def safe_logo_url(url) -> str:
    """네이버 로고 주소만 통과시킨다(화면이 img src 로 그대로 쓰므로). 그 밖의 값은 빈 문자열."""
    return url if isinstance(url, str) and _LOGO_URL_RE.fullmatch(url) else ""


SECURITY_TYPES = ("stock", "etf", "etn")


def safe_security_type(value) -> str:
    """종목 종류(네이버 stockEndType). stock/etf/etn 만 통과, 그 밖의 값·없음은 빈 문자열(= 모름, 화면은 태그를 달지 않는다)."""
    return value if isinstance(value, str) and value in SECURITY_TYPES else ""


def get_realtime_stock_info(code):
    """
    단일 종목 실시간 상세 시세 정보 조회
    logo_url: 응답의 itemLogoPngUrl. 주식은 종목 로고, ETF·ETN 은 운용사·증권사 로고다(코드로 만든 주소는 ETF 에서 404)
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
                "volume": int(data.get("accumulatedTradingVolume", "0").replace(",", "")),
                "logo_url": safe_logo_url(data.get("itemLogoPngUrl")),
                "security_type": safe_security_type(data.get("stockEndType"))
            }
    except Exception:
        pass
    return None

SEARCH_LIMIT = 6  # 검색 결과(후보) 최대 개수


def _autocomplete_candidates(query: str):
    """네이버 자동완성 후보 [(code, name, market)]. 이름 앞부분 일치만 되고, 색인에 아직 없는 신규 상장 등을 보완한다. 실패하면 빈 목록."""
    try:
        # 검색어는 params 로 보낸다: 주소에 끼워 넣으면 "S&P500" 의 & 가 요청을 깨뜨린다
        res = requests.get("https://ac.stock.naver.com/ac", params={"q": query, "target": "stock"},
                           headers=HEADERS, timeout=4)
        if res.status_code != 200:
            return []
        out = []
        for item in res.json().get("items", []):
            code, name = item.get("code"), item.get("name")
            if code and name:
                out.append((code, name, item.get("typeCode") or "KOSPI"))
        return out
    except Exception as e:
        print(f"Autocomplete error: {e}")
        return []


def search_stocks(query: str):
    """
    종목 검색. 후보는 두 곳에서 모은다.
    1) 종목 색인(symbol_index): 이름 가운데 글자·코드 앞부분 일치 (거래대금이 큰 종목 먼저)
    2) 네이버 자동완성(ac.stock.naver.com): 색인에 없던 후보(신규 상장 등)를 뒤에 덧붙인다
    코드 기준으로 중복을 없애고 최대 SEARCH_LIMIT 개까지 남긴 뒤, 후보마다 **실시간 시세**로 가격·등락·로고·종류를 채운다.
    색인은 읽기만 한다(갱신은 서버가 백그라운드로 시작한다). 한쪽이 실패하면 다른 쪽 결과만 돌려준다.
    """
    if not query or len(query.strip()) < 1:
        return []
    q = query.strip()[:MAX_QUERY_LEN]

    candidates, seen = [], set()
    for sym in symbol_index.search(q, SEARCH_LIMIT):
        seen.add(sym.code)
        candidates.append((sym.code, sym.name, sym.market))
    for code, name, market in _autocomplete_candidates(q):
        if code not in seen:
            seen.add(code)
            candidates.append((code, name, market))
    candidates = candidates[:SEARCH_LIMIT]

    try:
        results = []
        for code, name, market in candidates:
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
                # 시세 응답의 로고(ETF 는 운용사 로고)를 우선하고, 없을 때만 코드로 만든 주식 로고 주소
                "logo_url": (info or {}).get("logo_url") or f"{LOGO_URL_PREFIX}fn/real/logo/png/stock/Stock{code}.png",
                # 자동완성 응답은 ETF 도 stock 으로 분류하므로 시세 응답의 종류를 쓴다(시세 실패면 모름)
                "security_type": (info or {}).get("security_type", "")
            })

        return results
    except Exception as e:
        print(f"Search error: {e}")
        return []

def is_stock_fractional_tradable(code: str, broker: str = None) -> tuple[bool, str]:
    """증권사 소수점 거래 가능 종목 목록 기준 판별 (목록에 없으면 정수만). 네트워크 호출 없음."""
    import fractional
    return fractional.is_fractional_tradable(code, broker or fractional.DEFAULT_BROKER)

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
        "logo_url": info.get("logo_url", ""),
        "security_type": info.get("security_type", ""),
        "chart_data": chart_data,
        "is_fractional": is_fractional,
        "fractional_desc": fractional_desc,
        "grade": grade_result["grade"],
        "grade_score": grade_result["score"],
        "grade_reasons": grade_result["grade_reasons"]
    }

def attach_diagnosis(recs, candles_provider, budget: int = 100000, security_types=None):
    """
    추천 목록의 각 항목에 AI 진단 등급(grade, grade_score, grade_reasons)과
    소수점 판별(is_fractional, fractional_desc), 종목 종류(security_type, 코드→종류 dict 로 받으며 없으면 "")를 덧붙인 새 목록을 반환합니다.
    상세 조회(get_stock_detail_with_chart)와 같은 get_stock_grade 기준을 사용하며 strategy.py는 바꾸지 않습니다.
    일봉 조회가 실패하거나 25일 미만이면 등급은 N/A, 소수점 판별(네트워크 없음)은 그대로 유지합니다.
    """
    from strategy import get_stock_grade

    result = []
    for rec in recs:
        is_fractional, fractional_desc = is_stock_fractional_tradable(rec["code"])
        grade_result = {"grade": "N/A", "score": 0, "grade_reasons": ["데이터 부족"]}
        try:
            candles = candles_provider(rec["code"], count=60)
            if candles is not None and len(candles) >= 25:
                grade_result = get_stock_grade(
                    {"current_price": rec["current_price"]}, candles,
                    budget=budget, is_fractional=is_fractional)
        except Exception as e:
            print(f"Diagnosis error for {rec.get('code')}: {e}")
        result.append({
            **rec,
            "grade": grade_result["grade"],
            "grade_score": grade_result["score"],
            "grade_reasons": grade_result["grade_reasons"],
            "is_fractional": is_fractional,
            "fractional_desc": fractional_desc,
            "security_type": (security_types or {}).get(rec["code"], rec.get("security_type", "")),
        })
    return result


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
