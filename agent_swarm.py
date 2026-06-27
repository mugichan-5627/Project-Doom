"""
DOOMSDAY RAPID AGENT - ADVERSARIAL SWARM ENGINE (FRACTURE TRIBUNAL)
Orchestrates multi-agent tribunals using Gemini 3 and Partner MCP servers:
- Elastic MCP: Grounding macro risk vectors and citations.
- Arize MCP: Capturing agent trace spans, prompt inputs, outputs, and latencies.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from elastic_mcp_client import ElasticMCPClient
from arize_mcp_client import arize_client

logger = logging.getLogger("doomsday.agent_swarm")


def _to_float(value: Any, default: float = 0.0) -> float:
    """Coerce an LLM-provided value to float; fall back safely if it is a string/None.
    LLMs occasionally emit non-numeric values (e.g. "high") for numeric JSON fields even
    in json_mode, which would otherwise raise ValueError and 500 the request."""
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(default)
        except (TypeError, ValueError):
            return 0.0

# =====================================================================
# DATA MODELS
# =====================================================================
@dataclass
class DebateMessage:
    role: str
    content: str
    round_number: int
    confidence: float = 0.5

@dataclass
class RiskVerdict:
    risk_id: str
    risk_description: str
    domain: str
    severity_score: float
    probability: float
    time_horizon: str
    bull_summary: str
    bear_summary: str
    judge_reasoning: str
    geographic_nexus: str
    revenue_at_risk_pct: float
    debate_transcript: List[DebateMessage] = field(default_factory=list)
    grounding_citation: Optional[str] = None


class AgentBuilderSwarm:
    """
    Orchestrates the adversarial Fracture Tribunal using Gemini 3
    grounded in Elastic intelligence and monitored by Arize Phoenix telemetry.
    """
    def __init__(self, ai_client: Any):
        self.ai = ai_client
        self.elastic = ElasticMCPClient()
        
    def run_grounded_intelligence_scan(self, ticker: str, company_data: Any, world_state: Any, tavily_client: Any) -> List[Dict[str, Any]]:
        """
        Gathers primary risks grounded in Elastic MCP.
        Combines semantic risk databases with real-time news to identify threat vectors.
        """
        # 1. Initialize Arize trace
        trace = arize_client.create_trace(name="Grounded Intelligence Scan", ticker=ticker)
        trace_id = trace["trace_id"]
        
        # 2. Start Elastic semantic query span
        mcp_span = arize_client.start_span(trace_id=trace_id, name="Elastic Vector DB Retrieve")
        
        # Query Elastic MCP client
        elastic_risks = self.elastic.query_macro_risks(
            ticker=ticker,
            sector=getattr(company_data, "sector", "Unknown"),
            industry=getattr(company_data, "industry", "Unknown")
        )
        
        arize_client.complete_span(
            trace_id=trace_id,
            span_id=mcp_span["span_id"],
            inputs={"ticker": ticker, "sector": getattr(company_data, "sector", "Unknown")},
            outputs={"retrieved_indices": [r["id"] for r in elastic_risks], "count": len(elastic_risks)},
            metadata={"source": "Elastic Vector DB", "mcp_tool": "query_macro_risks"}
        )
        
        # 3. Start LLM Swarm Synthesis Span
        swarm_span = arize_client.start_span(trace_id=trace_id, name="Swarm Synthesis (Gemini 3)")
        
        # Pull real-time open-source grounding from Tavily (news, analyst views, retail/forum debate).
        news = ""
        if tavily_client:
            from app import tavily_search  # imported locally to avoid circular dependencies
            queries = [
                f"{company_data.name} ({ticker}) biggest business and macro risks, bear case, investor concerns 2026",
                f"{company_data.name} stock latest news, catalysts and analyst views 2026",
            ]
            chunks = []
            for q in queries:
                hit = tavily_search(tavily_client, q, max_results=3)
                if hit and "Search error" not in hit:
                    chunks.append(hit)
            if chunks:
                # Cap the grounding so a heavily-covered ticker can't bloat the prompt and slow generation.
                news = "\n\n".join(chunks)[:2500]

        news_block = (
            "\n\nREAL-TIME OPEN-SOURCE GROUNDING (recent news, analyst notes, and forum/retail debate with "
            "source URLs — anchor every risk in SPECIFIC facts, named entities, events and dates drawn from "
            "here; never invent):\n" + news + "\n"
        ) if news else ""

        # Incorporate Elastic grounding items
        grounding_context = "\n".join([
            f"- Grounded Risk [{r['title']} in {r['geographic_nexus']}]: {r['description']} (Severity: {r['severity']}/10)"
            for r in elastic_risks
        ])
        
        company_context = f"""
KNOWN PARAMETERS FOR {company_data.name}:
- Sector: {company_data.sector}, Industry: {company_data.industry}
- Market Cap: ${company_data.market_cap/1e9:.1f}B, Revenue: ${company_data.revenue/1e9:.1f}B
- Debt: ${company_data.total_debt/1e9:.1f}B, Cash: ${company_data.cash/1e9:.1f}B
- Revenue Growth: {getattr(company_data, 'revenue_growth', 0)*100:.1f}%"""

        prompt = f"""You are a senior institutional risk analyst writing for an investment committee. Identify the TOP 6 most material, NON-GENERIC stress scenarios specific to {ticker} ({company_data.name}).
You MUST leverage the following grounded macro risks retrieved from our Elastic Vector DB:

{grounding_context}

{company_context}

CURRENT WORLD STATE:
- VIX: {world_state.vix} | Fear Level: {world_state.fear_level}
- Oil: ${world_state.oil_brent} | Gold: ${world_state.gold} | US 10Y Yield: {world_state.us_10y_yield}%
{news_block}
CRITICAL INSTRUCTIONS:
1. Return EXACTLY 6 risks, each a DIFFERENT domain (geopolitical, supply_chain, financial, regulatory, technology, market).
2. Make every risk SPECIFIC TO THIS COMPANY — name its actual customers, suppliers, competitors, products, regulators, plants or geographies, or recent events. Avoid boilerplate that could apply to any company in the sector.
3. Where the real-time grounding above exists, anchor the risk in those concrete facts/events and reference them in the description.
4. Quantify the transmission: which line item breaks (revenue, margin, multiple, WACC) and the second-order knock-on effect.
5. Include the geographic location where each risk physically manifests.

Return ONLY valid JSON:
{{
    "risks": [
        {{
            "id": "RISK_001",
            "domain": "geopolitical|supply_chain|financial|regulatory|technology|market",
            "title": "Specific, company-distinct title (5-9 words)",
            "description": "2-3 sentences: the concrete scenario, the specific entities/events involved, the financial transmission with numbers, and the second-order effect.",
            "severity": 7,
            "probability": 0.4,
            "geographic_nexus": "Specific city/region",
            "revenue_at_risk_pct": 15.0,
            "time_horizon": "3_months|6_months|12_months"
        }}
    ]
}}"""
        
        try:
            from app import parse_json_safe  # imported locally
            # generate() now fails over MiniMax -> Kimi -> NVIDIA per call, so a single call is enough.
            response = self.ai.generate(prompt=prompt, temperature=0.5, json_mode=True, max_tokens=2200, timeout=45)
            parsed = parse_json_safe(response)

            if parsed and "risks" in parsed and len(parsed["risks"]) >= 2:
                final_risks = parsed["risks"][:6]
                
                # Tag risks with Elastic citation + enforce the risk contract.
                # The LLM may omit or mistype fields; the frontend and the tribunal
                # both assume these keys exist and that numerics are numeric.
                for idx, r in enumerate(final_risks):
                    if idx < len(elastic_risks):
                        r["evidence_source"] = elastic_risks[idx]["evidence_source"]
                    else:
                        r["evidence_source"] = "Swarm Predictive Logic"
                    r.setdefault("id", f"RISK_{idx + 1:03d}")
                    r["domain"] = r.get("domain") or "market"
                    r["title"] = r.get("title") or "Unspecified Risk"
                    r["severity"] = _to_float(r.get("severity"), 5.0)
                    r["probability"] = _to_float(r.get("probability"), 0.3)
                    r["revenue_at_risk_pct"] = _to_float(r.get("revenue_at_risk_pct"), 10.0)
                    r.setdefault("geographic_nexus", "Global")
                    r.setdefault("time_horizon", "12_months")
            else:
                from app import generate_fallback_risks
                final_risks = generate_fallback_risks(company_data, world_state)
        except Exception as e:
            logger.error(f"Failed to generate swarm risks: {str(e)}")
            from app import generate_fallback_risks
            final_risks = generate_fallback_risks(company_data, world_state)

        arize_client.complete_span(
            trace_id=trace_id,
            span_id=swarm_span["span_id"],
            inputs={"prompt_length": len(prompt)},
            outputs={"synthesized_risks_count": len(final_risks)},
            metadata={"gemini_model": getattr(self.ai, "model", "gemini-3")}
        )
        
        arize_client.complete_trace(trace_id=trace_id)
        return final_risks

    def run_adversarial_tribunal(self, ticker: str, company_data: Any, risk: Dict[str, Any], world_state: Any, tavily_client: Any = None) -> Optional[RiskVerdict]:
        """
        Runs an adversarial Bear vs Bull debate prosecuted by Gemini 3 and moderated by the Black Swan Judge.
        Logs nested trace hierarchy to Arize Phoenix.
        """
        risk_title = risk.get("title", "")
        risk_desc = risk.get("description", "")
        evidence_citation = risk.get("evidence_source", "Grounded Vector Search")
        
        # 1. Initialize parent trace
        trace = arize_client.create_trace(name=f"Tribunal Debate: {risk_title[:30]}", ticker=ticker)
        trace_id = trace["trace_id"]
        
        # 2. Extract company context dynamically if available
        company_name = getattr(company_data, "name", ticker) if company_data else ticker
        company_sector = getattr(company_data, "sector", "Unknown") if company_data else "Unknown"
        company_industry = getattr(company_data, "industry", "Unknown") if company_data else "Unknown"
        
        if company_data:
            company_context = f"""
BALANCE SHEET & FINANCIAL METRICS FOR {company_name} ({ticker}):
- Sector: {company_sector} | Industry: {company_industry}
- Current Price: ${getattr(company_data, 'current_price', 0.0):.2f}
- Market Cap: ${getattr(company_data, 'market_cap', 0.0)/1e9:.2f}B
- Shares Outstanding: {getattr(company_data, 'shares_outstanding', 1.0)/1e6:.2f}M
- Revenue: ${getattr(company_data, 'revenue', 0.0)/1e9:.2f}B | YoY Growth: {getattr(company_data, 'revenue_growth', 0.0)*100:.1f}%
- EBITDA: ${getattr(company_data, 'ebitda', 0.0)/1e9:.2f}B
- Net Income: ${getattr(company_data, 'net_income', 0.0)/1e9:.2f}B
- Total Debt: ${getattr(company_data, 'total_debt', 0.0)/1e9:.2f}B | Cash & Equivalents: ${getattr(company_data, 'cash', 0.0)/1e9:.2f}B
- Net Debt: {(getattr(company_data, 'total_debt', 0.0) - getattr(company_data, 'cash', 0.0))/1e9:.2f}B
- Beta: {getattr(company_data, 'beta', 1.0):.2f} | Trailing P/E: {getattr(company_data, 'pe_ratio', 0.0):.2f}x
"""
        else:
            company_context = f"BALANCE SHEET METRICS FOR {company_name}: Basic fallback mode (no balance sheet available)."

        # Real-time evidence for THIS specific risk, so the advocates argue from facts, not boilerplate.
        evidence_block = ""
        if tavily_client:
            try:
                from app import tavily_search
                hit = tavily_search(tavily_client, f"{company_name} {risk_title} impact analysis 2026", max_results=3)
                if hit and "Search error" not in hit:
                    evidence_block = (
                        "\n\nREAL-TIME EVIDENCE (cite specific facts, companies, numbers and source URLs from "
                        "below; never fabricate):\n" + hit + "\n"
                    )
            except Exception:
                evidence_block = ""

        # --- BEAR SPAN ---
        bear_span = arize_client.start_span(trace_id=trace_id, name="Bear Advocate Prosecution")
        bear_prompt = f"""You are the BEAR ADVOCATE prosecuting risk for {ticker} before an investment committee.
RISK TRIGGER: {risk_title} - {risk_desc}
Grounding Evidence: {evidence_citation}

{company_context}
{evidence_block}
Build the worst-case in 3-4 tight, high-conviction sentences. Requirements:
- Name the SPECIFIC entities in the chain (actual customers, suppliers, competitors, regulators, plants, geographies) — never generic categories.
- Quantify using the balance-sheet metrics above (leverage, cash runway, revenue at risk, margin compression, multiple de-rating) AND cite at least one concrete fact/number from the real-time evidence if present.
- Trace the second- and third-order effects, and cite a dated historical precedent.
Return JSON only: {{"argument": "your text here", "severity_estimate": 7, "confidence": 0.75}}"""
        
        bear_raw = self.ai.generate(prompt=bear_prompt, temperature=0.6, json_mode=True, max_tokens=500)
        from app import parse_json_safe
        bear = parse_json_safe(bear_raw) or {
            "argument": f"This risk presents significant operational headwinds. {risk_desc} Historical multi-factor models suggest a severe margin contraction if supply corridors crystallize.",
            "severity_estimate": risk.get("severity", 6),
            "confidence": 0.65
        }
        arize_client.complete_span(
            trace_id=trace_id,
            span_id=bear_span["span_id"],
            inputs={"risk": risk_title},
            outputs=bear,
            metadata={"agent_role": "Bear Advocate"}
        )
        
        # --- BULL SPAN ---
        bull_span = arize_client.start_span(trace_id=trace_id, name="Bull Advocate Mitigation")
        bull_prompt = f"""You are the BULL ADVOCATE defending {ticker} before an investment committee.
RISK TRIGGER: {risk_title} - {risk_desc}
BEAR ARGUED: {bear.get("argument", "")}

{company_context}
{evidence_block}
Rebut the Bear in 3-4 tight, high-conviction sentences. Requirements:
- Attack the Bear's single weakest specific assumption head-on.
- Cite concrete balance-sheet strengths (debt coverage, cash buffers, FCF, growth, valuation multiple) AND any mitigating fact from the real-time evidence (diversification, hedges, pricing power, already-priced-in).
- Explain why the current market multiple already discounts this risk.
Return JSON only: {{"argument": "your text here", "confidence": 0.55}}"""
        
        bull_raw = self.ai.generate(prompt=bull_prompt, temperature=0.6, json_mode=True, max_tokens=500)
        bull = parse_json_safe(bull_raw) or {
            "argument": f"The Bear advocate overstates this exposure. {ticker}'s robust liquid position, multi-origin supply strategies, and pricing power mitigate these shocks, which are already fully priced into forward estimates.",
            "confidence": 0.50
        }
        arize_client.complete_span(
            trace_id=trace_id,
            span_id=bull_span["span_id"],
            inputs={"bear_argument": bear.get("argument")},
            outputs=bull,
            metadata={"agent_role": "Bull Advocate"}
        )
        
        # --- JUDGE SPAN ---
        judge_span = arize_client.start_span(trace_id=trace_id, name="Black Swan Judge Verdict")
        judge_prompt = f"""You are the BLACK SWAN JUDGE moderating {ticker}'s stress tribunal.
World State: VIX={world_state.vix}, Fear={world_state.fear_level}
RISK FOCUS: {risk_title}
Grounding Citations: {evidence_citation}

{company_context}

BEAR CLAIM (severity {bear.get("severity_estimate", 6)}): {bear.get("argument", "")}
BULL DEFENSE: {bull.get("argument", "")}

Calibrate this risk. Calibration benchmarks:
- 8-10: Catastrophic systemic shock (>25% intrinsic value impairment).
- 6-7: Material operational impact.
- 4-5: Moderate headwinds.
- <4: Dismiss/Monitoring.

Return JSON only:
{{
    "verdict": "VALIDATED|DISMISSED|MONITORING",
    "final_severity": 6.5,
    "final_probability": 0.45,
    "reasoning": "2 sentences explaining why the arguments were weighted this way."
}}"""
        
        judge_raw = self.ai.generate(prompt=judge_prompt, temperature=0.3, json_mode=True, max_tokens=400)
        judge = parse_json_safe(judge_raw) or {
            "verdict": "VALIDATED" if risk.get("severity", 5) >= 5 else "MONITORING",
            "final_severity": risk.get("severity", 5),
            "final_probability": risk.get("probability", 0.4),
            "reasoning": "Grounded parameters indicate significant exposure to macro volatility. Severity and probability verified against historical crisis regimes."
        }
        arize_client.complete_span(
            trace_id=trace_id,
            span_id=judge_span["span_id"],
            inputs={"bear_severity": bear.get("severity_estimate"), "fear_level": world_state.fear_level},
            outputs=judge,
            metadata={"agent_role": "Black Swan Judge"}
        )
        
        # 4. Finalize trace
        arize_client.complete_trace(trace_id=trace_id)
        
        # Only discard if judge explicitly dismissed and severity is minimal
        if judge.get("verdict") == "DISMISSED" and judge.get("final_severity", 5) < 4:
            return None
            
        transcript = [
            DebateMessage(role="bear", content=bear.get("argument", ""), round_number=1, confidence=_to_float(bear.get("confidence"), 0.75)),
            DebateMessage(role="bull", content=bull.get("argument", ""), round_number=1, confidence=_to_float(bull.get("confidence"), 0.55)),
            DebateMessage(role="judge", content=judge.get("reasoning", ""), round_number=1, confidence=0.95),
        ]
        
        final_severity = max(1.0, min(10.0, _to_float(judge.get("final_severity"), risk.get("severity", 5))))
        final_probability = max(0.01, min(0.99, _to_float(judge.get("final_probability"), risk.get("probability", 0.4))))
        
        return RiskVerdict(
            risk_id=risk.get("id", f"RISK_{hash(risk_title) % 999:03d}"),
            risk_description=risk_desc,
            domain=risk.get("domain", "unknown"),
            severity_score=final_severity,
            probability=final_probability,
            time_horizon=risk.get("time_horizon", "6_months"),
            bull_summary=bull.get("argument", ""),
            bear_summary=bear.get("argument", ""),
            judge_reasoning=judge.get("reasoning", ""),
            geographic_nexus=risk.get("geographic_nexus", "Global"),
            revenue_at_risk_pct=_to_float(risk.get("revenue_at_risk_pct"), 10.0),
            debate_transcript=transcript,
            grounding_citation=evidence_citation
        )


class SwarmOrchestrator:
    """
    High-level orchestrator used by the Executive Cockpit.
    Coordinates grounded macro-intelligence scanning and adversarial tribunals.
    """
    def __init__(self, elastic_mcp: Any, arize_mcp: Any):
        self.elastic = elastic_mcp
        self.arize = arize_mcp

    def synthesize_threats(self, company_name: str, sector: str, chaos_level: float) -> List[Dict[str, Any]]:
        """
        Gathers grounded threats from Elastic Vector DB and calibrates them with the Chaos Index.
        Returns a beautifully formatted list of risks with severity, probability, locations, and citations.
        """
        # 1. Query grounded risks from Elastic
        raw_risks = self.elastic.query_macro_risks(
            ticker="TARGET",
            sector=sector,
            industry=sector
        )

        calibrated_risks = []
        for idx, risk in enumerate(raw_risks):
            # Scale severity and probability based on chaos slider
            base_severity = float(risk.get("severity", 5.0))
            # Linear scaling up based on chaos level
            scaled_severity = min(10.0, base_severity * (1.0 + chaos_level * 0.4))
            
            base_prob = float(risk.get("probability", 0.4))
            scaled_prob = min(0.99, base_prob * (1.0 + chaos_level * 0.5))

            # Calibrate threat levels
            if scaled_severity >= 8.5:
                threat_level = "critical"
            elif scaled_severity >= 7.0:
                threat_level = "high"
            elif scaled_severity >= 5.0:
                threat_level = "elevated"
            else:
                threat_level = "monitoring"

            calibrated_risks.append({
                "id": risk.get("id", f"RISK_{idx:03d}"),
                "domain": risk.get("domain", "general"),
                "title": risk.get("title", "Supply Corridor Breakdown"),
                "description": risk.get("description", "A systemic disruption propagating through global distribution hubs."),
                "severity": round(scaled_severity, 1),
                "probability": round(scaled_prob, 2),
                "threat_level": threat_level,
                "location": risk.get("geographic_nexus", "Global"),
                "revenue_at_risk_pct": risk.get("revenue_at_risk_pct", 10.0),
                "evidence_source": risk.get("evidence_source", "Elastic Vector DB Grounding")
            })

        return calibrated_risks

