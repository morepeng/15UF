# 🎯 MJ 13F SmartPick v2.0 · ICT/SMC Elite

> **機構13F持股爬蟲 × ICT/SMC結構分析 × 複合評分選股系統**  
> SEC EDGAR 13F Scraper × Technical Analysis × Smart Money Concepts

[![GitHub Pages](https://img.shields.io/badge/Live_Demo-GitHub_Pages-00d4ff?style=for-the-badge&logo=github)](https://你的帳號.github.io/mj-13f-smartpick/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

---

## 📋 目錄

- [系統概覽](#系統概覽)
- [即時 Web 儀表板](#即時-web-儀表板)
- [Python 本地版](#python-本地版)
- [分析邏輯架構](#分析邏輯架構)
- [ICT/SMC 信號說明](#ictsMC-信號說明)
- [評分系統](#評分系統)
- [安裝與執行](#安裝與執行)
- [配置說明](#配置說明)
- [版本歷史](#版本歷史)

---

## 系統概覽

```
┌─────────────────────────────────────────────────────────────┐
│              MJ 13F SmartPick v2.0 · 五步驟流程             │
├─────────────────────────────────────────────────────────────┤
│  STEP 1  SEC EDGAR 13F-HR 爬蟲                             │
│          └─ 15家機構 → 聚合持股 → 前30大排名               │
│                                                             │
│  STEP 2  三道預篩                                           │
│          ├─ ① 流動性  日均量 > 50萬股                      │
│          ├─ ② 趨勢    收盤 > MA60                          │
│          └─ ③ 資金流  5日量 > 20日均量                     │
│                                                             │
│  STEP 3  傳統技術分析 (300根K線)                            │
│          └─ RSI · MACD · KDJ · BB · MA排列 · Volume        │
│                                                             │
│  STEP 4  ICT/SMC 六維結構評分                              │
│          ├─ ⚡ Stop Hunt   +30                              │
│          ├─ 📊 FVG 缺口   +25                              │
│          ├─ 🟦 Order Block +25                              │
│          ├─ 🎯 OTE 62~79% +20                              │
│          ├─ 🔺 BOS/CHoCH  +20                              │
│          └─ 💚 Discount區  +10                              │
│                                                             │
│  STEP 5  複合評分決策                                       │
│          ├─ ≥ 80分 → 買進 ▲                                │
│          ├─ ≥ 50分 → 觀察 ◆                                │
│          └─ CHoCH空頭 → 賣出 ▼                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 即時 Web 儀表板

### 🌐 GitHub Pages 部署

只需一個 `index.html`，零後端，直接部署：

```bash
# 1. Fork 或 Clone 本專案
git clone https://github.com/你的帳號/mj-13f-smartpick.git
cd mj-13f-smartpick

# 2. 啟用 GitHub Pages
# GitHub → Settings → Pages → Source: main / (root) → Save

# 3. 訪問
# https://你的帳號.github.io/mj-13f-smartpick/
```

### 功能一覽

| 功能 | 說明 |
|------|------|
| ⚡ **SEC EDGAR 爬蟲** | 實時抓取15家機構13F-HR申報，S1~S4四層XML解析策略 |
| 📊 **前30大持股** | 依總持股市值聚合排名，自動解析公司名→Ticker |
| 🎯 **Kill Zone** | 台北時間即時顯示亞盤/倫敦/紐約交易時窗 |
| 🔍 **三道預篩** | 流動性+趨勢+資金流向，自動過濾不符條件個股 |
| 📈 **TA指標** | RSI/MACD/KDJ/布林/MA排列/Volume 七維評分 |
| 🏦 **ICT/SMC** | Stop Hunt/FVG/OB/OTE/BOS/CHoCH 六維結構分析 |
| 🤖 **AI洞察** | 整合 Anthropic Claude API 生成個股操作建議 |
| 📥 **CSV匯出** | 一鍵下載含35欄的完整分析報告 |
| 🌓 **深色主題** | Bloomberg Terminal 風格 · 掃描線特效 |

### 螢幕截圖

```
╔══════════════════════════════════════════════════════════════════╗
║  MJ 13F SmartPick  v2.0  ·  ICT/SMC Elite                      ║
║  🎯 London Kill Zone (15:08 TWN)              ⚡ 執行分析       ║
╠══════════════════════════════════════════════════════════════════╣
║  分析: 30  買進: 5  觀察: 12  賣出: 2  Kill Zone: London       ║
╠══╦══════╦══════════════╦══════╦══════╦═════╦═════════════╦═════╣
║# ║ 代碼 ║ 公司         ║複合分║TA×3 ║ ICT ║ ICT 信號    ║ 建議║
╠══╬══════╬══════════════╬══════╬══════╬═════╬═════════════╬═════╣
║8 ║ PLTR ║ PALANTIR..   ║ +95  ║ +21  ║ +74 ║ ⚡SH↑ 📊FVG║ 買進║
║2 ║ NVDA ║ NVIDIA..     ║ +82  ║ +18  ║ +64 ║ 🟦OB+縮 🎯 ║ 買進║
╚══╩══════╩══════════════╩══════╩══════╩═════╩═════════════╩═════╝
```

---

## Python 本地版

### 系統需求

```
Python 3.10+
Anaconda / Miniconda (建議)
Windows / macOS / Linux
```

### 快速安裝

```bash
pip install yfinance requests pandas numpy colorama tqdm pytz
```

### 執行

```bash
# MJ 13F SmartPick v2.0 (13F爬蟲 + ICT/SMC)
python MJ_13F_SmartPick_v2.py

# MJ Sniper v9.0 (ETF板塊輪動 + ICT/SMC)
python MJ_Sniper_v9_ICT_Elite.py
```

### 輸出

```
.\13F_Output\
  ├── 13F_v2_分析_20260521_1030.csv    # 35欄完整分析
  └── 13F_持股排行_20260521_1030.csv   # 機構持股聚合
```

---

## 分析邏輯架構

### STEP 1 · SEC EDGAR 13F 爬蟲

```
機構 CIK → data.sec.gov/submissions/CIK{cik}.json
         → 找最新 13F-HR 申報 (含翻頁支援)
         → 五層XML解析策略:
             S1: Archives/index.json → 關鍵字XML
             S2: Archives/index.json → 掃全部XML
             S3: 固定候選檔名 (infotable.xml等)
             S4: HTML index 爬取連結
             S5: SGML完整文件串流解析 (Python限定)
         → 持股聚合池 → 前30大 → 解析Ticker
```

### STEP 2 · 三道預篩

| 篩選項 | 條件 | 通過效果 |
|--------|------|---------|
| 流動性 | 日均量 > 500,000股 | +15複合分 |
| 趨勢 | 收盤 > MA60 | +20複合分 |
| 資金流 | 5日均量 > 20日均量 | +15複合分 |
| **全通過** | 3/3 | **+10預篩加成** |

### STEP 3 · 傳統技術分析

| 指標 | 多頭條件 | 分值 |
|------|---------|------|
| MA5上漲 | 連續5日遞增 | +1 |
| RSI | <30回升 / 30~50中低位 | +1 |
| MACD | 金叉 / 柱狀擴張 | +1~+2 |
| KDJ | KD金叉 / K>D低位上揚 | +1~+2 |
| Volume | 量比>2x放量上漲 | +1~+2 |
| BB | %B<0.1~0.3 下軌區 | +1~+2 |
| MA排列 | 5>10>20>60>120 | +1~+2 |

### STEP 4 · ICT/SMC 結構分析

| 信號 | 觸發條件 | 分值 |
|------|---------|------|
| ⚡ Stop Hunt | 下影線掃低+吞噬收盤回 | **+30** |
| 📊 FVG 缺口 | 在未填補多頭缺口內 | **+25** |
| 🟦 Order Block | 回踩機構訂單塊+量縮 | **+25** |
| 🎯 OTE | 在62%~79% Fib區間 | **+20** |
| 🔺 BOS/CHoCH | 多頭突破/空轉多 | **+20/+25** |
| 💚 Discount | 低於擺動中位線50% | **+10** |
| 📡 MTF共振 | 日線+1H方向一致 | **+15** |
| ⏰ Kill Zone | 在交易時窗內 | **+5** |

---

## ICT/SMC 信號說明

### Stop Hunt (流動性獵殺)
```
條件: K棒下影線突破前低 0.1%以上，但收盤回到前低之上
含義: 空單停損被掃除後，Smart Money 接盤反轉
確認: 吞噬K棒（今收 > 昨高）
```

### Fair Value Gap (公允缺口)
```
條件: K[n-2].高 < K[n].低（上升跳空 ≥ 0.2%）
含義: 機構快速建倉留下的未填補缺口
進場: 價格回踩至缺口區間
```

### Order Block (機構訂單塊)
```
條件: 強勢上漲前的最後一根陰線區間
確認: 回踩至OB區間 + 量縮（今量 < 前5根均量）
含義: 機構原始建倉區，二次進場
```

### OTE 62%~79% (最佳進場區)
```
工具: Fibonacci 回撤
計算: 最近擺動高→低，62%~79%回撤區間
含義: ICT體系中機率最高的精準進場點位
```

### BOS / CHoCH
```
BOS  (Break of Structure): 突破前高 = 多頭結構確立
CHoCH (Change of Character): 空頭格局首次突破前高 = 趨勢轉換信號
```

---

## 評分系統

### 複合評分公式

```
複合分 = (傳統TA原始分 × 3) + ICT/SMC分 + 預篩加成

傳統TA原始分: -12 ~ +12
ICT/SMC分:   最大 +125, 最低 -75
預篩加成:    全通過+10, 通2項+5, 通1項0, 全失敗-10

複合分上限: +120  |  下限: -60
```

### 決策門檻

| 複合分 | 建議 | 說明 |
|--------|------|------|
| ≥ 100 | 買進 ★★★ | 強烈買進，多重ICT確認 |
| ≥ 90 | 買進 ★★☆ | 積極買進 |
| ≥ 80 | 買進 ★☆☆ | 謹慎買進 |
| 50~79 | 觀察 ◆ | 等待更佳進場條件 |
| CHoCH空頭 | 賣出 ▼ | 趨勢反轉，規避做空 |
| < 50 | 略過 ─ | 條件不足 |

---

## 安裝與執行

### Web 版 (GitHub Pages)

```bash
# Step 1: 建立 Repository
# GitHub → New repository → Public → Create

# Step 2: 上傳 index.html
# Add file → Upload → 選擇 index.html → Commit

# Step 3: 啟用 Pages
# Settings → Pages → Branch: main / (root) → Save

# 完成！約1~2分鐘後訪問:
# https://{你的帳號}.github.io/{repo名稱}/
```

### Python 版 (本地執行)

```bash
# 建立虛擬環境 (建議)
conda create -n mj_sniper python=3.11
conda activate mj_sniper

# 安裝依賴
pip install -r requirements.txt

# 執行 MJ 13F SmartPick v2.0
python MJ_13F_SmartPick_v2.py

# 執行 MJ Sniper v9.0 ETF板塊輪動
python MJ_Sniper_v9_ICT_Elite.py
```

---

## 配置說明

### MJ_13F_SmartPick_v2.py 主要參數

```python
CONFIG = {
    # 13F 設定
    'TOP_N_STOCKS'    : 30,       # 前N大持股
    'MAX_INSTITUTIONS': 15,       # 抓取機構數
    'REQUEST_DELAY'   : 0.5,      # SEC請求間隔(秒)

    # 三道預篩
    'R1_MIN_VOL_US'   : 500_000,  # 美股最低日均量
    'R1_TREND_MA'     : 60,       # 趨勢均線周期

    # ICT/SMC 評分
    'ICT_STOP_HUNT'   : 30,       # Stop Hunt 分值
    'ICT_FVG'         : 25,       # FVG 分值
    'ICT_OB'          : 25,       # Order Block 分值
    'ICT_OTE'         : 20,       # OTE 分值
    
    # 複合評分門檻
    'BUY_COMPOSITE'   : 80,       # 買進最低分
    'WATCH_COMPOSITE' : 50,       # 觀察最低分
}
```

### Web 版 API Key 設定

在頁面頂部輸入 Anthropic API Key 即可啟用 AI 個股洞察功能：

```
sk-ant-api03-...
```

API Key 儲存於瀏覽器 `localStorage`，不會上傳至任何伺服器。

---

## 每日操作 SOP

```
08:45 盤前   執行 MJ_13F_SmartPick_v2.py 或開啟 GitHub Pages
             確認當季最新13F持股排名

09:00-09:30  London Kill Zone 開始
             確認個股是否形成 OTE 進場點

進場條件     趨勢↑ + BOS/CHoCH多頭 + Discount區 + OTE 62~79%
停損設置     MA5 × 0.985（程式自動計算，嚴格執行）
出場邏輯     到達 Premium 區 或 CHoCH 空頭信號出現

風險管理     同時持有 ≤ 8 檔
             每筆風險 ≤ 總資金 1.5%
             RR (風險報酬比) ≥ 2:1
```

---

## 版本歷史

| 版本 | 日期 | 更新內容 |
|------|------|---------|
| v2.0 | 2026-05 | ICT/SMC六維評分、三道預篩、複合評分、GitHub Pages |
| v1.2 | 2026-05 | XML串流解析S5、CORS雙代理備援、closure修復 |
| v1.1 | 2026-05 | index.json API取代HTML爬蟲、命名空間修復 |
| v1.0 | 2026-05 | SEC EDGAR 13F爬蟲、六大TA信號、初始版本 |

---

## 免責聲明

> ⚠️ 本系統僅供學術研究與技術探討，**不構成任何投資建議**。  
> 股市有風險，投資需謹慎。使用者應自行判斷投資決策，作者不承擔任何損失責任。

---

## 授權

MIT License · © 2026 MJ Sniper Lab

---

<div align="center">
<sub>Built with ❤️ by MJ Sniper Lab · SEC EDGAR · Yahoo Finance · Anthropic Claude</sub>
</div>
