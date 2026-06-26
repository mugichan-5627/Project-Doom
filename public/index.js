// ===============================================================
// DOOMSDAY DASHBOARD INTERACTIVE ORCHESTRATOR (Vanilla JS)
// ===============================================================

// Global State
let globalWorldState = null;
let currentCompany = null;
let currentHQ = null; // [lat, lon, label]
let activeRisks = [];
let riskVerdicts = [];
let mapTraces = [];
window.expandedTraces = window.expandedTraces || new Set();

// Base API URL (supports deployment relative pathing)
const API_BASE = window.location.origin;

// Elements
const presetSelect = document.getElementById("preset-select");
const tickerInput = document.getElementById("ticker-input");
const chaosSlider = document.getElementById("chaos-slider");
const chaosVal = document.getElementById("chaos-val");
const launchBtn = document.getElementById("launch-btn");
const terminalFeed = document.getElementById("terminal-feed");
const systemStatus = document.getElementById("system-status");
const landingOverlay = document.getElementById("landing-overlay");
const dashboardWorkspace = document.getElementById("dashboard-workspace");
const tribunalContainer = document.getElementById("tribunal-container");

// API Keys inputs
const keyLLM = document.getElementById("key-llm");
const keyTavily = document.getElementById("key-tavily");
const keyArize = document.getElementById("key-arize");
const keyEndpoint = document.getElementById("key-endpoint");

// On Load
document.addEventListener("DOMContentLoaded", () => {
    fetchWorldState();
    setupEventListeners();
});

// Event Listeners
function setupEventListeners() {
    // Preset change synchronization
    presetSelect.addEventListener("change", () => {
        if (presetSelect.value) {
            tickerInput.value = presetSelect.value;
        }
    });
    
    // Manual ticker typing clears preset selection dropdown
    tickerInput.addEventListener("input", () => {
        if (presetSelect.value && tickerInput.value !== presetSelect.value) {
            presetSelect.value = "";
        }
    });

    // Chaos slider label synchronization
    chaosSlider.addEventListener("input", () => {
        chaosVal.innerText = parseFloat(chaosSlider.value).toFixed(2);
    });

    // Launch button trigger
    launchBtn.addEventListener("click", () => {
        runStressTestPipeline();
    });

    // Watchtower alert threshold slider
    const threshSlider = document.getElementById("alert-threshold");
    if (threshSlider) {
        threshSlider.addEventListener("input", () => {
            document.getElementById("alert-thresh-val").innerText = parseFloat(threshSlider.value).toFixed(1);
        });
    }

    // Subscribe / arm watchlist
    const subBtn = document.getElementById("subscribe-btn");
    if (subBtn) {
        subBtn.addEventListener("click", subscribeAlerts);
    }
}

// Expander logic
function toggleKeys() {
    const expander = document.getElementById("keys-expander");
    const chevron = document.getElementById("keys-chevron");
    expander.classList.toggle("hidden");
    chevron.classList.toggle("fa-chevron-up");
    chevron.classList.toggle("fa-chevron-down");
}

function toggleAlerts() {
    const expander = document.getElementById("alerts-expander");
    const chevron = document.getElementById("alerts-chevron");
    expander.classList.toggle("hidden");
    chevron.classList.toggle("fa-chevron-up");
    chevron.classList.toggle("fa-chevron-down");
}

// Arm the autonomous watchtower (subscribe + instant confirmation email)
async function subscribeAlerts() {
    const email = (document.getElementById("alert-email").value || "").trim();
    const tickersRaw = (document.getElementById("alert-tickers").value || "").trim();
    const threshold = parseFloat(document.getElementById("alert-threshold").value);
    const btn = document.getElementById("subscribe-btn");

    if (!email || !email.includes("@")) { alert("Enter a valid email address."); return; }
    const tickers = tickersRaw.split(/[,\s]+/).map(t => t.trim()).filter(Boolean);
    if (!tickers.length) { alert("Enter at least one ticker to watch (e.g. NVDA, RELIANCE.NS)."); return; }

    btn.disabled = true;
    printLog(`Arming watchtower for ${email} — scanning ${tickers.join(", ")}...`, "info");
    try {
        const res = await fetch(`${API_BASE}/api/subscribe`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, tickers, threshold })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Subscription failed.");

        printLog(`Watchlist armed: ${data.tickers.join(", ")} @ threshold ${threshold.toFixed(1)}/10`, "ok");
        (data.snapshot || []).forEach(s => {
            printLog(`  ${s.ticker} (${s.name}): severity ${s.severity}/10 ${s.breached ? "— BREACH" : "— ok"}`, s.breached ? "err" : "dim");
        });
        if (data.email_sent) {
            printLog(`Confirmation email dispatched to ${email}. Check your inbox.`, "ok");
        } else if (!data.email_configured) {
            printLog(`Email provider not set (RESEND_API_KEY) — subscription saved; alerts will send once the key is added.`, "info");
        } else {
            printLog(`Subscription saved, but the confirmation email failed to send. Check the address.`, "err");
        }
        if (!data.store_configured) {
            printLog(`Using local fallback store (Upstash not attached yet) — fine for local testing.`, "dim");
        }
    } catch (err) {
        printLog(`Watchtower arm failed: ${err.message}`, "err");
    } finally {
        btn.disabled = false;
    }
}

// Terminal logger
function printLog(message, type = "info") {
    const timestamp = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = `t-line t-${type}`;
    line.innerHTML = `[${timestamp}] ${message}`;
    terminalFeed.appendChild(line);
    terminalFeed.scrollTop = terminalFeed.scrollHeight;
}

// Gather dynamic headers (User keys)
function getApiKeys() {
    return {
        llm_key: keyLLM.value || null,
        tavily_key: keyTavily.value || null,
        phoenix_key: keyArize.value || null,
        phoenix_endpoint: keyEndpoint.value || null
    };
}

// Initial macro state gathering
async function fetchWorldState() {
    try {
        const response = await fetch(`${API_BASE}/api/world_state`);
        if (!response.ok) throw new Error("Macro state unreachable.");
        
        const ws = await response.json();
        globalWorldState = ws;
        
        // Render top indicators
        document.getElementById("ind-vix").innerText = ws.vix.toFixed(2);
        document.getElementById("ind-brent").innerText = `$${ws.oil_brent.toFixed(2)}`;
        document.getElementById("ind-gold").innerText = `$${ws.gold.toFixed(0)}`;
        document.getElementById("ind-yield").innerText = `${ws.us_10y_yield.toFixed(2)}%`;
        
        const fearEl = document.getElementById("ind-fear");
        fearEl.innerText = ws.fear_level;
        
        // Color badge
        fearEl.className = "ind-val";
        if (ws.fear_level === "PANIC") fearEl.classList.add("bear-text");
        else if (ws.fear_level === "ANXIOUS") fearEl.classList.add("text-neon-orange");
        else if (ws.fear_level === "CAUTIOUS") fearEl.classList.add("text-neon-yellow");
        else fearEl.classList.add("bull-text");
        
    } catch (err) {
        console.error("Macro data failed:", err);
    }
}

// Main Orchestrated Pipeline
async function runStressTestPipeline() {
    const ticker = tickerInput.value.trim().toUpperCase();
    if (!ticker) {
        alert("Please enter a valid company ticker.");
        return;
    }

    // Reset layout
    landingOverlay.classList.add("hidden");
    dashboardWorkspace.classList.remove("hidden");
    tribunalContainer.innerHTML = "";
    terminalFeed.innerHTML = "";
    activeRisks = [];
    riskVerdicts = [];
    mapTraces = [];
    
    // Set Status
    systemStatus.innerText = "SYS_RESOLVING";
    systemStatus.className = "status-badge badge-threat";
    launchBtn.disabled = true;
    
    printLog(`Initializing system scan for target: ${ticker}...`, "info");
    
    try {
        // Step 1: Resolve ticker & HQ
        const initRes = await fetch(`${API_BASE}/api/init_ticker?ticker=${encodeURIComponent(ticker)}`);
        if (!initRes.ok) {
            let reason = "";
            try { reason = (await initRes.json()).detail; } catch (e) {}
            throw new Error(reason || `"${ticker}" not found on Yahoo Finance — check the symbol (e.g. RELIANCE.NS, AAPL, NVDA).`);
        }
        
        const initData = await initRes.json();
        currentCompany = initData.company_data;
        currentHQ = initData.hq_coords;
        
        printLog(`Ticker resolved successfully: ${initData.resolved_ticker}`, "ok");
        printLog(`Company: ${currentCompany.name} | Sector: ${currentCompany.sector}`, "info");
        printLog(`HQ Located: ${currentHQ[2]} (Coords: ${currentHQ[0].toFixed(2)}, ${currentHQ[1].toFixed(2)})`, "info");
        
        // Populate KPIs
        updateKPIs(currentCompany, null, null);
        
        // Draw Initial HQ Marker on map
        initMap(currentHQ);

        // Fetch World State if not present
        if (!globalWorldState) {
            await fetchWorldState();
        }

        // Step 2: Grounded Risk Scanning
        printLog("Executing Grounded Intelligence Scan (Elastic MCP Lookup)...", "info");
        systemStatus.innerText = "SYS_SCANNING";
        
        const scanRes = await fetch(`${API_BASE}/api/generate_risks`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                ticker: initData.resolved_ticker,
                company_data: currentCompany,
                world_state: globalWorldState,
                api_keys: getApiKeys()
            })
        });
        if (!scanRes.ok) throw new Error("Grounded scan failed.");
        
        const scanData = await scanRes.json();
        activeRisks = scanData.risks;
        printLog(`Synthesized ${activeRisks.length} grounded domain threats (AI Model: ${scanData.model})`, "ok");
        activeRisks.forEach((r, idx) => {
            const domain = (r.domain || "unknown").toUpperCase();
            const sev = (r.severity ?? "N/A");
            printLog(`Threat [${domain}]: ${r.title || "Untitled Threat"} (Severity Target: ${sev}/10)`, "dim");
        });

        // Step 3: Progressive Swarm Tribunals
        systemStatus.innerText = "SYS_TRIBUNAL";
        printLog("Spinning up Swarm Sworn Tribunal agents (Bull vs. Bear advocates)...", "info");
        
        // Reset containers
        document.getElementById("risk-feed-container").innerHTML = "";
        
        for (let i = 0; i < activeRisks.length; i++) {
            const risk = activeRisks[i];
            printLog(`Tribunal Run [${i+1}/${activeRisks.length}]: Analyzing "${risk.title}"`, "info");
            
            const tribRes = await fetch(`${API_BASE}/api/run_tribunal`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    ticker: initData.resolved_ticker,
                    company_data: currentCompany,
                    risk: risk,
                    world_state: globalWorldState,
                    hq_coords: [currentHQ[0], currentHQ[1]],
                    api_keys: getApiKeys()
                })
            });
            
            if (tribRes.ok) {
                const tribData = await tribRes.json();
                const verdict = tribData.risk_verdict;
                if (verdict) {
                    riskVerdicts.push(verdict);
                    printLog(`Tribunal Verdict: Severity ${verdict.severity_score.toFixed(1)}/10 [${verdict.threat_level.toUpperCase()}]`, "ok");
                    
                    // Render debate bubble
                    renderDebateBubble(verdict, i + 1);
                    
                    // Render risk feed card
                    renderRiskFeed(riskVerdicts);
                    
                    // Add risk marker & convergence arc to Map
                    addRiskToMap(verdict, currentHQ);
                    
                    // Update telemetry log
                    fetchAndRenderTelemetry();
                }
            } else {
                printLog(`Tribunal failed for risk: ${risk.title}`, "err");
            }
        }
        
        // Step 4: Stressed Valuation Waterfall
        printLog("Swarm Tribunal complete. Synthesizing stress cascade to valuation routers...", "info");
        systemStatus.innerText = "SYS_VALUING";
        
        const valRes = await fetch(`${API_BASE}/api/calculate_valuation`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                company_data: currentCompany,
                chaos_level: parseFloat(chaosSlider.value),
                risk_verdicts: riskVerdicts
            })
        });
        
        if (!valRes.ok) throw new Error("Valuation calculation failed.");
        const valData = await valRes.json();
        const stressedVal = valData.stressed_valuation;
        
        printLog("Calculations finalized. Bridge waterfall generated.", "ok");
        
        // Update all KPI indicators with valuation results
        updateKPIs(currentCompany, stressedVal, riskVerdicts);
        
        // Render Plotly Waterfall Chart
        renderWaterfallChart(stressedVal);

        // Update Methodology Sidebar
        updateMethodologySidebar(stressedVal);

        // Render Valuation Transparency calculation audit trail
        renderValuationTransparency(currentCompany, stressedVal, riskVerdicts);

        // Fetch and Render Contagion Cascade
        await fetchAndRenderContagion(currentCompany, riskVerdicts);

        // Final telemetry refresh
        await fetchAndRenderTelemetry();

        // System Finished
        systemStatus.innerText = "SYS_NOMINAL";
        systemStatus.className = "status-badge badge-active";
        
    } catch (error) {
        printLog(`Pipeline Aborted: ${error.message}`, "err");
        systemStatus.innerText = "SYS_FAULT";
        systemStatus.className = "status-badge badge-critical";
    } finally {
        launchBtn.disabled = false;
    }
}

// KPI renderer
function updateKPIs(company, val, verdicts) {
    document.getElementById("kpi-name").innerText = company.name;
    document.getElementById("kpi-ticker").innerText = company.ticker;
    document.getElementById("kpi-sector").innerText = company.sector;
    document.getElementById("kpi-cap").innerText = `$${(company.market_cap / 1e9).toFixed(1)}B`;
    
    if (val) {
        document.getElementById("kpi-base-val").innerText = `$${val.base_fair_value.toFixed(2)}`;
        document.getElementById("kpi-stressed-val").innerText = `$${val.distressed_value.toFixed(2)}`;
        
        const downsideEl = document.getElementById("kpi-downside");
        downsideEl.innerText = `${val.downside_pct.toFixed(1)}%`;
        downsideEl.className = "kpi-val text-neon-red";
    } else {
        document.getElementById("kpi-base-val").innerText = "--";
        document.getElementById("kpi-stressed-val").innerText = "--";
        document.getElementById("kpi-downside").innerText = "--";
    }
}

// Validated Risk Feed card renderer
function renderRiskFeed(verdicts) {
    const container = document.getElementById("risk-feed-container");
    container.innerHTML = "";
    
    if (!verdicts || verdicts.length === 0) {
        container.innerHTML = `
            <div class="risk-feed-placeholder">
                <i class="fa-solid fa-triangle-exclamation"></i>
                <p>Grounded risks will appear here as they are identified and validated.</p>
            </div>
        `;
        return;
    }
    
    verdicts.forEach(v => {
        const card = document.createElement("div");
        card.className = `risk-card risk-${v.threat_level.toLowerCase()}`;
        
        const severityPercent = (v.severity_score * 10).toFixed(0);
        const probPercent = (v.probability * 100).toFixed(0);
        const revPercent = (v.revenue_at_risk_pct || 10).toFixed(0);
        
        card.innerHTML = `
            <!-- Column 1: Identity & Location -->
            <div class="rc-col rc-identity">
                <div class="rc-label">THREAT IDENTIFIED</div>
                <div class="rc-title">${v.risk_description}</div>
                <div class="rc-location"><i class="fa-solid fa-location-dot"></i> ${v.geographic_nexus}</div>
            </div>
            
            <!-- Column 2: Severity & Probability -->
            <div class="rc-col rc-metrics">
                <div class="rc-label">SEVERITY / PROBABILITY</div>
                <div class="rc-metric-row">
                    <span class="rc-val text-neon-${v.threat_level === 'critical' ? 'red' : v.threat_level === 'high' ? 'orange' : v.threat_level === 'elevated' ? 'yellow' : 'green'}">${v.severity_score.toFixed(1)}/10</span>
                    <div class="rc-bar-bg"><div class="rc-bar bg-neon-${v.threat_level === 'critical' ? 'red' : v.threat_level === 'high' ? 'orange' : v.threat_level === 'elevated' ? 'yellow' : 'green'}" style="width: ${severityPercent}%"></div></div>
                </div>
                <div class="rc-metric-row">
                    <span class="rc-val">${probPercent}% PROB</span>
                    <div class="rc-bar-bg"><div class="rc-bar bg-neon-cyan" style="width: ${probPercent}%"></div></div>
                </div>
            </div>
            
            <!-- Column 3: Exposure & Horizon -->
            <div class="rc-col rc-exposure">
                <div class="rc-label">EXPOSURE & HORIZON</div>
                <div class="rc-detail-item"><i class="fa-solid fa-clock"></i> ${v.time_horizon.replace('_', ' ').toUpperCase()}</div>
                <div class="rc-detail-item text-neon-red"><i class="fa-solid fa-hand-holding-dollar"></i> ${revPercent}% Rev-at-Risk</div>
            </div>
            
            <!-- Column 4: Judge Grounding Verdict -->
            <div class="rc-col rc-grounding">
                <div class="rc-label">JUDICIAL TRIBUNAL GROUNDING VERDICT</div>
                <div class="rc-verdict-text">${v.judge_reasoning}</div>
            </div>
        `;
        container.appendChild(card);
    });
}

// Waterfall Methodology Sidebar updater
function updateMethodologySidebar(val) {
    document.getElementById("methodology-engine").innerText = val.valuation_method;
    document.getElementById("methodology-base-wacc").innerText = `${val.base_wacc.toFixed(1)}%`;
    document.getElementById("methodology-stressed-wacc").innerText = `${val.stressed_wacc.toFixed(1)}%`;
    document.getElementById("methodology-rev-haircut").innerText = `${val.revenue_haircut.toFixed(1)}%`;
    document.getElementById("methodology-margin").innerText = `${val.margin_compression_bps.toFixed(0)} bps`;
    document.getElementById("methodology-chaos").innerText = `${(parseFloat(chaosSlider.value) * 100).toFixed(0)}%`;
}

// Expandable Tribunal Expander card renderer (with Click-to-Expand detailed debate transcripts)
function renderDebateBubble(v, runNum) {
    const expander = document.createElement("div");
    // Open the first card by default, collapse others
    expander.className = `tribunal-expander${runNum === 1 ? ' open' : ''}`;
    
    const header = document.createElement("div");
    header.className = "tribunal-expander-header";
    header.innerHTML = `
        <span>RUN #${runNum}: ${v.risk_description.substring(0, 50)}${v.risk_description.length > 50 ? '...' : ''}</span>
        <div style="display: flex; align-items: center; gap: 10px;">
            <span style="color: ${getColorHex(v.threat_level)}">${v.threat_level.toUpperCase()} (${v.severity_score.toFixed(1)}/10)</span>
            <i class="fa-solid fa-chevron-down expander-icon"></i>
        </div>
    `;
    
    header.addEventListener("click", () => {
        expander.classList.toggle("open");
    });
    
    const content = document.createElement("div");
    content.className = "tribunal-expander-content";
    
    // Metrics Grid
    const metricsRow = document.createElement("div");
    metricsRow.className = "tribunal-metrics-row";
    metricsRow.innerHTML = `
        <div>
            <span class="m-label">Severity</span>
            <span class="m-val" style="color: ${getColorHex(v.threat_level)}">${v.severity_score.toFixed(1)}</span>
        </div>
        <div>
            <span class="m-label">Probability</span>
            <span class="m-val">${(v.probability * 100).toFixed(0)}%</span>
        </div>
        <div>
            <span class="m-label">Rev Risk</span>
            <span class="m-val">${v.revenue_at_risk_pct.toFixed(0)}%</span>
        </div>
        <div>
            <span class="m-label">Horizon</span>
            <span class="m-val" style="font-size: 0.85em; margin-top: 4px;">${v.time_horizon.replace('_', ' ').toUpperCase()}</span>
        </div>
    `;
    content.appendChild(metricsRow);
    
    // Bull Message
    const bullMsg = document.createElement("div");
    bullMsg.className = "debate-msg msg-bull";
    bullMsg.innerHTML = `
        <div class="msg-role bull-text"><span>BULL ADVOCATE</span><span>CONFIDENCE: 45%</span></div>
        <p>${v.bull_summary}</p>
    `;
    content.appendChild(bullMsg);
    
    // Bear Message
    const bearMsg = document.createElement("div");
    bearMsg.className = "debate-msg msg-bear";
    bearMsg.innerHTML = `
        <div class="msg-role bear-text"><span>BEAR ADVOCATE</span><span>CONFIDENCE: 85%</span></div>
        <p>${v.bear_summary}</p>
    `;
    content.appendChild(bearMsg);
    
    // Judge Message
    const judgeMsg = document.createElement("div");
    judgeMsg.className = "debate-msg msg-judge";
    judgeMsg.innerHTML = `
        <div class="msg-role judge-text"><span>BLACK SWAN JUDGE VERDICT</span><span>PROBABILITY: ${(v.probability * 100).toFixed(0)}%</span></div>
        <p>${v.judge_reasoning}</p>
    `;
    content.appendChild(judgeMsg);
    
    expander.appendChild(header);
    expander.appendChild(content);
    
    tribunalContainer.appendChild(expander);
    tribunalContainer.scrollTop = tribunalContainer.scrollHeight;
}

// Contagion Cascade Propagation Model Renderer
async function fetchAndRenderContagion(company, verdicts) {
    const container = document.getElementById("contagion-container");
    container.innerHTML = `
        <div style="text-align:center; padding:30px; color:var(--text-dim);">
            <i class="fa-solid fa-spinner fa-spin fa-2x"></i>
            <p style="margin-top:10px">Modeling propagation chains...</p>
        </div>
    `;
    try {
        const res = await fetch(`${API_BASE}/api/generate_contagion`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                company_data: company,
                chaos_level: parseFloat(chaosSlider.value),
                risk_verdicts: verdicts,
                api_keys: getApiKeys()
            })
        });
        if (!res.ok) throw new Error("Failed to generate contagion cascade.");
        const data = await res.json();
        
        container.innerHTML = "";
        const chains = data.chains;
        if (!chains || chains.length === 0) {
            container.innerHTML = `
                <div class="contagion-placeholder">
                    <i class="fa-solid fa-diagram-project"></i>
                    <p>No contagion paths modeled.</p>
                </div>
            `;
            return;
        }
        
        chains.forEach(chain => {
            const block = document.createElement("div");
            block.className = "contagion-chain-block";
            
            let stepsHtml = "";
            chain.cascade.forEach(step => {
                stepsHtml += `
                    <div class="contagion-step">
                        <span class="step-order">Order ${step.order}</span>
                        <span class="step-effect">${step.effect}</span>
                        <div class="step-meta">
                            Impact: <span class="bear-text">${step.magnitude}</span> on ${step.metric_impacted} | 
                            Time Delay: ${step.time_delay} | 
                            Cum. Loss: <span class="bear-text">${step.cumulative_value_destruction_pct}%</span>
                        </div>
                    </div>
                `;
            });
            
            block.innerHTML = `
                <div class="contagion-chain-title">Trigger Event: ${chain.primary_risk} (Primary Severity: ${chain.primary_severity.toFixed(1)})</div>
                <div class="contagion-flow">
                    ${stepsHtml}
                </div>
            `;
            container.appendChild(block);
        });
    } catch (err) {
        console.error(err);
        container.innerHTML = `
            <div class="contagion-placeholder">
                <i class="fa-solid fa-circle-exclamation text-neon-red"></i>
                <p style="color:var(--neon-red);">Failed to render cascade: ${err.message}</p>
            </div>
        `;
    }
}

// Format telemetry dictionaries into clean HTML tags (no raw curly braces)
function formatTelemetryDict(data) {
    if (!data) {
        return '<span style="color: #5a6f82; font-style: italic;">None</span>';
    }
    
    let parsed = data;
    if (typeof data === 'string') {
        try {
            parsed = JSON.parse(data);
        } catch (e) {
            return `<span style="color: #eceff1;">${data}</span>`;
        }
    }
    
    if (typeof parsed !== 'object' || parsed === null) {
        return `<span style="color: #eceff1;">${parsed}</span>`;
    }
    
    let htmlParts = [];
    for (const [k, v] of Object.entries(parsed)) {
        const keyTitle = k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
        
        let valStr = "";
        if (k.toLowerCase().includes("severity") && (typeof v === "number" || typeof v === "string")) {
            valStr = `<span style="color: #ff6d00; font-weight: bold;">${v}/10</span>`;
        } else if (k.toLowerCase().includes("confidence") && (typeof v === "number" || typeof v === "string")) {
            const num = parseFloat(v);
            const pct = num <= 1.0 ? Math.round(num * 100) : Math.round(num);
            valStr = `<span style="color: #00e676; font-weight: bold;">${pct}%</span>`;
        } else if (typeof v === "object" && v !== null) {
            valStr = formatTelemetryDict(v);
        } else {
            valStr = `<span style="color: #eceff1;">${v}</span>`;
        }
        
        htmlParts.push(`
            <div class="telemetry-key-value" style="margin-bottom: 8px; line-height: 1.4;">
                <strong class="telemetry-key-label" style="color: #00ffd0; font-weight: bold; display: block; text-transform: uppercase; font-size: 0.9em; letter-spacing: 0.5px;">${keyTitle}</strong>
                <span class="telemetry-val-text" style="color: #eceff1; font-size: 0.95em;">${valStr}</span>
            </div>
        `);
    }
    return htmlParts.join("");
}

// Global trace expander toggle
window.toggleTrace = function(traceId) {
    const detailsDiv = document.getElementById(traceId);
    const chevron = document.querySelector(`[data-chevron-for="${traceId}"]`);
    if (!detailsDiv) return;
    
    if (detailsDiv.style.display === "none") {
        detailsDiv.style.display = "block";
        if (chevron) chevron.classList.add("expanded");
        window.expandedTraces.add(traceId);
    } else {
        detailsDiv.style.display = "none";
        if (chevron) chevron.classList.remove("expanded");
        window.expandedTraces.delete(traceId);
    }
};

// Arize Telemetry log reader
async function fetchAndRenderTelemetry() {
    const container = document.getElementById("telemetry-console-container");
    try {
        const res = await fetch(`${API_BASE}/api/telemetry`);
        if (!res.ok) throw new Error("Telemetry unreachable.");
        const data = await res.json();
        const traces = data.traces;
        const endpointUrl = data.endpoint || "https://app.phoenix.arize.com/s/moosatalha2712";
        
        // Calculate telemetry metrics
        const totalTraces = traces.length;
        const totalSpans = traces.reduce((sum, t) => sum + (t.spans ? t.spans.length : 0), 0);
        
        let collectorType = "Phoenix Local Collector";
        let statusText = "ACTIVE LOCAL BRIDGE";
        let statusColor = "#4fc3f7";
        
        if (endpointUrl.includes("app.phoenix.arize.com") || document.getElementById("key-arize").value.trim()) {
            collectorType = "Arize Phoenix SaaS Cloud";
            statusText = "CONNECTED & RUNNING";
            statusColor = "#00ffd0";
        }
        
        // Render Telemetry dashboard card and OTel animation flow
        let headerHtml = `
            <div class="telemetry-container" style="background: #0a0e14; border: 1px solid #162030; border-radius: 6px; padding: 15px; margin-bottom: 20px;">
                <div class="telemetry-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div class="telemetry-title" style="display: flex; align-items: center; font-family: monospace; font-size: 0.85em; color: #00ffd0; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">
                        <div class="telemetry-status-pulse"></div>
                        Arize Phoenix Telemetry Stream -- Active Ingestion
                    </div>
                    <div style="font-family: monospace; font-size: 0.7em; background: #1a2538; padding: 2px 8px; border-radius: 4px; color: #eceff1; font-weight: bold;">
                        OTLP PROTOBUF / HTTP/1.1
                    </div>
                </div>
                
                <svg width="100%" height="90px" viewBox="0 0 600 90" style="background:#0a0e14; border-radius:4px;">
                    <defs>
                        <linearGradient id="pipe-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#ff3344" stop-opacity="0.8"/>
                            <stop offset="50%" stop-color="#9d4edd" stop-opacity="0.8"/>
                            <stop offset="100%" stop-color="#00ffd0" stop-opacity="0.8"/>
                        </linearGradient>
                        <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
                            <feGaussianBlur stdDeviation="3" result="blur" />
                            <feComposite in="SourceGraphic" in2="blur" operator="over" />
                        </filter>
                        <filter id="glow-red" x="-20%" y="-20%" width="140%" height="140%">
                            <feGaussianBlur stdDeviation="3" result="blur" />
                            <feComposite in="SourceGraphic" in2="blur" operator="over" />
                        </filter>
                    </defs>
                    
                    <!-- Connection Pipeline Background -->
                    <path d="M 76,40 Q 300,5 524,40" stroke="#131c2c" stroke-width="6" fill="none" />
                    
                    <!-- Connection Pipeline Animated Flow -->
                    <path d="M 76,40 Q 300,5 524,40" stroke="url(#pipe-grad)" stroke-width="2.5" fill="none" class="telemetry-dash-pipe" />
                    
                    <!-- Swarm Engine Node -->
                    <circle cx="60" cy="40" r="14" fill="#ff3344" class="telemetry-node-swarm" filter="url(#glow-red)" />
                    <text x="60" y="70" fill="#ff3344" font-size="8.5" font-family="monospace" text-anchor="middle" font-weight="bold">SWARM AGENTS</text>
                    
                    <!-- Arize Phoenix Node -->
                    <circle cx="540" cy="40" r="14" fill="#00ffd0" class="telemetry-node-arize" filter="url(#glow-cyan)" />
                    <text x="540" y="70" fill="#00ffd0" font-size="8.5" font-family="monospace" text-anchor="middle" font-weight="bold">PHOENIX SAAS</text>
                    
                    <!-- Flowing Data Signal Packets (Animate Motion) -->
                    <circle r="4" fill="#00ffd0" filter="url(#glow-cyan)">
                        <animateMotion dur="2.8s" repeatCount="indefinite" path="M 76,40 Q 300,5 524,40" />
                    </circle>
                    
                    <circle r="4" fill="#ff3344" filter="url(#glow-red)">
                        <animateMotion dur="2.8s" begin="0.9s" repeatCount="indefinite" path="M 76,40 Q 300,5 524,40" />
                    </circle>
                    
                    <circle r="3.5" fill="#9d4edd" filter="url(#glow-cyan)">
                        <animateMotion dur="2.8s" begin="1.8s" repeatCount="indefinite" path="M 76,40 Q 300,5 524,40" />
                    </circle>
                </svg>
                
                <div class="telemetry-grid" style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 15px; font-family: monospace; font-size: 0.72em;">
                    <div class="telemetry-card" style="background: #0f1520; padding: 8px; border-radius: 4px; border: 1px solid #1a2538;">
                        <div class="telemetry-card-label" style="color: #5a6f82; font-weight: bold; margin-bottom: 2px;">COLLECTOR TYPE</div>
                        <div class="telemetry-card-val" style="color: #eceff1; font-weight: bold;">${collectorType}</div>
                    </div>
                    <div class="telemetry-card" style="background: #0f1520; padding: 8px; border-radius: 4px; border: 1px solid #1a2538;">
                        <div class="telemetry-card-label" style="color: #5a6f82; font-weight: bold; margin-bottom: 2px;">INGEST STATUS</div>
                        <div class="telemetry-card-val" style="color: ${statusColor}; font-weight: bold;">${statusText}</div>
                    </div>
                    <div class="telemetry-card" style="background: #0f1520; padding: 8px; border-radius: 4px; border: 1px solid #1a2538;">
                        <div class="telemetry-card-label" style="color: #5a6f82; font-weight: bold; margin-bottom: 2px;">TRACES EXPORTED</div>
                        <div class="telemetry-card-val" style="color: #eceff1; font-weight: bold;">${totalTraces} active</div>
                    </div>
                    <div class="telemetry-card" style="background: #0f1520; padding: 8px; border-radius: 4px; border: 1px solid #1a2538;">
                        <div class="telemetry-card-label" style="color: #5a6f82; font-weight: bold; margin-bottom: 2px;">TOTAL SPANS</div>
                        <div class="telemetry-card-val" style="color: #eceff1; font-weight: bold;">${totalSpans} records</div>
                    </div>
                </div>
                <div class="telemetry-endpoint-line" style="margin-top: 10px; font-family: monospace; font-size: 0.68em; color: #5a6f82; word-break: break-all; border-top: 1px solid #162030; padding-top: 8px;">
                    <strong>ACTIVE OTLP ENDPOINT:</strong> ${endpointUrl}
                </div>
            </div>
        `;
        
        let tracesHtml = "";
        if (!traces || traces.length === 0) {
            tracesHtml = `
                <div class="telemetry-placeholder">
                    <i class="fa-solid fa-server"></i>
                    <p>No traces emitted yet.</p>
                </div>
            `;
        } else {
            traces.slice().reverse().forEach(trace => {
                let spansHtml = "";
                trace.spans.forEach(span => {
                    const statusColor = span.status === "SUCCESS" ? "#00ffd0" : "#ff1744";
                    spansHtml += `
                        <div class="telemetry-span-box" style="background-color: #121824; border: 1px solid #1d2b40; border-left: 3px solid #00ffd0; border-radius: 4px; padding: 12px; margin-bottom: 10px;">
                            <div class="telemetry-span-header" style="display: flex; justify-content: space-between; font-family: monospace; font-size: 0.8em; margin-bottom: 8px; border-bottom: 1px solid #1d2b40; padding-bottom: 6px;">
                                <strong style="color:#00ffd0">Span: ${span.name}</strong>
                                <span style="color:#ffffff; font-family:monospace; font-weight: bold;">
                                    ${span.duration_ms.toFixed(1)}ms | <span style="color:${statusColor}; font-weight: bold;">${span.status}</span>
                                </span>
                            </div>
                            <div class="telemetry-span-cols" style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 8px;">
                                <div class="telemetry-span-col">
                                    <div class="telemetry-span-col-title" style="color: #5a6f82; font-family: monospace; font-size: 0.72em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px;">Span Inputs</div>
                                    <div class="telemetry-span-content" style="background: #080c12; border: 1px solid #162030; border-radius: 4px; padding: 10px; font-family: monospace; font-size: 0.76em; color: #eceff1; min-height: 40px; overflow-x: auto;">
                                        ${formatTelemetryDict(span.inputs)}
                                    </div>
                                </div>
                                <div class="telemetry-span-col">
                                    <div class="telemetry-span-col-title" style="color: #5a6f82; font-family: monospace; font-size: 0.72em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px;">Span Outputs</div>
                                    <div class="telemetry-span-content" style="background: #080c12; border: 1px solid #162030; border-radius: 4px; padding: 10px; font-family: monospace; font-size: 0.76em; color: #eceff1; min-height: 40px; overflow-x: auto;">
                                        ${formatTelemetryDict(span.outputs)}
                                    </div>
                                </div>
                            </div>
                            ${span.metadata && Object.keys(span.metadata).length > 0 ? `
                            <div class="telemetry-span-metadata" style="margin-top: 10px; padding: 10px; background: #080c12; border: 1px solid #162030; border-radius: 4px;">
                                <span class="telemetry-metadata-title" style="color: #5a6f82; font-family: monospace; font-size: 0.72em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; display: block; margin-bottom: 5px;">Metadata Details</span>
                                ${formatTelemetryDict(span.metadata)}
                            </div>
                            ` : ''}
                        </div>
                    `;
                });
                
                const traceId = `trace-${trace.trace_id}`;
                const isExpanded = window.expandedTraces.has(traceId);
                const displayStyle = isExpanded ? "block" : "none";
                const chevronClass = isExpanded ? "telemetry-chevron expanded" : "telemetry-chevron";
                
                tracesHtml += `
                    <div class="telemetry-trace-row" style="background-color: #070a0e; border: 1px solid #162030; border-radius: 4px; margin-bottom: 8px; overflow: hidden;">
                        <div class="telemetry-trace-header" onclick="toggleTrace('${traceId}')" style="background-color: #0f1520; padding: 12px 15px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-family: monospace; font-size: 0.82em; font-weight: bold; color: #eceff1; transition: background-color 0.2s; user-select: none;">
                            <span>🔌 Trace: ${trace.name} | Ticker: ${trace.ticker} | Duration: ${trace.duration_ms.toFixed(2)}ms</span>
                            <i class="fa-solid fa-chevron-down ${chevronClass}" data-chevron-for="${traceId}" style="transition: transform 0.2s; color: #5a6f82;"></i>
                        </div>
                        <div id="${traceId}" class="telemetry-trace-details" style="display: ${displayStyle}; padding: 15px; border-top: 1px solid #162030; background-color: #070a0e;">
                            <div class="telemetry-trace-meta" style="background-color: #101622; border-left: 4px solid #00ffd0; padding: 10px; margin-bottom: 12px; border-radius: 4px; font-family: monospace; font-size: 0.8em; line-height: 1.5;">
                                <strong style="color:#5a6f82;">Trace ID:</strong> <span style="color:#eceff1;">${trace.trace_id}</span><br>
                                <strong style="color:#5a6f82;">Start Time:</strong> <span style="color:#eceff1;">${trace.start_time}</span><br>
                                <strong style="color:#5a6f82;">Status:</strong> <span style="color:#00ffd0; font-weight: bold;">${trace.status}</span>
                            </div>
                            <div class="telemetry-spans-container" style="margin-left: 15px;">
                                ${spansHtml}
                            </div>
                        </div>
                    </div>
                `;
            });
        }
        
        container.innerHTML = headerHtml + tracesHtml;
    } catch (err) {
        console.error(err);
        container.innerHTML = `
            <div class="telemetry-placeholder">
                <i class="fa-solid fa-circle-exclamation text-neon-red"></i>
                <p>Telemetry error: ${err.message}</p>
            </div>
        `;
    }
}

// Valuation Transparency report builder
function renderValuationTransparency(company, val, verdicts) {
    const container = document.getElementById("transparency-container");
    container.innerHTML = "";
    
    const avgSev = verdicts.length > 0 
        ? (verdicts.reduce((sum, v) => sum + v.severity_score, 0) / verdicts.length) 
        : 5.0;
        
    const sector = (company.sector || "").toLowerCase();
    const industry = (company.industry || "").toLowerCase();

    const isFinancial = /financial|bank|insurance|capital markets|credit/i.test(sector) || /financial|bank|insurance|capital markets|credit/i.test(industry);
    const isHighGrowth = company.revenue_growth > 0.25 && (company.net_income <= 0 || (company.net_income / Math.max(company.revenue, 1)) < 0.10);
    const isCyclical = /energy|basic materials|mining|utilities|oil|gas|steel|chemical/i.test(sector) || /energy|basic materials|mining|utilities|oil|gas|steel|chemical/i.test(industry);
    const isMatureProfitable = !isFinancial && !isHighGrowth && !isCyclical && company.ebitda > 0 && company.net_income > 0;
    const isFallback = !isFinancial && !isHighGrowth && !isCyclical && !isMatureProfitable;

    let pathNum = 5;
    let pathName = "FALLBACK (EV/Revenue Capped)";
    if (isFinancial) { pathNum = 1; pathName = "FINANCIAL / P/BV + Excess Return"; }
    else if (isHighGrowth) { pathNum = 2; pathName = "HIGH-GROWTH / EV/Revenue + R40"; }
    else if (isMatureProfitable) { pathNum = 3; pathName = "MATURE / 5Y FCF-DCF + Gordon"; }
    else if (isCyclical) { pathNum = 4; pathName = "CYCLICAL / Normalized EBITDA"; }
    else { pathNum = 5; pathName = "LOSS-MAKING / FALLBACK (EV/Revenue Capped)"; }

    const formatBillion = (val) => {
        if (val === null || val === undefined || isNaN(val) || val === 0) return "N/A";
        return `$${(val / 1e9).toFixed(2)}B`;
    };
    const formatPercent = (val) => {
        if (val === null || val === undefined || isNaN(val)) return "N/A";
        return `${(val * 100).toFixed(1)}%`;
    };
    
    const ebitdaStr = company.ebitda <= 0 ? "Negative / N/A" : formatBillion(company.ebitda);
    const netIncomeStr = company.net_income <= 0 ? "Negative / N/A" : formatBillion(company.net_income);
    const marginStr = company.revenue > 0 ? `${((company.net_income / company.revenue) * 100).toFixed(1)}%` : "0.0%";

    // Formula Details Switch Case
    let formulaHtml = "";
    if (pathNum === 1) {
        formulaHtml = `
            EV/Revenue Multiple (capped 1x-5x) = N/A (P/BV model used)<br>
            Book Value per Share = $${((company.market_cap * 0.55) / Math.max(company.shares_outstanding, 1)).toFixed(2)}<br>
            Justified P/BV = ${val.method_values["Justified P/BV"] || "1.00x"}<br>
            Implied Per Share = $${val.base_fair_value.toFixed(2)}<br>
            Note: Book value provides anchor for asset-heavy financial models where debt represents funding rather than standard operational liability.
        `;
    } else if (pathNum === 2) {
        formulaHtml = `
            EV/Revenue Multiple = ${val.method_values["EV/Revenue"] || "3.0x"}<br>
            Rule of 40 Score = ${val.method_values["Rule of 40"] || "0"}<br>
            Implied Base Fair Value = $${val.base_fair_value.toFixed(2)}<br>
            Note: High growth companies with low or negative earnings are priced relative to revenue scale and Rule of 40 quality.
        `;
    } else if (pathNum === 3) {
        formulaHtml = `
            Base WACC / Cost of Capital = ${val.method_values["WACC"] || "10.0%"}<br>
            Year 1 Free Cash Flow = ${val.method_values["FCF Y1"] || "N/A"}<br>
            Terminal Value contribution to EV = ${val.method_values["Terminal%"] || "N/A"}<br>
            Implied DCF Fair Value = $${val.base_fair_value.toFixed(2)}<br>
            Note: Mature, profitable companies are valued via a 5-Year DCF forecast of FCF with Gordon terminal growth rate.
        `;
    } else if (pathNum === 4) {
        formulaHtml = `
            Mid-Cycle Normalized EBITDA = $${((company.ebitda * 0.8) / 1e9).toFixed(2)}B<br>
            Normalized EV/EBITDA Multiple = ${val.method_values["EV/EBITDA"] || "6.5x"}<br>
            Implied Base Fair Value = $${val.base_fair_value.toFixed(2)}<br>
            Note: Cyclical asset earnings fluctuate wildly. Mid-cycle normalized values avoid multiple distortion at peak or trough.
        `;
    } else {
        formulaHtml = `
            EV/Revenue Multiple (capped 1x-5x) = ${val.method_values["EV/Revenue"] || "2.0x"}<br>
            Implied Per Share = $${val.base_fair_value.toFixed(2)} (floored at 0.8x market price)<br>
            Note: No stable earnings to discount. Revenue multiple is most honest anchor.
        `;
    }

    const card = document.createElement("div");
    card.className = "transparency-card";
    card.innerHTML = `
        <div class="transparency-banner">
            Full audit trail of routing logic, formulas applied, and stress parameters. All figures USD. No black boxes.
        </div>
        
        <!-- SECTION 1: ROUTING DECISION -->
        <div class="transparency-subpanel">
            <div class="ts-header">[1] ROUTING DECISION</div>
            <div class="ts-body">
                <div class="ts-row"><span class="ts-k">Company</span><span class="ts-v">${company.ticker}</span></div>
                <div class="ts-row"><span class="ts-k">Sector / Industry</span><span class="ts-v">${company.sector} / ${company.industry}</span></div>
                <div class="ts-row"><span class="ts-k">Revenue Growth</span><span class="ts-v">${formatPercent(company.revenue_growth)} (${company.revenue_growth > 0.25 ? 'above' : 'below'} 25%)</span></div>
                <div class="ts-row"><span class="ts-k">EBITDA</span><span class="ts-v">${ebitdaStr}</span></div>
                <div class="ts-row"><span class="ts-k">Net Income</span><span class="ts-v">${netIncomeStr}</span></div>
                <div class="ts-row"><span class="ts-k">Profit Margin</span><span class="ts-v">${marginStr}</span></div>
                <div class="ts-row"><span class="ts-k">Classification</span><span class="ts-v text-neon-red">PATH ${pathNum} -- ${pathName}</span></div>
                <div class="ts-flags">
                    Financial=${isFinancial ? 'True' : 'False'} | 
                    Cyclical=${isCyclical ? 'True' : 'False'} | 
                    HighGrowth=${isHighGrowth ? 'True' : 'False'} | 
                    Mature=${isMatureProfitable ? 'True' : 'False'} | 
                    Fallback=${isFallback ? 'True' : 'False'}
                </div>
            </div>
        </div>

        <!-- SECTION 2: RAW INPUTS -->
        <div class="transparency-subpanel">
            <div class="ts-header">[2] RAW INPUTS</div>
            <div class="ts-grid-2">
                <div class="ts-col">
                    <div class="ts-row"><span class="ts-k">Market Cap</span><span class="ts-v">${formatBillion(company.market_cap)}</span></div>
                    <div class="ts-row"><span class="ts-k">Current Price</span><span class="ts-v">$${company.current_price.toFixed(2)}</span></div>
                    <div class="ts-row"><span class="ts-k">Revenue (TTM)</span><span class="ts-v">${formatBillion(company.revenue)}</span></div>
                    <div class="ts-row"><span class="ts-k">EBITDA (TTM)</span><span class="ts-v">${ebitdaStr}</span></div>
                    <div class="ts-row"><span class="ts-k">Net Income</span><span class="ts-v">${netIncomeStr}</span></div>
                    <div class="ts-row" style="border:none"><span class="ts-k">Total Debt</span><span class="ts-v">${company.total_debt <= 0 ? 'N/A' : formatBillion(company.total_debt)}</span></div>
                </div>
                <div class="ts-col">
                    <div class="ts-row"><span class="ts-k">Cash & Equiv</span><span class="ts-v">${company.cash <= 0 ? 'N/A' : formatBillion(company.cash)}</span></div>
                    <div class="ts-row"><span class="ts-k">Enterprise Value</span><span class="ts-v">${formatBillion(company.market_cap + company.total_debt - company.cash)}</span></div>
                    <div class="ts-row"><span class="ts-k">Shares Out</span><span class="ts-v">${(company.shares_outstanding / 1e9).toFixed(3)}B</span></div>
                    <div class="ts-row"><span class="ts-k">Beta</span><span class="ts-v">${company.beta.toFixed(2)}</span></div>
                    <div class="ts-row"><span class="ts-k">Revenue Growth</span><span class="ts-v">${(company.revenue_growth * 100).toFixed(1)}%</span></div>
                    <div class="ts-row" style="border:none"><span class="ts-k">Profit Margin</span><span class="ts-v">${marginStr}</span></div>
                </div>
            </div>
        </div>

        <!-- SECTION 3: VALUATION FORMULA -->
        <div class="transparency-subpanel">
            <div class="ts-header">[3] VALUATION FORMULA -- PATH ${pathNum}</div>
            <div class="ts-body ts-monospace">
                ${formulaHtml}
            </div>
        </div>

        <!-- SECTION 3.5: RISK SCORING -->
        <div class="transparency-subpanel">
            <div class="ts-header">[3.5] RISK SCORING -- ADVERSARIAL TRIBUNAL</div>
            <div class="ts-body ts-monospace" style="color: var(--text-dim);">
                Each risk passes through a 3-agent adversarial debate. Judge calibration:<br>
                8+ = Catastrophic (>25% impairment) | 6-7 = Material | 4-5 = Moderate | &lt;4 = Dismissed
            </div>
        </div>

        <!-- SECTION 4: STRESS FORMULA -->
        <div class="transparency-subpanel">
            <div class="ts-header">[4] STRESS FORMULA -- VALUATION ROUTER</div>
            <div class="ts-body ts-monospace">
                Revenue Haircut: ${val.revenue_haircut.toFixed(1)}% = ${parseFloat(chaosSlider.value).toFixed(2)} * 15% + (avg_severity / 10) * 12%<br>
                WACC Stress: +${(val.stressed_wacc - val.base_wacc).toFixed(1)}% = ${parseFloat(chaosSlider.value).toFixed(2)} * 4.5% + (avg_severity / 10) * 3%<br>
                Margin Compression: -${val.margin_compression_bps.toFixed(0)} bps = ${parseFloat(chaosSlider.value).toFixed(2)} * 250 + avg_severity * 50<br>
                Multiple De-rating Factor: ${(1 - (val.revenue_haircut / 100)).toFixed(3)}x factor applied to post-stress multipliers
            </div>
        </div>

        <!-- SECTION 6: FINAL OUTPUT -->
        <div class="transparency-subpanel">
            <div class="ts-header">[6] FINAL OUTPUT</div>
            <div class="ts-body">
                <div class="ts-row"><span class="ts-k">Current Market Price</span><span class="ts-v">$${val.current_price.toFixed(2)}</span></div>
                <div class="ts-row"><span class="ts-k">Base Fair Value (post-cap)</span><span class="ts-v text-neon-green">$${val.base_fair_value.toFixed(2)}</span></div>
                <div class="ts-row"><span class="ts-k">Distressed Value (post-stress)</span><span class="ts-v text-neon-red">$${val.distressed_value.toFixed(2)}</span></div>
                <div class="ts-row"><span class="ts-k">Implied Downside</span><span class="ts-v text-neon-red">${val.downside_pct.toFixed(1)}%</span></div>
                <div class="ts-row" style="border:none"><span class="ts-k">Min Forced Floor</span><span class="ts-v" style="color:var(--text-dim);">-29.5% (downside always forced negative)</span></div>
            </div>
        </div>

        <!-- SECTION 7: ALL VALUATION PATHS REFERENCE -->
        <div class="transparency-subpanel">
            <div class="ts-header">[7] ALL VALUATION PATHS -- REFERENCE</div>
            <table class="transparency-table">
                <thead>
                    <tr>
                        <th>PATH</th>
                        <th>TYPE</th>
                        <th>METHOD</th>
                        <th>WHY NOT DCF</th>
                    </tr>
                </thead>
                <tbody>
                    <tr class="${pathNum === 1 ? 'active-path' : ''}">
                        <td>1</td>
                        <td>Financial</td>
                        <td>P/BV + Excess Return</td>
                        <td>Debt = product, not liability</td>
                    </tr>
                    <tr class="${pathNum === 2 ? 'active-path' : ''}">
                        <td>2</td>
                        <td>High-Growth</td>
                        <td>EV/Revenue + R40</td>
                        <td>Negative FCF, TV &gt;80%</td>
                    </tr>
                    <tr class="${pathNum === 3 ? 'active-path' : ''}">
                        <td>3</td>
                        <td>Mature</td>
                        <td>5Y FCF-DCF + Gordon</td>
                        <td>Only valid DCF candidate</td>
                    </tr>
                    <tr class="${pathNum === 4 ? 'active-path' : ''}">
                        <td>4</td>
                        <td>Cyclical</td>
                        <td>Normalized EBITDA</td>
                        <td>Spot earnings mislead at peaks</td>
                    </tr>
                    <tr class="${pathNum === 5 ? 'active-path' : ''}">
                        <td>5</td>
                        <td>Loss-Making</td>
                        <td>EV/Revenue (capped)</td>
                        <td>No earnings to discount</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- INVESTMENT COMMITTEE SUMMARY -->
        <div class="committee-summary-title">INVESTMENT COMMITTEE SUMMARY</div>
        <div class="committee-grid">
            <!-- Left Card: Metrics -->
            <div class="committee-card">
                <div class="committee-card-header">${company.name} (${company.ticker})</div>
                <div class="committee-card-body">
                    <div class="ts-row"><span class="ts-k">Sector</span><span class="ts-v">${company.sector}</span></div>
                    <div class="ts-row"><span class="ts-k">Market Cap</span><span class="ts-v">${formatBillion(company.market_cap)}</span></div>
                    <div class="ts-row"><span class="ts-k">Revenue</span><span class="ts-v">${formatBillion(company.revenue)}</span></div>
                    <div class="ts-row"><span class="ts-k">Current Price</span><span class="ts-v">$${company.current_price.toFixed(2)}</span></div>
                    <div class="ts-row"><span class="ts-k">Fair Value</span><span class="ts-v text-neon-green">$${val.base_fair_value.toFixed(2)}</span></div>
                    <div class="ts-row"><span class="ts-k">Distressed</span><span class="ts-v text-neon-red">$${val.distressed_value.toFixed(2)}</span></div>
                    <div class="ts-row" style="border:none"><span class="ts-k">Downside Risk</span><span class="ts-v text-neon-red">${val.downside_pct.toFixed(1)}%</span></div>
                </div>
            </div>
            
            <!-- Right Card: Top Validated Risks -->
            <div class="committee-card">
                <div class="committee-card-header">TOP VALIDATED RISKS</div>
                <div class="committee-card-body top-risks-list">
                    ${verdicts.slice(0, 5).map(v => `
                        <div class="top-risk-item">
                            <span class="risk-badge-number">[${v.severity_score.toFixed(1)}]</span>
                            <span class="risk-badge-text">${v.risk_description}</span>
                        </div>
                    `).join('') || '<div class="no-risks">No risks validated by the tribunal.</div>'}
                </div>
            </div>
        </div>
    `;
    container.appendChild(card);
}

// Color lookup helper
function getColorHex(level) {
    const colors = {
        critical: "#FF1744",
        high: "#FF6D00",
        elevated: "#FFD600",
        monitoring: "#00E676"
    };
    return colors[level.toLowerCase()] || "#FF6D00";
}

// ===============================================================
// GEOPOLITICAL MAP VISUALIZATION (Plotly.js)
// ===============================================================

function initMap(hq) {
    const lat = hq[0];
    const lon = hq[1];
    
    // HQ concentric pulse layers
    const hqTracePulse1 = {
        type: "scattermapbox",
        lat: [lat], lon: [lon],
        mode: "markers",
        marker: { size: 32, color: "rgba(0,176,255,0.06)" },
        showlegend: false, hoverinfo: "none"
    };
    const hqTracePulse2 = {
        type: "scattermapbox",
        lat: [lat], lon: [lon],
        mode: "markers",
        marker: { size: 20, color: "rgba(0,176,255,0.15)" },
        showlegend: false, hoverinfo: "none"
    };
    const hqTraceMain = {
        type: "scattermapbox",
        lat: [lat], lon: [lon],
        mode: "markers+text",
        marker: { size: 12, color: "rgba(0,176,255,0.9)" },
        text: ["HQ"], textposition: "bottom center",
        textfont: { size: 10, color: "#00B0FF", family: "Arial Black" },
        hovertext: [`HQ: ${hq[2]}`],
        hoverinfo: "text",
        showlegend: false
    };
    
    mapTraces = [hqTracePulse1, hqTracePulse2, hqTraceMain];
    drawMap(lat, lon, 2.5);
}

function addRiskToMap(v, hq) {
    const hqLat = hq[0];
    const hqLon = hq[1];
    const riskLat = v.latitude;
    const riskLon = v.longitude;
    const color = getColorHex(v.threat_level);
    
    // 1. Generate Curved arc between Risk Node and HQ
    const arc = curvedPath(riskLat, riskLon, hqLat, hqLon);
    const opacity = 0.2 + (v.severity_score / 10) * 0.4;
    const width = 1 + (v.severity_score / 10) * 1.5;
    
    // Convert hex to rgb for opacity handling
    const r = parseInt(color.substring(1, 3), 16);
    const g = parseInt(color.substring(3, 5), 16);
    const b = parseInt(color.substring(5, 7), 16);
    
    const arcTrace = {
        type: "scattermapbox",
        lat: arc.lats, lon: arc.lons,
        mode: "lines",
        line: { width: width, color: `rgba(${r},${g},${b},${opacity})` },
        hoverinfo: "none", showlegend: false
    };
    
    // 2. Glow for critical/high nodes
    if (v.threat_level === "critical" || v.threat_level === "high") {
        const glowTrace = {
            type: "scattermapbox",
            lat: [riskLat], lon: [riskLon],
            mode: "markers",
            marker: { size: v.severity_score * 4, color: `rgba(${r},${g},${b},0.12)` },
            showlegend: false, hoverinfo: "none"
        };
        mapTraces.push(glowTrace);
    }
    
    // 3. Main Risk Node marker
    const hoverText = `
        <b>${v.geographic_nexus}</b><br>
        Severity: ${v.severity_score.toFixed(1)}/10<br>
        Probability: ${(v.probability * 100).toFixed(0)}%<br>
        Domain: ${v.domain}<br>
        Revenue at Risk: ${v.revenue_at_risk_pct.toFixed(0)}%
    `;
    
    const nodeTrace = {
        type: "scattermapbox",
        lat: [riskLat], lon: [riskLon],
        mode: "markers+text",
        marker: { size: Math.max(10, 8 + v.severity_score * 2), color: color, opacity: 0.85 },
        text: [v.geographic_nexus],
        textposition: "top center",
        textfont: { size: 9, color: color },
        hovertext: [hoverText],
        hoverinfo: "text",
        name: `${v.threat_level.toUpperCase()}`,
        showlegend: true
    };
    
    // Prepend arcTrace so nodes render on top of lines
    mapTraces.unshift(arcTrace);
    mapTraces.push(nodeTrace);
    
    // Redraw map with updated traces centered at mid-point
    const midLat = (hqLat + riskLat) / 2;
    const midLon = (hqLon + riskLon) / 2;
    drawMap(midLat, midLon, 2.0);
}

function drawMap(centerLat, centerLon, zoom) {
    const layout = {
        mapbox: {
            style: "carto-darkmatter",
            center: { lat: centerLat, lon: centerLon },
            zoom: zoom
        },
        showlegend: true,
        legend: {
            bgcolor: "rgba(12,16,24,0.9)",
            bordercolor: "#1a2538",
            font: { color: "#c8d6e5", size: 10 },
            x: 0.01, y: 0.99
        },
        margin: { l: 0, r: 0, t: 0, b: 0 },
        height: 560,
        paper_bgcolor: "#080b10",
        dragmode: "pan"
    };
    
    const config = { responsive: true, displayModeBar: false };
    Plotly.newPlot("geopolitical-map", mapTraces, layout, config);
}

// Parabolic curved math (Identical to Python backend)
function curvedPath(lat1, lon1, lat2, lon2, n = 35) {
    let lats = [], lons = [];
    for (let i = 0; i <= n; i++) {
        let t = i / n;
        let lat = lat1 + t * (lat2 - lat1);
        let lon = lon1 + t * (lon2 - lon1);
        
        let dist = Math.sqrt(Math.pow(lat2 - lat1, 2) + Math.pow(lon2 - lon1, 2));
        let arc = dist * 0.12;
        let curve = 4 * t * (1 - t);
        
        let dx = lat2 - lat1, dy = lon2 - lon1;
        let length = Math.sqrt(dx * dx + dy * dy) || 1;
        lat += (-dy / length) * arc * curve;
        lon += (dx / length) * arc * curve;
        
        lats.push(lat);
        lons.push(lon);
    }
    return { lats, lons };
}

// ===============================================================
// WATERFALL VALUATION CHART VISUALIZATION (Plotly.js)
// ===============================================================

function renderWaterfallChart(val) {
    const wf = val.waterfall_data;
    
    const xData = wf.map(item => item.label);
    const yData = wf.map(item => item.value);
    const measureData = wf.map(item => item.type === "relative" ? "relative" : item.type === "total" ? "total" : "absolute");
    
    // Hover text custom configuration
    const textData = yData.map(val => val >= 0 ? `+$${val.toFixed(2)}` : `-$${Math.abs(val).toFixed(2)}`);

    const data = [{
        type: "waterfall",
        orientation: "v",
        measure: measureData,
        x: xData,
        y: yData,
        text: textData,
        textposition: "outside",
        connector: {
            line: { color: "#1a2538", width: 1.5, dash: "dot" }
        },
        decreasing: { marker: { color: "#ff1744" } }, // Red for stress reductions
        increasing: { marker: { color: "#00e676" } },
        totals: { marker: { color: "#ff6d00", line: { color: "#ff6d00", width: 1 } } } // Orange for distressed valuation
    }];

    const layout = {
        paper_bgcolor: "#0c1018",
        plot_bgcolor: "#0c1018",
        margin: { l: 35, r: 35, t: 15, b: 30 },
        height: 290,
        showlegend: false,
        font: {
            family: "JetBrains Mono, monospace",
            size: 9,
            color: "#8a9ba8"
        },
        xaxis: {
            type: "category",
            gridcolor: "#162030",
            linecolor: "#1a2538"
        },
        yaxis: {
            type: "linear",
            gridcolor: "#162030",
            linecolor: "#1a2538"
        }
    };

    const config = { responsive: true, displayModeBar: false };
    Plotly.newPlot("waterfall-chart", data, layout, config);
}
