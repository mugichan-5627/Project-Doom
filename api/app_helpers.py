import os
import json
import time
import sys
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

logger = logging.getLogger("doomsday.app_helpers")

# ===============================================================
# DATA MODELS (Must mirror app.py exactly)
# ===============================================================

@dataclass
class WorldState:
    timestamp: str = ""
    vix: float = 20.0
    vix_trend: str = "stable"
    dxy: float = 104.0
    us_10y_yield: float = 4.5
    oil_brent: float = 80.0
    gold: float = 2400.0
    fear_level: str = "CAUTIOUS"
    active_crises: List[Dict] = field(default_factory=list)

@dataclass 
class CompanyData:
    ticker: str = ""
    name: str = ""
    sector: str = "Unknown"
    industry: str = "Unknown"
    market_cap: float = 0.0
    revenue: float = 0.0
    ebitda: float = 0.0
    net_income: float = 0.0
    total_debt: float = 0.0
    cash: float = 0.0
    shares_outstanding: float = 1.0
    current_price: float = 0.0
    revenue_growth: float = 0.0
    beta: float = 1.0
    pe_ratio: float = 0.0
    company_type: str = "mature"
    city: str = ""
    country: str = ""

@dataclass
class SimpleValuation:
    current_price: float = 0.0
    base_fair_value: float = 0.0
    distressed_value: float = 0.0
    downside_pct: float = 0.0
    valuation_method: str = "Multi-Factor DCF"
    base_wacc: float = 10.0
    stressed_wacc: float = 15.0
    revenue_haircut: float = 0.0
    margin_compression_bps: float = 0.0
    waterfall_data: List[Dict] = field(default_factory=list)
    method_values: Dict = field(default_factory=dict)

# ===============================================================
# TIMEOUT UTILITY
# ===============================================================

def run_with_timeout(func, args=(), kwargs=None, timeout=30, default=None):
    """Run a function with a timeout. Returns default if it times out."""
    if kwargs is None:
        kwargs = {}
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args, **kwargs)
    try:
        res = future.result(timeout=timeout)
        executor.shutdown(wait=False)
        return res
    except (FuturesTimeoutError, Exception) as e:
        executor.shutdown(wait=False)
        return default

# ===============================================================
# JSON UTILITIES
# ===============================================================

def parse_json_safe(text: str) -> Optional[Dict]:
    """Safely parse JSON from LLM output, handling markdown blocks."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except:
                pass
    return None

# ===============================================================
# SEARCH WRAPPER
# ===============================================================

def tavily_search(client, query: str, max_results: int = 3) -> str:
    """Safe Tavily search with timeout."""
    if not client:
        return ""
    def _search():
        try:
            r = client.search(query=query, max_results=max_results)
            results = []
            for res in r.get("results", []):
                results.append(f"Title: {res.get('title')}\nURL: {res.get('url')}\nContent: {res.get('content')}")
            return "\n\n".join(results)
        except Exception as e:
            return f"Search error: {str(e)}"
    return run_with_timeout(_search, timeout=10, default="")

# ===============================================================
# FALLBACK RISKS GENERATOR
# ===============================================================

def generate_fallback_risks(company: CompanyData, ws: WorldState):
    """Generate intelligent fallback risks when AI/search fails."""
    sector = (company.sector or "").lower()
    industry = (company.industry or "").lower()
    name = company.name
    risks = []
    risks.append({
        "id": "RISK_001", "domain": "market",
        "title": f"Global macro deterioration impacting {company.sector}",
        "description": f"With VIX at {ws.vix} and oil at ${ws.oil_brent}, macroeconomic headwinds could compress {name}'s multiples by 15-25%. Rising rates increase discount rates and could trigger multiple compression across the {company.sector} sector.",
        "severity": 5 + (1 if ws.vix > 20 else 0) + (1 if ws.vix > 30 else 0),
        "probability": 0.4, "geographic_nexus": "New York",
        "revenue_at_risk_pct": 8.0, "time_horizon": "6_months"
    })
    if "tech" in sector or "semiconductor" in industry:
        risks.extend([
            {"id": "RISK_002", "domain": "geopolitical",
             "title": "US-China tech export controls escalation",
             "description": f"Escalating US-China tensions could lead to expanded export controls, restricting {name}'s access to Chinese customers. China represents significant semiconductor demand, and further restrictions could reduce revenue by 10-20%.",
             "severity": 7, "probability": 0.45, "geographic_nexus": "Beijing",
             "revenue_at_risk_pct": 15.0, "time_horizon": "6_months"},
            {"id": "RISK_003", "domain": "supply_chain",
             "title": "Taiwan Strait geopolitical risk to manufacturing",
             "description": f"Military escalation in the Taiwan Strait could disrupt semiconductor manufacturing. Even a limited blockade would halt chip production and shipments globally, catastrophically impacting {name}'s operations.",
             "severity": 9, "probability": 0.15, "geographic_nexus": "Taiwan",
             "revenue_at_risk_pct": 40.0, "time_horizon": "12_months"},
            {"id": "RISK_004", "domain": "technology",
             "title": "Competitive disruption from new entrants",
             "description": f"Rapid advances by competitors in AI chips, custom silicon (Google TPU, Amazon Graviton), and emerging architectures could erode {name}'s market share. Technology cycles are accelerating.",
             "severity": 6, "probability": 0.35, "geographic_nexus": "Silicon Valley",
             "revenue_at_risk_pct": 12.0, "time_horizon": "12_months"},
            {"id": "RISK_005", "domain": "regulatory",
             "title": "Antitrust and regulatory scrutiny intensification",
             "description": f"Global regulators are increasingly scrutinizing dominant tech companies. {name} faces potential antitrust investigations in the US, EU, and China that could result in fines or forced licensing.",
             "severity": 5, "probability": 0.3, "geographic_nexus": "Brussels",
             "revenue_at_risk_pct": 8.0, "time_horizon": "12_months"},
        ])
    elif "financial" in sector or "bank" in industry:
        risks.extend([
            {"id": "RISK_002", "domain": "financial",
             "title": "Credit quality deterioration in loan portfolio",
             "description": f"Rising interest rates and economic slowdown could increase non-performing assets. {name}'s loan book may face 50-100bps increase in NPAs, requiring significant provisioning.",
             "severity": 7, "probability": 0.4, "geographic_nexus": "Mumbai" if ".NS" in (company.ticker or "") else "New York",
             "revenue_at_risk_pct": 15.0, "time_horizon": "6_months"},
            {"id": "RISK_003", "domain": "regulatory",
             "title": "Basel IV tighter capital requirements",
             "description": f"New regulatory capital requirements could force {name} to hold additional buffers, reducing return on equity by 100-200bps and limiting dividend capacity.",
             "severity": 5, "probability": 0.5, "geographic_nexus": "Washington DC",
             "revenue_at_risk_pct": 8.0, "time_horizon": "12_months"},
            {"id": "RISK_004", "domain": "market",
             "title": "Net interest margin compression from rate cuts",
             "description": f"If rate cuts begin, {name}'s net interest margin could compress 20-40bps, directly impacting the core earnings driver.",
             "severity": 6, "probability": 0.45, "geographic_nexus": "Washington DC",
             "revenue_at_risk_pct": 10.0, "time_horizon": "6_months"},
        ])
    else:
        # Default fallbacks
        risks.extend([
            {"id": "RISK_002", "domain": "supply_chain",
             "title": "Logistics cost inflation and bottlenecks",
             "description": f"Disruptions in global logistics corridors could delay shipments and increase transport costs for {name}, impacting margins.",
             "severity": 6, "probability": 0.35, "geographic_nexus": "Global",
             "revenue_at_risk_pct": 5.0, "time_horizon": "6_months"},
            {"id": "RISK_003", "domain": "regulatory",
             "title": "Environmental and ESG regulatory compliance cost",
             "description": f"New compliance frameworks require significant reporting and operational adjustments from {name}, raising SG&A costs.",
             "severity": 4, "probability": 0.4, "geographic_nexus": "Brussels",
             "revenue_at_risk_pct": 3.0, "time_horizon": "12_months"},
        ])
    return risks

# ===============================================================
# UNIFIED AI CLIENT
# ===============================================================

class DoomsdayAI:
    """Single unified AI client with automatic failover and timeouts."""
    
    def __init__(self, gemini_key: Optional[str] = None, nvidia_key: Optional[str] = None, fireworks_key: Optional[str] = None):
        self.gemini_key = gemini_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.nvidia_key = nvidia_key or os.getenv("NVIDIA_API_KEY")
        self.fireworks_key = fireworks_key or os.getenv("FIREWORKS_API_KEY")
        # OpenAI-compatible providers — primary failover order is MiniMax -> Kimi.
        self.minimax_key = os.getenv("MINIMAX_API_KEY")
        self.minimax_model = os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
        self.minimax_base = os.getenv("MINIMAX_BASE_URL")
        self.kimi_key = os.getenv("KIMI_API_KEY")
        self.kimi_model = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
        self.kimi_base = os.getenv("KIMI_BASE_URL")
        self.model = None
        self.provider = None
        self._genai = None
        
    def initialize(self) -> str:
        """Find working model. Returns model name or raises."""
        errors = []

        # Try MiniMax (primary)
        if self.minimax_key and self.minimax_base:
            try:
                result = run_with_timeout(
                    self._test_openai,
                    args=(self.minimax_model, self.minimax_key, self.minimax_base),
                    timeout=15, default=None
                )
                if result:
                    self.model = self.minimax_model
                    self.provider = "minimax"
                    return f"MiniMax [{self.minimax_model}]"
                else:
                    errors.append("MiniMax: timeout or invalid key")
            except Exception as e:
                errors.append(f"MiniMax: {str(e)[:80]}")
        else:
            errors.append("MiniMax: no key/base (MINIMAX_API_KEY/MINIMAX_BASE_URL not set)")

        # Try Kimi (secondary)
        if self.kimi_key and self.kimi_base:
            try:
                result = run_with_timeout(
                    self._test_openai,
                    args=(self.kimi_model, self.kimi_key, self.kimi_base),
                    timeout=15, default=None
                )
                if result:
                    self.model = self.kimi_model
                    self.provider = "kimi"
                    return f"Kimi [{self.kimi_model}]"
                else:
                    errors.append("Kimi: timeout or invalid key")
            except Exception as e:
                errors.append(f"Kimi: {str(e)[:80]}")
        else:
            errors.append("Kimi: no key/base (KIMI_API_KEY/KIMI_BASE_URL not set)")

        # Try Gemini
        if self.gemini_key:
            try:
                from google import genai
                self._genai = genai.Client(api_key=self.gemini_key)
                result = run_with_timeout(
                    self._test_gemini, timeout=12, default=None
                )
                if result:
                    self.model = result
                    self.provider = "gemini"
                    return f"Gemini [{result}]"
                else:
                    errors.append("Gemini: timeout or invalid key")
            except Exception as e:
                errors.append(f"Gemini: {str(e)[:80]}")
        else:
            errors.append("Gemini: no key (GOOGLE_API_KEY / GEMINI_API_KEY not set)")
        
        # Try NVIDIA
        if self.nvidia_key:
            nvidia_models = [
                "meta/llama-3.3-70b-instruct",
                "meta/llama-3.1-8b-instruct",
                "meta/llama-3.1-70b-instruct",
                "nvidia/llama-3.1-nemotron-70b-instruct",
            ]
            for model in nvidia_models:
                try:
                    result = run_with_timeout(
                        self._test_openai,
                        args=(model, self.nvidia_key, "https://integrate.api.nvidia.com/v1"),
                        timeout=15, default=None
                    )
                    if result:
                        self.model = model
                        self.provider = "nvidia"
                        return f"NVIDIA [{model.split('/')[-1]}]"
                except Exception as e:
                    errors.append(f"NVIDIA/{model.split('/')[-1]}: {str(e)[:80]}")
                    continue
            errors.append("NVIDIA: all models failed")
        else:
            errors.append("NVIDIA: no key (NVIDIA_API_KEY not set)")
        
        # Try Fireworks
        if self.fireworks_key:
            fw_models = [
                "accounts/fireworks/models/llama-v3p3-70b-instruct",
                "accounts/fireworks/models/llama-v3p1-70b-instruct",
            ]
            for model in fw_models:
                try:
                    result = run_with_timeout(
                        self._test_openai,
                        args=(model, self.fireworks_key, "https://api.fireworks.ai/inference/v1"),
                        timeout=12, default=None
                    )
                    if result:
                        self.model = model
                        self.provider = "fireworks"
                        return f"Fireworks [{model.split('/')[-1]}]"
                except Exception as e:
                    errors.append(f"Fireworks/{model.split('/')[-1]}: {str(e)[:80]}")
                    continue
            errors.append("Fireworks: all models failed")
        else:
            errors.append("Fireworks: no key (FIREWORKS_API_KEY not set)")
        
        raise ValueError("No AI provider available. Diagnostics: " + " | ".join(errors))
    
    def _test_gemini(self):
        """Test Gemini models."""
        from google.genai import types
        for m in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                r = self._genai.models.generate_content(
                    model=m, contents="Say OK",
                    config=types.GenerateContentConfig(max_output_tokens=5, temperature=0)
                )
                if r and r.text:
                    return m
            except:
                continue
        return None
    
    def _test_openai(self, model, api_key, base_url):
        """Test OpenAI-compatible endpoint."""
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=12.0, max_retries=0)
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5, temperature=0
        )
        if r.choices[0].message.content:
            return True
        return None
    
    def _provider_chain(self):
        """Ordered OpenAI-compatible providers for PER-CALL failover: MiniMax -> Kimi -> NVIDIA -> Fireworks.
        Returns (provider_name, model, api_key, base_url) tuples for every configured provider."""
        chain = []
        if self.minimax_key and self.minimax_base:
            chain.append(("minimax", self.minimax_model, self.minimax_key, self.minimax_base))
        if self.kimi_key and self.kimi_base:
            chain.append(("kimi", self.kimi_model, self.kimi_key, self.kimi_base))
        if self.nvidia_key:
            chain.append(("nvidia", "meta/llama-3.3-70b-instruct", self.nvidia_key, "https://integrate.api.nvidia.com/v1"))
        if self.fireworks_key:
            chain.append(("fireworks", "accounts/fireworks/models/llama-v3p3-70b-instruct", self.fireworks_key, "https://api.fireworks.ai/inference/v1"))
        return chain

    def generate(self, prompt: str, temperature: float = 0.4, max_tokens: int = 2048, json_mode: bool = False, timeout: int = 25) -> Optional[str]:
        """Generate with per-call failover (MiniMax -> Kimi -> NVIDIA -> Fireworks). Each provider is
        tried in turn until one returns text, so a single flaky provider never drops us to templates.
        Returns None only if EVERY configured provider fails."""
        # Gemini (if it was the initialized provider) keeps its native path; falls through on failure.
        if self.provider == "gemini":
            def _gem():
                return self._gen_gemini(prompt, temperature, max_tokens, json_mode, timeout)
            out = run_with_timeout(_gem, timeout=timeout + 5, default=None)
            if out:
                return out

        best = None
        for prov, model, api_key, base_url in self._provider_chain():
            def _gen(m=model, k=api_key, b=base_url):
                return self._gen_openai_direct(prompt, temperature, max_tokens, json_mode, timeout, m, k, b)
            out = run_with_timeout(_gen, timeout=timeout + 5, default=None)
            if not out:
                continue
            # In json_mode a non-parseable response (some reasoning models emit prose or
            # truncated JSON) counts as a miss — fail over to the next provider, don't return junk.
            if json_mode and parse_json_safe(out) is None:
                if best is None:
                    best = out
                continue
            self.provider, self.model = prov, model  # record what actually served the request
            return out
        return best

    def _gen_gemini(self, prompt, temp, max_tokens, json_mode, timeout=25):
        from google.genai import types
        config_kwargs = {"temperature": temp, "max_output_tokens": max_tokens}
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**config_kwargs)
        r = self._genai.models.generate_content(model=self.model, contents=prompt, config=config)
        return r.text if r else None
    
    def _gen_openai_direct(self, prompt, temp, max_tokens, json_mode, timeout, model, api_key, base_url):
        from openai import OpenAI
        to = float(timeout)
        # max_retries=0: a throttled/invalid model returns fast so we fail over to the next
        # model immediately, instead of the client silently retrying a slow/throttled endpoint.
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=to, max_retries=0)

        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temp,
            "max_tokens": max_tokens,
            "timeout": to
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            r = client.chat.completions.create(**kwargs)
        except Exception:
            # Some OpenAI-compatible providers reject response_format; the prompt already
            # asks for JSON and parse_json_safe extracts it, so retry once without it.
            if "response_format" in kwargs:
                kwargs.pop("response_format", None)
                r = client.chat.completions.create(**kwargs)
            else:
                raise
        return r.choices[0].message.content
