from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os
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
from portfolio import MultiUserPortfolioManager

app = FastAPI(title="Alpha Stock", description="10만원 소액 맞춤형 한국 주식 스윙 추천 PWA (Multi-User)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

portfolio_mgr = MultiUserPortfolioManager(initial_balance=100000)

cache = {
    "last_updated": 0,
    "recommendations": []
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
def stock_detail_api(code: str):
    """특정 종목 상세 및 30일 인터랙티브 차트 데이터 조회"""
    detail = get_stock_detail_with_chart(code)
    if not detail:
        raise HTTPException(status_code=404, detail="종목 정보를 찾을 수 없습니다.")
    return {"success": True, "stock": detail}

@app.get("/api/recommendations")
def get_recs(refresh: bool = False, budget: int = 100000):
    """실시간 10만원 맞춤 스윙 추천 종목 조회"""
    recs = update_recommendations_cache(force=refresh, budget=budget)
    return {
        "success": True,
        "updated_at": datetime.fromtimestamp(cache["last_updated"]).strftime("%Y-%m-%d %H:%M:%S") if cache["last_updated"] else "",
        "recommendations": recs
    }

class GoogleAuthRequest(BaseModel):
    user_id: str
    name: Optional[str] = "투자자"
    email: Optional[str] = ""
    picture: Optional[str] = ""

@app.post("/api/auth/google")
def google_auth(req: GoogleAuthRequest):
    """구글 로그인 및 유저 계정 동기화"""
    user = portfolio_mgr.get_or_create_user(
        user_id=req.user_id,
        name=req.name,
        email=req.email,
        picture=req.picture
    )
    return {"success": True, "user": user}

@app.get("/api/portfolio")
def get_portfolio(user_id: str = Query("default_user")):
    """사용자별 가상 10만원 계좌 요약 및 보유 현황 조회"""
    user_data = portfolio_mgr.get_or_create_user(user_id)
    current_prices = {}
    chart_data_map = {}

    for code in user_data["holdings"].keys():
        info = get_realtime_stock_info(code)
        if info:
            current_prices[code] = info["current_price"]
        candles = get_stock_daily_candles(code, count=30)
        if candles is not None and len(candles) > 0:
            chart_data_map[code] = {
                "dates": candles["date"].dt.strftime("%m.%d").tolist(),
                "prices": candles["close"].tolist()
            }

    summary = portfolio_mgr.get_summary(user_id, current_prices)
    for h in summary["holdings"]:
        h["chart_data"] = chart_data_map.get(h["code"], {"dates": [], "prices": []})

    return {
        "success": True,
        "portfolio": summary
    }

class BuyRequest(BaseModel):
    user_id: Optional[str] = "default_user"
    code: str
    name: str
    price: int
    quantity: int
    target_price: Optional[int] = None
    stop_loss_price: Optional[int] = None
    max_hold_days: Optional[int] = 5
    logo_url: Optional[str] = ""

@app.post("/api/buy")
def buy_stock(req: BuyRequest):
    """사용자별 모의 매수 실행"""
    success, msg = portfolio_mgr.buy(
        user_id=req.user_id,
        code=req.code,
        name=req.name,
        price=req.price,
        quantity=req.quantity,
        target_price=req.target_price,
        stop_loss_price=req.stop_loss_price,
        max_hold_days=req.max_hold_days,
        logo_url=req.logo_url
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

class SellRequest(BaseModel):
    user_id: Optional[str] = "default_user"
    code: str
    price: int
    quantity: Optional[int] = None

@app.post("/api/sell")
def sell_stock(req: SellRequest):
    """사용자별 모의 매도 실행"""
    success, msg = portfolio_mgr.sell(
        user_id=req.user_id,
        code=req.code,
        price=req.price,
        quantity=req.quantity
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

class ResetRequest(BaseModel):
    user_id: Optional[str] = "default_user"

@app.post("/api/reset")
def reset_portfolio(req: ResetRequest):
    """사용자별 계좌 10만원 초기화"""
    portfolio_mgr.reset(req.user_id)
    return {"success": True, "message": "가상 계좌가 100,000원으로 초기화되었습니다."}

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
