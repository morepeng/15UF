#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║   MJ Sniper v9.0  ·  ICT / SMC Elite Trading System  v9.1                            ║
║                                                                                  ║
║   第一輪  ETF 賽道篩選 (三道預篩 + 強度評分)                                   ║
║   ├─ 流動性門檻   日均量 > 50萬股(美股) / 1000萬台幣(台股)                    ║
║   ├─ 趨勢一致性   收盤 > MA60                                                   ║
║   └─ 資金流向     近5日量 > 近20日均量                                           ║
║                                                                                  ║
║   第二輪  成分股 ICT/SMC 精密評分                                               ║
║   ├─ 多時框共振 MTF  1D / 1H / 15M                                              ║
║   ├─ BOS / CHoCH 結構突破                                                       ║
║   ├─ FVG 公允缺口 (+25)                                                         ║
║   ├─ Order Block 訂單塊 (+25)                                                   ║
║   ├─ Stop Hunt 流動性獵殺 (+30)                                                 ║
║   ├─ OTE 62%~79% 最佳進場區 (+20)                                               ║
║   ├─ Premium / Discount 區域判斷                                                ║
║   └─ Kill Zone 時間窗口過濾                                                     ║
║                                                                                  ║
║   門檻: Score ≥ 80 → 買進  |  60~79 → 持有觀察  |  BOS空頭 → 賣出            ║
╚══════════════════════════════════════════════════════════════════════════════════╝

依賴套件:
    pip install yfinance requests pandas numpy colorama tqdm pytz

作者: MJ Sniper Lab
版本: 9.0.0
日期: 2026-05
"""

import os
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from functools import lru_cache

warnings.filterwarnings('ignore')

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class Fore:
        RED=GREEN=YELLOW=CYAN=MAGENTA=WHITE=BLUE=LIGHTBLUE_EX=LIGHTGREEN_EX=RESET=''
    class Style:
        BRIGHT=DIM=RESET_ALL=''


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ CONFIG v9.0  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
CONFIG = {
    # ── 第一輪: 賽道預篩 ──────────────────────────────────────────────────────
    'R1_MIN_VOL_US'         : 500_000,    # 美股日均量 > 50萬股
    'R1_MIN_TURNOVER_TW'    : 10_000_000, # 台股日均成交額 > 1000萬台幣
    'R1_TREND_MA'           : 60,         # 趨勢均線
    'R1_FLOW_SHORT'         : 5,          # 近N日量（分子）
    'R1_FLOW_LONG'          : 20,         # 均量週期（分母）
    'R1_ETF_SCORE_PASS'     : 50,         # ETF進入第二輪門檻分數
    'R1_TOP_N_ETF'          : 5,          # 最多取前N強ETF
    'R1_TOP_HOLDINGS'       : 15,         # 每支ETF取前N大成分股

    # ── 第二輪: ICT/SMC 評分 ─────────────────────────────────────────────────
    'R2_STOP_HUNT_SCORE'    : 30,
    'R2_FVG_SCORE'          : 25,
    'R2_OB_SCORE'           : 25,
    'R2_OTE_SCORE'          : 20,
    'R2_BOS_BULL_SCORE'     : 20,
    'R2_MTF_BONUS'          : 15,         # 三框共振加分
    'R2_DISCOUNT_BONUS'     : 10,         # Discount 區加分
    'R2_MA20_PENALTY'       : -20,        # 股價 < MA20 扣分
    'R2_PREMIUM_PENALTY'    : -10,        # Premium 區追高扣分
    'R2_CHOCH_BEAR_PENALTY' : -30,        # 空頭 CHoCH 扣分

    # ── 門檻 ─────────────────────────────────────────────────────────────────
    'BUY_SCORE'             : 80,
    'HOLD_SCORE'            : 60,

    # ── 結構偵測參數 ─────────────────────────────────────────────────────────
    'SWING_LOOKBACK'        : 5,          # 擺動高低點偵測窗口
    'FVG_MIN_GAP_PCT'       : 0.002,      # FVG 最小缺口 0.2%
    'OB_MIN_IMPULSE_PCT'    : 0.005,      # OB 後的最小衝擊幅度 0.5%
    'STOP_HUNT_WIG_PCT'     : 0.001,      # Stop Hunt 最小出格比例 0.1%
    'OTE_LOW'               : 0.62,       # OTE 低端 62% fib
    'OTE_HIGH'              : 0.79,       # OTE 高端 79% fib

    # ── Kill Zone (台北時間 UTC+8) ───────────────────────────────────────────
    # 亞盤: 09:00-11:00  倫敦: 15:00-17:00  紐約: 21:30-23:30
    'KILL_ZONES'            : {
        'Asia'   : (9, 0, 11, 0),     # (開始時, 開始分, 結束時, 結束分)
        'London' : (15, 0, 17, 0),
        'NewYork': (21, 30, 23, 30),
    },

    # ── 執行設定 ─────────────────────────────────────────────────────────────
    'MAX_WORKERS'           : 5,
    'REQUEST_DELAY'         : 0.3,
    'OUTPUT_DIR'            : r'.\MJ_Sniper_v9',
    'OUTPUT_CSV'            : True,
    'CHANGE_LOOKBACK'       : 5,          # 漲幅回看天數
}

# ═══════════════════════════════════════════════════════════════════════════════
# ░░ ETF Universe  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
ETF_UNIVERSE = {
    'US': [
        # 科技
        'QQQ', 'XLK', 'SOXX', 'SMH', 'HACK', 'IGV', 'SKYY', 'ARKG',
        # 能源
        'XLE', 'XOP', 'OIH',
        # 金融
        'XLF', 'KRE', 'KBE',
        # 醫療
        'XLV', 'IBB', 'XBI',
        # 工業/國防
        'XLI', 'ITA', 'XAR',
        # 消費
        'XLY', 'XLP',
        # 材料/大宗
        'XLB', 'GDX', 'COPX',
        # 房地產
        'VNQ', 'IYR',
        # 廣基
        'SPY', 'IWM', 'DIA',
        # 固定收益
        'BIL', 'TLT', 'HYG',
    ],
    'TW': [
        # 主要指數型 ETF
        '0050.TW', '0051.TW', '006208.TW',
        # 高股息
        '00878.TW', '00919.TW', '00929.TW', '00940.TW',
        # 科技/半導體
        '00881.TW', '00692.TW', '00900.TW',
    ],
    'HK': [
        '2800.HK', '2823.HK', '3033.HK',
    ],
    'CN': [
        '512480.SS', '515050.SS', '588000.SS', '159949.SZ',
        '512000.SS', '159941.SZ',
    ],
}

# ═══════════════════════════════════════════════════════════════════════════════
# ░░ ETF 成分股備援持股表  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# 當 yfinance funds_data 抓不到時使用此備援（定期手動更新）
# ═══════════════════════════════════════════════════════════════════════════════
ETF_HOLDINGS_FALLBACK: dict[str, list[str]] = {
    # ── 科技 ──────────────────────────────────────────────────────────────────
    'QQQ' : ['MSFT','NVDA','AAPL','AMZN','GOOGL','META','TSLA','AVGO','COST','NFLX',
              'AMD','ADBE','QCOM','CSCO','INTU'],
    'XLK' : ['NVDA','AAPL','MSFT','AVGO','MU','AMD','ORCL','AMAT','QCOM','INTC',
              'NOW','ANET','KLAC','LRCX','TXN'],
    'IGV' : ['MSFT','ORCL','PLTR','CRM','PANW','ADBE','CRWD','SNOW','NOW','TEAM',
              'WDAY','ZS','DDOG','OKTA','HUBS'],
    'SOXX': ['NVDA','AVGO','AMD','QCOM','TXN','INTC','AMAT','LRCX','KLAC','MU',
              'ON','MCHP','ADI','SWKS','MPWR'],
    'SMH' : ['NVDA','TSMC','ASML','AVGO','AMD','QCOM','TXN','AMAT','LRCX','KLAC',
              'MU','INTC','ON','ADI','MCHP'],
    'HACK': ['CRWD','PANW','CSCO','FTNT','ZS','OKTA','VRNS','TENB','QLYS','SAIL',
              'FFIV','S','CYBR','NTCT','FEYE'],
    'SKYY': ['MSFT','AMZN','GOOGL','ORCL','CRM','IBM','NOW','WDAY','DDOG','SNOW',
              'ZS','OKTA','HUBS','BOX','TWLO'],
    'ARKG': ['RXRX','IRTC','PACB','TWST','VCYT','NVTA','FATE','CDNA','EXAS','TNDM',
              'NTLA','BEAM','CRSP','EDIT','ARCT'],
    # ── 能源 ──────────────────────────────────────────────────────────────────
    'XLE' : ['XOM','CVX','COP','SLB','WMB','KMI','PSX','VLO','MPC','OXY',
              'EOG','FANG','DVN','PXD','HES'],
    'XOP' : ['MPC','OXY','FANG','VLO','PSX','DVN','EOG','PXD','COP','CXO',
              'APA','MRO','CTRA','XEC','SM'],
    'OIH' : ['SLB','HAL','BKR','NOV','FTI','PTEN','WHD','RES','PUMP','NR',
              'NINE','OIS','KOS','HP','NGL'],
    # ── 金融 ──────────────────────────────────────────────────────────────────
    'XLF' : ['BRK-B','JPM','V','MA','BAC','WFC','GS','MS','BLK','SCHW',
              'C','AXP','CB','MMC','AON'],
    'KRE' : ['FRC','SIVB','ZION','HBAN','RF','CFG','KEY','MTB','FITB','COLB',
              'WAL','BOKF','WTFC','IBOC','CVBF'],
    'KBE' : ['JPM','BAC','WFC','C','USB','PNC','GS','MS','TFC','COF',
              'FITB','KEY','RF','HBAN','ZION'],
    # ── 醫療 ──────────────────────────────────────────────────────────────────
    'XLV' : ['UNH','LLY','JNJ','ABBV','MRK','TMO','ABT','AMGN','DHR','VRTX',
              'ISRG','REGN','ZTS','ELV','BSX'],
    'IBB' : ['AMGN','VRTX','REGN','GILD','BIIB','MRNA','ALNY','SGEN','ILMN','BMRN',
              'EXEL','JAZZ','NBIX','SRPT','RARE'],
    'XBI' : ['RCUS','KRYS','DNLI','ARWR','KROS','PCVX','IMVT','CYTK','RVMD','PTGX',
              'INVA','ACAD','EXAS','FOLD','NKTR'],
    # ── 工業/國防 ──────────────────────────────────────────────────────────────
    'XLI' : ['GE','RTX','HON','UNP','CAT','DE','ETN','EMR','LMT','NOC',
              'UPS','FDX','ITW','PH','CMI'],
    'ITA' : ['RTX','LMT','BA','NOC','GD','L3H','TDG','HEI','LDOS','SAIC',
              'KTOS','DRS','CW','AXON','CACI'],
    # ── 消費 ──────────────────────────────────────────────────────────────────
    'XLY' : ['AMZN','TSLA','HD','MCD','NKE','LOW','SBUX','BKNG','TJX','ROST',
              'CMG','MAR','HLT','YUM','EBAY'],
    'XLP' : ['PG','COST','KO','PEP','WMT','PM','MO','MDLZ','CL','KMB',
              'SYY','KR','HSY','CPB','K'],
    # ── 材料/大宗 ──────────────────────────────────────────────────────────────
    'XLB' : ['LIN','APD','ECL','SHW','FCX','NEM','NUE','DOW','DD','PPG',
              'IFF','EMN','CF','MOS','ALB'],
    'GDX' : ['NEM','GOLD','AEM','WPM','KGC','PAAS','HL','SA','CDE','SBGL',
              'AGI','OR','EDV','BTG','PVG'],
    'COPX': ['FCX','SCCO','HBM','TECK','FM','ANTO','CS','LUN','TRQ','SFR',
              'CZICF','GLCNF','IVPAF','WRLG','ELBM'],
    # ── 廣基/其他 ──────────────────────────────────────────────────────────────
    'SPY' : ['MSFT','NVDA','AAPL','AMZN','META','GOOGL','TSLA','AVGO','BRK-B','LLY',
              'UNH','JPM','V','XOM','MA'],
    'IWM' : ['SMCI','INSM','SAIA','MOD','CAVA','PLXS','PCVX','HIMS','STEP','SPSC',
              'SHAK','TMDX','HRI','LNTH','SFM'],
    'DIA' : ['GS','UNH','MSFT','HON','CAT','SHW','MCD','V','AMGN','AXP',
              'CRM','HD','IBM','JNJ','TRV'],
    'VNQ' : ['PLD','AMT','EQIX','WELL','SPG','PSA','O','CCI','DLR','AVB',
              'EQR','MAA','ARE','BXP','IRM'],
    'IYR' : ['PLD','AMT','EQIX','SPG','PSA','WELL','O','CCI','DLR','AVB',
              'WPC','NNN','VICI','FR','EXR'],
    # ── 台股 ETF ─────────────────────────────────────────────────────────────
    '0050.TW' : ['2330.TW','2454.TW','2317.TW','2308.TW','3008.TW',
                 '2881.TW','2882.TW','2303.TW','1301.TW','2412.TW'],
    '00981A.TW' : ['2330.TW','2454.TW','2317.TW','2308.TW','3008.TW',
                 '2395.TW','6505.TW','2891.TW','2886.TW','2382.TW'],
    '00992A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00987A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00991A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00995A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00403A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    
    
    # ── A股 ETF ──────────────────────────────────────────────────────────────
    '512480.SS':['300750.SZ','002594.SZ','300014.SZ','002027.SZ','300274.SZ',
                 '300124.SZ','002049.SZ','300773.SZ','300316.SZ','002460.SZ'],
    '515050.SS':['600519.SS','000858.SZ','601318.SS','000568.SZ','002304.SZ',
                 '603288.SS','600887.SS','000799.SZ','002507.SZ','000596.SZ'],
    '588000.SS':['688981.SS','600845.SS','688041.SS','603501.SS','688036.SS',
                 '688012.SS','600703.SS','688008.SS','002607.SZ','688009.SS'],
    '159949.SZ':['300750.SZ','300014.SZ','002594.SZ','002049.SZ','300274.SZ',
                 '300124.SZ','300316.SZ','002142.SZ','002460.SZ','300773.SZ'],
    # ── 港股 ETF ─────────────────────────────────────────────────────────────
    '2800.HK' : ['0700.HK','0005.HK','0939.HK','1299.HK','0941.HK',
                 '0388.HK','2318.HK','1398.HK','3988.HK','0011.HK'],
    '2823.HK' : ['0700.HK','BABA','JD','BIDU','NTES','TME',
                 'BILI','VIPS','IQ','CTRP'],
    # ── 槓桿 ETF（台灣）─────────────────────────────────────────────────────
    '0050.TW' : ['2330.TW','2454.TW','2317.TW','2308.TW','3008.TW',
                 '2881.TW','2882.TW','2303.TW','1301.TW','2412.TW'],
    '00981A.TW' : ['2330.TW','2454.TW','2317.TW','2308.TW','3008.TW',
                 '2395.TW','6505.TW','2891.TW','2886.TW','2382.TW'],
    '00992A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00987A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00991A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00995A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    '00403A.TW':['2330.TW','2317.TW','2454.TW','2308.TW','3008.TW',
                 '2881.TW','2303.TW','1301.TW','2882.TW','2412.TW'],
    

}
# ─────────────────────────────────────────────────────────────────────────────
TW_LEVERAGE_ETF =  ['0050.TW' 
'00981A.TW','00992A.TW','00987A.TW','00991A.TW',       
'00995A.TW',               
'00403A.TW']


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ 顯示工具  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
def banner():
    print(f"""
{Fore.CYAN}{Style.BRIGHT}
╔══════════════════════════════════════════════════════════════════════════╗
║   MJ Sniper v9.0  ·  ICT / SMC Elite Trading System  v9.1                    ║
║   第一輪: ETF賽道三道預篩  ·  第二輪: 六維ICT/SMC精密評分               ║
╚══════════════════════════════════════════════════════════════════════════╝
{Style.RESET_ALL}""")

def sep(c='═', n=76, color=Fore.CYAN):
    print(f"{color}{c*n}{Style.RESET_ALL}")

def cp(text, color=Fore.WHITE, bold=False):
    b = Style.BRIGHT if bold else ''
    print(f"{b}{color}{text}{Style.RESET_ALL}")


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 1: 資料快取層  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
_DATA_CACHE: dict = {}

def get_ohlcv(ticker: str, period: str = '1y', interval: str = '1d') -> pd.DataFrame | None:
    """帶快取的 OHLCV 下載"""
    key = f"{ticker}|{period}|{interval}"
    if key in _DATA_CACHE:
        return _DATA_CACHE[key]
    try:
        time.sleep(CONFIG['REQUEST_DELAY'])
        obj = yf.Ticker(ticker)
        df  = obj.history(period=period, interval=interval)
        if df is None or len(df) < 5:
            return None
        df.index = pd.to_datetime(df.index)
        _DATA_CACHE[key] = df
        return df
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 2: Kill Zone 時間過濾器  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
class KillZoneFilter:
    """判斷目前是否處於 Kill Zone 時間窗口 (台北時間 UTC+8)"""

    TZ_TW = pytz.timezone('Asia/Taipei')

    def __init__(self, zones: dict | None = None):
        self.zones = zones or CONFIG['KILL_ZONES']

    def now_tw(self) -> datetime:
        return datetime.now(self.TZ_TW)

    def current_zone(self) -> str | None:
        """回傳目前所在的 Kill Zone 名稱，否則回傳 None"""
        now = self.now_tw()
        h, m = now.hour, now.minute
        current_minutes = h * 60 + m
        for zone_name, (sh, sm, eh, em) in self.zones.items():
            start = sh * 60 + sm
            end   = eh * 60 + em
            if start <= current_minutes <= end:
                return zone_name
        return None

    def is_in_kill_zone(self) -> bool:
        return self.current_zone() is not None

    def status_str(self) -> str:
        zone = self.current_zone()
        now  = self.now_tw()
        if zone:
            return f"🎯 {zone} Kill Zone  ({now.strftime('%H:%M')} TWN)"
        # 找下一個開始
        mins = now.hour * 60 + now.minute
        nxt  = None
        for name, (sh, sm, eh, em) in sorted(self.zones.items(),
                                               key=lambda x: x[1][0]*60+x[1][1]):
            start = sh * 60 + sm
            if start > mins:
                nxt = (name, sh, sm)
                break
        if nxt:
            return (f"⏰ 非Kill Zone  ({now.strftime('%H:%M')} TWN)  "
                    f"│ 下一個: {nxt[0]} {nxt[1]:02d}:{nxt[2]:02d}")
        return f"⏰ 非Kill Zone  ({now.strftime('%H:%M')} TWN)"


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 3: 結構偵測引擎 (Swing / BOS / CHoCH / FVG / OB / Stop Hunt)  ░░
# ═══════════════════════════════════════════════════════════════════════════════
class StructureEngine:
    """
    ICT/SMC 核心結構偵測
    所有方法均只接受 pd.DataFrame (OHLCV)，回傳結果字典
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg

    # ── 工具: 擺動高低點 ───────────────────────────────────────────────────
    def swing_points(self, df: pd.DataFrame, lookback: int | None = None) -> tuple:
        """
        回傳 (swing_highs, swing_lows)
        每個元素: [(bar_index, price), ...]
        """
        lb   = lookback or self.cfg['SWING_LOOKBACK']
        high = df['High'].values
        low  = df['Low'].values
        n    = len(df)
        
        swing_highs, swing_lows = [], []
        for i in range(lb, n - lb):
            if high[i] == max(high[i-lb: i+lb+1]):
                swing_highs.append((i, high[i]))
            if low[i] == min(low[i-lb: i+lb+1]):
                swing_lows.append((i, low[i]))
        
        return swing_highs, swing_lows

    # ── BOS / CHoCH ────────────────────────────────────────────────────────
    def detect_bos_choch(self, df: pd.DataFrame) -> dict:
        """
        BOS  (Break of Structure): 多頭突破前高 / 空頭跌破前低
        CHoCH (Change of Character): 趨勢中的首次反向突破
        
        回傳:
          bos_bull      : bool  最新收盤 > 上一個擺動高點
          bos_bear      : bool  最新收盤 < 上一個擺動低點
          choch_bull    : bool  空頭格局中首次突破高點 (反轉信號)
          choch_bear    : bool  多頭格局中首次跌破低點 (反轉信號)
          structure     : str   'BULLISH' / 'BEARISH' / 'RANGING'
          last_sh       : float 最近擺動高點
          last_sl       : float 最近擺動低點
        """
        close = df['Close']
        latest_close = close.iloc[-1]
        
        sh_list, sl_list = self.swing_points(df)
        
        result = {
            'bos_bull'  : False, 'bos_bear'  : False,
            'choch_bull': False, 'choch_bear': False,
            'structure' : 'RANGING',
            'last_sh'   : None,  'last_sl'   : None,
        }
        
        if not sh_list or not sl_list:
            return result
        
        last_sh = sh_list[-1][1]
        last_sl = sl_list[-1][1]
        result['last_sh'] = last_sh
        result['last_sl'] = last_sl
        
        # BOS
        result['bos_bull'] = latest_close > last_sh
        result['bos_bear'] = latest_close < last_sl
        
        # 多空結構: 連續三個擺動點判斷
        if len(sh_list) >= 2 and len(sl_list) >= 2:
            hh = sh_list[-1][1] > sh_list[-2][1]   # Higher High
            hl = sl_list[-1][1] > sl_list[-2][1]   # Higher Low
            lh = sh_list[-1][1] < sh_list[-2][1]   # Lower High
            ll = sl_list[-1][1] < sl_list[-2][1]   # Lower Low
            
            if hh and hl:
                result['structure'] = 'BULLISH'
            elif lh and ll:
                result['structure'] = 'BEARISH'
            
            # CHoCH: 趨勢轉折
            if result['structure'] == 'BEARISH' and result['bos_bull']:
                result['choch_bull'] = True
            if result['structure'] == 'BULLISH' and result['bos_bear']:
                result['choch_bear'] = True
        
        return result

    # ── FVG (Fair Value Gap) ────────────────────────────────────────────────
    def detect_fvg(self, df: pd.DataFrame) -> dict:
        """
        偵測最近未填補的 Fair Value Gap
        
        Bullish FVG: df['High'][i-2] < df['Low'][i]   (上升缺口)
        Bearish FVG: df['Low'][i-2]  > df['High'][i]  (下降缺口)
        
        「未填補」: 當前價格回踩至FVG區間但未完全覆蓋
        """
        min_gap = self.cfg['FVG_MIN_GAP_PCT']
        close   = df['Close'].iloc[-1]
        
        bullish_fvgs = []
        bearish_fvgs = []
        
        hi = df['High'].values
        lo = df['Low'].values
        n  = len(df)
        
        # 掃描最近60根K線內的FVG
        scan_range = min(n, 60)
        for i in range(scan_range - 2, 0, -1):
            # Bullish FVG
            if lo[i] > hi[i-2]:
                gap_pct = (lo[i] - hi[i-2]) / hi[i-2]
                if gap_pct >= min_gap:
                    # 未填補: 當前價格在 FVG 區間之上 (未回踩) 或在區間內 (正在填補)
                    fvg_bot = hi[i-2]
                    fvg_top = lo[i]
                    if close >= fvg_bot:  # 價格未完全跌破FVG下沿
                        bullish_fvgs.append({
                            'bar_idx': i,
                            'top': fvg_top, 'bot': fvg_bot,
                            'pct': gap_pct,
                            'in_fvg': fvg_bot <= close <= fvg_top,
                        })
            
            # Bearish FVG
            elif hi[i] < lo[i-2]:
                gap_pct = (lo[i-2] - hi[i]) / hi[i]
                if gap_pct >= min_gap:
                    fvg_top = lo[i-2]
                    fvg_bot = hi[i]
                    if close <= fvg_top:
                        bearish_fvgs.append({
                            'bar_idx': i,
                            'top': fvg_top, 'bot': fvg_bot,
                            'pct': gap_pct,
                            'in_fvg': fvg_bot <= close <= fvg_top,
                        })
        
        # 找最近一個未填補FVG（距離最短）
        best_bull = None
        if bullish_fvgs:
            # 優先選價格在FVG區間內的
            in_zone = [f for f in bullish_fvgs if f['in_fvg']]
            best_bull = in_zone[0] if in_zone else bullish_fvgs[0]
        
        best_bear = None
        if bearish_fvgs:
            in_zone = [f for f in bearish_fvgs if f['in_fvg']]
            best_bear = in_zone[0] if in_zone else bearish_fvgs[0]
        
        return {
            'has_bullish_fvg' : best_bull is not None,
            'in_bullish_fvg'  : best_bull['in_fvg'] if best_bull else False,
            'bull_fvg_top'    : best_bull['top'] if best_bull else None,
            'bull_fvg_bot'    : best_bull['bot'] if best_bull else None,
            'has_bearish_fvg' : best_bear is not None,
            'in_bearish_fvg'  : best_bear['in_fvg'] if best_bear else False,
            'bear_fvg_top'    : best_bear['top'] if best_bear else None,
            'bear_fvg_bot'    : best_bear['bot'] if best_bear else None,
            'fvg_count'       : len(bullish_fvgs) + len(bearish_fvgs),
        }

    # ── Order Block (OB) ────────────────────────────────────────────────────
    def detect_order_block(self, df: pd.DataFrame) -> dict:
        """
        Bullish OB: 衝擊上漲前的最後一根空頭K棒（陰線）
                    → 當前回踩至OB區間 且 量縮
        Bearish OB: 衝擊下跌前的最後一根多頭K棒（陽線）
        """
        min_impulse = self.cfg['OB_MIN_IMPULSE_PCT']
        
        close  = df['Close'].values
        open_  = df['Open'].values
        high   = df['High'].values
        low    = df['Low'].values
        vol    = df['Volume'].values
        n      = len(df)
        
        latest_close = close[-1]
        avg_vol5     = np.mean(vol[-6:-1]) if n > 6 else np.mean(vol)
        latest_vol   = vol[-1]
        vol_contraction = latest_vol < avg_vol5  # 量縮確認
        
        bull_obs, bear_obs = [], []
        
        scan_n = min(n - 2, 60)
        for i in range(1, scan_n):
            # Bullish OB: 陰線後跟大陽線
            if close[i] < open_[i]:  # 陰線
                if i + 1 < n:
                    impulse = (high[i+1] - close[i]) / (close[i] + 1e-10)
                    if impulse >= min_impulse:
                        bull_obs.append({
                            'bar_idx' : i,
                            'top'     : high[i],
                            'bot'     : low[i],
                            'impulse' : impulse,
                        })
            
            # Bearish OB: 陽線後跟大陰線
            elif close[i] > open_[i]:
                if i + 1 < n:
                    impulse = (close[i] - low[i+1]) / (close[i] + 1e-10)
                    if impulse >= min_impulse:
                        bear_obs.append({
                            'bar_idx' : i,
                            'top'     : high[i],
                            'bot'     : low[i],
                            'impulse' : impulse,
                        })
        
        # 找最近且當前價格回踩至 OB 區間的
        def price_in_ob(ob_list, price):
            for ob in reversed(ob_list):
                if ob['bot'] <= price <= ob['top']:
                    return ob
            return None
        
        bull_hit = price_in_ob(bull_obs, latest_close)
        bear_hit = price_in_ob(bear_obs, latest_close)
        
        return {
            'in_bull_ob'      : bull_hit is not None,
            'in_bear_ob'      : bear_hit is not None,
            'bull_ob_top'     : bull_hit['top'] if bull_hit else None,
            'bull_ob_bot'     : bull_hit['bot'] if bull_hit else None,
            'bear_ob_top'     : bear_hit['top'] if bear_hit else None,
            'bear_ob_bot'     : bear_hit['bot'] if bear_hit else None,
            'vol_contraction' : vol_contraction,
            'bull_ob_count'   : len(bull_obs),
            'bear_ob_count'   : len(bear_obs),
        }

    # ── Stop Hunt（流動性獵殺後反轉）──────────────────────────────────────
    def detect_stop_hunt(self, df: pd.DataFrame) -> dict:
        """
        Bullish Stop Hunt: K棒下影線超越前低 但 收盤回到前低之上
                           → 空頭停損被掃後多頭接管
        Bearish Stop Hunt: K棒上影線超越前高 但 收盤回到前高之下
        
        條件:
          ① 前高/前低必須是明確的局部高低點
          ② 出格比例 >= STOP_HUNT_WIG_PCT
          ③ 吞噬確認: 今日收盤 > 昨日最高（多頭吞噬）或反向
        """
        sh_list, sl_list = self.swing_points(df)
        wig_pct = self.cfg['STOP_HUNT_WIG_PCT']
        
        latest     = df.iloc[-1]
        lat_hi     = latest['High']
        lat_lo     = latest['Low']
        lat_close  = latest['Close']
        prev_close = df['Close'].iloc[-2]
        prev_hi    = df['High'].iloc[-2]
        
        result = {
            'bull_stop_hunt' : False,
            'bear_stop_hunt' : False,
            'hunt_level'     : None,
            'hunt_type'      : None,
        }
        
        if not sl_list or not sh_list:
            return result
        
        # 取最近3個擺動點
        recent_sl = [x[1] for x in sl_list[-3:]]
        recent_sh = [x[1] for x in sh_list[-3:]]
        
        # 多頭Stop Hunt: 下影線掃低但收盤在前低之上
        for sl_price in recent_sl:
            if lat_lo < sl_price * (1 - wig_pct) and lat_close > sl_price:
                result['bull_stop_hunt'] = True
                result['hunt_level']     = sl_price
                result['hunt_type']      = 'Bullish Stop Hunt'
                break
        
        # 空頭Stop Hunt: 上影線掃高但收盤在前高之下
        if not result['bull_stop_hunt']:
            for sh_price in recent_sh:
                if lat_hi > sh_price * (1 + wig_pct) and lat_close < sh_price:
                    result['bear_stop_hunt'] = True
                    result['hunt_level']     = sh_price
                    result['hunt_type']      = 'Bearish Stop Hunt'
                    break
        
        # 吞噬K棒確認（多頭吞噬: 今日收盤 > 昨日最高）
        result['bull_engulf'] = lat_close > prev_hi and lat_close > prev_close
        
        return result

    # ── OTE (Optimal Trade Entry) ───────────────────────────────────────────
    def calc_ote(self, df: pd.DataFrame) -> dict:
        """
        OTE 62%~79% Fibonacci 最佳進場區
        
        計算最近一次完整擺動 (swing high → swing low 或反向)
        判斷當前價格是否落在 62%~79% 回撤區間
        """
        sh_list, sl_list = self.swing_points(df)
        
        result = {
            'in_ote'        : False,
            'ote_low'       : None,
            'ote_high'      : None,
            'fib_pct'       : None,
            'ote_direction' : None,
        }
        
        if len(sh_list) < 1 or len(sl_list) < 1:
            return result
        
        close = df['Close'].iloc[-1]
        last_sh_idx, last_sh = sh_list[-1]
        last_sl_idx, last_sl = sl_list[-1]
        
        # 判斷最近是否高點先 or 低點先
        if last_sh_idx > last_sl_idx:
            # 高點在後: 上升波段，計算回撤（做多OTE）
            swing_hi, swing_lo = last_sh, last_sl
            rng = swing_hi - swing_lo
            ote_lo = swing_hi - self.cfg['OTE_HIGH'] * rng  # 79%回撤
            ote_hi = swing_hi - self.cfg['OTE_LOW']  * rng  # 62%回撤
            fib_pct = (swing_hi - close) / (rng + 1e-10)
            direction = 'BULL'
        else:
            # 低點在後: 下降波段，計算反彈（做空OTE）
            swing_hi, swing_lo = last_sh, last_sl
            rng = swing_hi - swing_lo
            ote_lo = swing_lo + self.cfg['OTE_LOW']  * rng  # 62%反彈
            ote_hi = swing_lo + self.cfg['OTE_HIGH'] * rng  # 79%反彈
            fib_pct = (close - swing_lo) / (rng + 1e-10)
            direction = 'BEAR'
        
        result.update({
            'in_ote'        : ote_lo <= close <= ote_hi,
            'ote_low'       : round(ote_lo, 4),
            'ote_high'      : round(ote_hi, 4),
            'fib_pct'       : round(fib_pct * 100, 1),
            'ote_direction' : direction,
        })
        return result

    # ── Premium / Discount Zone ─────────────────────────────────────────────
    def premium_discount(self, df: pd.DataFrame) -> dict:
        """
        以最近完整擺動範圍的中位點（Equilibrium 50%）判斷
        Discount  : close < equilibrium → 適合做多
        Premium   : close > equilibrium → 適合做空 / 避免追高
        Equilibrium: close ≈ equilibrium
        """
        sh_list, sl_list = self.swing_points(df)
        close = df['Close'].iloc[-1]
        
        if not sh_list or not sl_list:
            return {'zone': 'UNKNOWN', 'eq_price': None, 'pct_from_eq': None}
        
        swing_hi = max(x[1] for x in sh_list[-3:]) if sh_list else close
        swing_lo = min(x[1] for x in sl_list[-3:]) if sl_list else close
        eq       = (swing_hi + swing_lo) / 2
        
        pct = (close - eq) / (swing_hi - swing_lo + 1e-10) * 100
        
        if close < eq * 0.995:
            zone = 'DISCOUNT'
        elif close > eq * 1.005:
            zone = 'PREMIUM'
        else:
            zone = 'EQUILIBRIUM'
        
        return {
            'zone'        : zone,
            'eq_price'    : round(eq, 4),
            'swing_hi'    : round(swing_hi, 4),
            'swing_lo'    : round(swing_lo, 4),
            'pct_from_eq' : round(pct, 1),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 4: 第一輪 ETF 賽道預篩  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
class ETFPreScreener:
    """
    三道預篩 + 賽道強度評分
    ① 流動性門檻
    ② 趨勢一致性 (Close > MA60)
    ③ 資金流向 (5日均量 > 20日均量)
    """

    def __init__(self, cfg: dict):
        self.cfg    = cfg
        self.engine = StructureEngine(cfg)

    def screen(self, ticker: str, market: str = 'US') -> dict:
        """評估單一ETF，回傳預篩結果與評分"""
        result = {
            'ticker'        : ticker,
            'market'        : market,
            'pass'          : False,
            'score'         : 0,
            'price'         : None,
            'change_5d'     : 0.0,
            'avg_vol_20d'   : 0,
            'liquidity_ok'  : False,
            'trend_ok'      : False,
            'flow_ok'       : False,
            'ma60'          : None,
            'vol_ratio'     : 0.0,
            'top_holdings'  : [],
            'holding_return': 0.0,
            'reasons'       : [],
            'structure'     : 'RANGING',
            'bos_bull'      : False,
        }
        
        df = get_ohlcv(ticker, period='1y', interval='1d')
        if df is None or len(df) < 65:
            return result
        
        close  = df['Close']
        vol    = df['Volume']
        latest = close.iloc[-1]
        result['price'] = round(latest, 4)
        
        # 5日漲幅
        if len(close) >= 6:
            result['change_5d'] = round(
                (latest - close.iloc[-6]) / close.iloc[-6] * 100, 2)
        
        # ① 流動性
        avg_vol_20 = vol.tail(20).mean()
        result['avg_vol_20d'] = int(avg_vol_20)
        
        if market == 'TW':
            avg_turnover = (close.tail(20) * vol.tail(20)).mean()
            liq_ok = avg_turnover >= self.cfg['R1_MIN_TURNOVER_TW']
        else:
            liq_ok = avg_vol_20 >= self.cfg['R1_MIN_VOL_US']
        
        result['liquidity_ok'] = liq_ok
        
        # ② 趨勢 (Close > MA60)
        ma60     = close.rolling(self.cfg['R1_TREND_MA']).mean().iloc[-1]
        trend_ok = latest > ma60
        result['trend_ok'] = trend_ok
        result['ma60']     = round(ma60, 4)
        
        # ③ 資金流向 (近5日量 > 近20日均量)
        vol_5d  = vol.tail(self.cfg['R1_FLOW_SHORT']).mean()
        vol_20d = vol.tail(self.cfg['R1_FLOW_LONG']).mean()
        vol_ratio = vol_5d / (vol_20d + 1e-10)
        flow_ok = vol_ratio > 1.0
        result['flow_ok']    = flow_ok
        result['vol_ratio']  = round(vol_ratio, 2)
        
        # ── 評分 ────────────────────────────────────────────────────────────
        score = 0
        reasons = []
        
        if liq_ok:
            score += 15
            reasons.append(f'流動性✅ {avg_vol_20/1e6:.1f}M均量')
        else:
            reasons.append(f'流動性❌ {avg_vol_20/1e4:.0f}萬均量不足')
        
        if trend_ok:
            score += 20
            reasons.append(f'MA60趨勢✅ {latest:.2f}>{ma60:.2f}')
        else:
            reasons.append(f'MA60趨勢❌ 低於MA60')
        
        if flow_ok:
            score += 15
            reasons.append(f'量增✅ 量比{vol_ratio:.1f}x')
        else:
            reasons.append(f'量縮❌ 量比{vol_ratio:.1f}x')
        
        # 漲幅加分
        chg = result['change_5d']
        if chg >= 5:
            score += 30
            reasons.append(f'強勢漲幅+{chg:.1f}%🔥')
        elif chg >= 2:
            score += 20
            reasons.append(f'漲幅+{chg:.1f}%')
        elif chg >= 0:
            score += 10
            reasons.append(f'小漲+{chg:.1f}%')
        else:
            score -= 10
            reasons.append(f'下跌{chg:.1f}%')
        
        # BOS 多頭加分
        bos = self.engine.detect_bos_choch(df)
        result['structure'] = bos['structure']
        result['bos_bull']  = bos['bos_bull']
        if bos['bos_bull']:
            score += 10
            reasons.append('BOS多頭突破')
        elif bos['bos_bear']:
            score -= 10
            reasons.append('BOS空頭跌破')
        
        result['score']   = score
        result['pass']    = (liq_ok or market in ('CN', 'HK')) and score >= self.cfg['R1_ETF_SCORE_PASS']
        result['reasons'] = reasons
        
        # ── 取 ETF 前N大持股 ───────────────────────────────────────────────
        # 策略①: yfinance funds_data.top_holdings
        # 策略②: yfinance Ticker.info['holdings']
        # 策略③: 備援持股表 ETF_HOLDINGS_FALLBACK
        holdings_found = []
        try:
            obj = yf.Ticker(ticker)
            # 策略①
            if hasattr(obj, 'funds_data') and obj.funds_data is not None:
                hdf = obj.funds_data.top_holdings
                if hdf is not None and len(hdf) > 0:
                    holdings_found = [str(t).strip() for t in
                                      list(hdf.head(self.cfg['R1_TOP_HOLDINGS']).index)
                                      if t]
            # 策略②
            if not holdings_found:
                info = obj.info or {}
                raw = info.get('holdings', [])
                holdings_found = [h.get('symbol','') for h in raw
                                  if h.get('symbol')][:self.cfg['R1_TOP_HOLDINGS']]
        except Exception:
            pass
        
        # 策略③: 備援表
        if not holdings_found:
            holdings_found = ETF_HOLDINGS_FALLBACK.get(ticker, [])[:self.cfg['R1_TOP_HOLDINGS']]
        
        result['top_holdings'] = [t for t in holdings_found if t]
        
        # 計算持股均漲幅（用前5支）
        hold_changes = []
        for h_ticker in result['top_holdings'][:5]:
            h_df = get_ohlcv(h_ticker, period='1mo', interval='1d')
            if h_df is not None and len(h_df) >= 6:
                hc = (h_df['Close'].iloc[-1] - h_df['Close'].iloc[-6]
                      ) / h_df['Close'].iloc[-6] * 100
                hold_changes.append(hc)
        if hold_changes:
            result['holding_return'] = round(np.mean(hold_changes), 2)
        
        return result

    def scan_all(self, etf_universe: dict) -> list:
        """掃描所有市場ETF，回傳通過預篩的ETF列表（依評分降序）"""
        all_results = []
        
        for market, tickers in etf_universe.items():
            cp(f"\n  📡 掃描 {market} ETF ({len(tickers)} 檔)...", Fore.CYAN)
            
            with ThreadPoolExecutor(max_workers=self.cfg['MAX_WORKERS']) as ex:
                futures = {ex.submit(self.screen, t, market): t
                           for t in tickers}
                for future in futures:
                    res = future.result()
                    if res['price']:
                        all_results.append(res)
        
        # 也掃描台灣槓桿ETF
        cp(f"  📌 掃描台灣槓桿ETF...", Fore.CYAN)
        for t in TW_LEVERAGE_ETF:
            res = self.screen(t, 'TW')
            if res['price']:
                all_results.append(res)
        
        # 排序: 通過預篩 → 評分降序
        passed  = sorted([r for r in all_results if r['pass']],
                         key=lambda x: -x['score'])
        failed  = sorted([r for r in all_results if not r['pass']],
                         key=lambda x: -x['score'])
        return passed, failed


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 5: 第二輪 成分股 ICT/SMC 評分  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
class ICTSMCScorer:
    """
    多時框共振 + 六維ICT/SMC評分引擎
    
    評分項目:
      +30  Stop Hunt 流動性獵殺後反轉
      +25  FVG 未填補缺口且價格回踩
      +25  Order Block 回踩且量縮
      +20  OTE 62%~79% 最佳進場區
      +20  BOS 多頭結構突破
      +15  MTF三框共振加分
      +10  Discount 區加分
      -10  Premium 區追高扣分
      -20  股價 < MA20
      -30  CHoCH 空頭轉換
    """

    def __init__(self, cfg: dict):
        self.cfg    = cfg
        self.engine = StructureEngine(cfg)

    def analyze(self, ticker: str, source_etf: str = '') -> dict:
        """完整分析單一股票，返回ICT/SMC評分結果"""
        result = {
            'ticker'       : ticker,
            'source_etf'   : source_etf,
            'success'      : False,
            'price'        : None,
            'score'        : 0,
            'action'       : 'HOLD',
            'action_zh'    : '持有觀察',
            'change_5d'    : 0.0,
            'stop_hunt'    : {},
            'fvg'          : {},
            'ob'           : {},
            'ote'          : {},
            'bos'          : {},
            'pd_zone'      : {},
            'mtf_bull'     : False,
            'kill_zone'    : None,
            'kill_zone_ok' : False,
            'stop_loss'    : None,
            'kill_price_lo': None,
            'kill_price_hi': None,
            'reasons'      : [],
            'error'        : '',
        }
        
        try:
            # ── 日線資料 ─────────────────────────────────────────────────
            df_1d = get_ohlcv(ticker, period='1y', interval='1d')
            if df_1d is None or len(df_1d) < 65:
                result['error'] = '日線資料不足'
                return result
            
            price     = df_1d['Close'].iloc[-1]
            result['price'] = round(price, 4)
            
            if len(df_1d) >= 6:
                result['change_5d'] = round(
                    (price - df_1d['Close'].iloc[-6]) / df_1d['Close'].iloc[-6] * 100, 2)
            
            # ── MA20 門檻（-20分）───────────────────────────────────────
            ma20   = df_1d['Close'].rolling(20).mean().iloc[-1]
            ma60   = df_1d['Close'].rolling(60).mean().iloc[-1]
            ma5    = df_1d['Close'].rolling(5).mean().iloc[-1]
            
            # ── 六大 ICT/SMC 結構偵測 ────────────────────────────────────
            bos      = self.engine.detect_bos_choch(df_1d)
            fvg      = self.engine.detect_fvg(df_1d)
            ob       = self.engine.detect_order_block(df_1d)
            sh       = self.engine.detect_stop_hunt(df_1d)
            ote      = self.engine.calc_ote(df_1d)
            pd_zone  = self.engine.premium_discount(df_1d)
            
            result.update({
                'bos': bos, 'fvg': fvg, 'ob': ob,
                'stop_hunt': sh, 'ote': ote, 'pd_zone': pd_zone,
            })
            
            # ── 多時框共振 (1H + 15M) ─────────────────────────────────
            df_1h  = get_ohlcv(ticker, period='60d',  interval='1h')
            df_15m = get_ohlcv(ticker, period='5d',   interval='15m')
            
            mtf_bull = self._check_mtf_confluence(df_1d, df_1h, df_15m)
            result['mtf_bull'] = mtf_bull
            
            # ── Kill Zone ───────────────────────────────────────────────
            kz = KillZoneFilter()
            result['kill_zone']    = kz.current_zone()
            result['kill_zone_ok'] = kz.is_in_kill_zone()
            
            # ══════════════════════════════════════════════════════════════
            # ★ 評分初始化 (v9.2修復: 此處必須初始化，否則後續 += 拋出 NameError)
            # ══════════════════════════════════════════════════════════════
            score   = 0
            reasons = []
            
            # 計算RSI（用於底分）
            delta   = df_1d['Close'].diff()
            gain    = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
            loss    = (-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
            rsi_now = 100 - 100 / (1 + gain.iloc[-1] / (loss.iloc[-1] + 1e-10))
            
            # MA5連續上漲（3日）→ +10
            ma5_series = df_1d['Close'].rolling(5).mean().dropna()
            ma5_rising = (len(ma5_series) >= 4 and
                          ma5_series.iloc[-1] > ma5_series.iloc[-2] > ma5_series.iloc[-3])
            
            # 量比（5日量/20日均量）
            vol_5d_avg  = df_1d['Volume'].tail(5).mean()
            vol_20d_avg = df_1d['Volume'].tail(20).mean()
            vol_ratio   = vol_5d_avg / (vol_20d_avg + 1e-10)
            
            # 5日漲幅強勢
            chg5 = result['change_5d']
            
            # 底分計算 (最多 +35，避免掩蓋ICT信號的分量感)
            base_score   = 0
            base_reasons = []
            
            if price > ma60:                        # 價格在MA60之上 +10
                base_score += 10
                base_reasons.append(f'📈 MA60上方+10')
            else:
                base_score -= 5
            
            if price > ma20:                        # 價格在MA20之上 +8
                base_score += 8
                base_reasons.append('📈 MA20上方+8')
            
            if ma5_rising:                          # MA5連漲 +7
                base_score += 7
                base_reasons.append('📈 MA5上升+7')
            
            if 30 < rsi_now < 50:                   # RSI低位回升 +8
                base_score += 8
                base_reasons.append(f'📊 RSI低位{rsi_now:.0f}+8')
            elif 50 <= rsi_now < 65:                # RSI健康區間 +5
                base_score += 5
                base_reasons.append(f'📊 RSI中性{rsi_now:.0f}+5')
            elif rsi_now >= 75:                     # RSI超買 -5
                base_score -= 5
                base_reasons.append(f'📊 RSI超買{rsi_now:.0f}-5')
            
            if vol_ratio >= 1.5:                    # 大量能 +7
                base_score += 7
                base_reasons.append(f'💥 量比{vol_ratio:.1f}x+7')
            elif vol_ratio >= 1.0:                  # 正常量能 +3
                base_score += 3
                base_reasons.append(f'💥 量比{vol_ratio:.1f}x+3')
            
            if chg5 >= 5:                           # 強勢5日漲幅 +5
                base_score += 5
                base_reasons.append(f'🔥 5日+{chg5:.1f}%+5')
            elif chg5 >= 2:
                base_score += 3
                base_reasons.append(f'漲{chg5:.1f}%+3')
            elif chg5 < -3:
                base_score -= 5
                base_reasons.append(f'跌{chg5:.1f}%-5')
            
            score += base_score
            reasons.extend(base_reasons)
            
            # 儲存底分指標供輸出使用
            result['rsi']       = round(rsi_now, 1)
            result['vol_ratio'] = round(vol_ratio, 2)
            
            # ① Stop Hunt +30
            if sh.get('bull_stop_hunt'):
                score += self.cfg['R2_STOP_HUNT_SCORE']
                reasons.append(f"⚡ Stop Hunt ↑ +{self.cfg['R2_STOP_HUNT_SCORE']} "
                               f"({sh.get('hunt_level', ''):.2f})")
            elif sh.get('bear_stop_hunt'):
                score -= 15
                reasons.append('⚡ Stop Hunt ↓ 空頭 -15')
            
            # ② FVG +25
            if fvg.get('in_bullish_fvg'):
                score += self.cfg['R2_FVG_SCORE']
                reasons.append(f"📊 Bullish FVG +{self.cfg['R2_FVG_SCORE']} "
                               f"[{fvg['bull_fvg_bot']:.2f}~{fvg['bull_fvg_top']:.2f}]")
            elif fvg.get('has_bullish_fvg'):
                score += 10
                reasons.append('📊 FVG存在(未回踩) +10')
            
            if fvg.get('in_bearish_fvg'):
                score -= 15
                reasons.append('📊 Bearish FVG 空頭 -15')
            
            # ③ Order Block +25
            if ob.get('in_bull_ob') and ob.get('vol_contraction'):
                score += self.cfg['R2_OB_SCORE']
                reasons.append(f"🟦 Bull OB+量縮 +{self.cfg['R2_OB_SCORE']} "
                               f"[{ob['bull_ob_bot']:.2f}~{ob['bull_ob_top']:.2f}]")
            elif ob.get('in_bull_ob'):
                score += 15
                reasons.append('🟦 Bull OB(無量縮) +15')
            
            if ob.get('in_bear_ob'):
                score -= 15
                reasons.append('🟦 Bear OB 空頭 -15')
            
            # ④ OTE +20
            if ote.get('in_ote') and ote.get('ote_direction') == 'BULL':
                score += self.cfg['R2_OTE_SCORE']
                reasons.append(f"🎯 OTE {ote['fib_pct']:.0f}% 最佳進場 "
                               f"+{self.cfg['R2_OTE_SCORE']}")
            elif ote.get('in_ote') and ote.get('ote_direction') == 'BEAR':
                score -= 10
                reasons.append(f"🎯 OTE {ote['fib_pct']:.0f}% 空頭區 -10")
            
            # ⑤ BOS +20
            if bos.get('bos_bull') or bos.get('choch_bull'):
                bonus = 25 if bos.get('choch_bull') else self.cfg['R2_BOS_BULL_SCORE']
                score += bonus
                tag = 'CHoCH多頭反轉' if bos.get('choch_bull') else 'BOS多頭突破'
                reasons.append(f"🔺 {tag} +{bonus}")
            
            if bos.get('choch_bear'):
                score += self.cfg['R2_CHOCH_BEAR_PENALTY']
                reasons.append(f"🔻 CHoCH空頭轉換 {self.cfg['R2_CHOCH_BEAR_PENALTY']}")
            elif bos.get('bos_bear'):
                score -= 15
                reasons.append('🔻 BOS空頭跌破 -15')
            
            # ⑥ MTF共振 +15
            if mtf_bull:
                score += self.cfg['R2_MTF_BONUS']
                reasons.append(f"📡 三框MTF共振 +{self.cfg['R2_MTF_BONUS']}")
            
            # Premium / Discount
            zone = pd_zone.get('zone', 'UNKNOWN')
            if zone == 'DISCOUNT':
                score += self.cfg['R2_DISCOUNT_BONUS']
                reasons.append(f"💚 Discount區 +{self.cfg['R2_DISCOUNT_BONUS']}")
            elif zone == 'PREMIUM':
                score += self.cfg['R2_PREMIUM_PENALTY']
                reasons.append(f"🔴 Premium區 {self.cfg['R2_PREMIUM_PENALTY']}")
            
            # MA20 門檻
            if price < ma20:
                score += self.cfg['R2_MA20_PENALTY']
                reasons.append(f"❌ 低於MA20({ma20:.2f}) {self.cfg['R2_MA20_PENALTY']}")
            
            # ── 停損 & Kill Zone 信號 ──────────────────────────────────
            stop_loss   = round(ma5 * 0.985, 4)
            kill_lo     = round(price * 0.993, 4)
            kill_hi     = round(price * 1.007, 4)
            result.update({
                'stop_loss'     : stop_loss,
                'kill_price_lo' : kill_lo,
                'kill_price_hi' : kill_hi,
            })
            
            # Kill Zone 時間加成
            if result['kill_zone_ok']:
                score += 5
                reasons.append(f"⏰ {result['kill_zone']} Kill Zone +5")
            
            # ── 最終決策 ────────────────────────────────────────────────
            score = max(-100, min(120, score))  # 限幅
            result['score'] = score
            
            if score >= self.cfg['BUY_SCORE']:
                result['action']    = 'BUY'
                result['action_zh'] = '買進 ▲'
                if score >= 100:
                    result['grade'] = '★★★ 精英進場'
                elif score >= 90:
                    result['grade'] = '★★☆ 強力買進'
                else:
                    result['grade'] = '★☆☆ 謹慎買進'
            elif score >= self.cfg['HOLD_SCORE']:
                result['action']    = 'WATCH'
                result['action_zh'] = '觀察 ◆'
                result['grade']     = '等待進場點'
            elif bos.get('choch_bear') or bos.get('bos_bear'):
                result['action']    = 'SELL'
                result['action_zh'] = '賣出 ▼'
                result['grade']     = '空頭結構'
            else:
                result['action']    = 'SKIP'
                result['action_zh'] = '略過 ─'
                result['grade']     = '條件不足'
            
            result['reasons'] = reasons
            result['success'] = True
            result['ma20']    = round(ma20, 4)
            result['ma60']    = round(ma60, 4)
            result['ma5']     = round(ma5, 4)
            result['zone']    = zone
            result['structure'] = bos.get('structure', 'RANGING')
            
        except Exception as e:
            result['error'] = str(e)[:100]
        
        return result

    def _check_mtf_confluence(self, df_1d, df_1h, df_15m) -> bool:
        """
        三框共振: 1D 多頭 + 1H 多頭 + 15M 多頭
        判斷: Close > MA20 且 BOS 多頭
        """
        bulls = []
        for df in [df_1d, df_1h, df_15m]:
            if df is None or len(df) < 25:
                continue
            ma20  = df['Close'].rolling(20).mean().iloc[-1]
            close = df['Close'].iloc[-1]
            bos   = self.engine.detect_bos_choch(df)
            is_bull = (close > ma20) and (bos['bos_bull'] or bos['structure'] == 'BULLISH')
            bulls.append(is_bull)
        
        # 至少2框多頭 = 共振
        return sum(bulls) >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 6: 報表輸出  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
def print_r1_results(passed: list, failed: list):
    """第一輪結果報表"""
    sep()
    cp(f"  🔥 第一輪: ETF賽道篩選結果  通過: {len(passed)} 檔  "
       f"淘汰: {len(failed)} 檔", Fore.CYAN, bold=True)
    sep()
    
    header = f"  {'ETF':<12} {'市場':<5} {'評分':>5} {'5日%':>7} {'量比':>6} " \
             f"{'流動':>5} {'趨勢':>5} {'量增':>5} {'BOS':>6} {'結構':<10}"
    cp(header, Fore.YELLOW, bold=True)
    sep('-', 76, Fore.YELLOW)
    
    for r in passed[:CONFIG['R1_TOP_N_ETF']]:
        c = Fore.GREEN
        liq  = '✅' if r['liquidity_ok'] else '❌'
        trnd = '✅' if r['trend_ok']     else '❌'
        flw  = '✅' if r['flow_ok']      else '❌'
        bos  = '↑BOS' if r['bos_bull']  else '──'
        print(
            f"  {c}{r['ticker']:<12}{Style.RESET_ALL}"
            f" {r['market']:<5} {c}{r['score']:>5}{Style.RESET_ALL}"
            f" {r['change_5d']:>+7.2f}%"
            f" {r['vol_ratio']:>5.1f}x"
            f"  {liq}  {trnd}  {flw}"
            f"  {bos:<6}"
            f" {r['structure']:<10}"
        )
        # 顯示理由
        reasons_str = ' | '.join(r['reasons'][:3])
        cp(f"  {'':12}  {reasons_str}", Fore.WHITE)
        if r.get('holding_return', 0) != 0:
            cp(f"  {'':12}  持股均漲: {r['holding_return']:+.1f}%  "
               f"前5大持股: {', '.join(r['top_holdings'][:5])}", Fore.MAGENTA)
        sep('-', 76, Fore.CYAN)


def print_r2_result(i: int, r: dict):
    """第二輪單股詳細結果"""
    sep('─', 76, Fore.CYAN)
    
    action_color = {
        'BUY': Fore.GREEN, 'WATCH': Fore.YELLOW,
        'SELL': Fore.RED,  'SKIP': Fore.WHITE,
    }.get(r['action'], Fore.WHITE)
    
    # 標題列
    print(
        f"  {Fore.CYAN}#{i:02d}{Style.RESET_ALL} "
        f"{Style.BRIGHT}{r['ticker']:<7}{Style.RESET_ALL} "
        f"來自 {Fore.MAGENTA}{r['source_etf']:<8}{Style.RESET_ALL} "
        f"${r.get('price', 'N/A')}"
        f"  {Fore.CYAN}{r.get('change_5d', 0):+.2f}%{Style.RESET_ALL}"
        f"  {action_color}{Style.BRIGHT}{r['action_zh']:<8}{Style.RESET_ALL}"
        f"  {action_color}{r.get('grade','')}{Style.RESET_ALL}"
    )
    
    # ICT 信號列
    bos   = r.get('bos', {})
    fvg   = r.get('fvg', {})
    ob    = r.get('ob', {})
    sh    = r.get('stop_hunt', {})
    ote   = r.get('ote', {})
    pd    = r.get('pd_zone', {})
    
    icons = []
    if sh.get('bull_stop_hunt'):    icons.append(f"{Fore.GREEN}⚡StopHunt↑{Style.RESET_ALL}")
    if sh.get('bear_stop_hunt'):    icons.append(f"{Fore.RED}⚡StopHunt↓{Style.RESET_ALL}")
    if fvg.get('in_bullish_fvg'):  icons.append(f"{Fore.GREEN}📊FVG↑{Style.RESET_ALL}")
    if fvg.get('in_bearish_fvg'):  icons.append(f"{Fore.RED}📊FVG↓{Style.RESET_ALL}")
    if ob.get('in_bull_ob'):        icons.append(f"{Fore.GREEN}🟦OB{'+縮量' if ob.get('vol_contraction') else ''}{Style.RESET_ALL}")
    if ote.get('in_ote'):           icons.append(f"{Fore.CYAN}🎯OTE{ote['fib_pct']:.0f}%{Style.RESET_ALL}")
    if bos.get('choch_bull'):       icons.append(f"{Fore.GREEN}🔺CHoCH↑{Style.RESET_ALL}")
    if bos.get('choch_bear'):       icons.append(f"{Fore.RED}🔻CHoCH↓{Style.RESET_ALL}")
    if bos.get('bos_bull'):         icons.append(f"{Fore.GREEN}BOS↑{Style.RESET_ALL}")
    if r.get('mtf_bull'):           icons.append(f"{Fore.CYAN}📡MTF{Style.RESET_ALL}")
    
    pd_color = Fore.GREEN if pd.get('zone') == 'DISCOUNT' else (
               Fore.RED if pd.get('zone') == 'PREMIUM' else Fore.WHITE)
    icons.append(f"{pd_color}{pd.get('zone','?')}{Style.RESET_ALL}")
    
    print(f"       {' '.join(icons)}")
    
    # 技術資料
    print(
        f"       MA5:{r.get('ma5',0):.2f}  MA20:{r.get('ma20',0):.2f}  "
        f"MA60:{r.get('ma60',0):.2f}  "
        f"結構:{r.get('structure','?')}  "
        f"區域:{pd.get('zone','?')}({pd.get('pct_from_eq',0):+.1f}%)"
    )
    
    # Kill Zone & 進場信息
    kz_str = f"🎯 {r['kill_zone']}" if r.get('kill_zone_ok') else "⏰ 非Kill Zone"
    print(
        f"       {kz_str}  "
        f"評分:{action_color}{Style.BRIGHT}{r['score']:+d}{Style.RESET_ALL}  "
        f"Kill區:{r.get('kill_price_lo',0):.2f}~{r.get('kill_price_hi',0):.2f}  "
        f"停損:{r.get('stop_loss',0):.2f}"
    )
    
    # 評分理由
    if r.get('reasons'):
        reasons_str = '  '.join(r['reasons'][:5])
        cp(f"       {reasons_str}", Fore.WHITE)


def print_final_table(results: list):
    """最終匯總排行榜"""
    sep()
    cp("  🎯 【MJ Sniper v9.0 最終狙擊名單】", Fore.CYAN, bold=True)
    sep()
    
    buy   = sorted([r for r in results if r['action']=='BUY'],  key=lambda x: -x['score'])
    watch = sorted([r for r in results if r['action']=='WATCH'], key=lambda x: -x['score'])
    sell  = sorted([r for r in results if r['action']=='SELL'],  key=lambda x: x['score'])
    
    hdr = (f"  {'代碼':<7} {'來源ETF':<8} {'評分':>5} {'建議':<10} "
           f"{'5日%':>7} {'Stop Hunt':>10} {'FVG':>5} {'OB':>4} "
           f"{'OTE':>5} {'MTF':>5} {'區域':<12} {'停損':>8}")
    cp(hdr, Fore.YELLOW, bold=True)
    sep('-', 76, Fore.YELLOW)
    
    groups = [
        (buy,   '▲ 精準狙擊目標', Fore.GREEN),
        (watch, '◆ 觀察候選名單', Fore.YELLOW),
        (sell,  '▼ 規避 / 賣出', Fore.RED),
    ]
    
    for grp, label, color in groups:
        if not grp:
            continue
        cp(f"\n  ── {label} ──", color)
        for r in grp:
            if not r.get('success'):
                continue
            sh   = r.get('stop_hunt', {})
            fvg  = r.get('fvg', {})
            ob   = r.get('ob', {})
            ote  = r.get('ote', {})
            
            print(
                f"  {color}{r['ticker']:<7}{Style.RESET_ALL}"
                f" {r['source_etf']:<8}"
                f" {color}{r['score']:>+5d}{Style.RESET_ALL}"
                f" {color}{r['action_zh']:<10}{Style.RESET_ALL}"
                f" {r['change_5d']:>+7.2f}%"
                f" {'⚡' if sh.get('bull_stop_hunt') else '──':>10}"
                f" {'✅' if fvg.get('in_bullish_fvg') else '──':>5}"
                f" {'✅' if ob.get('in_bull_ob') else '──':>4}"
                f" {'✅' if ote.get('in_ote') else '──':>5}"
                f" {'✅' if r.get('mtf_bull') else '──':>5}"
                f" {r.get('zone','?'):<12}"
                f" {r.get('stop_loss',0):>8.2f}"
            )
    
    # ── 略過股票（緊湊格式，附底分指標）──────────────────────────────────
    skips = sorted([r for r in results if r['action']=='SKIP' and r.get('success')],
                   key=lambda x: -x['score'])
    if skips:
        cp(f"\n  ── ─ 條件不足（略過）共 {len(skips)} 檔 ──", Fore.WHITE)
        cp(f"  {'代碼':<7} {'ETF':<8} {'評分':>5} {'5日%':>7} "
           f"{'RSI':>5} {'量比':>5} {'MA20':>7} {'結構':<10}", Fore.WHITE)
        sep('-', 76, Fore.WHITE)
        for r in skips:
            print(
                f"  {Fore.WHITE}{r['ticker']:<7}{Style.RESET_ALL}"
                f" {r['source_etf']:<8}"
                f" {r['score']:>+5d}"
                f" {r['change_5d']:>+7.2f}%"
                f" {r.get('rsi', 0):>5.0f}"
                f" {r.get('vol_ratio', 0):>5.1f}x"
                f" {r.get('ma20', 0):>7.2f}"
                f" {r.get('structure','?'):<10}"
            )


def export_csv(r1_results: list, r2_results: list, output_dir: str):
    """匯出 CSV — v9.1 修復: pd 命名衝突改為 pdz"""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    
    # 第一輪
    r1_rows = []
    for r in r1_results:
        r1_rows.append({
            'ETF': r['ticker'], '市場': r['market'], '評分': r['score'],
            '5日漲幅%': r['change_5d'], '量比': r['vol_ratio'],
            '流動性': r['liquidity_ok'], '趨勢MA60': r['trend_ok'],
            '量能增加': r['flow_ok'], 'BOS多頭': r['bos_bull'],
            '結構': r['structure'], '通過預篩': r['pass'],
            '理由': ' | '.join(r['reasons']),
        })
    pd.DataFrame(r1_rows).to_csv(
        f"{output_dir}/R1_ETF_賽道_{ts}.csv",
        index=False, encoding='utf-8-sig')
    
    # 第二輪 — 修復: 本地變數改名為 pdz，避免遮蓋 pandas 模組
    r2_rows = []
    for r in r2_results:
        if not r.get('success'):
            continue
        bos = r.get('bos', {})
        fvg = r.get('fvg', {})
        ob  = r.get('ob',  {})
        sh  = r.get('stop_hunt', {})
        ote = r.get('ote', {})
        pdz = r.get('pd_zone', {})   # ← 改名 pd → pdz
        r2_rows.append({
            '代碼': r['ticker'], '來源ETF': r['source_etf'],
            '評分': r['score'], '建議': r['action_zh'],
            '等級': r.get('grade',''), '5日漲幅%': r['change_5d'],
            '現價': r['price'], '停損': r['stop_loss'],
            'Kill區低': r['kill_price_lo'], 'Kill區高': r['kill_price_hi'],
            'Stop Hunt↑': sh.get('bull_stop_hunt', False),
            'FVG↑回踩':   fvg.get('in_bullish_fvg', False),
            'OB+量縮':    ob.get('in_bull_ob', False) and ob.get('vol_contraction', False),
            'OTE區間':    ote.get('in_ote', False),
            'BOS多頭':    bos.get('bos_bull', False),
            'CHoCH多頭':  bos.get('choch_bull', False),
            'CHoCH空頭':  bos.get('choch_bear', False),
            'MTF共振':    r.get('mtf_bull', False),
            '價格區域':   r.get('zone', ''),
            'RSI':        r.get('rsi', ''),
            '量比':       r.get('vol_ratio', ''),
            'MA5': r.get('ma5',''), 'MA20': r.get('ma20',''),
            '結構': r.get('structure',''),
            'Kill Zone':  r.get('kill_zone','非Kill Zone'),
            '理由': ' | '.join(r.get('reasons', [])),
        })
    r2_path = f"{output_dir}/R2_成分股_ICT_{ts}.csv"
    pd.DataFrame(r2_rows).to_csv(r2_path, index=False, encoding='utf-8-sig')
    
    cp(f"\n  💾 CSV已輸出:", Fore.GREEN)
    cp(f"     {output_dir}/R1_ETF_賽道_{ts}.csv", Fore.WHITE)
    cp(f"     {r2_path}", Fore.WHITE)


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 7: 主程式  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    banner()
    cp(f"  執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", Fore.WHITE)
    
    # Kill Zone 狀態
    kz = KillZoneFilter()
    cp(f"  {kz.status_str()}", Fore.CYAN, bold=True)
    cp(f"  買進門檻: ≥{CONFIG['BUY_SCORE']}分  |  持有觀察: ≥{CONFIG['HOLD_SCORE']}分  |  "
       f"賣出: BOS空頭 / CHoCH", Fore.WHITE)
    sep()
    
    # ══════════════════════════════════════════════════════
    # 第一輪: ETF 賽道預篩
    # ══════════════════════════════════════════════════════
    cp("\n  【第一輪】ETF 賽道三道預篩 + 強度評分", Fore.CYAN, bold=True)
    sep('-', 76)
    cp("  ① 流動性門檻  ② 趨勢一致性(>MA60)  ③ 資金流向(5日量>20日均量)", Fore.WHITE)
    
    screener = ETFPreScreener(CONFIG)
    passed, failed = screener.scan_all(ETF_UNIVERSE)
    
    print_r1_results(passed, failed)
    
    cp(f"\n  ✅ 通過賽道: {[r['ticker'] for r in passed[:CONFIG['R1_TOP_N_ETF']]]}", Fore.GREEN)
    
    if not passed:
        cp("  ⚠ 無ETF通過預篩，請確認網路或降低門檻 R1_ETF_SCORE_PASS", Fore.YELLOW)
        return
    
    # ══════════════════════════════════════════════════════
    # 第二輪: 成分股 ICT/SMC 分析
    # ══════════════════════════════════════════════════════
    sep()
    cp("\n  【第二輪】成分股 ICT/SMC 精密評分 (多時框共振)", Fore.CYAN, bold=True)
    sep('-', 76)
    
    # ── 建立成分股池，並打印完整清單 ────────────────────────────────────
    stock_pool = []   # [(ticker, source_etf), ...]
    seen       = set()
    top_etfs   = passed[:CONFIG['R1_TOP_N_ETF']]
    
    sep('─', 76, Fore.YELLOW)
    cp("  📋 第一輪通過 ETF → 解鎖成分股清單", Fore.YELLOW, bold=True)
    sep('─', 76, Fore.YELLOW)
    
    for etf_r in top_etfs:
        etf_ticker   = etf_r['ticker']
        holdings     = etf_r.get('top_holdings', [])
        
        # 若第一輪沒抓到，直接查備援表
        if not holdings:
            holdings = ETF_HOLDINGS_FALLBACK.get(etf_ticker, [])[:CONFIG['R1_TOP_HOLDINGS']]
            etf_r['top_holdings'] = holdings
        
        # 打印 ETF 標題 + 評分 + 結構
        print(
            f"\n  {Fore.CYAN}{'─'*4} {Style.BRIGHT}{etf_ticker}{Style.RESET_ALL}"
            f"{Fore.CYAN} ({etf_r['market']})  "
            f"評分:{etf_r['score']}  5日:{etf_r['change_5d']:+.2f}%  "
            f"結構:{etf_r['structure']}  "
            f"{'BOS↑' if etf_r['bos_bull'] else ''} {'─'*4}{Style.RESET_ALL}"
        )
        
        if not holdings:
            cp(f"     ⚠ 無成分股資料（備援表未包含此ETF）", Fore.RED)
            continue
        
        # 打印成分股表格
        col_per_row = 5
        rows = [holdings[i:i+col_per_row] for i in range(0, len(holdings), col_per_row)]
        for row_idx, row in enumerate(rows):
            row_str = '   '.join(
                f"{Fore.GREEN if (t not in seen) else Fore.WHITE}"
                f"{t:<10}{Style.RESET_ALL}"
                for t in row
            )
            prefix = f"     {'新增' if row_idx==0 else '    '} → "
            print(f"  {prefix}{row_str}")
        
        # 加入股票池（去重）
        new_added = 0
        for t in holdings:
            if t and t not in seen:
                stock_pool.append((t, etf_ticker))
                seen.add(t)
                new_added += 1
        
        cp(f"     共 {len(holdings)} 支成分股，新增 {new_added} 支（累計 {len(seen)} 支）",
           Fore.YELLOW)
    
    sep('─', 76, Fore.YELLOW)
    
    # 若完全沒成分股，降級用 ETF 自身
    if not stock_pool:
        cp("  ⚠ 無法取得任何成分股，改用第一輪ETF本身進行分析", Fore.YELLOW)
        stock_pool = [(r['ticker'], r['ticker']) for r in top_etfs]
    
    # ── 打印最終進入第二輪的完整股票清單 ────────────────────────────────
    sep()
    cp(f"  🎯 進入第二輪分析: 共 {len(stock_pool)} 支個股", Fore.CYAN, bold=True)
    
    # 依 source_etf 分組打印
    from itertools import groupby
    pool_sorted = sorted(stock_pool, key=lambda x: x[1])
    for etf_src, grp in groupby(pool_sorted, key=lambda x: x[1]):
        grp_list  = [t for t, _ in grp]
        grp_str   = '  '.join(f"{Fore.WHITE}{t}{Style.RESET_ALL}" for t in grp_list)
        cp(f"  {Fore.MAGENTA}{etf_src:<10}{Style.RESET_ALL} → {grp_str}")
    sep('─', 76)
    
    scorer  = ICTSMCScorer(CONFIG)
    results = []
    
    def analyze_one(args):
        ticker, source = args
        return scorer.analyze(ticker, source)
    
    with ThreadPoolExecutor(max_workers=CONFIG['MAX_WORKERS']) as ex:
        futures = {ex.submit(analyze_one, args): args for args in stock_pool}
        for future in tqdm(as_completed(futures), total=len(futures),
                           desc="  ICT/SMC分析", ncols=74):
            r = future.result()
            results.append(r)
    
    # 排序: 買進優先, 然後評分降序
    action_order = {'BUY': 0, 'WATCH': 1, 'SELL': 2, 'SKIP': 3}
    results.sort(key=lambda x: (action_order.get(x['action'], 9), -x['score']))
    
    # ── 詳細輸出: BUY/WATCH/SELL 完整格式 + SKIP 緊湊格式 ───────────────
    sep()
    cp("  📋 成分股詳細分析報告", Fore.CYAN, bold=True)
    key_results = [r for r in results if r.get('success') and r['action'] != 'SKIP']
    skip_results = [r for r in results if r.get('success') and r['action'] == 'SKIP']
    for i, r in enumerate(key_results, 1):
        print_r2_result(i, r)
    if skip_results:
        sep('─', 76, Fore.WHITE)
        cp(f"  （略過 {len(skip_results)} 檔，評分不足，詳見匯總表底部）", Fore.WHITE)
    
    # ── 最終名單 ─────────────────────────────────────────
    print_final_table(results)
    
    # ── SOP 提醒 ─────────────────────────────────────────
    sep()
    cp("  📋 每日操作 SOP", Fore.CYAN, bold=True)
    sep('-', 76, Fore.CYAN)
    sop = [
        ("08:45 盤前", "執行本腳本確認ETF賽道方向（第一輪結果）"),
        ("09:00-09:30", "對照第二輪名單，確認個股是否在 Kill Zone 時間窗內"),
        ("進場條件",
         "趨勢↑ + BOS/CHoCH多頭 + Discount區 + 量縮回踩 + OTE 62%-79%"),
        ("停損設置",
         "嚴格用程式輸出 stop_loss（MA5×0.985），不主觀移動"),
        ("出場邏輯",
         "到達 Premium 區（前高結構）或出現 CHoCH 空頭訊號"),
        ("風險管理",
         "同時持有 ≤ 8 檔，每筆風險 ≤ 總資金 1.5%，RR ≥ 2:1"),
    ]
    for step, desc in sop:
        cp(f"  {Fore.YELLOW}{step:<14}{Fore.WHITE}{desc}", Fore.WHITE)
    
    # ── CSV 匯出 ─────────────────────────────────────────
    if CONFIG['OUTPUT_CSV']:
        export_csv(passed + failed, results, CONFIG['OUTPUT_DIR'])
    
    # ── 統計 ─────────────────────────────────────────────
    sep()
    buy_n   = len([r for r in results if r['action']=='BUY'])
    watch_n = len([r for r in results if r['action']=='WATCH'])
    sell_n  = len([r for r in results if r['action']=='SELL'])
    cp(f"  ✅ 分析完成  ETF通過: {len(passed)}檔  "
       f"買進: {buy_n}  觀察: {watch_n}  賣出: {sell_n}",
       Fore.WHITE, bold=True)
    cp(f"  完成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", Fore.WHITE)
    sep()
    
    return results, passed


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        results, etf_passed = main()
    except KeyboardInterrupt:
        cp("\n  ⚠ 用戶中止執行", Fore.YELLOW)
    except Exception as e:
        import traceback
        cp(f"\n  ✗ 系統錯誤: {e}", Fore.RED)
        traceback.print_exc()
