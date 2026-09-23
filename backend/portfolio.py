"""
portfolio.py
멀티 유저(Multi-User) 지원 10만원 가상 계좌 관리 모듈
- 사용자별(Google email / user_id) 독립적인 100,000 KRW 시드 계좌 개설 및 관리
- 수수료: 매수 0.015%, 매도 0.015% + 증권거래세 0.18%
"""
import json
import os
from datetime import datetime, date

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
USERS_DIR = os.path.join(DATA_DIR, "users")

BUY_FEE_RATE = 0.00015    # 0.015%
SELL_FEE_RATE = 0.00015   # 0.015%
TAX_RATE = 0.0018         # 증권거래세 0.18%

class MultiUserPortfolioManager:
    def __init__(self, initial_balance=100000):
        os.makedirs(USERS_DIR, exist_ok=True)
        self.initial_balance = initial_balance

    def _get_user_file(self, user_id: str) -> str:
        # 안전한 파일명 생성 (이메일의 특수문자 치환)
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in user_id)
        return os.path.join(USERS_DIR, f"{safe_id}.json")

    def get_or_create_user(self, user_id: str, name: str = "", email: str = "", picture: str = ""):
        file_path = self._get_user_file(user_id)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 프로필 정보 업데이트
                    if name: data["name"] = name
                    if picture: data["picture"] = picture
                    return data
            except Exception:
                pass

        # 신규 유저 초기 계좌 생성 (100,000원)
        new_data = {
            "user_id": user_id,
            "name": name or "투자자",
            "email": email or user_id,
            "picture": picture or "",
            "initial_balance": self.initial_balance,
            "cash_balance": self.initial_balance,
            "realized_pnl": 0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "holdings": {},
            "history": []
        }
        self._save_user(user_id, new_data)
        return new_data

    def _save_user(self, user_id: str, data: dict):
        file_path = self._get_user_file(user_id)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_summary(self, user_id: str, current_prices=None):
        data = self.get_or_create_user(user_id)
        current_prices = current_prices or {}
        holdings_list = []
        total_eval = 0
        total_invested = 0

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_date = date.today()

        for code, item in data["holdings"].items():
            qty = item["quantity"]
            avg_price = item["avg_price"]
            invested = avg_price * qty
            total_invested += invested

            cur_price = current_prices.get(code, avg_price)
            eval_val = cur_price * qty
            total_eval += eval_val

            est_sell_cost = int(eval_val * (SELL_FEE_RATE + TAX_RATE))
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
        init_bal = data["initial_balance"]
        total_return_pct = round(((total_asset - init_bal) / init_bal) * 100, 2)

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

    def buy(self, user_id: str, code: str, name: str, price: int, quantity: int, target_price=None, stop_loss_price=None, max_hold_days=5, logo_url=""):
        data = self.get_or_create_user(user_id)
        total_cost = price * quantity
        fee = int(total_cost * BUY_FEE_RATE)
        required_cash = total_cost + fee

        if required_cash > data["cash_balance"]:
            return False, f"현금 잔고가 부족합니다. (필요: {required_cash:,}원, 보유: {data['cash_balance']:,}원)"

        data["cash_balance"] -= required_cash
        today_str = datetime.now().strftime("%Y-%m-%d")

        if code in data["holdings"]:
            curr = data["holdings"][code]
            total_qty = curr["quantity"] + quantity
            new_avg = int((curr["avg_price"] * curr["quantity"] + total_cost) / total_qty)
            curr["quantity"] = total_qty
            curr["avg_price"] = new_avg
            if target_price: curr["target_price"] = target_price
            if stop_loss_price: curr["stop_loss_price"] = stop_loss_price
        else:
            data["holdings"][code] = {
                "name": name,
                "quantity": quantity,
                "avg_price": price,
                "target_price": target_price or int(price * 1.065),
                "stop_loss_price": stop_loss_price or int(price * 0.97),
                "buy_date": today_str,
                "max_hold_days": max_hold_days,
                "logo_url": logo_url
            }

        data["history"].append({
            "type": "BUY",
            "code": code,
            "name": name,
            "price": price,
            "quantity": quantity,
            "fee": fee,
            "tax": 0,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        self._save_user(user_id, data)
        return True, f"{name} {quantity}주 매수 완료! (체결가: {price:,}원)"

    def sell(self, user_id: str, code: str, price: int, quantity=None):
        data = self.get_or_create_user(user_id)
        if code not in data["holdings"]:
            return False, "보유하고 있지 않은 종목입니다."

        holding = data["holdings"][code]
        cur_qty = holding["quantity"]
        sell_qty = cur_qty if quantity is None else min(quantity, cur_qty)

        sell_amount = price * sell_qty
        fee = int(sell_amount * SELL_FEE_RATE)
        tax = int(sell_amount * TAX_RATE)
        net_received = sell_amount - fee - tax

        invested_cost = holding["avg_price"] * sell_qty
        pnl = net_received - invested_cost

        data["cash_balance"] += net_received
        data["realized_pnl"] += pnl

        if sell_qty >= cur_qty:
            del data["holdings"][code]
        else:
            holding["quantity"] -= sell_qty

        data["history"].append({
            "type": "SELL",
            "code": code,
            "name": holding["name"],
            "price": price,
            "quantity": sell_qty,
            "fee": fee,
            "tax": tax,
            "pnl": pnl,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        self._save_user(user_id, data)
        pnl_sign = "+" if pnl >= 0 else ""
        return True, f"{holding['name']} {sell_qty}주 매도 완료! (실현손익: {pnl_sign}{pnl:,}원)"

    def reset(self, user_id: str):
        data = self.get_or_create_user(user_id)
        data["cash_balance"] = self.initial_balance
        data["realized_pnl"] = 0
        data["holdings"] = {}
        data["history"] = []
        self._save_user(user_id, data)
        return True

if __name__ == "__main__":
    pm = PortfolioManager(initial_balance=100000)
    print("Portfolio Initial State:", pm.get_summary())
