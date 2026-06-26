"""
DOOMSDAY RAPID AGENT - ARIZE MCP CLIENT
Logs multi-agent swarm traces, prompts, latencies, and severity verdicts back to Arize Phoenix.
Supports live nested trace recording and visual rendering within the dashboard UI console.
"""

import os
import json
import time
import uuid
import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

# OpenTelemetry safety imports for robust protobuf ingestion
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

logger = logging.getLogger("doomsday.arize_mcp")


# In-memory global store to capture active traces for dashboard UI visualization
GLOBAL_TRACE_CONSOLE: List[Dict[str, Any]] = []


class ArizePhoenixTelemetry:
    """
    Connects to Arize Phoenix or OpenTelemetry collector via Arize MCP.
    Captures full trace trees for multi-agent tribunal debates.
    """
    def __init__(self, endpoint_url: Optional[str] = None):
        raw_endpoint = (
            endpoint_url 
            or os.getenv("PHOENIX_COLLECTOR_ENDPOINT") 
            or os.getenv("PHOENIX_COLLECTOR_URL")
            or os.getenv("ARIZE_ENDPOINT_URL")
            or os.getenv("ARIZE_COLLECTOR_URL")
            or os.getenv("ARIZE_COLLECTOR_ENDPOINT")
        )
        # Sanitize empty placeholders
        if raw_endpoint:
            raw_endpoint = raw_endpoint.strip()
            # Clean string quotes if present
            if raw_endpoint.startswith('"') and raw_endpoint.endswith('"'):
                raw_endpoint = raw_endpoint[1:-1]
            if raw_endpoint.lower() in ["", "optional", "none", "null"]:
                raw_endpoint = None

        api_key = os.getenv("PHOENIX_API_KEY") or os.getenv("ARIZE_API_KEY")

        # If API key is present and endpoint is empty or points to localhost, auto-route to SaaS Cloud
        is_local = False
        if raw_endpoint and ("localhost" in raw_endpoint or "127.0.0.1" in raw_endpoint):
            is_local = True

        if api_key and (not raw_endpoint or is_local):
            self.endpoint_url = "https://app.phoenix.arize.com/v1/traces"
        elif raw_endpoint:
            # Auto-sanitize any SaaS UI dashboard links or general domains to official OTLP ingest endpoints
            if "app.phoenix.arize.com" in raw_endpoint:
                if "/s/" in raw_endpoint:
                    parts = raw_endpoint.split("/s/")
                    space_part = parts[1].split("/")[0]
                    self.endpoint_url = f"https://app.phoenix.arize.com/s/{space_part}/v1/traces"
                else:
                    self.endpoint_url = "https://app.phoenix.arize.com/v1/traces"
            elif "app.arize.com" in raw_endpoint:
                self.endpoint_url = "https://app.phoenix.arize.com/v1/traces"
            else:
                self.endpoint_url = raw_endpoint
                if not self.endpoint_url.startswith("http"):
                    self.endpoint_url = "https://" + self.endpoint_url
                if not self.endpoint_url.endswith("/v1/traces"):
                    self.endpoint_url = self.endpoint_url.rstrip("/") + "/v1/traces"
        else:
            self.endpoint_url = "http://localhost:6006/v1/traces"

            
        self.connected = False
        self.initialize_collector()

    def reconfigure(self, endpoint_url: Optional[str] = None):
        """Dynamic reconfiguration of the telemetry collector settings."""
        raw_endpoint = (
            endpoint_url 
            or os.getenv("PHOENIX_COLLECTOR_ENDPOINT") 
            or os.getenv("PHOENIX_COLLECTOR_URL")
            or os.getenv("ARIZE_ENDPOINT_URL")
            or os.getenv("ARIZE_COLLECTOR_URL")
            or os.getenv("ARIZE_COLLECTOR_ENDPOINT")
        )
        if raw_endpoint:
            raw_endpoint = raw_endpoint.strip()
            if raw_endpoint.startswith('"') and raw_endpoint.endswith('"'):
                raw_endpoint = raw_endpoint[1:-1]
            if raw_endpoint.lower() in ["", "optional", "none", "null"]:
                raw_endpoint = None

        api_key = os.getenv("PHOENIX_API_KEY") or os.getenv("ARIZE_API_KEY")

        is_local = False
        if raw_endpoint and ("localhost" in raw_endpoint or "127.0.0.1" in raw_endpoint):
            is_local = True

        if api_key and (not raw_endpoint or is_local):
            self.endpoint_url = "https://app.phoenix.arize.com/v1/traces"
        elif raw_endpoint:
            if "app.phoenix.arize.com" in raw_endpoint:
                if "/s/" in raw_endpoint:
                    parts = raw_endpoint.split("/s/")
                    space_part = parts[1].split("/")[0]
                    self.endpoint_url = f"https://app.phoenix.arize.com/s/{space_part}/v1/traces"
                else:
                    self.endpoint_url = "https://app.phoenix.arize.com/v1/traces"
            elif "app.arize.com" in raw_endpoint:
                self.endpoint_url = "https://app.phoenix.arize.com/v1/traces"
            else:
                self.endpoint_url = raw_endpoint
                if not self.endpoint_url.startswith("http"):
                    self.endpoint_url = "https://" + self.endpoint_url
                if not self.endpoint_url.endswith("/v1/traces"):
                    self.endpoint_url = self.endpoint_url.rstrip("/") + "/v1/traces"
        else:
            self.endpoint_url = "http://localhost:6006/v1/traces"
        
        if hasattr(self, "tracer"):
            delattr(self, "tracer")
        
        self.connected = False
        self.initialize_collector()

    def initialize_collector(self) -> bool:
        """Verify presence of Arize Phoenix collector and configure OTel exporter."""
        api_key = os.getenv("PHOENIX_API_KEY") or os.getenv("ARIZE_API_KEY")
        # Check all possible endpoint env vars
        has_endpoint = (
            os.getenv("PHOENIX_COLLECTOR_ENDPOINT") 
            or os.getenv("PHOENIX_COLLECTOR_URL")
            or os.getenv("ARIZE_ENDPOINT_URL")
            or os.getenv("ARIZE_COLLECTOR_URL")
            or os.getenv("ARIZE_COLLECTOR_ENDPOINT")
        )
        if has_endpoint or api_key:
            logger.info(f"Connecting to Arize Phoenix Collector at {self.endpoint_url}...")
            
            if not HAS_OTEL:
                logger.warning("OpenTelemetry library not installed. Falling back to HTTP trace reporting.")
                self.connected = True
                return self.connected

            # Set up the OTLP exporter with space authentication headers
            headers = {}
            project_name = os.getenv("PHOENIX_PROJECT_NAME") or "doomsday-rapid-agent"
            headers["x-project-name"] = project_name
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
                headers["api-key"] = api_key
                headers["X-Phoenix-Api-Key"] = api_key
                headers["X-Arize-Api-Key"] = api_key

            try:
                # OTLPSpanExporter handles standard Protocol Buffer (protobuf) formatting
                exporter = OTLPSpanExporter(
                    endpoint=self.endpoint_url,
                    headers=headers,
                    timeout=5
                )
                
                resource = Resource.create(attributes={
                    "service.name": "doomsday_rapid_agent",
                    "openinference.project.name": project_name
                })
                provider = TracerProvider(resource=resource)
                processor = SimpleSpanProcessor(exporter)
                provider.add_span_processor(processor)
                
                self.tracer = provider.get_tracer("doomsday.agent_swarm")
                self.connected = True
                logger.info("OpenTelemetry OTLP Protobuf Exporter successfully initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize OpenTelemetry exporter: {str(e)}")
                self.connected = False
        else:
            logger.warning("No live Arize Phoenix collector configured. Logging locally to dashboard console.")
            self.connected = False
        return self.connected




    def create_trace(self, name: str, ticker: str) -> Dict[str, Any]:
        """Initialize a new trace tree."""
        trace_id = str(uuid.uuid4())
        trace = {
            "trace_id": trace_id,
            "name": name,
            "ticker": ticker,
            "start_time": datetime.utcnow().isoformat() + "Z",
            "end_time": None,
            "duration_ms": 0,
            "status": "RUNNING",
            "spans": []
        }
        GLOBAL_TRACE_CONSOLE.append(trace)
        logger.info(f"[ARIZE TRACE START] {name} for {ticker} | ID: {trace_id}")
        return trace

    def start_span(self, trace_id: str, name: str, parent_span_id: Optional[str] = None) -> Dict[str, Any]:
        """Start a child span in an active trace."""
        span_id = str(uuid.uuid4())
        span = {
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": name,
            "start_time": time.time(),
            "end_time": None,
            "duration_ms": 0,
            "inputs": {},
            "outputs": {},
            "status": "RUNNING",
            "metadata": {}
        }
        
        # Locate trace in global store and append span
        for t in GLOBAL_TRACE_CONSOLE:
            if t["trace_id"] == trace_id:
                t["spans"].append(span)
                break
                
        return span

    def complete_span(self, trace_id: str, span_id: str, inputs: Dict[str, Any], outputs: Dict[str, Any], status: str = "SUCCESS", metadata: Optional[Dict] = None) -> None:
        """Complete a span, calculating duration and recording payload."""
        now = time.time()
        for t in GLOBAL_TRACE_CONSOLE:
            if t["trace_id"] == trace_id:
                for s in t["spans"]:
                    if s["span_id"] == span_id:
                        s["end_time"] = now
                        s["duration_ms"] = round((now - s["start_time"]) * 1000, 2)
                        s["inputs"] = inputs
                        s["outputs"] = outputs
                        s["status"] = status
                        s["metadata"] = metadata or {}
                        logger.info(f"  [ARIZE SPAN COMPLETE] {s['name']} | Duration: {s['duration_ms']}ms | Status: {status}")
                        break

    def complete_trace(self, trace_id: str, final_status: str = "COMPLETED") -> None:
        """End a trace, calculating aggregate duration and shipping telemetry to Arize collector."""
        for t in GLOBAL_TRACE_CONSOLE:
            if t["trace_id"] == trace_id:
                t["end_time"] = datetime.utcnow().isoformat() + "Z"
                
                # Calculate aggregate duration from span timestamps
                if t["spans"]:
                    start = min(s["start_time"] for s in t["spans"])
                    end = max(s.get("end_time") or time.time() for s in t["spans"])
                    t["duration_ms"] = round((end - start) * 1000, 2)
                    
                    # Convert start_time of spans to human readable timestamps
                    for s in t["spans"]:
                        s["start_time"] = datetime.fromtimestamp(s["start_time"]).isoformat() + "Z"
                        if s.get("end_time"):
                            s["end_time"] = datetime.fromtimestamp(s["end_time"]).isoformat() + "Z"
                
                t["status"] = final_status
                logger.info(f"[ARIZE TRACE COMPLETE] Trace ID: {trace_id} | Total Duration: {t['duration_ms']}ms")
                
                # Ship telemetry asynchronously if collector endpoint is available
                if self.connected:
                    self._ship_telemetry(t)
                break


    def _transcribe_to_otlp(self, t: Dict[str, Any]) -> Dict[str, Any]:
        """Convert custom trace tree into official OTLP HTTP JSON format."""
        # Convert times to nanosecond string safely
        def to_nano_str(ts_val) -> str:
            if isinstance(ts_val, (int, float)):
                return str(int(ts_val * 1e9))
            if isinstance(ts_val, str):
                try:
                    clean_str = ts_val.rstrip("Z")
                    dt = datetime.fromisoformat(clean_str)
                    return str(int(dt.timestamp() * 1e9))
                except Exception:
                    pass
            return str(int(time.time() * 1e9))

        # OTLP trace ID must be a 32-char hex string
        trace_id_hex = t["trace_id"].replace("-", "")
        if len(trace_id_hex) < 32:
            trace_id_hex = trace_id_hex.ljust(32, "0")
        elif len(trace_id_hex) > 32:
            trace_id_hex = trace_id_hex[:32]

        otlp_spans = []

        # 1. Create a root span for the entire debate trace
        root_span_id = uuid.uuid4().hex[:16]
        start_nano = to_nano_str(t["start_time"])
        # Calculate end_time based on duration or start time
        duration_sec = (t.get("duration_ms") or 0.0) / 1000.0
        if isinstance(t["start_time"], (int, float)):
            end_nano = to_nano_str(t["start_time"] + duration_sec)
        else:
            try:
                dt = datetime.fromisoformat(t["start_time"].rstrip("Z"))
                end_nano = to_nano_str(dt.timestamp() + duration_sec)
            except Exception:
                end_nano = to_nano_str(time.time())

        # Add root span attributes
        project_name = os.getenv("PHOENIX_PROJECT_NAME") or "doomsday-rapid-agent"
        root_attributes = [
            {"key": "service.name", "value": {"stringValue": "doomsday_rapid_agent"}},
            {"key": "openinference.project.name", "value": {"stringValue": project_name}},
            {"key": "ticker", "value": {"stringValue": t.get("ticker", "AAPL")}},
            {"key": "scan_type", "value": {"stringValue": "multi_agent_consensus"}}
        ]

        otlp_spans.append({
            "traceId": trace_id_hex,
            "spanId": root_span_id,
            "name": t["name"],
            "kind": 1, # SPAN_KIND_INTERNAL
            "startTimeUnixNano": start_nano,
            "endTimeUnixNano": end_nano,
            "attributes": root_attributes,
            "status": {"code": 1} # STATUS_CODE_OK
        })

        # 2. Add child spans for each logged agent debate step
        for s in t.get("spans", []):
            child_span_id = s["span_id"].replace("-", "")[:16]
            if len(child_span_id) < 16:
                child_span_id = child_span_id.ljust(16, "0")
            
            c_start_nano = to_nano_str(s["start_time"])
            c_end_nano = to_nano_str(s.get("end_time") or s["start_time"])

            # Format inputs/outputs/metadata as span attributes
            attributes = [
                {"key": "span.name", "value": {"stringValue": s["name"]}}
            ]

            # Add inputs
            for k, val in s.get("inputs", {}).items():
                attributes.append({"key": f"input.{k}", "value": {"stringValue": str(val)}})
            # Add outputs
            for k, val in s.get("outputs", {}).items():
                attributes.append({"key": f"output.{k}", "value": {"stringValue": str(val)}})
            # Add metadata
            for k, val in s.get("metadata", {}).items():
                attributes.append({"key": f"meta.{k}", "value": {"stringValue": str(val)}})

            otlp_spans.append({
                "traceId": trace_id_hex,
                "spanId": child_span_id,
                "parentSpanId": root_span_id,
                "name": s["name"],
                "kind": 1,
                "startTimeUnixNano": c_start_nano,
                "endTimeUnixNano": c_end_nano,
                "attributes": attributes,
                "status": {"code": 1}
            })

        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "doomsday_rapid_agent"}},
                            {"key": "openinference.project.name", "value": {"stringValue": project_name}}
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "doomsday.agent_swarm"
                            },
                            "spans": otlp_spans
                        }
                    ]
                }
            ]
        }

    def _ship_telemetry(self, trace_payload: Dict[str, Any]) -> None:
        """Ship telemetry asynchronously in a background daemon thread to prevent blocking the main thread."""
        import threading
        try:
            thread = threading.Thread(target=self._ship_telemetry_sync, args=(trace_payload,), daemon=True)
            thread.start()
        except Exception as e:
            logger.error(f"Failed to spawn background thread for telemetry shipping: {str(e)}")

    def _ship_telemetry_sync(self, trace_payload: Dict[str, Any]) -> None:
        """Synchronous inner shipping logic (runs on background daemon thread)."""
        if not self.connected:
            return

        # 1. Standard OpenTelemetry Exporter Pathway (Uses robust binary protobuf OTLP payload formatting)
        if HAS_OTEL and hasattr(self, "tracer"):
            try:
                t = trace_payload
                
                # Convert ISO string or float to epoch seconds for start/end
                def parse_time(ts_val):
                    if isinstance(ts_val, (int, float)):
                        return ts_val
                    if isinstance(ts_val, str):
                        try:
                            clean_str = ts_val.rstrip("Z")
                            return datetime.fromisoformat(clean_str).timestamp()
                        except Exception:
                            pass
                    return time.time()
                    
                parent_start = parse_time(t["start_time"])
                duration_sec = (t.get("duration_ms") or 0.0) / 1000.0
                parent_end = parent_start + duration_sec
                
                # Convert times to nanosecond integers for OTel span creation
                parent_start_nano = int(parent_start * 1e9)
                parent_end_nano = int(parent_end * 1e9)
                
                # Start the parent trace span manually
                parent_span = self.tracer.start_span(
                    name=t["name"],
                    start_time=parent_start_nano,
                    attributes={
                        "ticker": t.get("ticker", "AAPL"),
                        "scan_type": "multi_agent_consensus"
                    }
                )
                
                # Add child spans
                for s in t.get("spans", []):
                    c_start = parse_time(s["start_time"])
                    c_end = parse_time(s.get("end_time") or s["start_time"])
                    
                    c_start_nano = int(c_start * 1e9)
                    c_end_nano = int(c_end * 1e9)
                    
                    # Log child span
                    child_span = self.tracer.start_span(
                        name=s["name"],
                        context=otel_trace.set_span_in_context(parent_span),
                        start_time=c_start_nano
                    )
                    
                    # Set inputs/outputs/metadata as attributes
                    child_span.set_attribute("span.name", s["name"])
                    
                    # Add inputs
                    for k, val in s.get("inputs", {}).items():
                        child_span.set_attribute(f"input.{k}", str(val))
                    # Add outputs
                    for k, val in s.get("outputs", {}).items():
                        child_span.set_attribute(f"output.{k}", str(val))
                    # Add metadata
                    for k, val in s.get("metadata", {}).items():
                        child_span.set_attribute(f"meta.{k}", str(val))
                        
                    # Set status
                    if s.get("status") == "SUCCESS":
                        child_span.set_status(otel_trace.StatusCode.OK)
                    else:
                        child_span.set_status(otel_trace.StatusCode.ERROR)
                        
                    child_span.end(end_time=c_end_nano)
                    
                parent_span.set_status(otel_trace.StatusCode.OK)
                parent_span.end(end_time=parent_end_nano)
                
                logger.info("Successfully exported OTLP/Protobuf telemetry trace to Arize Phoenix Cloud.")
                return

            except Exception as e:
                logger.error(f"Failed to export telemetry using OpenTelemetry: {str(e)}. Falling back to HTTP JSON...")

        # 2. Resilient Fallback: Custom HTTP JSON Post
        try:
            # Transcribe to standard OTLP JSON model
            otlp_payload = self._transcribe_to_otlp(trace_payload)
            
            headers = {"Content-Type": "application/json"}
            api_key = os.getenv("PHOENIX_API_KEY") or os.getenv("ARIZE_API_KEY")
            if api_key:
                headers["X-Phoenix-Api-Key"] = api_key
                headers["X-Arize-Api-Key"] = api_key
                headers["api-key"] = api_key
                headers["Authorization"] = f"Bearer {api_key}"
            
            # Non-blocking post request
            res = requests.post(self.endpoint_url, json=otlp_payload, headers=headers, timeout=2.0)
            logger.info(f"Arize POST Response Status: {res.status_code} | Body: {res.text[:200]}")
        except Exception as e:
            logger.error(f"Failed to ship fallback telemetry to Arize Phoenix collector: {str(e)}")






# Initialize global static client
arize_client = ArizePhoenixTelemetry()
ArizeMCPClient = ArizePhoenixTelemetry

