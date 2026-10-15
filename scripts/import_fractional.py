"""증권사 소수점 거래 가능 종목 엑셀 → backend/data/fractional/<broker>.json 변환.

사용법:
  python scripts/import_fractional.py "미래에셋 소수점 매수 가능.xlsx" --broker miraeasset --date 2026-10-01

엑셀 형식: 헤더 없음, A열=종목코드(예: A005930), B열=종목명.
ETF/ETN 으로 보이는 이름이 섞여 있으면 중단한다(소수점 불가 정책).
"""
import argparse
import json
import os
import re
import sys

import pandas as pd

ETF_HINTS = ("KODEX", "TIGER", "KBSTAR", "ARIRANG", "ACE ", "SOL ", "HANARO", "KOSEF", "RISE ", "PLUS ", "ETN", "ETF")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "fractional")


def convert(xlsx: str, broker: str, date: str) -> dict:
    df = pd.read_excel(xlsx, header=None, dtype=str).dropna(how="all")
    stocks, seen = {}, set()
    for raw_code, name in zip(df[0], df[1]):
        code = str(raw_code).strip().upper()
        code = code[1:] if code.startswith("A") and len(code) == 7 else code
        if not re.fullmatch(r"[0-9A-Z]{6}", code):
            sys.exit(f"잘못된 종목코드: {raw_code!r}")
        name = str(name).strip()
        if not name or name == "nan":
            sys.exit(f"종목명 없음: {raw_code!r}")
        if any(h in name.upper() for h in ETF_HINTS):
            sys.exit(f"ETF/ETN 의심 항목(소수점 불가 정책): {code} {name}")
        if code in seen:
            sys.exit(f"중복 코드: {code}")
        seen.add(code)
        stocks[code] = name
    return {"broker": broker, "updated_at": date, "count": len(stocks), "stocks": stocks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--broker", default="miraeasset")
    ap.add_argument("--date", required=True, help="목록을 가져온 날짜 YYYY-MM-DD")
    a = ap.parse_args()
    data = convert(a.xlsx, a.broker, a.date)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.abspath(os.path.join(OUT_DIR, f"{a.broker}.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print(f"{path}: {data['count']}종목 (기준일 {a.date})")


if __name__ == "__main__":
    main()
