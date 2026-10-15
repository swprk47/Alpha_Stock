"""
portfolio.py
사용자별 가상 계좌 관리 모듈
- 사용자 식별자는 서버 세션에서만 얻는다(클라이언트 입력 사용 금지)
- 체결가는 호출자(orders.py)가 서버에서 조회한 시세만 전달한다
- 수수료/세금 계산은 fees.py 순수 함수 사용
"""
import math
from datetime import datetime, date

import config
from fees import calc_buy_cost, calc_sell_proceeds, estimate_sell_cost
from storage import UserStore

SCHEMA_VERSION = 1
QTY_EPS = 1e-6


class OrderError(Exception):
    """주문 검증 실패 (HTTP 400으로 변환)."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_qty(quantity: float) -> float:
    if quantity is None or not math.isfinite(quantity):
        raise OrderError("수량이 올바르지 않습니다.")
    q = round(float(quantity), 4)
    if q <= 0:
        raise OrderError("수량은 0보다 커야 합니다.")
    if q > config.MAX_ORDER_QUANTITY:
        raise OrderError(f"1회 주문 수량은 {config.MAX_ORDER_QUANTITY:,}주 이하입니다.")
    return q


def _check_price(price: int) -> int:
    if not isinstance(price, int) or price <= 0:
        raise OrderError("체결가가 올바르지 않습니다.")
    return price


class MultiUserPortfolioManager:
    def __init__(self, initial_balance: int = config.DEFAULT_INITIAL_BALANCE, store: UserStore | None = None):
        self.initial_balance = initial_balance
        self.store = store or UserStore()

    # ---------- 계정 ----------
    def _new_user(self, user_id: str, name: str = "") -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "user_id": user_id,
            "name": name or "투자자",
            "picture": "",
            "initial_balance": self.initial_balance,
            "cash_balance": self.initial_balance,
            "realized_pnl": 0,
            "created_at": _now(),
            "holdings": {},
            "history": [],
        }

    def _load_or_new(self, user_id: str, name: str = "") -> dict:
        data = self.store.load(user_id)
        if data is None:
            data = self._new_user(user_id, name)
            self.store.save(user_id, data)
        return data

    def get_or_create_user(self, user_id: str, name: str = "") -> dict:
        with self.store.locked(user_id):
            data = self._load_or_new(user_id, name)
            if name and data.get("name") != name:
                data["name"] = name
                self.store.save(user_id, data)
            return data

    def set_user_budget(self, user_id: str, new_budget: int):
        """시드 예산 변경 (PR-B에서 입출금 원장으로 대체 예정)."""
        if not (config.MIN_BUDGET <= new_budget <= config.MAX_BUDGET):
            raise OrderError("예산 범위를 벗어났습니다.")
        with self.store.locked(user_id):
            data = self._load_or_new(user_id)
            old_initial = data.get("initial_balance", self.initial_balance)
            diff = new_budget - old_initial
            if data["cash_balance"] + diff < 0:
                raise OrderError("보유 현금보다 많이 줄일 수 없습니다. 먼저 매도하세요.")
            data["initial_balance"] = new_budget
            data["cash_balance"] += diff
            self.store.save(user_id, data)
            return True, data

    # ---------- 조회 ----------
    def get_summary(self, user_id: str, current_prices=None):
        data = self.get_or_create_user(user_id)
        current_prices = current_prices or {}
        holdings_list = []
        total_eval = 0
        total_invested = 0

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_date = date.today()

        for code, item in data["holdings"].items():
            qty = round(float(item["quantity"]), 4)
            avg_price = item["avg_price"]
            invested = int(avg_price * qty)
            total_invested += invested

            cur_price = current_prices.get(code, avg_price)
            eval_val = int(cur_price * qty)
            total_eval += eval_val

            est_sell_cost = estimate_sell_cost(eval_val)
            unrealized_pnl = eval_val - invested - est_sell_cost
            pnl_pct = round(((eval_val - est_sell_cost - invested) / invested) * 100, 2) if invested > 0 else 0.0

            buy_dt = datetime.strptime(item.get("buy_date", today_str), "%Y-%m-%d").date()
            hold_days = (today_date - buy_dt).days

            signal_status = "HOLD"
            if cur_price >= item.get("target_price", float("inf")):
                signal_status = "TARGET_REACHED"
            elif cur_price <= item.get("stop_loss_price", 0):
                signal_status = "STOP_LOSS_REACHED"
            elif hold_days >= item.get("max_hold_days", 5):
                signal_status = "TIME_EXPIRED"

            holdings_list.append({
                "code": code,
                "name": item["name"],
                "quantity": qty,
                "avg_price": avg_price,
                "current_price": cur_price,
                "invested_amount": invested,
                "eval_amount": eval_val,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct": pnl_pct,
                "target_price": item.get("target_price"),
                "stop_loss_price": item.get("stop_loss_price"),
                "buy_date": item.get("buy_date"),
                "hold_days": hold_days,
                "max_hold_days": item.get("max_hold_days", 5),
                "signal_status": signal_status,
                "logo_url": item.get("logo_url", "")
            })

        cash = data["cash_balance"]
        total_asset = cash + total_eval
        init_bal = data.get("initial_balance", self.initial_balance)
        total_return_pct = round(((total_asset - init_bal) / init_bal) * 100, 2) if init_bal > 0 else 0.0

        return {
            "user_id": data["user_id"],
            "name": data.get("name", "투자자"),
            "picture": data.get("picture", ""),
            "initial_balance": init_bal,
            "cash_balance": cash,
            "total_invested": total_invested,
            "total_evaluation": total_eval,
            "total_asset": total_asset,
            "total_return_pct": total_return_pct,
            "realized_pnl": data["realized_pnl"],
            "holdings": holdings_list,
            "history": data.get("history", [])
        }

    # ---------- 주문 ----------
    def buy(self, user_id: str, code: str, name: str, price: int, quantity: float,
            target_price: int, stop_loss_price: int, max_hold_days: int = 5,
            logo_url: str = "", allow_fractional: bool = True) -> dict:
        price = _check_price(price)
        qty = _norm_qty(quantity)
        if not allow_fractional and abs(qty - round(qty)) > QTY_EPS:
            raise OrderError("소수점 거래가 지원되지 않는 종목입니다. 정수 수량만 가능합니다.")
        if not (stop_loss_price < price < target_price):
            raise OrderError("목표가 > 체결가 > 손절가 조건을 만족해야 합니다.")

        cost = calc_buy_cost(price, qty)
        if cost["gross"] <= 0:
            raise OrderError("주문 금액이 너무 작습니다.")

        with self.store.locked(user_id):
            data = self._load_or_new(user_id)
            if cost["total"] > data["cash_balance"]:
                raise OrderError(
                    f"현금 잔고가 부족합니다. (필요: {cost['total']:,}원, 보유: {data['cash_balance']:,}원)")
            data["cash_balance"] -= cost["total"]
            today = datetime.now().strftime("%Y-%m-%d")
            h = data["holdings"].get(code)
            if h:
                total_qty = round(h["quantity"] + qty, 4)
                h["avg_price"] = int((h["avg_price"] * h["quantity"] + cost["gross"]) / total_qty)
                h["quantity"] = total_qty
                h["target_price"] = target_price
                h["stop_loss_price"] = stop_loss_price
            else:
                data["holdings"][code] = {
                    "name": name, "quantity": qty, "avg_price": price,
                    "target_price": target_price, "stop_loss_price": stop_loss_price,
                    "buy_date": today, "max_hold_days": max_hold_days, "logo_url": logo_url,
                }
            data["history"].append({
                "type": "BUY", "code": code, "name": name, "price": price, "quantity": qty,
                "fee": cost["fee"], "tax": 0, "date": _now(),
            })
            self.store.save(user_id, data)
        return {"code": code, "name": name, "price": price, "quantity": qty, **cost,
                "message": f"{name} {qty:g}주 매수 완료! (체결가: {price:,}원)"}

    def get_holding_quantity(self, user_id: str, code: str) -> float:
        data = self.store.load(user_id) or {}
        return float(data.get("holdings", {}).get(code, {}).get("quantity", 0))

    def sell(self, user_id: str, code: str, price: int, quantity: float | None = None) -> dict:
        price = _check_price(price)
        with self.store.locked(user_id):
            data = self._load_or_new(user_id)
            h = data["holdings"].get(code)
            if not h:
                raise OrderError("보유하고 있지 않은 종목입니다.")
            cur_qty = round(float(h["quantity"]), 4)
            qty = cur_qty if quantity is None else _norm_qty(quantity)
            if qty > cur_qty + QTY_EPS:
                raise OrderError(f"보유 수량({cur_qty:g}주)보다 많이 매도할 수 없습니다.")
            proceeds = calc_sell_proceeds(price, qty)
            invested = int(h["avg_price"] * qty)
            pnl = proceeds["net"] - invested
            data["cash_balance"] += proceeds["net"]
            data["realized_pnl"] += pnl
            remaining = round(cur_qty - qty, 4)
            if remaining <= QTY_EPS:
                del data["holdings"][code]
            else:
                h["quantity"] = remaining
            data["history"].append({
                "type": "SELL", "code": code, "name": h["name"], "price": price, "quantity": qty,
                "fee": proceeds["fee"], "tax": proceeds["tax"], "pnl": pnl, "date": _now(),
            })
            self.store.save(user_id, data)
        sign = "+" if pnl >= 0 else ""
        return {"code": code, "price": price, "quantity": qty, "pnl": pnl, **proceeds,
                "message": f"{h['name']} {qty:g}주 매도 완료! (실현손익: {sign}{pnl:,}원)"}

    def reset(self, user_id: str) -> bool:
        """계좌 초기화 (PR-B에서 이력 보존 방식으로 변경 예정)."""
        with self.store.locked(user_id):
            data = self._load_or_new(user_id)
            data["cash_balance"] = data.get("initial_balance", self.initial_balance)
            data["realized_pnl"] = 0
            data["holdings"] = {}
            data["history"] = []
            self.store.save(user_id, data)
        return True
