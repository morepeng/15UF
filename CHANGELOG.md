# CHANGELOG · MJ 13F SmartPick

版本更新記錄 · All notable changes to this project will be documented here.

---

## [v2.0.0] - 2026-05-25

### 🆕 新增

#### ICT/SMC 六維結構分析引擎
- `StructureEngine` 類別：BOS/CHoCH 結構突破偵測
- **Stop Hunt**：前高/低掃除後吞噬反轉 (+30分)
- **Fair Value Gap (FVG)**：公允缺口未填補回踩 (+25分)
- **Order Block (OB)**：機構訂單塊回踩+量縮確認 (+25分)
- **OTE 62%~79%**：Fibonacci 最佳進場區間 (+20分)
- **BOS/CHoCH**：多頭結構突破/空轉多反轉信號 (+20~+25分)
- **Premium/Discount Zone**：擺動中位線上下區域判斷 (+10/-10分)
- **MTF 多時框共振**：日線+1H方向一致性 (+15分)

#### 三道預篩系統
- 流動性門檻：日均成交量 > 50萬股（美股）
- 趨勢一致性：收盤 > MA60（60日均線）
- 資金流向確認：近5日量 > 近20日均量
- 預篩加成機制：全通+10、通2項+5、通1項0、全失-10

#### 複合評分系統
- 傳統TA原始分 × 3倍
- ICT/SMC結構分加減
- 預篩加成
- 買進門檻：複合分 ≥ 80
- 觀察門檻：複合分 ≥ 50
- 賣出條件：CHoCH/BOS 空頭結構

#### Kill Zone 時間過濾器
- 亞盤開盤：09:00–11:00 TWN
- 倫敦開盤：15:00–17:00 TWN
- 紐約開盤：21:30–23:30 TWN
- 身處 Kill Zone 內 +5複合分

#### GitHub Pages Web 儀表板 (index.html)
- 單檔 HTML + CSS + JS (74.8KB，零後端依賴)
- SEC EDGAR 實時爬蟲（四層策略 + 雙CORS代理）
- 完整 ICT/SMC JavaScript 計算引擎
- Anthropic Claude API AI個股洞察
- Chart.js 互動K線圖
- 可排序/篩選表格 + CSV匯出

### 🔧 改進

- SEC 13F XML 解析新增第五層：SGML 完整文件串流解析（Python版）
- 瀏覽器版 DOMParser + getElementsByTagNameNS 兼容所有命名空間格式
- 翻頁支援：處理大型機構超過1000筆申報的分頁 JSON
- 13F-HR/A（修正版申報）支援

### 🐛 修復

- `pd` 命名衝突（局部變數覆蓋 pandas 模組）
- `score = 0` 初始化遺漏導致 NameError（全部輸出為 SKIP 的根本原因）
- TW ETF 清單字串連接 Bug（缺少逗號導致 `0050.TW00981A.TW`）
- `_ft()` closure 在 for loop 中的 Python closure 覆蓋問題

---

## [v1.2.0] - 2026-05-22

### 🆕 新增

- **S5 SGML 串流解析**：`stream=True` 以 512KB chunks 讀取，遇到 INFORMATION TABLE 即截斷，支援 200MB+ 大型文件
- **S6 EFTS 全文搜尋**（實驗性）：透過 `efts.sec.gov` 搜尋引擎定位 infotable 連結
- `FALLBACK_HOLDINGS` 備援靜態名單（爬蟲全失敗時自動啟用）

### 🔧 改進

- S4 改用 `{accession}-index.htm` 精確路徑取代裸目錄
- 正則表達式擴展，覆蓋 `href='...'` 與 `href="..."` 兩種格式
- index.json 掃描支援子目錄路徑中的 XML 檔案

### 🐛 修復

- `Host: data.sec.gov` 鎖死在 Session header 導致 www.sec.gov 請求被拒
- closure bug：`_ft(tag, parent=info)` 在 for loop 中使用 default argument 的 Python 閉包問題
- `<value>` 欄位含逗號格式解析（e.g., `"1,234,567"` → `1234567`）

---

## [v1.1.0] - 2026-05-21

### 🔧 改進

- **data.sec.gov/Archives/.../index.json API** 取代不穩定的 HTML 目錄爬取
- 四層降級策略：index.json → 關鍵字匹配 → 全體XML → 固定候選名
- DOMParser 萬用字元命名空間 `getElementsByTagNameNS('*', 'infoTable')`
- Regex 備援解析支援 `<ns1:nameOfIssuer>` 格式

### 🐛 修復

- 命名空間尾隨空格問題（SEC 部分文件含 `"http://...informationTable "` 尾空格）
- 動態偵測文件實際使用的 namespace URI

---

## [v1.0.0] - 2026-05-20

### 🆕 初始版本

- SEC EDGAR 13F-HR 爬蟲（15家主要機構）
- 六大傳統技術分析信號：RSI / MACD / KDJ / BB / MA排列 / MA5上漲 / Volume
- 公司名稱 → Yahoo Finance Ticker 靜態映射表
- CSV 輸出（UTF-8 BOM，Excel 直接開啟）
- colorama 終端機彩色輸出
- tqdm 進度條顯示
- 備用持股名單（EDGAR 無法連線時）

---

## 計劃功能 (Roadmap)

- [ ] 台股 13F 等效資料（TWSE 大額持股申報）
- [ ] A股北向資金流向整合
- [ ] 自動化排程（GitHub Actions 每週五收盤後執行）
- [ ] Discord / Line Notify 買進警報推送
- [ ] 歷史回測：ICT信號勝率統計
- [ ] 多時框完整 1H / 15M 資料整合（Web版）
