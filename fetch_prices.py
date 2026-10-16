#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""讀 holdings.json → 用 yfinance 抓 1 年日K + 基本面 → 輸出 prices.json
本機執行:  pip install yfinance pandas   然後  python fetch_prices.py
GitHub Actions 會每天自動執行並 commit。"""
import json, math, sys, time, datetime
import yfinance as yf

def num(x):
    try:
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else x
    except Exception:
        return None

def get_rows(tk):
    df = tk.history(period="1y", interval="1d", auto_adjust=False)
    rows = []
    for ts, r in df.iterrows():
        c = num(r["Close"])
        if c is None:
            continue
        rows.append({
            "t": int(ts.timestamp() * 1000),
            "o": round(num(r["Open"]) or c, 4),
            "h": round(num(r["High"]) or c, 4),
            "l": round(num(r["Low"]) or c, 4),
            "c": round(c, 4),
            "v": int(num(r["Volume"]) or 0),
        })
    return rows[-300:]

def get_fin(tk):
    """與 index.html 的 get_financials 評分邏輯一致"""
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    pe = num(info.get("trailingPE"))
    roe = num(info.get("returnOnEquity"))
    score = 0
    if pe is not None and 0 < pe < 20:
        score += 20
    if roe is not None and roe > 0.15:
        score += 20
    capex_ratio, capex_score = None, 0
    try:
        cf = tk.cashflow
        ocf = capex = None
        for k in ("Operating Cash Flow", "Total Cash From Operating Activities"):
            if k in cf.index:
                ocf = num(cf.loc[k].dropna().iloc[0]); break
        for k in ("Capital Expenditure", "Capital Expenditures"):
            if k in cf.index:
                capex = num(cf.loc[k].dropna().iloc[0]); break
        if ocf and capex is not None and ocf > 0:
            capex_ratio = abs(capex) / ocf * 100
            if capex_ratio < 25: capex_score = 10
            elif capex_ratio < 50: capex_score = 5
            elif capex_ratio > 100: capex_score = -10
    except Exception:
        pass
    score += capex_score
    return {"PE": pe, "ROE": roe * 100 if roe is not None else None,
            "CapEx_Ratio": capex_ratio, "CapEx_Score": capex_score,
            "Total_Score": score}

def main():
    with open("holdings.json", encoding="utf-8") as f:
        tickers = sorted({h["ticker"] for h in json.load(f)["holdings"]})
    out, fail = {}, []
    for t in tickers:
        ok = False
        for attempt in range(3):
            try:
                tk = yf.Ticker(t)
                rows = get_rows(tk)
                if len(rows) >= 30:
                    out[t] = {"rows": rows, "fin": get_fin(tk)}
                    ok = True
                    break
            except Exception as e:
                print(f"{t} 第{attempt+1}次失敗: {e}", file=sys.stderr)
            time.sleep(2)
        print(("OK  " if ok else "FAIL"), t)
        if not ok:
            fail.append(t)
        time.sleep(0.5)
    if not out:
        sys.exit("全部失敗，不覆蓋舊的 prices.json")
    payload = {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
               "failed": fail, "tickers": out}
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"完成: {len(out)} 支成功, {len(fail)} 支失敗 {fail}")

if __name__ == "__main__":
    main()
