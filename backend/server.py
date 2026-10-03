from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import re
import time
from datetime import datetime

from market_data import (
    get_market_candidate_stocks,
    get_stock_daily_candles,
    get_realtime_stock_info,
    search_stocks,
    get_stock_detail_with_chart
)
from strategy import get_recommendations
from portfolio import MultiUserPortfolioManager, OrderError
import config
import orders
from auth import (clear_session_cookie, create_session_token, dev_user_id,
                  get_current_user, set_session_cookie)
from schemas import CODE_PATTERN, BuyRequest, DevLoginRequest, SellRequest, SetBudgetRequest

config.validate_runtime()

app = FastAPI(title="Alpha Stock", description="10만원 소액 맞춤형 한국 주식 스윙 추천 PWA (Multi-User)")

# 프론트는 같은 서버에서 서빙되므로 기본은 CORS 미적용(동일 출처).
# 다른 출처가 필요할 때만 ALLOWED_ORIGINS에 명시한 도메인 허용.
if config.ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

portfolio_mgr = MultiUserPortfolioManager(initial_balance=config.DEFAULT_INITIAL_BALANCE)

cache = {
    "last_updated": 0,
    "recommendations": [],
    "last_forced": {},
}

def update_recommendations_cache(force=False, budget=100000):
    now = time.time()
    if not force and cache["recommendations"] and (now - cache["last_updated"] < 300):
        return cache["recommendations"]

    try:
        candidates = get_market_candidate_stocks(max_price=50000, min_trading_value_m=2000)
        recs = get_recommendations(candidates[:30], get_stock_daily_candles, budget=budget, top_n=3)
        cache["recommendations"] = recs
        cache["last_updated"] = now
        return recs
    except Exception as e:
        print(f"Error updating recommendations: {e}")
        return cache["recommendations"]

@app.on_event("startup")
def startup_event():
    update_recommendations_cache()

@app.get("/api/search")
def search_stock_api(q: str = Query(..., min_length=1)):
    """실시간 종목 자동완성 검색"""
    results = search_stocks(q)
    return {"success": True, "results": results}

@app.get("/api/stock/{code}")
def stock_detail_api(code: str, budget: int = Query(100000, ge=config.MIN_BUDGET, le=config.MAX_BUDGET)):
    """특정 종목 상세 및 30일 인터랙티브 차트 데이터 조회 (예산 및 소수점 판별 포함)"""
    if not re.fullmatch(CODE_PATTERN, code):
        raise HTTPException(status_code=400, detail="종목코드는 영문 대문자·숫자 6자리입니다.")
    detail = get_stock_detail_with_chart(code, budget=budget)
    if not detail:
        raise HTTPException(status_code=404, detail="종목 정보를 찾을 수 없습니다.")
    return {"success": True, "stock": detail}

@app.get("/api/recommendations")
def get_recs(request: Request, refresh: bool = False,
             budget: int = Query(100000, ge=config.MIN_BUDGET, le=config.MAX_BUDGET)):
    """실시간 맞춤 스윙 추천 종목 조회. 강제 갱신은 로그인 사용자만, 간격 제한."""
    if refresh:
        user = get_current_user(request)
        now = time.time()
        last = cache["last_forced"].get(user["user_id"], 0)
        if now - last < config.REFRESH_MIN_INTERVAL:
            raise HTTPException(status_code=429, detail="강제 갱신은 잠시 후 다시 시도하세요.")
        cache["last_forced"][user["user_id"]] = now
    recs = update_recommendations_cache(force=refresh, budget=budget)
    return {
        "success": True,
        "updated_at": datetime.fromtimestamp(cache["last_updated"]).strftime("%Y-%m-%d %H:%M:%S") if cache["last_updated"] else "",
        "recommendations": recs
    }

@app.get("/api/health")
def health():
    return {"ok": True}


# ---------- 인증 ----------
@app.post("/api/auth/dev-login")
def dev_login(req: DevLoginRequest, response: Response):
    """개발용 닉네임 로그인. ALLOW_DEV_LOGIN=true 일 때만 허용."""
    if not config.ALLOW_DEV_LOGIN:
        raise HTTPException(status_code=404, detail="Not Found")
    user_id = dev_user_id(req.nickname)
    name = req.nickname.strip()
    portfolio_mgr.get_or_create_user(user_id, name=name)
    set_session_cookie(response, create_session_token(user_id, name))
    return {"success": True, "user": {"name": name, "dev": True}}


@app.post("/api/auth/google")
def google_auth():
    """Google ID 토큰 검증 로그인 — PR-A 마지막 단계에서 구현."""
    raise HTTPException(status_code=501, detail="Google 로그인은 아직 준비 중입니다.")


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"success": True}


@app.get("/api/me")
def me(user: dict = Depends(get_current_user)):
    return {"success": True, "user": {"name": user["name"], "dev": user["user_id"].startswith("dev:")},
            "dev_login_enabled": config.ALLOW_DEV_LOGIN}


# ---------- 계좌 (모두 세션 사용자 기준) ----------
@app.get("/api/portfolio")
def get_portfolio(user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    user_data = portfolio_mgr.get_or_create_user(user_id)
    current_prices, chart_data_map = {}, {}
    for code in user_data["holdings"].keys():
        info = get_realtime_stock_info(code)
        if info and info.get("current_price", 0) > 0:
            current_prices[code] = info["current_price"]
        candles = get_stock_daily_candles(code, count=30)
        if candles is not None and len(candles) > 0:
            chart_data_map[code] = {
                "dates": candles["date"].dt.strftime("%m.%d").tolist(),
                "prices": candles["close"].tolist(),
            }
    summary = portfolio_mgr.get_summary(user_id, current_prices)
    summary.pop("user_id", None)
    for h in summary["holdings"]:
        h["chart_data"] = chart_data_map.get(h["code"], {"dates": [], "prices": []})
        h["price_stale"] = h["code"] not in current_prices
    return {"success": True, "portfolio": summary}


@app.post("/api/portfolio/budget")
def set_portfolio_budget(req: SetBudgetRequest, user: dict = Depends(get_current_user)):
    try:
        portfolio_mgr.set_user_budget(user["user_id"], req.budget)
    except OrderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "message": f"시드머니가 {req.budget:,}원으로 설정되었습니다."}


@app.post("/api/buy")
def buy_stock(req: BuyRequest, user: dict = Depends(get_current_user)):
    """모의 매수: 서버 실시간 시세로 체결."""
    r = orders.place_buy(portfolio_mgr, user["user_id"], req)
    return {"success": True, "message": r["message"], "order": r}


@app.post("/api/sell")
def sell_stock(req: SellRequest, user: dict = Depends(get_current_user)):
    """모의 매도: 서버 실시간 시세로 체결."""
    r = orders.place_sell(portfolio_mgr, user["user_id"], req)
    return {"success": True, "message": r["message"], "order": r}


@app.post("/api/reset")
def reset_portfolio(user: dict = Depends(get_current_user)):
    portfolio_mgr.reset(user["user_id"])
    return {"success": True, "message": "가상 계좌가 초기화되었습니다."}


# 프론트엔드 정적 파일 서빙
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Frontend not ready yet."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
