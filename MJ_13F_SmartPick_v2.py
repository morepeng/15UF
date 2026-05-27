#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║   MJ 13F 智能選股系統  v2.0  ·  ICT/SMC Enhanced Edition                       ║
║                                                                                  ║
║   STEP 1  SEC EDGAR 13F-HR 爬蟲  → 前30大機構持股                              ║
║   STEP 2  三道預篩 (流動性 / 趨勢 / 資金流向)                                   ║
║   STEP 3  300根K線傳統技術分析 (RSI/MACD/KDJ/BB/MA/Volume)                     ║
║   STEP 4  ICT/SMC 六維結構評分                                                   ║
║           ├─ Stop Hunt  流動性獵殺後反轉   +30                                  ║
║           ├─ FVG        公允缺口未填補     +25                                  ║
║           ├─ OB         訂單塊回踩+量縮   +25                                  ║
║           ├─ OTE        62%~79%最佳進場    +20                                  ║
║           ├─ BOS/CHoCH  結構突破/反轉      +20                                  ║
║           └─ P/D Zone   折扣區加分        +10                                   ║
║   STEP 5  複合評分 → 買進 / 持有觀察 / 賣出                                     ║
╚══════════════════════════════════════════════════════════════════════════════════╝

依賴套件:
    pip install yfinance requests pandas numpy colorama tqdm pytz

作者: MJ Sniper Lab  |  版本: 2.0.0  |  日期: 2026-05
"""

import os, time, warnings, requests
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
from xml.etree import ElementTree as ET
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import re

warnings.filterwarnings('ignore')

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class Fore:
        RED=GREEN=YELLOW=CYAN=MAGENTA=WHITE=BLUE=RESET=''
    class Style:
        BRIGHT=DIM=RESET_ALL=''


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ CONFIG v2.0  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
CONFIG = {
    # ── 13F 設定 ─────────────────────────────────────────────────────────────
    'TOP_N_STOCKS'        : 30,
    'MAX_INSTITUTIONS'    : 15,
    'REQUEST_DELAY'       : 0.5,
    'KLINE_BARS'          : 300,
    'MAX_WORKERS'         : 5,
    'OUTPUT_CSV'          : True,
    'OUTPUT_DIR'          : r'.\13F_Output',
    'DEBUG_13F'           : False,

    # ── STEP 2: 三道預篩 ────────────────────────────────────────────────────
    'R1_MIN_VOL_US'       : 500_000,   # 美股日均量 > 50萬股
    'R1_TREND_MA'         : 60,        # 收盤 > MA60
    'R1_FLOW_SHORT'       : 5,         # 近5日量
    'R1_FLOW_LONG'        : 20,        # 20日均量
    'R1_PRESCREEN_PASS'   : 2,         # 至少通過N項才進入完整分析

    # ── STEP 3: 傳統技術分析 ─────────────────────────────────────────────────
    'RSI_PERIOD'          : 14,
    'RSI_OVERSOLD'        : 30,
    'RSI_OVERBOUGHT'      : 70,
    'MACD_FAST'           : 12,
    'MACD_SLOW'           : 26,
    'MACD_SIGNAL'         : 9,
    'KDJ_PERIOD'          : 9,
    'BB_PERIOD'           : 20,
    'BB_STD'              : 2,
    'VOL_MA_PERIOD'       : 20,
    'VOL_SPIKE_RATIO'     : 2.0,
    'MA5_RISE_DAYS'       : 5,

    # ── STEP 4: ICT/SMC 結構偵測 ─────────────────────────────────────────────
    'SWING_LOOKBACK'      : 5,
    'FVG_MIN_GAP_PCT'     : 0.002,
    'OB_MIN_IMPULSE_PCT'  : 0.005,
    'STOP_HUNT_WIG_PCT'   : 0.001,
    'OTE_LOW'             : 0.62,
    'OTE_HIGH'            : 0.79,

    # ICT/SMC 評分權重
    'ICT_STOP_HUNT'       : 30,
    'ICT_FVG'             : 25,
    'ICT_OB'              : 25,
    'ICT_OTE'             : 20,
    'ICT_BOS_BULL'        : 20,
    'ICT_CHOCH_BULL'      : 25,
    'ICT_MTF_BONUS'       : 15,
    'ICT_DISCOUNT'        : 10,
    'ICT_PREMIUM_PEN'     : -10,
    'ICT_CHOCH_BEAR_PEN'  : -30,
    'ICT_MA20_PEN'        : -20,

    # ── STEP 5: 複合評分門檻 ─────────────────────────────────────────────────
    # 複合分 = TA原始分(×3) + ICT/SMC分
    # BUY ≥ 80 | WATCH 50~79 | SELL: CHoCH/BOS空頭 | SKIP < 50
    'BUY_COMPOSITE'       : 80,
    'WATCH_COMPOSITE'     : 50,

    # Kill Zone (台北時間 UTC+8)
    'KILL_ZONES': {
        'Asia'   : (9,  0, 11,  0),
        'London' : (15, 0, 17,  0),
        'NewYork': (21,30, 23, 30),
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# ░░ 機構 CIK 名單  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
MAJOR_INSTITUTIONS = {
    'Berkshire Hathaway' : '0001067983',
    'BlackRock'          : '0001364742',
    'Vanguard Group'     : '0000102909',
    'State Street'       : '0000093751',
    'JPMorgan Chase'     : '0000019617',
    'Goldman Sachs'      : '0000886982',
    'Morgan Stanley'     : '0000895421',
    'T. Rowe Price'      : '0001113169',
    'Capital Group'      : '0000814163',
    'Fidelity'           : '0000315066',
    'Invesco'            : '0000049764',
    'Wellington Mgmt'    : '0000101016',
    'Geode Capital'      : '0001239827',
    'Northern Trust'     : '0000073124',
    'BNY Mellon'         : '0000009626',
}

# ═══════════════════════════════════════════════════════════════════════════════
# ░░ 公司名稱 → Ticker 映射  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
NAME_TO_TICKER = {
    'APPLE INC':'AAPL','MICROSOFT CORP':'MSFT','NVIDIA CORP':'NVDA',
    'AMAZON COM INC':'AMZN','ALPHABET INC':'GOOGL','ALPHABET INC-CL A':'GOOGL',
    'ALPHABET INC-CL C':'GOOG','META PLATFORMS INC':'META',
    'BERKSHIRE HATHAWAY INC':'BRK-B','TESLA INC':'TSLA',
    'ELI LILLY & CO':'LLY','UNITEDHEALTH GROUP INC':'UNH',
    'EXXON MOBIL CORP':'XOM','JPMORGAN CHASE & CO':'JPM',
    'VISA INC':'V','MASTERCARD INC':'MA','MASTERCARD INCORPORATED':'MA',
    'JOHNSON & JOHNSON':'JNJ','PROCTER & GAMBLE CO':'PG',
    'PROCTER AND GAMBLE CO':'PG','BROADCOM INC':'AVGO',
    'HOME DEPOT INC':'HD','COSTCO WHOLESALE CORP':'COST',
    'COSTCO WHSL CORP NEW':'COST','MERCK & CO INC':'MRK',
    'ABBVIE INC':'ABBV','CHEVRON CORP':'CVX','CHEVRON CORP NEW':'CVX',
    'ORACLE CORP':'ORCL','SALESFORCE INC':'CRM',
    'WALMART INC':'WMT','NETFLIX INC':'NFLX',
    'ADVANCED MICRO DEVICES':'AMD','ADVANCED MICRO DEVICES INC':'AMD',
    'QUALCOMM INC':'QCOM','INTEL CORP':'INTC',
    'PEPSICO INC':'PEP','COCA COLA CO':'KO','COCA-COLA CO':'KO',
    'THERMO FISHER SCIENTIFIC':'TMO','ADOBE INC':'ADBE',
    'PAYPAL HOLDINGS INC':'PYPL','BOOKING HOLDINGS INC':'BKNG',
    'SERVICENOW INC':'NOW','PALANTIR TECHNOLOGIES':'PLTR',
    'CROWDSTRIKE HOLDINGS':'CRWD','CLOUDFLARE INC':'NET',
    'SNOWFLAKE INC':'SNOW','UBER TECHNOLOGIES INC':'UBER',
    'TAIWAN SEMICONDUCTOR':'TSM','ASML HOLDING NV':'ASML',
    'S&P GLOBAL INC':'SPGI','AMERICAN EXPRESS CO':'AXP',
    'GOLDMAN SACHS GROUP INC':'GS','MORGAN STANLEY':'MS',
    'BANK OF AMERICA CORP':'BAC','BANK AMERICA CORP':'BAC',
    'CITIGROUP INC':'C','WELLS FARGO & CO':'WFC',
    'CATERPILLAR INC':'CAT','LOCKHEED MARTIN CORP':'LMT',
    'RAYTHEON TECHNOLOGIES':'RTX','BLACKROCK INC':'BLK',
    'APPLIED MATERIALS INC':'AMAT','LAM RESEARCH CORP':'LRCX',
    'TEXAS INSTRUMENTS INC':'TXN','MICRON TECHNOLOGY INC':'MU',
    'PALO ALTO NETWORKS INC':'PANW','FORTINET INC':'FTNT',
    'INTUITIVE SURGICAL INC':'ISRG','VERTEX PHARMACEUTICALS':'VRTX',
    'REGENERON PHARMACEUTICALS':'REGN','NEXTERA ENERGY INC':'NEE',
}

# ═══════════════════════════════════════════════════════════════════════════════
# ░░ 顯示工具  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
def cprint(text, color=Fore.WHITE, bold=False):
    print(f"{''+Style.BRIGHT if bold else ''}{color}{text}{Style.RESET_ALL}")

def sep(c='═', n=78, color=Fore.CYAN):
    print(f"{color}{c*n}{Style.RESET_ALL}")

def print_banner():
    print(f"""{Fore.CYAN}{Style.BRIGHT}
╔══════════════════════════════════════════════════════════════════════════════╗
║   MJ 13F 智能選股系統  v2.0  ·  ICT/SMC Enhanced                           ║
║   13F機構持股 → 三道預篩 → 傳統TA × ICT/SMC 複合評分                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
{Style.RESET_ALL}""")


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 1: Kill Zone 時間過濾器  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
class KillZoneFilter:
    TZ = pytz.timezone('Asia/Taipei')

    def __init__(self):
        self.zones = CONFIG['KILL_ZONES']

    def now_tw(self):
        return datetime.now(self.TZ)

    def current_zone(self):
        now = self.now_tw()
        cur = now.hour * 60 + now.minute
        for name, (sh, sm, eh, em) in self.zones.items():
            if sh*60+sm <= cur <= eh*60+em:
                return name
        return None

    def status_str(self):
        zone = self.current_zone()
        now  = self.now_tw()
        if zone:
            return f"🎯 {zone} Kill Zone ({now.strftime('%H:%M')} TWN)"
        mins = now.hour*60 + now.minute
        for name, (sh, sm, eh, em) in sorted(self.zones.items(),
                                               key=lambda x: x[1][0]*60+x[1][1]):
            if sh*60+sm > mins:
                return (f"⏰ 非Kill Zone ({now.strftime('%H:%M')} TWN)"
                        f"  → 下一個: {name} {sh:02d}:{sm:02d}")
        return f"⏰ 非Kill Zone ({now.strftime('%H:%M')} TWN)"


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 2: SEC EDGAR 13F 爬蟲  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
class SEC13FScraper:
    BASE_URL  = "https://data.sec.gov"
    EDGAR_URL = "https://www.sec.gov"

    def __init__(self, delay=0.5):
        self.delay   = delay
        self.cfg_debug = CONFIG.get('DEBUG_13F', False)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MJSniper research@mjsniper.com',
            'Accept-Encoding': 'gzip, deflate',
        })

    def _get(self, url, headers=None, timeout=20):
        h = headers or {'User-Agent': 'MJSniper research@mjsniper.com'}
        for attempt in range(3):
            try:
                time.sleep(self.delay)
                r = self.session.get(url, headers=h, timeout=timeout)
                if r.status_code == 200:
                    return r
                if r.status_code == 429:
                    time.sleep(5)
            except Exception as e:
                if attempt == 2 and self.cfg_debug:
                    cprint(f"  ✗ {url[:60]}: {e}", Fore.RED)
        return None

    def get_latest_13f(self, cik, name):
        url  = f"{self.BASE_URL}/submissions/CIK{cik}.json"
        resp = self._get(url)
        if not resp:
            return None
        try:
            data = resp.json()
        except Exception:
            return None

        # 翻頁支援
        for filing_set in [data.get('filings',{}).get('recent',{})] + \
                          [None]:  # extra pages handled below
            if filing_set is None:
                for extra in data.get('filings',{}).get('files',[])[:3]:
                    er = self._get(f"{self.BASE_URL}/submissions/{extra.get('name','')}")
                    if er:
                        try:
                            filing_set = er.json()
                        except Exception:
                            continue
                        for i, form in enumerate(filing_set.get('form',[])):
                            if form in ('13F-HR','13F-HR/A'):
                                return {
                                    'cik': cik,
                                    'accession': filing_set['accessionNumber'][i],
                                    'filing_date': filing_set['filingDate'][i],
                                }
                break

            forms   = filing_set.get('form', [])
            accnums = filing_set.get('accessionNumber', [])
            dates   = filing_set.get('filingDate', [])
            for i, form in enumerate(forms):
                if form in ('13F-HR', '13F-HR/A'):
                    return {
                        'cik': cik,
                        'accession': accnums[i],
                        'filing_date': dates[i],
                    }
        return None

    def parse_holdings_xml(self, cik, accession):
        """五層策略解析13F XML"""
        acc_nd   = accession.replace('-', '')
        cik_int  = int(cik)
        base     = f"{self.EDGAR_URL}/Archives/edgar/data/{cik_int}/{acc_nd}"
        hdr      = {'User-Agent': 'MJSniper research@mjsniper.com'}

        # S1: index.json → 找關鍵字XML
        idx = self._get(f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{acc_nd}/index.json")
        if idx:
            try:
                items = idx.json().get('directory',{}).get('item',[])
                kws = ('infotable','informationtable','13f','form13f')
                for item in items:
                    fn = item.get('name','')
                    if fn.lower().endswith('.xml') and any(k in fn.lower() for k in kws):
                        r = self._get(f"{base}/{fn}", headers=hdr)
                        if r and len(r.text) > 500:
                            result = self._parse_xml(r.text)
                            if result:
                                return result
                # S2: 嘗試所有XML
                for item in items:
                    fn = item.get('name','')
                    if fn.lower().endswith('.xml') and not any(
                            x in fn.lower() for x in ('xsd','header','sgml','index')):
                        r = self._get(f"{base}/{fn}", headers=hdr)
                        if r and len(r.text) > 500:
                            result = self._parse_xml(r.text)
                            if result:
                                return result
            except Exception:
                pass

        # S3: 固定候選文件名
        for fn in ['infotable.xml','form13fInfoTable.xml','informationTable.xml',
                   'InformationTable.xml']:
            r = self._get(f"{base}/{fn}", headers=hdr)
            if r and len(r.text) > 500:
                result = self._parse_xml(r.text)
                if result:
                    return result

        # S4: HTML index 爬連結
        for suffix in [f'{accession}-index.htm', '']:
            hr = self._get(f"{base}/{suffix}", headers=hdr)
            if hr:
                for link in re.findall(r'href=["\']([^"\']*?\.xml)["\']',
                                       hr.text, re.IGNORECASE):
                    if any(x in link.lower() for x in ('xsd','schema','header')):
                        continue
                    full = (f"{self.EDGAR_URL}{link}" if link.startswith('/')
                            else f"{base}/{link.lstrip('./')}")
                    xr = self._get(full, headers=hdr)
                    if xr and len(xr.text) > 500:
                        result = self._parse_xml(xr.text)
                        if result:
                            return result

        # S5: 串流解析完整SGML文件
        try:
            sr = self.session.get(f"{base}/{accession}.txt",
                                  headers=hdr, stream=True, timeout=60)
            if sr.status_code == 200:
                buf, found = '', None
                for i, chunk in enumerate(sr.iter_content(512*1024, decode_unicode=True)):
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode('utf-8', errors='replace')
                    buf += chunk
                    m = re.search(
                        r'<TYPE>INFORMATION TABLE.*?<TEXT>(.*?)</TEXT>',
                        buf, re.DOTALL | re.IGNORECASE)
                    if m:
                        found = re.sub(r'^</?XML>\s*','',m.group(1),
                                       flags=re.MULTILINE|re.IGNORECASE).strip()
                        break
                    if len(buf) > 3*1024*1024:
                        buf = buf[-1024*1024:]
                    if i >= 50:
                        break
                sr.close()
                if found:
                    result = self._parse_xml(found)
                    if result:
                        return result
        except Exception:
            pass

        return []

    def _parse_xml(self, xml_text):
        """解析13F XML，四層fallback"""
        def safe_int(s):
            try: return int(float(str(s or '0').replace(',','')))
            except: return 0

        holdings = []
        xml_clean = xml_text.strip().lstrip('\ufeff')
        xml_clean = re.sub(r'</?XML>\s*','', xml_clean, flags=re.IGNORECASE|re.MULTILINE).strip()

        # ElementTree解析
        try:
            root = ET.fromstring(xml_clean)
            infos = (root.findall('.//{*}infoTable') or
                     root.findall('.//infoTable') or
                     [el for el in root.iter() if el.tag.endswith('infoTable')])
            for info in infos:
                def ft(tag):
                    el = info.find(f'{{*}}{tag}')
                    if el is None: el = info.find(tag)
                    return el.text.strip() if el is not None and el.text else None
                name, value, prnamt = ft('nameOfIssuer'), ft('value'), ft('sshPrnamt')
                if name and value:
                    holdings.append({
                        'name'  : name.upper().strip(),
                        'cusip' : ft('cusip') or '',
                        'value' : safe_int(value) * 1000,
                        'shares': safe_int(prnamt),
                    })
            if holdings:
                return holdings
        except ET.ParseError:
            pass

        # Regex fallback
        for m in re.finditer(
            r'<(?:\w+:)?nameOfIssuer[^>]*>(.*?)</(?:\w+:)?nameOfIssuer>.*?'
            r'<(?:\w+:)?value[^>]*>([\d,]+)</(?:\w+:)?value>.*?'
            r'<(?:\w+:)?sshPrnamt[^>]*>([\d,]+)</(?:\w+:)?sshPrnamt>',
            xml_text, re.DOTALL | re.IGNORECASE):
            holdings.append({
                'name'  : m.group(1).strip().upper(),
                'cusip' : '',
                'value' : safe_int(m.group(2)) * 1000,
                'shares': safe_int(m.group(3)),
            })
        return holdings

    def fetch_all(self, institutions, max_inst=15):
        sep()
        cprint("  📡 STEP 1: 抓取 SEC EDGAR 13F 機構持股", Fore.CYAN, bold=True)
        sep()

        pool   = defaultdict(lambda: {'value':0,'shares':0,'count':0,'names':[]})
        logged = []

        for name, cik in tqdm(list(institutions.items())[:max_inst],
                               desc="抓取13F", ncols=76):
            fi = self.get_latest_13f(cik, name)
            if not fi:
                cprint(f"  ✗ {name}: 找不到13F", Fore.RED)
                continue
            hlds = self.parse_holdings_xml(fi['cik'], fi['accession'])
            if not hlds:
                cprint(f"  ⚠ {name}: XML解析失敗 ({fi['filing_date']})", Fore.YELLOW)
                continue
            logged.append({'inst': name, 'date': fi['filing_date'], 'cnt': len(hlds)})
            for h in hlds:
                k = h['name']
                pool[k]['value']  += h['value']
                pool[k]['shares'] += h['shares']
                pool[k]['count']  += 1
                if name not in pool[k]['names']:
                    pool[k]['names'].append(name)

        sep('-', 78, Fore.YELLOW)
        cprint(f"  ✅ 成功 {len(logged)} 家機構", Fore.GREEN, bold=True)
        for lg in logged:
            cprint(f"     {lg['inst']:<30} {lg['date']}  ({lg['cnt']}筆持股)", Fore.WHITE)

        if not pool:
            return pd.DataFrame()

        total = sum(v['value'] for v in pool.values())
        rows  = []
        for name, d in pool.items():
            rows.append({
                'company_name': name,
                'total_value' : d['value'],
                'total_shares': d['shares'],
                'inst_count'  : d['count'],
                'holding_pct' : d['value']/total*100 if total else 0,
                'institutions': ', '.join(d['names'][:3]),
            })
        df = (pd.DataFrame(rows)
              .sort_values('total_value', ascending=False)
              .reset_index(drop=True))
        df['rank'] = df.index + 1
        return df


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 3: Ticker 解析  ░══════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
def resolve_ticker(company_name: str):
    name = company_name.upper().strip()
    if name in NAME_TO_TICKER:
        return NAME_TO_TICKER[name]
    suffixes = [' INC',' CORP',' LTD',' CO',' GROUP',' PLC','-CL A','-CL B',
                ' COM',' HOLDINGS',' TECHNOLOGIES',' NEW',' DEL']
    clean = name
    for s in suffixes:
        clean = clean.replace(s, '').strip()
    for k, v in NAME_TO_TICKER.items():
        kc = k
        for s in suffixes:
            kc = kc.replace(s,'').strip()
        if clean == kc:
            return v
    for k, v in NAME_TO_TICKER.items():
        if clean in k or k.split()[0] in clean:
            return v
    try:
        sr = yf.Search(clean[:20], max_results=1)
        if sr.quotes:
            t = sr.quotes[0].get('symbol','')
            if t and '.' not in t:
                return t
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 4: ICT/SMC 結構偵測引擎  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
class StructureEngine:
    def __init__(self):
        self.cfg = CONFIG

    def swing_points(self, df, lb=None):
        lb  = lb or self.cfg['SWING_LOOKBACK']
        hi  = df['High'].values
        lo  = df['Low'].values
        n   = len(df)
        shs, sls = [], []
        for i in range(lb, n-lb):
            if hi[i] == max(hi[i-lb:i+lb+1]): shs.append((i, hi[i]))
            if lo[i] == min(lo[i-lb:i+lb+1]): sls.append((i, lo[i]))
        return shs, sls

    def detect_bos_choch(self, df):
        cl = df['Close']
        price = cl.iloc[-1]
        shs, sls = self.swing_points(df)
        r = dict(bos_bull=False, bos_bear=False, choch_bull=False,
                 choch_bear=False, structure='RANGING',
                 last_sh=None, last_sl=None)
        if not shs or not sls:
            return r
        r['last_sh'] = shs[-1][1]
        r['last_sl'] = sls[-1][1]
        r['bos_bull'] = price > r['last_sh']
        r['bos_bear'] = price < r['last_sl']
        if len(shs) >= 2 and len(sls) >= 2:
            hh = shs[-1][1] > shs[-2][1]
            hl = sls[-1][1] > sls[-2][1]
            lh = shs[-1][1] < shs[-2][1]
            ll = sls[-1][1] < sls[-2][1]
            if hh and hl:   r['structure'] = 'BULLISH'
            elif lh and ll: r['structure'] = 'BEARISH'
            if r['structure'] == 'BEARISH' and r['bos_bull']:  r['choch_bull'] = True
            if r['structure'] == 'BULLISH' and r['bos_bear']:  r['choch_bear'] = True
        return r

    def detect_fvg(self, df):
        price = df['Close'].iloc[-1]
        hi, lo = df['High'].values, df['Low'].values
        n = len(df)
        bull_fvgs, bear_fvgs = [], []
        for i in range(min(n,60)-2, 0, -1):
            if lo[i] > hi[i-2] and (lo[i]-hi[i-2])/hi[i-2] >= self.cfg['FVG_MIN_GAP_PCT']:
                bot, top = hi[i-2], lo[i]
                if price >= bot:
                    bull_fvgs.append({'top':top,'bot':bot,'in_fvg': bot<=price<=top})
            elif hi[i] < lo[i-2] and (lo[i-2]-hi[i])/hi[i] >= self.cfg['FVG_MIN_GAP_PCT']:
                bot, top = hi[i], lo[i-2]
                if price <= top:
                    bear_fvgs.append({'top':top,'bot':bot,'in_fvg': bot<=price<=top})
        def best(lst):
            inz = [f for f in lst if f['in_fvg']]
            return inz[0] if inz else (lst[0] if lst else None)
        bf, brf = best(bull_fvgs), best(bear_fvgs)
        return {
            'has_bull_fvg': bf  is not None, 'in_bull_fvg': bf['in_fvg']  if bf  else False,
            'bull_top': bf['top']  if bf  else None, 'bull_bot': bf['bot']  if bf  else None,
            'has_bear_fvg': brf is not None, 'in_bear_fvg': brf['in_fvg'] if brf else False,
        }

    def detect_order_block(self, df):
        cl  = df['Close'].values
        op  = df['Open'].values
        hi  = df['High'].values
        lo  = df['Low'].values
        vol = df['Volume'].values
        n   = len(df)
        price       = cl[-1]
        avg_vol5    = np.mean(vol[-6:-1]) if n > 6 else np.mean(vol)
        vol_cont    = vol[-1] < avg_vol5
        thresh      = self.cfg['OB_MIN_IMPULSE_PCT']
        bull_obs, bear_obs = [], []
        for i in range(1, min(n-1, 60)):
            if cl[i] < op[i] and i+1 < n:
                if (hi[i+1]-cl[i])/(cl[i]+1e-10) >= thresh:
                    bull_obs.append({'top':hi[i],'bot':lo[i]})
            elif cl[i] > op[i] and i+1 < n:
                if (cl[i]-lo[i+1])/(cl[i]+1e-10) >= thresh:
                    bear_obs.append({'top':hi[i],'bot':lo[i]})
        def in_zone(obs): return next((o for o in reversed(obs)
                                       if o['bot'] <= price <= o['top']), None)
        bh = in_zone(bull_obs); brh = in_zone(bear_obs)
        return {
            'in_bull_ob': bh  is not None, 'bull_top': bh['top']  if bh  else None,
            'bull_bot': bh['bot']  if bh  else None, 'vol_contraction': vol_cont,
            'in_bear_ob': brh is not None,
        }

    def detect_stop_hunt(self, df):
        shs, sls = self.swing_points(df)
        price  = df['Close'].iloc[-1]
        lat_hi = df['High'].iloc[-1]
        lat_lo = df['Low'].iloc[-1]
        lat_cl = df['Close'].iloc[-1]
        prev_hi = df['High'].iloc[-2]
        wig     = self.cfg['STOP_HUNT_WIG_PCT']
        r = dict(bull=False, bear=False, hunt_level=None)
        for _, sl in sls[-3:]:
            if lat_lo < sl*(1-wig) and lat_cl > sl:
                r['bull'] = True; r['hunt_level'] = sl; break
        if not r['bull']:
            for _, sh in shs[-3:]:
                if lat_hi > sh*(1+wig) and lat_cl < sh:
                    r['bear'] = True; r['hunt_level'] = sh; break
        r['engulf'] = lat_cl > prev_hi
        return r

    def calc_ote(self, df):
        shs, sls = self.swing_points(df)
        price = df['Close'].iloc[-1]
        if not shs or not sls:
            return dict(in_ote=False, fib_pct=None, direction=None,
                        ote_lo=None, ote_hi=None)
        shi, shv = shs[-1]; sli, slv = sls[-1]
        rng = shv - slv + 1e-10
        if shi > sli:
            ote_lo = shv - self.cfg['OTE_HIGH'] * rng
            ote_hi = shv - self.cfg['OTE_LOW']  * rng
            fib = (shv - price) / rng
            direction = 'BULL'
        else:
            ote_lo = slv + self.cfg['OTE_LOW']  * rng
            ote_hi = slv + self.cfg['OTE_HIGH'] * rng
            fib = (price - slv) / rng
            direction = 'BEAR'
        return dict(in_ote=ote_lo<=price<=ote_hi,
                    fib_pct=round(fib*100,1), direction=direction,
                    ote_lo=round(ote_lo,4), ote_hi=round(ote_hi,4))

    def premium_discount(self, df):
        shs, sls = self.swing_points(df)
        price = df['Close'].iloc[-1]
        if not shs or not sls:
            return dict(zone='UNKNOWN', eq=None, pct=None)
        shv = max(x[1] for x in shs[-3:])
        slv = min(x[1] for x in sls[-3:])
        eq  = (shv + slv) / 2
        pct = (price - eq) / (shv - slv + 1e-10) * 100
        zone = 'DISCOUNT' if price < eq*0.995 else ('PREMIUM' if price > eq*1.005 else 'EQUILIBRIUM')
        return dict(zone=zone, eq=round(eq,4), pct=round(pct,1))


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 5: 三道預篩  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
def prescreen_stock(ticker: str, df: pd.DataFrame) -> dict:
    """
    對已有 OHLCV DataFrame 的個股執行三道預篩
    回傳: {'pass_count':N, 'liq':bool, 'trend':bool, 'flow':bool, 'reason':[...]}
    """
    cfg    = CONFIG
    close  = df['Close']
    vol    = df['Volume']
    price  = close.iloc[-1]
    reasons = []

    # ① 流動性 (日均量 > 50萬)
    avg_vol20 = vol.tail(20).mean()
    liq_ok    = avg_vol20 >= cfg['R1_MIN_VOL_US']
    reasons.append(f"{'✅' if liq_ok else '❌'} 流動性 {avg_vol20/1e6:.2f}M均量")

    # ② 趨勢 (收盤 > MA60)
    ma60      = close.rolling(cfg['R1_TREND_MA']).mean().iloc[-1]
    trend_ok  = price > ma60
    reasons.append(f"{'✅' if trend_ok else '❌'} 趨勢 {price:.2f}{'>' if trend_ok else '<'}MA60({ma60:.2f})")

    # ③ 資金流向 (近5日量 > 20日均量)
    vol5d    = vol.tail(cfg['R1_FLOW_SHORT']).mean()
    vol20d   = vol.tail(cfg['R1_FLOW_LONG']).mean()
    flow_ok  = vol5d > vol20d
    ratio    = vol5d / (vol20d + 1e-10)
    reasons.append(f"{'✅' if flow_ok else '❌'} 資金流 量比{ratio:.2f}x")

    pass_count = sum([liq_ok, trend_ok, flow_ok])
    return dict(pass_count=pass_count, liq=liq_ok, trend=trend_ok,
                flow=flow_ok, vol_ratio=round(ratio,2), reasons=reasons)


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 6: 複合分析引擎 (傳統TA + ICT/SMC)  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
class CompositeAnalyzer:
    """
    傳統TA (RSI/MACD/KDJ/BB/MA/Volume) 原始分 ×3
    + ICT/SMC 結構分 (Stop Hunt/FVG/OB/OTE/BOS/MTF)
    = 複合評分 (0~120)
    """

    def __init__(self):
        self.eng = StructureEngine()
        self.kz  = KillZoneFilter()

    # ── 傳統 TA 指標 ────────────────────────────────────────────────────────
    @staticmethod
    def _rsi(close, p=14):
        d = close.diff()
        g = d.clip(lower=0).ewm(com=p-1,min_periods=p).mean()
        l = (-d).clip(lower=0).ewm(com=p-1,min_periods=p).mean()
        return 100 - 100/(1 + g/(l+1e-10))

    @staticmethod
    def _macd(close, f=12, sl=26, sig=9):
        ef = close.ewm(span=f,adjust=False).mean()
        es = close.ewm(span=sl,adjust=False).mean()
        dif = ef - es
        dea = dif.ewm(span=sig,adjust=False).mean()
        return dif, dea, (dif-dea)*2

    @staticmethod
    def _kdj(high, low, close, p=9):
        lm = low.rolling(p).min()
        hm = high.rolling(p).max()
        rsv = (close-lm)/(hm-lm+1e-10)*100
        K = rsv.ewm(com=2,adjust=False).mean()
        D = K.ewm(com=2,adjust=False).mean()
        return K, D, 3*K-2*D

    @staticmethod
    def _bb(close, p=20, std=2):
        mid = close.rolling(p).mean()
        s   = close.rolling(p).std()
        return mid+std*s, mid, mid-std*s, (close-(mid-std*s))/((2*std*s)+1e-10)

    # ── 主分析入口 ──────────────────────────────────────────────────────────
    def analyze(self, ticker: str, company: str, rank: int,
                holding_pct: float, inst_count: int) -> dict:
        r = dict(
            ticker=ticker, company=company, rank=rank,
            holding_pct=holding_pct, inst_count=inst_count,
            success=False, error='',
            price=None, composite=0, action='SKIP', action_zh='略過',
            grade='', prescreen=None,
            # TA signals
            ta_score=0, ta_signals={},
            # ICT
            ict_score=0, ict_signals={},
            # detail
            bos={}, fvg={}, ob={}, sh={}, ote={}, pd_zone={},
            kill_zone=None, stop_loss=None,
            chg1d=0, chg1m=0, chg3m=0,
            high52=0, low52=0,
            rsi=0, K=0, D=0, pct_b=0, vol_ratio=0,
            ma5=0, ma20=0, ma60=0,
        )

        try:
            obj = yf.Ticker(ticker)
            df  = obj.history(period='2y', interval='1d')
            if df is None or len(df) < 65:
                r['error'] = f'資料不足 ({len(df) if df is not None else 0}根)'
                return r

            df = df.tail(300).copy()
            close  = df['Close']
            high   = df['High']
            low    = df['Low']
            volume = df['Volume']
            n      = len(df)
            price  = close.iloc[-1]
            r['price'] = round(float(price), 4)

            # 漲幅
            if n >= 2:  r['chg1d'] = round((price-close.iloc[-2])/close.iloc[-2]*100, 2)
            if n >= 22: r['chg1m'] = round((price-close.iloc[-22])/close.iloc[-22]*100, 2)
            if n >= 66: r['chg3m'] = round((price-close.iloc[-66])/close.iloc[-66]*100, 2)
            r['high52'] = round(float(close.max()), 2)
            r['low52']  = round(float(close.min()), 2)

            # ══ STEP 2: 三道預篩 ════════════════════════════════════════════
            ps = prescreen_stock(ticker, df)
            r['prescreen'] = ps
            pass_cnt = ps['pass_count']

            # ══ STEP 3: 傳統 TA ════════════════════════════════════════════
            rsi_s  = self._rsi(close)
            dif, dea, hist = self._macd(close)
            K, D, J  = self._kdj(high, low, close)
            _, _, bb_lo, pct_b = self._bb(close)
            ma5s  = close.rolling(5).mean()
            ma10s = close.rolling(10).mean()
            ma20s = close.rolling(20).mean()
            ma60s = close.rolling(60).mean()
            ma120 = close.rolling(120).mean()
            volma = volume.rolling(20).mean()

            rsi_v = float(rsi_s.iloc[-1]);   rsi_p = float(rsi_s.iloc[-2])
            dif_v = float(dif.iloc[-1]);     dif_p = float(dif.iloc[-2])
            dea_v = float(dea.iloc[-1]);     dea_p = float(dea.iloc[-2])
            hist_v= float(hist.iloc[-1]);    hist_p= float(hist.iloc[-2])
            K_v   = float(K.iloc[-1]);       K_p   = float(K.iloc[-2])
            D_v   = float(D.iloc[-1]);       D_p   = float(D.iloc[-2])
            pctb_v= float(pct_b.iloc[-1])
            vol_v = float(volume.iloc[-1]);  volma_v = float(volma.iloc[-1])
            ma5_v = float(ma5s.iloc[-1]);    ma20_v  = float(ma20s.iloc[-1])
            ma60_v= float(ma60s.iloc[-1]);   ma120_v = float(ma120.iloc[-1])

            r.update(rsi=round(rsi_v,1), K=round(K_v,1), D=round(D_v,1),
                     pct_b=round(pctb_v,3), ma5=round(ma5_v,2),
                     ma20=round(ma20_v,2), ma60=round(ma60_v,2))

            ta_score = 0
            ta_sigs  = {}

            # MA5 連漲
            ma5d = ma5s.dropna()
            days = CONFIG['MA5_RISE_DAYS']
            if len(ma5d) >= days+1:
                rising = all(ma5d.iloc[-i]>ma5d.iloc[-i-1] for i in range(1,days+1))
                sig = 1 if rising else (0 if ma5d.iloc[-1]>ma5d.iloc[-2] else -1)
            else:
                sig = 0
            ta_sigs['MA5'] = sig; ta_score += sig

            # RSI
            if rsi_v < 30 and rsi_v > rsi_p: sig=1
            elif rsi_v > 70: sig=-1
            elif 30 < rsi_v < 50: sig=1
            else: sig=0
            ta_sigs['RSI'] = sig; ta_score += sig

            # MACD
            cross_up = dif_p < dea_p and dif_v >= dea_v
            bull_exp = dif_v > dea_v and hist_v > hist_p
            cross_dn = dif_p > dea_p and dif_v <= dea_v
            if cross_up: sig=2
            elif bull_exp: sig=1
            elif cross_dn: sig=-2
            elif dif_v < dea_v: sig=-1
            else: sig=0
            sig = max(-2,min(2,sig)); ta_sigs['MACD'] = sig; ta_score += sig

            # KDJ
            kdj_cross = K_p<=D_p and K_v>D_v
            kdj_bull  = K_v>D_v>20 and K_v>K_p
            if kdj_cross: sig=2
            elif kdj_bull: sig=1
            elif K_v>80 and D_v>80: sig=-1
            else: sig=0
            sig = max(-2,min(2,sig)); ta_sigs['KDJ'] = sig; ta_score += sig

            # Volume
            if volma_v > 0:
                vr = vol_v / volma_v
                if vr >= 2.0 and price > float(close.iloc[-2]): sig=2
                elif vr >= 2.0 and price < float(close.iloc[-2]): sig=-2
                elif vr >= 1.3: sig=1
                elif vr < 0.5: sig=-1
                else: sig=0
            else:
                vr = 0; sig=0
            vr = round(vr, 2) if volma_v > 0 else 0
            r['vol_ratio'] = vr
            sig = max(-2,min(2,sig)); ta_sigs['Vol'] = sig; ta_score += sig

            # BB
            if pctb_v < 0.1: sig=2
            elif pctb_v < 0.3: sig=1
            elif pctb_v > 0.9: sig=-2
            elif pctb_v > 0.7: sig=-1
            else: sig=0
            sig = max(-2,min(2,sig)); ta_sigs['BB'] = sig; ta_score += sig

            # MA排列
            mvs = [v for v in [ma5_v,float(ma10s.iloc[-1]),ma20_v,ma60_v,ma120_v]
                   if not np.isnan(v)]
            if len(mvs) >= 4:
                pb = all(mvs[i]>mvs[i+1] for i in range(len(mvs)-1))
                if pb and price>ma5_v>ma20_v: sig=2
                elif price>ma5_v>ma20_v: sig=1
                elif price<ma5_v<ma20_v: sig=-1
                else: sig=0
            else: sig=0
            ta_sigs['MA'] = sig; ta_score += sig

            r['ta_score']   = ta_score
            r['ta_signals'] = ta_sigs

            # ══ STEP 4: ICT/SMC 結構評分 ════════════════════════════════════
            bos = self.eng.detect_bos_choch(df)
            fvg = self.eng.detect_fvg(df)
            ob  = self.eng.detect_order_block(df)
            sh  = self.eng.detect_stop_hunt(df)
            ote = self.eng.calc_ote(df)
            pdz = self.eng.premium_discount(df)

            r.update(bos=bos, fvg=fvg, ob=ob, sh=sh, ote=ote, pd_zone=pdz)

            # MTF (1H 簡易): close > ma20 且結構多頭
            try:
                df1h = yf.Ticker(ticker).history(period='60d', interval='1h')
                if df1h is not None and len(df1h) >= 25:
                    ma20h = df1h['Close'].rolling(20).mean().iloc[-1]
                    bos1h = self.eng.detect_bos_choch(df1h)
                    mtf_bull = (df1h['Close'].iloc[-1] > ma20h and
                                (bos1h['bos_bull'] or bos1h['structure']=='BULLISH'))
                else:
                    mtf_bull = False
            except Exception:
                mtf_bull = False

            ict_score = 0
            ict_sigs  = {}
            cfg = CONFIG

            # Stop Hunt
            if sh.get('bull'):
                ict_score += cfg['ICT_STOP_HUNT']
                ict_sigs['StopHunt'] = f"+{cfg['ICT_STOP_HUNT']} ⚡↑({sh.get('hunt_level',0):.2f})"
            elif sh.get('bear'):
                ict_score -= 15
                ict_sigs['StopHunt'] = '⚡↓ -15'

            # FVG
            if fvg.get('in_bull_fvg'):
                ict_score += cfg['ICT_FVG']
                ict_sigs['FVG'] = f"+{cfg['ICT_FVG']} 📊FVG↑"
            elif fvg.get('has_bull_fvg'):
                ict_score += 10
                ict_sigs['FVG'] = '+10 FVG存在'
            if fvg.get('in_bear_fvg'):
                ict_score -= 15
                ict_sigs['FVG_bear'] = '📊FVG↓ -15'

            # OB
            if ob.get('in_bull_ob') and ob.get('vol_contraction'):
                ict_score += cfg['ICT_OB']
                ict_sigs['OB'] = f"+{cfg['ICT_OB']} 🟦OB+量縮"
            elif ob.get('in_bull_ob'):
                ict_score += 15
                ict_sigs['OB'] = '+15 🟦OB'
            if ob.get('in_bear_ob'):
                ict_score -= 15
                ict_sigs['OB_bear'] = '🟦OB↓ -15'

            # OTE
            if ote.get('in_ote') and ote.get('direction') == 'BULL':
                ict_score += cfg['ICT_OTE']
                ict_sigs['OTE'] = f"+{cfg['ICT_OTE']} 🎯{ote['fib_pct']:.0f}%"
            elif ote.get('in_ote') and ote.get('direction') == 'BEAR':
                ict_score -= 10
                ict_sigs['OTE'] = f"🎯BEAR -10"

            # BOS / CHoCH
            if bos.get('choch_bull'):
                ict_score += cfg['ICT_CHOCH_BULL']
                ict_sigs['BOS'] = f"+{cfg['ICT_CHOCH_BULL']} 🔺CHoCH↑"
            elif bos.get('bos_bull'):
                ict_score += cfg['ICT_BOS_BULL']
                ict_sigs['BOS'] = f"+{cfg['ICT_BOS_BULL']} 🔺BOS↑"
            if bos.get('choch_bear'):
                ict_score += cfg['ICT_CHOCH_BEAR_PEN']
                ict_sigs['BOS_bear'] = f"🔻CHoCH↓ {cfg['ICT_CHOCH_BEAR_PEN']}"
            elif bos.get('bos_bear'):
                ict_score -= 15
                ict_sigs['BOS_bear'] = '🔻BOS↓ -15'

            # MTF
            if mtf_bull:
                ict_score += cfg['ICT_MTF_BONUS']
                ict_sigs['MTF'] = f"+{cfg['ICT_MTF_BONUS']} 📡1H共振"

            # Premium / Discount
            zone = pdz.get('zone','UNKNOWN')
            if zone == 'DISCOUNT':
                ict_score += cfg['ICT_DISCOUNT']
                ict_sigs['Zone'] = f"+{cfg['ICT_DISCOUNT']} 💚Discount"
            elif zone == 'PREMIUM':
                ict_score += cfg['ICT_PREMIUM_PEN']
                ict_sigs['Zone'] = f"🔴Premium {cfg['ICT_PREMIUM_PEN']}"

            # MA20門檻
            if price < ma20_v:
                ict_score += cfg['ICT_MA20_PEN']
                ict_sigs['MA20'] = f"❌<MA20 {cfg['ICT_MA20_PEN']}"

            # Kill Zone
            kz_name = self.kz.current_zone()
            r['kill_zone'] = kz_name
            if kz_name:
                ict_score += 5
                ict_sigs['KZ'] = f"+5 ⏰{kz_name}"

            r['ict_score']   = ict_score
            r['ict_signals'] = ict_sigs

            # ══ STEP 5: 複合評分 ═════════════════════════════════════════════
            # 傳統TA: -12~+12 → 乘3 → -36~+36
            # ICT/SMC: 加減分
            # 預篩加成: 全通過+10, 通2+5, 通1+0
            ps_bonus = {3:10, 2:5, 1:0, 0:-10}.get(pass_cnt, 0)
            composite = (ta_score * 3) + ict_score + ps_bonus
            composite = max(-60, min(120, composite))
            r['composite']  = composite
            r['stop_loss']  = round(float(ma5_v) * 0.985, 4)

            # 決策
            if (bos.get('choch_bear') or
                    (bos.get('bos_bear') and ict_score < -20)):
                r['action'] = 'SELL'; r['action_zh'] = '賣出 ▼'
                r['grade']  = '空頭結構'
            elif composite >= cfg['BUY_COMPOSITE']:
                r['action'] = 'BUY';  r['action_zh'] = '買進 ▲'
                r['grade']  = ('★★★ 強烈買進' if composite >= 100 else
                               '★★☆ 積極買進' if composite >= 90 else
                               '★☆☆ 謹慎買進')
            elif composite >= cfg['WATCH_COMPOSITE']:
                r['action'] = 'WATCH'; r['action_zh'] = '觀察 ◆'
                r['grade']  = '等待進場'
            else:
                r['action'] = 'SKIP'; r['action_zh'] = '略過 ─'
                r['grade']  = '條件不足'

            r['success'] = True

        except Exception as e:
            r['error'] = str(e)[:100]

        return r


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 7: 報表輸出  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
def _ac(action):
    return {
        'BUY': Fore.GREEN, 'SELL': Fore.RED,
        'WATCH': Fore.YELLOW, 'SKIP': Fore.WHITE,
    }.get(action, Fore.WHITE)


def print_detail(i, r):
    sep('─', 78, Fore.CYAN)
    ac = _ac(r['action'])
    ps = r.get('prescreen') or {}
    ps_icons = ('✅✅✅' if ps.get('pass_count',0)==3 else
                '✅✅❌' if ps.get('pass_count',0)==2 else
                '✅❌❌' if ps.get('pass_count',0)==1 else '❌❌❌')

    # 標題
    print(
        f"  {Fore.CYAN}#{i:02d}{Style.RESET_ALL} "
        f"{Style.BRIGHT}{r['ticker']:<7}{Style.RESET_ALL}"
        f" {r.get('company','')[:30]:<30} "
        f"{Fore.MAGENTA}持股{r['holding_pct']:.2f}%({r['inst_count']}機構){Style.RESET_ALL}"
    )

    # 預篩 + 價格
    chgc = Fore.GREEN if r['chg1d'] >= 0 else Fore.RED
    print(
        f"  預篩[{ps_icons}] 流動{'✅' if ps.get('liq') else '❌'} "
        f"MA60{'✅' if ps.get('trend') else '❌'} "
        f"量增{'✅' if ps.get('flow') else '❌'}  "
        f"${r['price']}  {chgc}{r['chg1d']:+.2f}%{Style.RESET_ALL} "
        f"1M:{r['chg1m']:+.1f}% 3M:{r['chg3m']:+.1f}%"
    )

    # 傳統TA信號條
    icons = {'MA5':'📈','RSI':'📊','MACD':'⚡','KDJ':'🔮','Vol':'💥','BB':'🎯','MA':'🏔'}
    ta_parts = []
    for k, v in r.get('ta_signals',{}).items():
        ico = icons.get(k,'·')
        c = Fore.GREEN if v > 0 else (Fore.RED if v < 0 else Fore.WHITE)
        m = '▲'*min(abs(v),2) if v > 0 else ('▼'*min(abs(v),2) if v < 0 else '─')
        ta_parts.append(f"{c}{ico}{m}{Style.RESET_ALL}")
    print(f"  TA [{' '.join(ta_parts)}]  "
          f"RSI:{r['rsi']:.0f} K:{r['K']:.0f}/D:{r['D']:.0f} "
          f"%B:{r['pct_b']:.2f} 量比:{r['vol_ratio']:.1f}x "
          f"MA5:{r['ma5']:.2f} MA20:{r['ma20']:.2f}")

    # ICT/SMC 信號
    ict_parts = list(r.get('ict_signals',{}).values())
    ict_str   = '  '.join(ict_parts[:6]) if ict_parts else '無ICT信號'
    pd_zone   = r.get('pd_zone',{}).get('zone','?')
    bos_s     = r.get('bos',{}).get('structure','?')
    print(f"  ICT [{ict_str}]")
    print(
        f"  結構:{bos_s}  區域:{pd_zone}  "
        f"{'⏰'+r['kill_zone'] if r.get('kill_zone') else '非KZ'}  "
        f"停損:{r.get('stop_loss',0):.2f}"
    )

    # 複合評分
    ta3  = r['ta_score'] * 3
    ict  = r['ict_score']
    comp = r['composite']
    bar  = '█' * min(int((comp+60)/1.8), 10) + '░' * max(0, 10 - int((comp+60)/1.8))
    print(
        f"  複合分: {ac}{bar}{Style.RESET_ALL} "
        f"TA(×3):{ta3:+d}  ICT:{ict:+d}  "
        f"= {ac}{Style.BRIGHT}{comp:+d}{Style.RESET_ALL}  "
        f"{ac}{Style.BRIGHT}{r['action_zh']}{Style.RESET_ALL}  {r['grade']}"
    )


def print_summary(results):
    sep()
    cprint("  📊 MJ 13F v2.0 最終排行榜", Fore.CYAN, bold=True)
    sep()

    buy   = sorted([r for r in results if r['action']=='BUY'],   key=lambda x: -x['composite'])
    watch = sorted([r for r in results if r['action']=='WATCH'],  key=lambda x: -x['composite'])
    sell  = sorted([r for r in results if r['action']=='SELL'],   key=lambda x: x['composite'])
    skip  = sorted([r for r in results if r['action']=='SKIP'],   key=lambda x: -x['composite'])

    hdr = (f"  {'#':>3} {'代碼':<7} {'公司':<22} {'複合':>6} "
           f"{'TA×3':>6} {'ICT':>6} {'建議':<10} "
           f"{'RSI':>5} {'量比':>5} {'1D%':>7} {'區域':<12} {'預篩':<6}")
    cprint(hdr, Fore.YELLOW, bold=True)
    sep('-', 78, Fore.YELLOW)

    def print_row(r, color):
        if not r.get('success'): return
        ps  = r.get('prescreen') or {}
        psi = f"{ps.get('pass_count',0)}/3"
        print(
            f"  {r['rank']:>3} "
            f"{color}{r['ticker']:<7}{Style.RESET_ALL}"
            f" {r.get('company','')[:22]:<22}"
            f" {color}{r['composite']:>+6d}{Style.RESET_ALL}"
            f" {r['ta_score']*3:>+6d}"
            f" {r['ict_score']:>+6d}"
            f" {color}{r['action_zh']:<10}{Style.RESET_ALL}"
            f" {r['rsi']:>5.0f}"
            f" {r['vol_ratio']:>5.1f}x"
            f" {r['chg1d']:>+7.2f}%"
            f" {r.get('pd_zone',{}).get('zone','?'):<12}"
            f" {psi:<6}"
        )

    groups = [(buy,'▲ 買進目標',Fore.GREEN),(watch,'◆ 觀察候選',Fore.YELLOW),
              (sell,'▼ 賣出/規避',Fore.RED),(skip,'─ 略過',Fore.WHITE)]
    for grp, label, color in groups:
        if not grp: continue
        cprint(f"\n  ── {label} ──", color)
        for r in grp:
            print_row(r, color)


def export_csv(results, holdings_df, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')

    rows = []
    for r in results:
        if not r.get('success'): continue
        ps  = r.get('prescreen') or {}
        bos = r.get('bos', {})
        fvg = r.get('fvg', {})
        ob  = r.get('ob',  {})
        sh  = r.get('sh',  {})
        ote = r.get('ote', {})
        pdz = r.get('pd_zone', {})
        rows.append({
            '排名': r['rank'], '代碼': r['ticker'],
            '公司': r.get('company',''), '現價': r['price'],
            '複合評分': r['composite'], 'TA分×3': r['ta_score']*3,
            'ICT分': r['ict_score'], '建議': r['action_zh'],
            '等級': r['grade'], '停損': r.get('stop_loss',''),
            '預篩通過': ps.get('pass_count',0),
            '流動性': ps.get('liq',False), '趨勢MA60': ps.get('trend',False),
            '資金流向': ps.get('flow',False), '量比': r['vol_ratio'],
            'RSI': r['rsi'], 'K值': r['K'], 'D值': r['D'],
            '%B': r['pct_b'], 'MA5': r['ma5'], 'MA20': r['ma20'],
            '1D漲跌%': r['chg1d'], '1M漲跌%': r['chg1m'], '3M漲跌%': r['chg3m'],
            '52W低': r['low52'], '52W高': r['high52'],
            '結構': bos.get('structure',''), '區域': pdz.get('zone',''),
            'BOS多頭': bos.get('bos_bull',False), 'CHoCH多頭': bos.get('choch_bull',False),
            'CHoCH空頭': bos.get('choch_bear',False),
            'FVG↑': fvg.get('in_bull_fvg',False), 'OB↑+縮量': ob.get('in_bull_ob',False),
            'Stop Hunt↑': sh.get('bull',False),
            'OTE': ote.get('in_ote',False), 'OTE%': ote.get('fib_pct',''),
            'Kill Zone': r.get('kill_zone',''),
            '持股比例%': r['holding_pct'], '機構數': r['inst_count'],
            'ICT信號': ' | '.join(r.get('ict_signals',{}).values()),
        })

    r_path = os.path.join(output_dir, f'13F_v2_分析_{ts}.csv')
    h_path = os.path.join(output_dir, f'13F_持股排行_{ts}.csv')
    pd.DataFrame(rows).to_csv(r_path, index=False, encoding='utf-8-sig')
    if not holdings_df.empty:
        holdings_df.to_csv(h_path, index=False, encoding='utf-8-sig')
    cprint(f"\n  💾 {r_path}", Fore.GREEN)
    if not holdings_df.empty:
        cprint(f"  💾 {h_path}", Fore.GREEN)


# ═══════════════════════════════════════════════════════════════════════════════
# ░░ SECTION 8: 主程式  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    print_banner()
    kz = KillZoneFilter()
    cprint(f"  執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", Fore.WHITE)
    cprint(f"  {kz.status_str()}", Fore.CYAN, bold=True)
    cprint(f"  複合買進門檻: ≥{CONFIG['BUY_COMPOSITE']}  觀察: ≥{CONFIG['WATCH_COMPOSITE']}  "
           f"賣出: CHoCH/BOS空頭", Fore.WHITE)

    # ── STEP 1: 抓取 13F ─────────────────────────────────────────────────────
    scraper = SEC13FScraper(delay=CONFIG['REQUEST_DELAY'])
    holdings_df = scraper.fetch_all(MAJOR_INSTITUTIONS, CONFIG['MAX_INSTITUTIONS'])

    if holdings_df.empty:
        cprint("\n  ⚠ 13F抓取失敗，使用備用名單", Fore.YELLOW)
        fallback = ['AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA','AVGO','LLY',
                    'UNH','XOM','JPM','V','MA','JNJ','PG','COST','HD','MRK','ABBV',
                    'CVX','CRM','NFLX','AMD','ORCL','BAC','WMT','TMO','SPGI','NOW']
        holdings_df = pd.DataFrame({
            'rank': range(1, len(fallback)+1), 'company_name': fallback,
            'total_value': [0]*len(fallback), 'holding_pct': [0]*len(fallback),
            'inst_count': [0]*len(fallback), 'institutions': ['']*len(fallback),
            'ticker': fallback,
        })
        top30 = holdings_df.head(CONFIG['TOP_N_STOCKS'])
    else:
        sep()
        cprint("  🔍 解析股票代碼...", Fore.CYAN, bold=True)
        holdings_df['ticker'] = [resolve_ticker(n) for n in holdings_df['company_name']]
        top30 = (holdings_df[holdings_df['ticker'].notna()]
                 .head(CONFIG['TOP_N_STOCKS']).reset_index(drop=True))
        cprint(f"  ✅ 解析 {len(top30)} 支股票代碼", Fore.GREEN)

    # ── STEP 2~5: 預篩 + 複合分析 ────────────────────────────────────────────
    sep()
    cprint(f"  📈 開始複合分析 ({len(top30)} 支 · 三道預篩 + TA + ICT/SMC)",
           Fore.CYAN, bold=True)
    cprint(f"  預篩門檻: 通過 ≥{CONFIG['R1_PRESCREEN_PASS']}/3 項進行完整分析", Fore.WHITE)
    sep()

    analyzer = CompositeAnalyzer()
    results  = []

    def analyze_one(row):
        tk = row.get('ticker') or row.get('company_name')
        if not tk: return None
        return analyzer.analyze(
            ticker      = tk,
            company     = str(row.get('company_name', tk))[:35],
            rank        = int(row.get('rank', row.name+1)),
            holding_pct = float(row.get('holding_pct', 0)),
            inst_count  = int(row.get('inst_count', 0)),
        )

    rows_iter = [row for _, row in top30.iterrows()]
    with ThreadPoolExecutor(max_workers=CONFIG['MAX_WORKERS']) as ex:
        futures = {ex.submit(analyze_one, row): row for row in rows_iter}
        for future in tqdm(as_completed(futures), total=len(futures),
                           desc="  分析進度", ncols=76):
            r = future.result()
            if r: results.append(r)

    # 排序: 買進優先, 複合分降序
    order = {'BUY':0,'WATCH':1,'SELL':2,'SKIP':3}
    results.sort(key=lambda x: (order.get(x['action'],9), -x['composite']))

    # ── 詳細報告 ─────────────────────────────────────────────────────────────
    sep()
    cprint("  📋 個股詳細分析報告", Fore.CYAN, bold=True)
    key = [r for r in results if r.get('success') and r['action'] in ('BUY','WATCH','SELL')]
    skip = [r for r in results if r.get('success') and r['action'] == 'SKIP']
    for i, r in enumerate(key, 1):
        print_detail(i, r)
    if skip:
        sep('─', 78, Fore.WHITE)
        cprint(f"  （略過 {len(skip)} 檔，詳見匯總表）", Fore.WHITE)

    # ── 匯總表 ───────────────────────────────────────────────────────────────
    print_summary(results)

    # ── 評分說明 ─────────────────────────────────────────────────────────────
    sep()
    cprint("  📖 評分機制說明", Fore.CYAN, bold=True)
    sep('-', 78, Fore.CYAN)
    guide = [
        ("三道預篩", "流動性(>50萬均量) + 趨勢(>MA60) + 資金流(5日量>20日均量)"),
        ("傳統TA×3", "RSI/MACD/KDJ/BB/MA排列/MA5/Volume → 原始分×3倍"),
        ("⚡ Stop Hunt", f"前高/低被掃後反轉吞噬 → +{CONFIG['ICT_STOP_HUNT']}"),
        ("📊 FVG",      f"公允缺口回踩 → +{CONFIG['ICT_FVG']}"),
        ("🟦 OB+量縮",  f"訂單塊回踩+量縮 → +{CONFIG['ICT_OB']}"),
        ("🎯 OTE",      f"62%~79% Fib最佳進場 → +{CONFIG['ICT_OTE']}"),
        ("🔺 BOS/CHoCH",f"結構突破/多頭反轉 → +{CONFIG['ICT_BOS_BULL']}~+{CONFIG['ICT_CHOCH_BULL']}"),
        ("💚 Discount", f"低於50%擺動中位線 → +{CONFIG['ICT_DISCOUNT']}"),
        ("複合門檻",    f"買進≥{CONFIG['BUY_COMPOSITE']}  觀察≥{CONFIG['WATCH_COMPOSITE']}  賣出=CHoCH空頭"),
    ]
    for k, v in guide:
        cprint(f"  {Fore.YELLOW}{k:<14}{Fore.WHITE}{v}", Fore.WHITE)

    # ── CSV ──────────────────────────────────────────────────────────────────
    if CONFIG['OUTPUT_CSV']:
        export_csv(results, holdings_df, CONFIG['OUTPUT_DIR'])

    sep()
    bc = len([r for r in results if r['action']=='BUY'])
    wc = len([r for r in results if r['action']=='WATCH'])
    sc = len([r for r in results if r['action']=='SELL'])
    sk = len([r for r in results if r['action']=='SKIP'])
    cprint(f"  ✅ 分析完成 | "
           f"{Fore.GREEN}買進:{bc}{Fore.WHITE} "
           f"{Fore.YELLOW}觀察:{wc}{Fore.WHITE} "
           f"{Fore.RED}賣出:{sc}{Fore.WHITE} "
           f"略過:{sk}  "
           f"完成: {datetime.now().strftime('%H:%M:%S')}", Fore.WHITE, bold=True)
    sep()
    return results, holdings_df


if __name__ == '__main__':
    try:
        results, holdings = main()
    except KeyboardInterrupt:
        cprint("\n  ⚠ 用戶中止", Fore.YELLOW)
    except Exception as e:
        import traceback
        cprint(f"\n  ✗ 系統錯誤: {e}", Fore.RED)
        traceback.print_exc()
