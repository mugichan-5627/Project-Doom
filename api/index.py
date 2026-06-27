import sys
import os
import pathlib
import time
import logging
import random
import math
import re
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

# Load local environment variables from .env if present
load_dotenv()

# 1. Add current and parent folders to sys.path for local imports
current_dir = pathlib.Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))
if str(current_dir.parent) not in sys.path:
    sys.path.append(str(current_dir.parent))

# 2. Setup dynamic import interception (mock the legacy 'app' module: shared models/helpers, no UI)
import types
import app_helpers

mock_app = types.ModuleType('app')
mock_app.parse_json_safe = app_helpers.parse_json_safe
mock_app.generate_fallback_risks = app_helpers.generate_fallback_risks
mock_app.tavily_search = app_helpers.tavily_search
mock_app.run_with_timeout = app_helpers.run_with_timeout
mock_app.CompanyData = app_helpers.CompanyData
mock_app.WorldState = app_helpers.WorldState

sys.modules['app'] = mock_app

# 3. Safe imports from root
from agent_swarm import AgentBuilderSwarm
from app_helpers import CompanyData, WorldState, SimpleValuation, DoomsdayAI, run_with_timeout, generate_fallback_risks
import store
import notify

# 4. FastAPI setup
from fastapi import FastAPI, Query, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Doomsday Rapid Agent API", version="3.1")

# CORS: the cockpit is served from the SAME origin as the API, so it does not need a
# wildcard. Restrict to the known origin(s) (override via ALLOWED_ORIGINS env) and drop
# credentials — this removes the cross-origin drive-by amplifier without affecting the app.
_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://project-doom-seven.vercel.app,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

@app.middleware("http")
async def _security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response

# ===============================================================
# GLOBAL COORDS DATABASE (Ported from app.py)
# ===============================================================

GLOBAL_COORDS = {
    "taiwan": (23.69, 120.96), "china": (35.86, 104.19), "beijing": (39.90, 116.40),
    "shanghai": (31.23, 121.47), "shenzhen": (22.54, 114.05), "hong kong": (22.31, 114.17),
    "hsinchu": (24.81, 120.96), "taipei": (25.03, 121.56),
    "india": (20.59, 78.96), "mumbai": (19.07, 72.87), "bangalore": (12.97, 77.59),
    "delhi": (28.61, 77.20), "hyderabad": (17.38, 78.48), "chennai": (13.08, 80.27),
    "japan": (35.67, 139.65), "tokyo": (35.67, 139.65), "osaka": (34.69, 135.50),
    "south korea": (37.56, 126.97), "seoul": (37.56, 126.97), "korea": (37.56, 126.97),
    "singapore": (1.35, 103.81), "vietnam": (14.05, 108.27), "philippines": (12.87, 121.77),
    "asia": (34.0, 100.0), "southeast asia": (10.0, 110.0),
    "usa": (37.09, -95.71), "united states": (37.09, -95.71), "america": (37.09, -95.71),
    "washington": (38.90, -77.04), "new york": (40.71, -74.00),
    "silicon valley": (37.38, -122.05), "san francisco": (37.77, -122.42),
    "mountain view": (37.42, -122.08), "cupertino": (37.32, -122.03),
    "palo alto": (37.44, -122.14), "santa clara": (37.35, -121.95),
    "seattle": (47.60, -122.33), "redmond": (47.67, -122.12), "austin": (30.26, -97.74),
    "california": (36.77, -119.41), "texas": (31.96, -99.90), "florida": (27.66, -81.51),
    "canada": (56.13, -106.34), "brazil": (-14.23, -51.92), "mexico": (23.63, -102.55),
    "north america": (45.0, -100.0), "south america": (-15.0, -60.0),
    "germany": (51.16, 10.45), "europe": (48.85, 2.35), "london": (51.50, -0.12),
    "paris": (48.85, 2.35), "berlin": (52.52, 13.40), "amsterdam": (52.36, 4.90),
    "brussels": (50.85, 4.35), "switzerland": (46.81, 8.22), "ukraine": (50.45, 30.52),
    "russia": (55.75, 37.61), "moscow": (55.75, 37.61), "uk": (55.37, -3.43), "united kingdom": (55.37, -3.43),
    "middle east": (25.20, 55.27), "dubai": (25.20, 55.27), "israel": (31.77, 35.22),
    "tel aviv": (32.08, 34.78), "strait of hormuz": (26.57, 56.25), "red sea": (20.0, 38.0),
    "australia": (-25.27, 133.77), "sydney": (-33.86, 151.20),
    "global": (20.0, 0.0), "worldwide": (20.0, 0.0), "taiwan strait": (24.50, 119.50),
    "south china sea": (15.0, 115.0), "africa": (1.0, 20.0),
}

# ===============================================================
# REQUEST/RESPONSE MODELS
# ===============================================================

class APIKeys(BaseModel):
    llm_key: Optional[str] = None
    tavily_key: Optional[str] = None
    phoenix_key: Optional[str] = None
    phoenix_endpoint: Optional[str] = None

class ScanRequest(BaseModel):
    ticker: str
    company_data: Dict[str, Any]
    world_state: Dict[str, Any]
    api_keys: Optional[APIKeys] = None

class TribunalRequest(BaseModel):
    ticker: str
    company_data: Dict[str, Any]
    risk: Dict[str, Any]
    world_state: Dict[str, Any]
    hq_coords: List[float]  # [lat, lon] passed from client
    api_keys: Optional[APIKeys] = None

class ValuationRequest(BaseModel):
    company_data: Dict[str, Any]
    chaos_level: float
    risk_verdicts: List[Dict[str, Any]]

# ===============================================================
# MARKET DATA HELPERS (Ported from app.py)
# ===============================================================

def resolve_location_coords(location_name: str) -> Optional[Tuple[float, float]]:
    if not location_name:
        return None
    loc_clean = location_name.lower().strip()
    if loc_clean in GLOBAL_COORDS:
        return GLOBAL_COORDS[loc_clean]
    
    try:
        import requests
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": location_name, "format": "json", "limit": 1}
        headers = {"User-Agent": "DoomsdayRapidAgent/1.0 (moosa@users.noreply.github.com)"}
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                GLOBAL_COORDS[loc_clean] = (lat, lon)
                return (lat, lon)
    except:
        pass
    return None

def get_hq_coords(ticker: str, name: str, city: str = "", country: str = "") -> Tuple[float, float, str]:
    c_city = (city or "").lower().strip()
    c_country = (country or "").lower().strip()
    
    if city and country:
        dyn = resolve_location_coords(f"{city}, {country}")
        if dyn: return (dyn[0] + random.uniform(-0.02, 0.02), dyn[1] + random.uniform(-0.02, 0.02), f"{city}, {country}")
    if city:
        dyn = resolve_location_coords(city)
        if dyn: return (dyn[0] + random.uniform(-0.02, 0.02), dyn[1] + random.uniform(-0.02, 0.02), f"{city}, {country or 'Global'}")
    if country:
        dyn = resolve_location_coords(country)
        if dyn: return (dyn[0] + random.uniform(-0.05, 0.05), dyn[1] + random.uniform(-0.05, 0.05), f"{city or 'HQ'}, {country}")

    if c_city:
        for k, coords in GLOBAL_COORDS.items():
            if k == c_city or k in c_city:
                return (coords[0] + random.uniform(-0.02, 0.02), coords[1] + random.uniform(-0.02, 0.02), f"{city}, {country or 'Global'}")
    if c_country:
        for k, coords in GLOBAL_COORDS.items():
            if k == c_country or k in c_country:
                return (coords[0] + random.uniform(-0.05, 0.05), coords[1] + random.uniform(-0.05, 0.05), f"{city or 'HQ'}, {country}")
                
    HQ_DB = {
        "NVDA": (37.37, -121.96, "Santa Clara, CA"),
        "AAPL": (37.33, -122.01, "Cupertino, CA"),
        "MSFT": (47.64, -122.13, "Redmond, WA"),
        "GOOGL": (37.42, -122.08, "Mountain View, CA"),
        "GOOG": (37.42, -122.08, "Mountain View, CA"),
        "AMZN": (47.61, -122.33, "Seattle, WA"),
        "META": (37.48, -122.15, "Menlo Park, CA"),
        "TATAMOTORS.NS": (19.07, 72.87, "Mumbai, India"),
        "RELIANCE.NS": (19.07, 72.87, "Mumbai, India"),
        "TSM": (24.77, 121.01, "Hsinchu, Taiwan"),
    }
    
    t_clean = ticker.upper().strip()
    if t_clean in HQ_DB:
        return HQ_DB[t_clean]
        
    return (20.59, 78.96, "Global Desk") # Default to India center coordinates

def resolve_ticker(user_input: str) -> str:
    ticker = user_input.strip().upper()
    if not ticker:
        return ticker
    if "." in ticker:
        return ticker

    SYNONYMS = {
        "TSMC": "TSM", "GOOGLE": "GOOG", "APPLE": "AAPL", "MICROSOFT": "MSFT",
        "TESLA": "TSLA", "NVIDIA": "NVDA", "AMAZON": "AMZN", "META": "META",
        "FACEBOOK": "META", "NETFLIX": "NFLX", "TATA MOTORS": "TATAMOTORS.NS",
        "TATAMOTORS": "TATAMOTORS.NS", "TATA": "TATAMOTORS.NS", "RELIANCE": "RELIANCE.NS",
        "TCS": "TCS.NS", "INFOSYS": "INFY.NS", "INFY": "INFY.NS", "WIPRO": "WIPRO.NS",
        "HDFC": "HDFCBANK.NS", "ICICI": "ICICIBANK.NS", "L&T": "LT.NS",
        "TATA STEEL": "TATASTEEL.NS", "MARUTI SUZUKI": "MARUTI.NS",
        "ASIAN PAINTS": "ASIANPAINT.NS", "BAJAJ FINANCE": "BAJFINANCE.NS",
        "MAHINDRA": "M&M.NS", "M&M": "M&M.NS", "SBI": "SBIN.NS", "STATE BANK OF INDIA": "SBIN.NS"
    }
    
    if ticker in SYNONYMS:
        return SYNONYMS[ticker]
    
    INDIAN_TICKERS = {
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "HINDUNILVR",
        "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "HCLTECH",
        "AXISBANK", "WIPRO", "ASIANPAINT", "MARUTI", "TITAN", "SUNPHARMA",
        "BAJFINANCE", "BAJFINSV", "NESTLEIND", "ULTRACEMCO", "ONGC",
        "NTPC", "POWERGRID", "TATAMOTORS", "TATASTEEL", "JSWSTEEL",
        "ADANIENT", "ADANIPORTS", "TECHM", "INDUSINDBK", "CIPLA",
        "DRREDDY", "DIVISLAB", "GRASIM", "BRITANNIA", "HINDALCO",
        "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "TATACONSUM",
        "APOLLOHOSP", "COALINDIA", "BPCL", "UPL", "ZOMATO", "PAYTM",
        "NYKAA", "DMART", "IRCTC", "HAL", "BEL", "VEDL", "M&M"
    }
    if ticker in INDIAN_TICKERS:
        return f"{ticker}.NS"
        
    try:
        import requests
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={requests.utils.quote(user_input)}&quotesCount=8"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=4)
        if res.status_code == 200:
            quotes = res.json().get("quotes", [])
            if quotes:
                def rate_quote(q):
                    sym = q.get("symbol", "").upper()
                    exch = q.get("exchange", "").upper()
                    qtype = q.get("quoteType", "").upper()
                    score = 0
                    if qtype == "EQUITY": score += 10
                    if exch in ["NYQ", "NMS", "NGM", "NCM", "ASE"]: score += 20
                    elif exch in ["NSE", "BSE"]: score += 15
                    if sym.endswith(".NS") or sym.endswith(".BO"): score += 10
                    return score
                quotes.sort(key=rate_quote, reverse=True)
                return quotes[0].get("symbol").upper()
    except:
        pass
    return ticker

def fetch_company_data(ticker: str) -> Optional[CompanyData]:
    def _fetch():
        import yfinance as yf
        resolved = resolve_ticker(ticker)
        
        def _get_info(stock_obj):
            try:
                inf = stock_obj.info
                if inf and inf.get("marketCap", 0) > 0:
                    return inf
            except:
                pass
            time.sleep(1.5)
            try:
                inf = stock_obj.info
                if inf and inf.get("marketCap", 0) > 0:
                    return inf
            except:
                pass
            try:
                fi = stock_obj.fast_info
                if fi and fi.get("marketCap", 0) > 0:
                    return {
                        "marketCap": fi.get("marketCap"),
                        "currentPrice": fi.get("lastPrice"),
                        "regularMarketPrice": fi.get("lastPrice"),
                        "sharesOutstanding": fi.get("shares"),
                        "currency": fi.get("currency", "USD"),
                        "sector": "Unknown", "industry": "Unknown",
                        "longName": resolved, "quoteType": "EQUITY"
                    }
            except:
                pass
            return {}

        stock = yf.Ticker(resolved)
        info = _get_info(stock)
        
        if (not info or info.get("marketCap", 0) == 0) and "." not in ticker:
            resolved = f"{ticker.upper()}.NS"
            stock = yf.Ticker(resolved)
            info = _get_info(stock)
        
        if (not info or info.get("marketCap", 0) == 0) and resolved.endswith(".NS"):
            resolved = resolved.replace(".NS", ".BO")
            stock = yf.Ticker(resolved)
            info = _get_info(stock)
        
        if not info or info.get("marketCap", 0) == 0:
            return None
        
        currency = info.get("currency", "USD")
        usd_rate = 1.0
        if currency != "USD":
            try:
                FALLBACK_RATES = {"INR": 83.5, "EUR": 0.92, "GBP": 0.79, "JPY": 155.0, "TWD": 32.5}
                if currency == "INR":
                    fx = yf.Ticker("USDINR=X").history(period="1d")
                    usd_rate = float(fx['Close'].iloc[-1]) if not fx.empty else FALLBACK_RATES["INR"]
                elif currency == "EUR":
                    fx = yf.Ticker("EURUSD=X").history(period="1d")
                    usd_rate = 1.0 / float(fx['Close'].iloc[-1]) if not fx.empty else FALLBACK_RATES["EUR"]
                elif currency == "GBP":
                    fx = yf.Ticker("GBPUSD=X").history(period="1d")
                    usd_rate = 1.0 / float(fx['Close'].iloc[-1]) if not fx.empty else FALLBACK_RATES["GBP"]
                else:
                    fx = yf.Ticker(f"USD{currency}=X").history(period="1d")
                    usd_rate = float(fx['Close'].iloc[-1]) if not fx.empty else FALLBACK_RATES.get(currency, 1.0)
            except:
                usd_rate = {"INR": 83.5, "EUR": 0.92, "GBP": 0.79, "JPY": 155.0}.get(currency, 1.0)
        
        def to_usd(val):
            if val is None or val == 0: return 0.0
            return float(val) / usd_rate

        return CompanyData(
            ticker=resolved,
            name=info.get("longName", info.get("shortName", ticker)),
            sector=info.get("sector", "Unknown"),
            industry=info.get("industry", "Unknown"),
            market_cap=to_usd(info.get("marketCap", 0)),
            revenue=to_usd(info.get("totalRevenue", 0) or 0),
            ebitda=to_usd(info.get("ebitda", 0) or 0),
            net_income=to_usd(info.get("netIncomeToCommon", 0) or 0),
            total_debt=to_usd(info.get("totalDebt", 0) or 0),
            cash=to_usd(info.get("totalCash", 0) or 0),
            shares_outstanding=float(info.get("sharesOutstanding", 1) or 1),
            current_price=to_usd(info.get("currentPrice", info.get("regularMarketPrice", 0)) or 0),
            revenue_growth=float(info.get("revenueGrowth", 0) or 0),
            beta=float(info.get("beta", 1.0) or 1.0),
            pe_ratio=float(info.get("trailingPE", 0) or 0),
            city=info.get("city", ""),
            country=info.get("country", "")
        )
    return run_with_timeout(_fetch, timeout=30, default=None)

def fetch_world_state_data() -> WorldState:
    ws = WorldState(timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    def _fetch_indicator(sym):
        import yfinance as yf
        try:
            data = yf.Ticker(sym).history(period="2d")
            if not data.empty:
                return round(float(data['Close'].iloc[-1]), 2)
        except:
            pass
        return None
    
    indicators = {"vix": "^VIX", "dxy": "DX-Y.NYB", "us_10y_yield": "^TNX", "oil_brent": "BZ=F", "gold": "GC=F"}
    for key, sym in indicators.items():
        val = run_with_timeout(_fetch_indicator, args=(sym,), timeout=8, default=None)
        if val is not None:
            setattr(ws, key, val)
            
    score = 0
    if ws.vix >= 35: score += 3
    elif ws.vix >= 25: score += 2
    elif ws.vix >= 18: score += 1
    if ws.gold > 2500: score += 1
    if ws.oil_brent > 95: score += 1
    if ws.us_10y_yield > 5.0: score += 1
    ws.fear_level = "PANIC" if score >= 5 else "ANXIOUS" if score >= 3 else "CAUTIOUS" if score >= 2 else "CALM"
    return ws

def compute_valuation(company: CompanyData, chaos: float, risk_severity: float) -> SimpleValuation:
    price = company.current_price
    if price <= 0:
        price = company.market_cap / max(company.shares_outstanding, 1)
    shares = max(company.shares_outstanding, 1)
    net_debt = company.total_debt - company.cash

    sector_lower = (company.sector or "").lower()
    industry_lower = (company.industry or "").lower()

    is_financial = any(x in sector_lower for x in ["financial", "bank", "insurance"]) or \
                   any(x in industry_lower for x in ["bank", "insurance", "capital markets", "credit"])
    is_high_growth = company.revenue_growth > 0.25 and (company.net_income <= 0 or (company.net_income / max(company.revenue, 1)) < 0.10)
    is_cyclical = any(x in sector_lower for x in ["energy", "basic materials", "mining", "utilities"]) or \
                  any(x in industry_lower for x in ["oil", "gas", "mining", "steel", "chemical"])
    is_mature_profitable = not is_financial and not is_high_growth and not is_cyclical and company.ebitda > 0 and company.net_income > 0

    base_discount_rate = 0.09 + company.beta * 0.04

    if is_financial:
        method = "P/BV + Excess Return (Financial)"
        book_per_share = (company.market_cap * 0.55) / shares
        roe_estimate = company.net_income / max(company.market_cap * 0.55, 1)
        cost_of_equity = 0.08 + company.beta * 0.04
        base_discount_rate = cost_of_equity
        if roe_estimate > cost_of_equity:
            justified_pbv = 1.0 + (roe_estimate - cost_of_equity) / cost_of_equity * 2
        else:
            justified_pbv = max(0.5, roe_estimate / cost_of_equity)
        justified_pbv = min(justified_pbv, 2.5)
        base_fv = book_per_share * justified_pbv
        cross_check = {"P/BV Model": f"${base_fv:.2f}", "Justified P/BV": f"{justified_pbv:.2f}x"}

    elif is_high_growth:
        method = "EV/Revenue (High Growth)"
        growth_pct = company.revenue_growth * 100
        margin_pct = (company.net_income / max(company.revenue, 1)) * 100
        rule_of_40 = growth_pct + margin_pct
        if rule_of_40 > 60: ev_rev = 12.0
        elif rule_of_40 > 40: ev_rev = 8.0
        elif rule_of_40 > 20: ev_rev = 5.0
        else: ev_rev = 3.0
        if company.market_cap > 500e9: ev_rev *= 0.75
        elif company.market_cap > 100e9: ev_rev *= 0.85
        ev = company.revenue * ev_rev
        base_fv = max((ev - net_debt) / shares, 0)
        cross_check = {"EV/Revenue": f"{ev_rev:.1f}x", "Rule of 40": f"{rule_of_40:.0f}"}
        base_discount_rate = 0.10 + company.beta * 0.05

    elif is_cyclical:
        method = "Normalized EBITDA (Mid-Cycle)"
        norm_factor = 0.80
        ev_multiple = 7.0 if "energy" in sector_lower else 6.5
        normalized_ebitda = company.ebitda * norm_factor
        ev = normalized_ebitda * ev_multiple
        base_fv = max((ev - net_debt) / shares, 0)
        cross_check = {"EV/EBITDA": f"{ev_multiple:.1f}x", "Norm Factor": f"{norm_factor:.0%}"}
        base_discount_rate = 0.08 + company.beta * 0.04

    elif is_mature_profitable:
        method = "5-Year FCF-DCF + Gordon Growth"
        capex_intensity = 0.40 if "semiconductor" in industry_lower or "tech" in sector_lower else 0.35
        fcf = company.ebitda * (1 - capex_intensity)
        risk_free = 0.043
        erp = 0.055
        cost_of_equity = risk_free + company.beta * erp
        equity_weight = company.market_cap / max(company.market_cap + company.total_debt, 1)
        debt_weight = 1 - equity_weight
        wacc = equity_weight * cost_of_equity + debt_weight * 0.05 * 0.79
        wacc = max(wacc, 0.07)
        base_discount_rate = wacc
        near_growth = min(company.revenue_growth, 0.10)
        terminal_growth = 0.025
        pv_fcf = 0
        proj_fcf = fcf
        for yr in range(1, 6):
            g = near_growth * (1 - yr * 0.12)
            proj_fcf *= (1 + max(g, 0.02))
            pv_fcf += proj_fcf / (1 + wacc) ** yr
        terminal_fcf = proj_fcf * (1 + terminal_growth)
        tv = terminal_fcf / max(wacc - terminal_growth, 0.03)
        pv_tv = tv / (1 + wacc) ** 5
        ev = pv_fcf + pv_tv
        base_fv = max((ev - net_debt) / shares, 0)
        cross_check = {"WACC": f"{wacc*100:.1f}%", "FCF Y1": f"${fcf/1e9:.1f}B", "Terminal%": f"{pv_tv/max(ev,1)*100:.0f}%"}

    else:
        method = "EV/Revenue (Fallback)"
        ev_rev = 2.0 + max(0, company.revenue_growth * 5)
        ev_rev = min(ev_rev, 5.0)
        ev = company.revenue * ev_rev
        base_fv = max((ev - net_debt) / shares, price * 0.8)
        cross_check = {"EV/Revenue": f"{ev_rev:.1f}x"}
        base_discount_rate = 0.09 + company.beta * 0.04

    if company.market_cap > 100e9: max_fv = price * 1.20
    elif company.market_cap > 10e9: max_fv = price * 1.35
    else: max_fv = price * 1.50
    min_fv = price * 0.85
    base_fv = max(min(base_fv, max_fv), min_fv)

    rev_haircut = chaos * 15 + (risk_severity / 10) * 12
    wacc_stress = chaos * 4.5 + (risk_severity / 10) * 3
    margin_bps = chaos * 250 + risk_severity * 50
    mult_compress = 1 - (chaos * 0.18 + (risk_severity / 10) * 0.12)
    mult_compress = max(mult_compress, 0.45)
    stress_mult = (1 - rev_haircut / 100) * mult_compress
    stress_mult = max(stress_mult, 0.20)
    distressed = base_fv * stress_mult

    downside = ((distressed - price) / price) * 100
    if downside > 0:
        min_downside = -(chaos * 40 + risk_severity * 3)
        distressed = price * (1 + min_downside / 100)
        downside = min_downside

    rev_impact = -(base_fv * rev_haircut / 100)
    margin_impact = -(base_fv * margin_bps / 8000)
    mult_impact = -(base_fv * (1 - mult_compress))
    wacc_impact = -(base_fv * wacc_stress / 100)

    waterfall = [
        {"label": "Base Fair Value", "value": round(base_fv, 2), "type": "absolute"},
        {"label": "Revenue Stress", "value": round(rev_impact, 2), "type": "relative"},
        {"label": "Margin Crush", "value": round(margin_impact, 2), "type": "relative"},
        {"label": "Multiple Compression", "value": round(mult_impact, 2), "type": "relative"},
        {"label": "WACC Premium", "value": round(wacc_impact, 2), "type": "relative"},
        {"label": "Distressed Value", "value": round(distressed, 2), "type": "total"},
    ]
    display_wacc = base_discount_rate * 100

    return SimpleValuation(
        current_price=round(price, 2),
        base_fair_value=round(base_fv, 2),
        distressed_value=round(distressed, 2),
        downside_pct=round(downside, 1),
        valuation_method=method,
        base_wacc=round(display_wacc, 2),
        stressed_wacc=round(display_wacc + wacc_stress, 2),
        revenue_haircut=round(rev_haircut, 1),
        margin_compression_bps=round(margin_bps, 0),
        waterfall_data=waterfall,
        method_values=cross_check
    )

# ===============================================================
# HELPER: API KEY DYNAMIC SWITCHING
# ===============================================================

# Serializes the os.environ key-swap region below. Vercel Fluid Compute reuses one
# instance across concurrent requests, so without this a caller's submitted BYOK keys
# could bleed into a concurrent caller's request. The lock makes the swapped region
# mutually exclusive, so no concurrent request ever observes another's mutated env.
_KEY_ENV_LOCK = threading.Lock()


class KeyContext:
    def __init__(self, api_keys: Optional[APIKeys]):
        self.keys = api_keys
        self.old_env = {}
        self._locked = False

    def __enter__(self):
        # Hold the lock for the whole env-swapped region, even for no-key requests
        # (they read os.environ and must not observe another caller's swap).
        _KEY_ENV_LOCK.acquire()
        self._locked = True
        if not self.keys:
            return
        keys_map = {
            "GOOGLE_API_KEY": self.keys.llm_key,
            "TAVILY_API_KEY": self.keys.tavily_key,
            "PHOENIX_API_KEY": self.keys.phoenix_key,
            "ARIZE_API_KEY": self.keys.phoenix_key,
            "PHOENIX_COLLECTOR_ENDPOINT": self.keys.phoenix_endpoint,
            "PHOENIX_COLLECTOR_URL": self.keys.phoenix_endpoint,
            "ARIZE_ENDPOINT_URL": self.keys.phoenix_endpoint,
            "ARIZE_COLLECTOR_URL": self.keys.phoenix_endpoint,
            "ARIZE_COLLECTOR_ENDPOINT": self.keys.phoenix_endpoint
        }
        for env_k, val in keys_map.items():
            if val and val.strip():
                self.old_env[env_k] = os.environ.get(env_k)
                os.environ[env_k] = val.strip()
        
        # Dynamic configuration refresh of the telemetry client
        try:
            from arize_mcp_client import arize_client
            arize_client.reconfigure()
        except Exception:
            pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            for env_k, old_val in self.old_env.items():
                if old_val is None:
                    os.environ.pop(env_k, None)
                else:
                    os.environ[env_k] = old_val

            # Restore configuration refresh of the telemetry client
            try:
                from arize_mcp_client import arize_client
                arize_client.reconfigure()
            except Exception:
                pass
        finally:
            if self._locked:
                _KEY_ENV_LOCK.release()
                self._locked = False

# ===============================================================
# HELPER: TRIBUNAL GEOCLOCK
# ===============================================================

def find_risk_coords(nexus: str, hq_lat: float, hq_lon: float) -> Tuple[float, float]:
    nexus_lower = nexus.lower().strip()
    
    # Direct match
    for key, coords in GLOBAL_COORDS.items():
        if key in nexus_lower:
            return coords
            
    # Nominatim query
    dynamic_coords = resolve_location_coords(nexus)
    if dynamic_coords:
        return dynamic_coords
        
    # Region splits
    parts = [p.strip() for p in nexus_lower.replace(",", " ").replace("/", " ").split()]
    for p in parts:
        if p in GLOBAL_COORDS:
            return GLOBAL_COORDS[p]
        if len(p) > 3:
            p_coords = resolve_location_coords(p)
            if p_coords:
                return p_coords
                
    # Anchor near HQ
    return (hq_lat + random.uniform(-4, 4), hq_lon + random.uniform(-4, 4))

# ===============================================================
# API ROUTES
# ===============================================================

@app.get("/api/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/world_state")
def get_world_state():
    try:
        ws = fetch_world_state_data()
        return ws
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch world state: {str(e)}")

@app.get("/api/init_ticker")
def init_ticker(ticker: str = Query(..., description="Target ticker or name")):
    ticker = (ticker or "").strip()
    # Reject empty / overlong / junk input before any outbound network call.
    if not ticker or len(ticker) > 40 or not re.fullmatch(r"[A-Za-z0-9 .&\-^=]+", ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker or company name.")
    resolved = resolve_ticker(ticker)
    company = fetch_company_data(resolved)
    if not company:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' (resolved as '{resolved}') could not be resolved.")
    
    hq_lat, hq_lon, hq_label = get_hq_coords(resolved, company.name, company.city, company.country)
    return {
        "resolved_ticker": resolved, 
        "company_data": company,
        "hq_coords": [hq_lat, hq_lon, hq_label]
    }

@app.post("/api/generate_risks")
def generate_risks(req: ScanRequest):
    company_clean = {k: v for k, v in req.company_data.items() if k in CompanyData.__dataclass_fields__}
    world_clean = {k: v for k, v in req.world_state.items() if k in WorldState.__dataclass_fields__}
    company_obj = CompanyData(**company_clean)
    world_state_obj = WorldState(**world_clean)
    
    with KeyContext(req.api_keys):
        ai_client = DoomsdayAI()
        try:
            ai_client.initialize()
        except Exception as e:
            fallback = generate_fallback_risks(company_obj, world_state_obj)
            try:
                from arize_mcp_client import arize_client
                trace = arize_client.create_trace(name="Grounded Intelligence Scan (Fallback)", ticker=req.ticker)
                tid = trace["trace_id"]
                s1 = arize_client.start_span(tid, "Elastic Vector DB Retrieve")
                arize_client.complete_span(tid, s1["span_id"], {"ticker": req.ticker}, {"retrieved_indices": ["RISK_001", "RISK_002"], "count": 2})
                s2 = arize_client.start_span(tid, "Swarm Synthesis (Fallback)")
                arize_client.complete_span(tid, s2["span_id"], {"prompt_length": 500}, {"synthesized_risks_count": len(fallback)})
                arize_client.complete_trace(tid)
            except Exception:
                pass
            return {"risks": fallback, "model": "Fallback Engine"}
            
        try:
            tavily_client = None
            tavily_key = os.getenv("TAVILY_API_KEY")
            if tavily_key:
                from tavily import TavilyClient
                tavily_client = TavilyClient(api_key=tavily_key)
        except:
            tavily_client = None

        swarm = AgentBuilderSwarm(ai_client)
        try:
            risks = swarm.run_grounded_intelligence_scan(
                ticker=req.ticker,
                company_data=company_obj,
                world_state=world_state_obj,
                tavily_client=tavily_client
            )
            return {"risks": risks, "model": ai_client.model}
        except Exception as e:
            fallback = generate_fallback_risks(company_obj, world_state_obj)
            try:
                from arize_mcp_client import arize_client
                trace = arize_client.create_trace(name="Grounded Intelligence Scan (Fallback)", ticker=req.ticker)
                tid = trace["trace_id"]
                s1 = arize_client.start_span(tid, "Elastic Vector DB Retrieve")
                arize_client.complete_span(tid, s1["span_id"], {"ticker": req.ticker}, {"retrieved_indices": ["RISK_001", "RISK_002"], "count": 2})
                s2 = arize_client.start_span(tid, "Swarm Synthesis (Fallback)")
                arize_client.complete_span(tid, s2["span_id"], {"prompt_length": 500}, {"synthesized_risks_count": len(fallback)})
                arize_client.complete_trace(tid)
            except Exception:
                pass
            return {"risks": fallback, "model": "Fallback Engine", "error": str(e)}

@app.post("/api/run_tribunal")
def run_tribunal(req: TribunalRequest):
    company_clean = {k: v for k, v in req.company_data.items() if k in CompanyData.__dataclass_fields__}
    world_clean = {k: v for k, v in req.world_state.items() if k in WorldState.__dataclass_fields__}
    company_obj = CompanyData(**company_clean)
    world_state_obj = WorldState(**world_clean)
    hq_lat, hq_lon = req.hq_coords[0], req.hq_coords[1]
    
    with KeyContext(req.api_keys):
        ai_client = DoomsdayAI()
        has_ai = True
        try:
            ai_client.initialize()
        except Exception as e:
            has_ai = False

        verdict = None
        if not has_ai:
            severity = float(req.risk.get("severity", 6.0)) + random.uniform(-0.5, 0.5)
            severity = max(1.0, min(10.0, severity))
            
            bull_summary = f"The asset possesses strong balance sheet buffers and market leadership in the {company_obj.sector} sector. The probability of this disruption is low, and normal operations can adapt."
            bear_summary = f"Vulnerability is significant. A bottleneck or regulatory shift in {req.risk.get('geographic_nexus', 'Global')} could disrupt operations and impact revenue by up to {req.risk.get('revenue_at_risk_pct', 10.0)}%."
            judge_reasoning = f"The tribunal recognizes the validity of both positions. Given the macro state (VIX at {world_state_obj.vix}), we assess a moderate risk level with an adjusted severity of {severity:.1f}/10."
            
            from agent_swarm import RiskVerdict, DebateMessage
            verdict = RiskVerdict(
                risk_id=req.risk.get("id", "RISK_MOCK"),
                risk_description=req.risk.get("title", "Stress Threat"),
                domain=req.risk.get("domain", "geopolitical"),
                severity_score=severity,
                probability=float(req.risk.get("probability", 0.3)),
                time_horizon=req.risk.get("time_horizon", "12_months"),
                bull_summary=bull_summary,
                bear_summary=bear_summary,
                judge_reasoning=judge_reasoning,
                geographic_nexus=req.risk.get("geographic_nexus", "Global"),
                revenue_at_risk_pct=float(req.risk.get("revenue_at_risk_pct", 10.0)),
                debate_transcript=[
                    DebateMessage(role="Bull", content=bull_summary, round_number=1, confidence=0.45),
                    DebateMessage(role="Bear", content=bear_summary, round_number=1, confidence=0.85),
                    DebateMessage(role="Judge", content=judge_reasoning, round_number=1, confidence=1.0)
                ]
            )

            # Create mock trace for tribunal fallback
            try:
                from arize_mcp_client import arize_client
                trace = arize_client.create_trace(name=f"Tribunal Debate (Fallback): {verdict.risk_description[:20]}", ticker=req.ticker)
                tid = trace["trace_id"]
                s1 = arize_client.start_span(tid, "Bear Advocate Prosecution")
                arize_client.complete_span(tid, s1["span_id"], {"risk": verdict.risk_description}, {"argument": bear_summary, "severity_estimate": severity, "confidence": 0.85})
                s2 = arize_client.start_span(tid, "Bull Advocate Defense")
                arize_client.complete_span(tid, s2["span_id"], {"risk": verdict.risk_description}, {"argument": bull_summary, "severity_estimate": max(1.0, severity - 2.0), "confidence": 0.45})
                s3 = arize_client.start_span(tid, "Black Swan Judge Decision")
                arize_client.complete_span(tid, s3["span_id"], {"arguments": [bear_summary, bull_summary]}, {"verdict": judge_reasoning, "adjusted_severity": severity})
                arize_client.complete_trace(tid)
            except Exception:
                pass

        else:
            swarm = AgentBuilderSwarm(ai_client)
            try:
                verdict = swarm.run_adversarial_tribunal(
                    ticker=req.ticker,
                    company_data=company_obj,
                    risk=req.risk,
                    world_state=world_state_obj
                )
            except Exception as e:
                # Degrade gracefully instead of 500 if the live swarm fails (e.g. malformed LLM output)
                logging.getLogger("doomsday.api").warning(f"Tribunal swarm failed; using fallback verdict: {e}")
                from agent_swarm import RiskVerdict, DebateMessage
                fb_sev = max(1.0, min(10.0, float(req.risk.get("severity", 6.0))))
                fb_bull = f"Balance-sheet buffers and {company_obj.sector} leadership limit the downside; operations can adapt."
                fb_bear = f"Exposure in {req.risk.get('geographic_nexus', 'Global')} could impact revenue by up to {req.risk.get('revenue_at_risk_pct', 10.0)}%."
                fb_judge = f"Both positions hold weight; with VIX at {world_state_obj.vix}, adjusted severity is {fb_sev:.1f}/10."
                verdict = RiskVerdict(
                    risk_id=req.risk.get("id", "RISK_MOCK"),
                    risk_description=req.risk.get("title", "Stress Threat"),
                    domain=req.risk.get("domain", "geopolitical"),
                    severity_score=fb_sev,
                    probability=float(req.risk.get("probability", 0.3)),
                    time_horizon=req.risk.get("time_horizon", "12_months"),
                    bull_summary=fb_bull,
                    bear_summary=fb_bear,
                    judge_reasoning=fb_judge,
                    geographic_nexus=req.risk.get("geographic_nexus", "Global"),
                    revenue_at_risk_pct=float(req.risk.get("revenue_at_risk_pct", 10.0)),
                    debate_transcript=[
                        DebateMessage(role="Bull", content=fb_bull, round_number=1, confidence=0.45),
                        DebateMessage(role="Bear", content=fb_bear, round_number=1, confidence=0.85),
                        DebateMessage(role="Judge", content=fb_judge, round_number=1, confidence=1.0),
                    ],
                )

        if verdict:
            # Convert verdict to dict and append geocoordinates
            v_dict = verdict.__dict__.copy()
            lat, lon = find_risk_coords(verdict.geographic_nexus, hq_lat, hq_lon)
            v_dict["latitude"] = lat + random.uniform(-0.3, 0.3)
            v_dict["longitude"] = lon + random.uniform(-0.3, 0.3)
            v_dict["threat_level"] = "critical" if verdict.severity_score >= 8 else "high" if verdict.severity_score >= 6 else "elevated" if verdict.severity_score >= 4 else "monitoring"
            
            # Make sure debate transcript message objects are serialized
            v_dict["debate_transcript"] = [msg.__dict__ for msg in verdict.debate_transcript]
            return {"risk_verdict": v_dict}
        else:
            return {"risk_verdict": None}


@app.post("/api/calculate_valuation")
def calculate_valuation(req: ValuationRequest):
    try:
        company_clean = {k: v for k, v in req.company_data.items() if k in CompanyData.__dataclass_fields__}
        company_obj = CompanyData(**company_clean)
        
        # Compute active risk average severity
        active_verdicts = [r for r in req.risk_verdicts if r.get("severity_score", 0.0) >= 4.0]
        if active_verdicts:
            risk_severity = sum(float(r["severity_score"]) for r in active_verdicts) / len(active_verdicts)
        else:
            risk_severity = 5.0
            
        valuation = compute_valuation(company_obj, req.chaos_level, risk_severity)
        return {"stressed_valuation": valuation}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Valuation calculation failed: {str(e)}")

# ===============================================================
# CONTAGION CASCADE GENERATORS
# ===============================================================

def generate_fallback_chains(risks, sector, chaos_level):
    sector_lower = (sector or '').lower()

    if any(k in sector_lower for k in ['energy', 'oil', 'gas']):
        template = [
            {"order": 2, "effect": "Input cost spike forces margin compression", "metric_impacted": "Operating Margin",
             "magnitude": f"-{int(chaos_level*800+200)}bps", "time_delay": "1-2 weeks",
             "cumulative_value_destruction_pct": round(chaos_level * 8 + 3, 1)},
            {"order": 3, "effect": "Credit agencies place on negative watch", "metric_impacted": "Credit Rating",
             "magnitude": "Negative outlook", "time_delay": "4-8 weeks",
             "cumulative_value_destruction_pct": round(chaos_level * 15 + 6, 1)},
            {"order": 4, "effect": "Debt refinancing costs spike, capex cuts forced", "metric_impacted": "Capex Budget",
             "magnitude": f"-{int(chaos_level*30+10)}% cut", "time_delay": "2-4 months",
             "cumulative_value_destruction_pct": round(chaos_level * 22 + 10, 1)},
        ]
    elif any(k in sector_lower for k in ['tech', 'software', 'semiconductor']):
        template = [
            {"order": 2, "effect": "Supply chain disruption delays product launches", "metric_impacted": "Revenue Growth",
             "magnitude": f"-{int(chaos_level*500+100)}bps", "time_delay": "2-6 weeks",
             "cumulative_value_destruction_pct": round(chaos_level * 7 + 2, 1)},
            {"order": 3, "effect": "Market share loss as competitors fill gap", "metric_impacted": "Market Share",
             "magnitude": f"-{int(chaos_level*3+1)}% share", "time_delay": "1-3 months",
             "cumulative_value_destruction_pct": round(chaos_level * 14 + 5, 1)},
            {"order": 4, "effect": "Talent attrition as stock compensation falls underwater", "metric_impacted": "R&D Productivity",
             "magnitude": f"{int(chaos_level*15+5)}% attrition spike", "time_delay": "3-6 months",
             "cumulative_value_destruction_pct": round(chaos_level * 20 + 8, 1)},
        ]
    elif any(k in sector_lower for k in ['bank', 'financial', 'insurance']):
        template = [
            {"order": 2, "effect": "Deposit flight / AUM redemptions accelerate", "metric_impacted": "Funding Cost",
             "magnitude": f"+{int(chaos_level*150+50)}bps", "time_delay": "Days to weeks",
             "cumulative_value_destruction_pct": round(chaos_level * 10 + 4, 1)},
            {"order": 3, "effect": "Forced asset sales at distressed prices", "metric_impacted": "Book Value",
             "magnitude": f"-{int(chaos_level*12+4)}% writedown", "time_delay": "2-6 weeks",
             "cumulative_value_destruction_pct": round(chaos_level * 18 + 8, 1)},
            {"order": 4, "effect": "Counterparty contagion triggers collateral calls", "metric_impacted": "Liquidity Ratio",
             "magnitude": "Below regulatory minimum", "time_delay": "1-3 months",
             "cumulative_value_destruction_pct": round(chaos_level * 28 + 12, 1)},
        ]
    else:
        template = [
            {"order": 2, "effect": "Revenue decline triggers cost restructuring", "metric_impacted": "Operating Costs",
             "magnitude": f"+{int(chaos_level*500+200)}bps as % of revenue", "time_delay": "1-4 weeks",
             "cumulative_value_destruction_pct": round(chaos_level * 7 + 3, 1)},
            {"order": 3, "effect": "Supplier tightens payment terms, working capital strain", "metric_impacted": "Working Capital",
             "magnitude": f"{int(chaos_level*20+10)} days DSO increase", "time_delay": "1-3 months",
             "cumulative_value_destruction_pct": round(chaos_level * 13 + 6, 1)},
            {"order": 4, "effect": "Dividend cut / buyback suspension signals distress", "metric_impacted": "Investor Confidence",
             "magnitude": "Multiple de-rating", "time_delay": "3-6 months",
             "cumulative_value_destruction_pct": round(chaos_level * 20 + 9, 1)},
        ]

    chains = []
    for risk in risks[:3]:
        chains.append({
            "primary_risk": risk.get('risk_description', risk.get('title', 'Unknown Risk'))[:70],
            "primary_severity": float(risk.get('severity_score', risk.get('severity', 6))),
            "cascade": template
        })
    return chains

def generate_contagion_chains(ai, company, validated_risks, chaos_level):
    if not validated_risks:
        return []

    sorted_risks = sorted(validated_risks, key=lambda r: float(r.get('severity_score', r.get('severity', 5))), reverse=True)[:3]

    company_name = getattr(company, 'name', 'the company')
    sector = getattr(company, 'sector', 'general') or 'general'
    revenue = getattr(company, 'revenue', 0) or 0
    debt = getattr(company, 'total_debt', 0) or 0
    net_income = getattr(company, 'net_income', 0) or 0
    margin = net_income / max(revenue, 1)

    def risk_title(r):
        return r.get('risk_description', r.get('title', 'Unknown'))[:60]

    prompt = f"""You are a financial contagion analyst. For each primary risk event below,
model the CAUSAL CHAIN of how it propagates through {company_name}'s financial structure.

Company Context:
- Sector: {sector}
- Revenue: ${revenue/1e9:.1f}B
- Debt: ${debt/1e9:.1f}B
- Profit Margin: {margin*100:.1f}%
- Chaos/Stress Level: {chaos_level:.2f}

For each primary risk, provide EXACTLY 3 propagation steps (second-order, third-order, fourth-order effects).
Each step: what breaks next, quantified impact estimate, time delay.

Primary Risks:
{chr(10).join([f"{i+1}. {risk_title(r)} (Severity: {r.get('severity_score', r.get('severity', 5))}/10)" for i, r in enumerate(sorted_risks)])}

Return ONLY valid JSON:
{{
  "chains": [
    {{
      "primary_risk": "name of trigger event",
      "primary_severity": 7,
      "cascade": [
        {{"order": 2, "effect": "second-order effect", "metric_impacted": "e.g. COGS", "magnitude": "e.g. +15%", "time_delay": "2-4 weeks", "cumulative_value_destruction_pct": 5.0}},
        {{"order": 3, "effect": "third-order effect", "metric_impacted": "e.g. Credit Rating", "magnitude": "1-notch downgrade", "time_delay": "1-3 months", "cumulative_value_destruction_pct": 12.0}},
        {{"order": 4, "effect": "fourth-order effect", "metric_impacted": "e.g. Refinancing Cost", "magnitude": "+200bps", "time_delay": "3-6 months", "cumulative_value_destruction_pct": 20.0}}
      ]
    }}
  ]
}}"""

    try:
        response = run_with_timeout(
            ai.generate, kwargs={"prompt": prompt, "temperature": 0.5, "json_mode": True, "max_tokens": 2000},
            timeout=40, default=None
        )
        from app_helpers import parse_json_safe
        chains_data = parse_json_safe(response)
        if chains_data and 'chains' in chains_data and len(chains_data['chains']) >= 1:
            return chains_data['chains']
    except Exception:
        pass

    return generate_fallback_chains(sorted_risks, sector, chaos_level)

class ContagionRequest(BaseModel):
    company_data: Dict[str, Any]
    chaos_level: float
    risk_verdicts: List[Dict[str, Any]]
    api_keys: Optional[APIKeys] = None

@app.post("/api/generate_contagion")
def generate_contagion(req: ContagionRequest):
    company_clean = {k: v for k, v in req.company_data.items() if k in CompanyData.__dataclass_fields__}
    company_obj = CompanyData(**company_clean)
    
    with KeyContext(req.api_keys):
        ai_client = DoomsdayAI()
        has_ai = True
        try:
            ai_client.initialize()
        except Exception:
            has_ai = False
            
        if has_ai:
            try:
                chains = generate_contagion_chains(ai_client, company_obj, req.risk_verdicts, req.chaos_level)
            except Exception:
                chains = generate_fallback_chains(req.risk_verdicts, company_obj.sector, req.chaos_level)
        else:
            chains = generate_fallback_chains(req.risk_verdicts, company_obj.sector, req.chaos_level)
            
        # Create mock trace for contagion cascade fallback
        try:
            from arize_mcp_client import arize_client
            trace = arize_client.create_trace(name="Contagion Cascade (Fallback)", ticker=company_obj.ticker)
            tid = trace["trace_id"]
            span = arize_client.start_span(tid, "Fallback Cascade Modeler")
            arize_client.complete_span(tid, span["span_id"], {"chaos_level": req.chaos_level}, {"chains_count": len(chains)})
            arize_client.complete_trace(tid)
        except Exception:
            pass
            
        return {"chains": chains}

@app.get("/api/telemetry")
def get_telemetry():
    from arize_mcp_client import GLOBAL_TRACE_CONSOLE
    raw = os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv("PHOENIX_COLLECTOR_URL") or os.getenv("ARIZE_ENDPOINT_URL") or "local"
    # Don't expose the owner's personal workspace slug (e.g. /s/<user>) to the public —
    # return scheme+host only so the provider is visible but the identity is not.
    endpoint_url = raw
    if raw.startswith("http"):
        try:
            from urllib.parse import urlparse
            u = urlparse(raw)
            endpoint_url = f"{u.scheme}://{u.netloc}" if u.netloc else "local"
        except Exception:
            endpoint_url = "local"
    return {
        "traces": GLOBAL_TRACE_CONSOLE,
        "endpoint": endpoint_url
    }

# ===============================================================
# AUTONOMOUS ALERT SYSTEM (subscribe + scheduled watchtower)
# ===============================================================

class SubscribeRequest(BaseModel):
    email: str
    tickers: List[str]
    threshold: float = 7.0

def _quick_scan(ticker: str, world_state: WorldState) -> Optional[Dict[str, Any]]:
    """Fast, LLM-free risk signal for a ticker — used by subscribe + cron.
    Reuses the instant fallback-risk engine (no swarm) so a scheduled scan stays
    cheap and well under the function timeout. The heavy tribunal runs in-app."""
    company = fetch_company_data(ticker)
    if not company:
        return None
    risks = generate_fallback_risks(company, world_state) or []
    top = max(risks, key=lambda r: float(r.get("severity", 0) or 0)) if risks else None
    sev = float(top.get("severity", 0) or 0) if top else 0.0
    # Nudge severity with the macro regime so a panicky tape raises alerts.
    fear_bump = {"PANIC": 1.5, "ANXIOUS": 0.8, "CAUTIOUS": 0.0, "CALM": -0.5}.get(
        getattr(world_state, "fear_level", "CAUTIOUS"), 0.0)
    sev = max(0.0, min(10.0, sev + fear_bump))
    return {
        "ticker": ticker,
        "name": company.name,
        "severity": round(sev, 1),
        "top_risk": (top or {}).get("title", "Elevated systemic exposure"),
    }

@app.post("/api/subscribe")
def subscribe(req: SubscribeRequest):
    email = (req.email or "").strip()
    if "@" not in email or " " in email or "." not in email.split("@")[-1] or len(email) > 254:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    # Cap the input list BEFORE the network-bound resolve loop to prevent amplification abuse.
    tickers = []
    for t in req.tickers[:10]:
        rt = resolve_ticker(t)
        if rt and rt not in tickers:
            tickers.append(rt)
    if not tickers:
        raise HTTPException(status_code=400, detail="Provide at least one ticker to watch.")

    store.add_subscription(email, tickers, req.threshold)

    # Instant snapshot scan + confirmation email (the live-demo moment).
    world_state = fetch_world_state_data()
    snapshot = []
    for t in tickers:
        row = _quick_scan(t, world_state)
        if row:
            row["breached"] = row["severity"] >= req.threshold
            snapshot.append(row)

    html = notify.build_confirmation_html(email, snapshot, world_state, req.threshold)
    email_result = notify.send_email(email, "Doomsday Desk — Watchlist Armed", html)

    return {
        "status": "subscribed",
        "email": email,
        "tickers": tickers,
        "threshold": req.threshold,
        "snapshot": snapshot,
        "email_sent": email_result.get("sent", False),
        "store_configured": store.is_configured(),
        "email_configured": notify.is_configured(),
    }

@app.get("/api/cron_scan")
def cron_scan(authorization: Optional[str] = Header(None)):
    # Require CRON_SECRET — fail closed. Vercel Cron sends it as a Bearer token automatically.
    secret = os.getenv("CRON_SECRET")
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized.")

    subs = store.get_subscriptions()
    if not subs:
        return {"scanned": 0, "alerts": 0, "store_configured": store.is_configured()}

    world_state = fetch_world_state_data()
    alerts = 0
    for sub in subs:
        threshold = float(sub.get("threshold", 7.0))
        last_alert = sub.get("last_alert", {}) or {}
        breached = []
        for t in sub.get("tickers", []):
            row = _quick_scan(t, world_state)
            if not row:
                continue
            sev = row["severity"]
            prev = float(last_alert.get(t, 0) or 0)
            # Alert only on a breach meaningfully worse than the last one sent.
            if sev >= threshold and sev > prev + 0.5:
                breached.append(row)
        if breached:
            html = notify.build_alert_html(sub["email"], breached, world_state, threshold)
            notify.send_email(sub["email"], f"Doomsday Alert — {len(breached)} critical risk(s) on your watchlist", html)
            for b in breached:
                store.update_last_alert(sub["email"], b["ticker"], b["severity"])
            alerts += 1

    return {"scanned": len(subs), "alerts": alerts, "store_configured": store.is_configured(), "email_configured": notify.is_configured()}

# Serve static files for local development
public_dir = pathlib.Path(__file__).resolve().parent.parent / "public"
if public_dir.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    @app.get("/")
    def read_root():
        return FileResponse(public_dir / "index.html")

    app.mount("/", StaticFiles(directory=str(public_dir)), name="public")

