/**
 * AutoFarm CoC Dashboard Controller
 */

let pollInterval = null;

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  fetchLogs();
  fetchDetections();
  loadConfigIntoUI();
  initLiveVideoStream();

  // Metrics, detections and logs polling (lightweight JSON only)
  pollInterval = setInterval(() => {
    fetchStatus();
    fetchLogs();
    fetchDetections();
  }, 1000);
});

// Setup true real-time video stream (WebSocket binary stream with MJPEG & fast-fetch fallbacks)
let activeStreamWs = null;
let currentBlobUrl = null;
let isFetchingFastFrame = false;
let isFrameRendering = false;

function initLiveVideoStream() {
  const img = document.getElementById("live-screen-img");
  if (!img) return;

  // 1. Primary: Ultra-low-latency WebSocket binary stream
  try {
    if (activeStreamWs) {
      activeStreamWs.close();
      activeStreamWs = null;
    }
    const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${location.host}/ws/stream`;
    activeStreamWs = new WebSocket(wsUrl);
    activeStreamWs.binaryType = "blob";

    activeStreamWs.onopen = () => {
      console.log("[AutoFarm Stream] WebSocket live stream connected (30+ FPS)!");
      const pill = document.getElementById("overlay-status-pill");
      if (pill) pill.textContent = "Live Stream: Connected (30 FPS)";
    };

    activeStreamWs.onmessage = (event) => {
      if (event.data instanceof Blob) {
        if (isFrameRendering) return; // Drop frame if previous is still rendering (prevents queue backup)
        isFrameRendering = true;
        const newUrl = URL.createObjectURL(event.data);
        const oldUrl = currentBlobUrl;
        img.onload = () => {
          if (oldUrl) {
            URL.revokeObjectURL(oldUrl);
          }
          isFrameRendering = false;
        };
        img.onerror = () => {
          if (oldUrl) URL.revokeObjectURL(oldUrl);
          isFrameRendering = false;
        };
        currentBlobUrl = newUrl;
        img.src = newUrl;
      }
    };

    activeStreamWs.onerror = () => {
      console.warn("[AutoFarm Stream] WebSocket unavailable, falling back to MJPEG stream...");
      fallbackToMjpeg(img);
    };

    activeStreamWs.onclose = (evt) => {
      if (evt.code !== 1000) {
        setTimeout(initLiveVideoStream, 2000);
      }
    };
  } catch (e) {
    fallbackToMjpeg(img);
  }
}

function fallbackToMjpeg(img) {
  img.src = "/api/stream";
  img.onerror = () => {
    startFastFetchLoop(img);
  };
}

async function startFastFetchLoop(img) {
  if (isFetchingFastFrame) return;
  isFetchingFastFrame = true;
  try {
    const res = await fetch("/api/frame?t=" + Date.now());
    if (res.ok) {
      const blob = await res.blob();
      const newUrl = URL.createObjectURL(blob);
      img.src = newUrl;
      if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
      currentBlobUrl = newUrl;
    }
  } catch (e) {
  } finally {
    isFetchingFastFrame = false;
    setTimeout(() => startFastFetchLoop(img), 40); // ~25 FPS
  }
}

// Format integers with thousand separators
function formatNumber(num) {
  if (num === undefined || num === null) return "0";
  return Number(num).toLocaleString();
}

// Fetch bot status and session metrics
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    // Update Metrics
    document.getElementById("stat-gold").textContent = formatNumber(data.gold_looted);
    document.getElementById("stat-elixir").textContent = formatNumber(data.elixir_looted);
    document.getElementById("stat-dark").textContent = formatNumber(data.dark_looted);
    document.getElementById("stat-walls").textContent = formatNumber(data.walls_upgraded);

    // Update Action & Telemetry
    document.getElementById("current-action-label").textContent = data.current_action || "Idle";
    document.getElementById("overlay-status-pill").textContent = `Action: ${data.current_action || "Idle"}`;
    document.getElementById("meta-scanned").textContent = formatNumber(data.bases_scanned);
    document.getElementById("meta-attacks").textContent = formatNumber(data.attacks_completed);
    document.getElementById("meta-last-loot").textContent = data.last_loot || "None";

    // Update Device Label
    const devLabel = document.getElementById("device-label");
    if (data.mode === "mock") {
      devLabel.textContent = "Simulation Mode (Mock)";
    } else {
      devLabel.textContent = "Android Device Connected";
    }

    // Update Safety Shield Badge
    const safetyBadge = document.getElementById("safety-shield-badge");
    const safetyLabel = document.getElementById("safety-label");
    if (safetyBadge && safetyLabel) {
      if (data.is_game_foreground === false) {
        safetyLabel.textContent = "🛡️ CoC Minimized (Safety Lock)";
        safetyBadge.style.background = "rgba(239, 68, 68, 0.15)";
        safetyBadge.style.color = "#f87171";
        safetyBadge.style.borderColor = "rgba(239, 68, 68, 0.3)";
      } else if (data.touch_enabled) {
        safetyLabel.textContent = "⚠️ Touch Active (Autonomous)";
        safetyBadge.style.background = "rgba(245, 158, 11, 0.15)";
        safetyBadge.style.color = "#fbbf24";
        safetyBadge.style.borderColor = "rgba(245, 158, 11, 0.3)";
      } else {
        safetyLabel.textContent = "🛡️ Touch Disabled (Safe)";
        safetyBadge.style.background = "rgba(16, 185, 129, 0.15)";
        safetyBadge.style.color = "#10b981";
        safetyBadge.style.borderColor = "rgba(16, 185, 129, 0.3)";
      }
    }

    // Update Quick Toggle Buttons
    const btnBoxes = document.getElementById("btn-toggle-boxes");
    if (btnBoxes) {
      btnBoxes.textContent = data.detection_overlay ? "👁️ Detection Boxes: ON" : "👁️ Detection Boxes: OFF";
      btnBoxes.style.color = data.detection_overlay ? "#38bdf8" : "#94a3b8";
    }

    const btnAuto = document.getElementById("btn-toggle-auto");
    if (btnAuto) {
      btnAuto.textContent = data.automation_enabled ? "⚔️ Automation: ACTIVE" : "🛡️ Touch Inputs: DISABLED";
      btnAuto.style.color = data.automation_enabled ? "#fbbf24" : "#10b981";
      btnAuto.style.borderColor = data.automation_enabled ? "rgba(245, 158, 11, 0.4)" : "rgba(16, 185, 129, 0.4)";
    }

    // Update Status Pill
    const badge = document.getElementById("status-badge");
    const statusLabel = document.getElementById("status-label");
    const btnStart = document.getElementById("btn-start");
    const btnPause = document.getElementById("btn-pause");
    const btnStop = document.getElementById("btn-stop");

    badge.className = "badge badge-status " + (data.status || "stopped").toLowerCase();
    statusLabel.textContent = data.status || "STOPPED";

    if (data.status === "RUNNING") {
      btnStart.disabled = true;
      btnPause.disabled = false;
      btnStop.disabled = false;
    } else if (data.status === "PAUSED") {
      btnStart.disabled = false;
      btnPause.disabled = true;
      btnStop.disabled = false;
    } else {
      btnStart.disabled = false;
      btnPause.disabled = true;
      btnStop.disabled = true;
    }
  } catch (err) {
    console.error("Status polling failed:", err);
  }
}

// Fetch terminal logs
async function fetchLogs() {
  try {
    const res = await fetch("/api/logs");
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById("terminal-logs");
    
    if (data.logs && data.logs.length > 0) {
      container.innerHTML = data.logs
        .map(entry => {
          let cls = "log-entry";
          if (entry.includes("[Attack]")) cls += " log-attack";
          if (entry.includes("[Walls]")) cls += " log-wall";
          if (entry.includes("[Trainer]")) cls += " log-trainer";
          return `<div class="${cls}">${escapeHtml(entry)}</div>`;
        })
        .join("");
      container.scrollTop = container.scrollHeight;
    }
  } catch (err) {
    console.error("Logs fetch failed:", err);
  }
}

// Reconnect / refresh live video stream
function refreshFrame() {
  initLiveVideoStream();
  fetchDetections();
}

// Fetch CV Perception / Identified Elements (Phase 1)
async function fetchDetections() {
  try {
    const res = await fetch("/api/detections");
    if (!res.ok) return;
    const data = await res.json();

    const stateEl = document.getElementById("current-screen-state");
    if (stateEl) {
      stateEl.textContent = `State: ${(data.state || "UNKNOWN").toUpperCase()}`;
    }

    const badgeEl = document.getElementById("detected-count-badge");
    if (badgeEl) {
      badgeEl.textContent = `${data.count || (data.entities ? data.entities.length : 0)} Identified`;
    }

    const container = document.getElementById("detections-container");
    if (!container) return;

    if (!data.entities || data.entities.length === 0) {
      container.innerHTML = `<div style="color: #64748b; font-size: 13px; grid-column: 1 / -1; padding: 12px 0;">No game elements recognized in current view. Open Clash of Clans on phone.</div>`;
      return;
    }

    container.innerHTML = data.entities
      .map(ent => {
        const cat = ent.category || "hud";
        const confPct = Math.round((ent.confidence !== undefined ? ent.confidence : 1.0) * 100);
        const bboxStr = ent.bbox ? `[${ent.bbox.join(", ")}]` : "N/A";
        return `
          <div class="detection-item">
            <div class="detection-header">
              <span class="detection-category cat-${cat}">${cat}</span>
              <span class="detection-conf">${confPct}%</span>
            </div>
            <div class="detection-title">${escapeHtml(ent.label || ent.id || "Element")}</div>
            <div class="detection-coords">${bboxStr}</div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    console.error("Detections fetch failed:", err);
  }
}

// Toggle HUD Bounding Boxes on/off
async function toggleDetectionBoxes() {
  try {
    const res = await fetch("/api/overlay/toggle", { method: "POST" });
    const data = await res.json();
    fetchStatus();
    fetchDetections();
  } catch (err) {
    alert("Failed to toggle detection overlay: " + err);
  }
}

// Force Connected Android Device into Landscape orientation via ADB
async function forceLandscape() {
  const btn = document.getElementById("btn-force-landscape");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/device/force_landscape", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      refreshFrame();
      fetchStatus();
    } else {
      alert("Could not force landscape: " + (data.error || "Device not connected. Connect phone via ADB."));
    }
  } catch (err) {
    alert("Force landscape request failed: " + err);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Toggle Autonomous Attacks & Touch Inputs
async function toggleAutomationMode() {
  const currentText = document.getElementById("btn-toggle-auto")?.textContent || "";
  const isEnabling = currentText.includes("DISABLED");
  if (isEnabling) {
    const ok = confirm("⚠️ SAFETY CONFIRMATION:\n\nDo you want to ENABLE autonomous touch inputs & attacking?\n\n(AutoFarm will only tap when Clash of Clans is foregrounded, and never touch other apps).");
    if (!ok) return;
  }
  try {
    await fetch("/api/automation/toggle", { method: "POST" });
    fetchStatus();
  } catch (err) {
    alert("Failed to toggle automation: " + err);
  }
}

// Start Bot
async function startBot() {
  try {
    await fetch("/api/start", { method: "POST" });
    fetchStatus();
  } catch (err) {
    alert("Failed to start bot: " + err);
  }
}

// Pause Bot
async function pauseBot() {
  try {
    await fetch("/api/pause", { method: "POST" });
    fetchStatus();
  } catch (err) {
    alert("Failed to pause bot: " + err);
  }
}

// Stop Bot
async function stopBot() {
  try {
    await fetch("/api/stop", { method: "POST" });
    fetchStatus();
  } catch (err) {
    alert("Failed to stop bot: " + err);
  }
}

// Trigger Wall Upgrade Immediately
async function triggerWallUpgrade() {
  try {
    const res = await fetch("/api/action/walls", { method: "POST" });
    const data = await res.json();
    alert(`Wall upgrade triggered! Upgraded ${data.upgraded} segments.`);
    fetchStatus();
  } catch (err) {
    alert("Wall upgrade action failed: " + err);
  }
}

// Trigger Army Train Immediately
async function triggerTrainArmy() {
  try {
    await fetch("/api/action/train", { method: "POST" });
    alert("Army Quick-Train command sent!");
  } catch (err) {
    alert("Train action failed: " + err);
  }
}

// Load config into form
async function loadConfigIntoUI() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const cfg = await res.json();

    if (cfg.farming) {
      document.getElementById("input-min-gold").value = cfg.farming.min_gold || 450000;
      document.getElementById("input-min-elixir").value = cfg.farming.min_elixir || 450000;
      document.getElementById("input-min-de").value = cfg.farming.min_dark_elixir || 3500;
    }
    if (cfg.walls) {
      document.getElementById("input-reserve-gold").value = cfg.walls.reserve_gold || 1500000;
    }
    if (cfg.attack) {
      document.getElementById("select-strategy").value = cfg.attack.strategy || "collector_snipe";
      document.getElementById("check-early-surrender").checked = cfg.attack.early_surrender !== false;
    }
  } catch (err) {
    console.error("Config fetch error:", err);
  }
}

// Save config from form
async function saveConfig() {
  const payload = {
    min_gold: parseInt(document.getElementById("input-min-gold").value),
    min_elixir: parseInt(document.getElementById("input-min-elixir").value),
    min_dark_elixir: parseInt(document.getElementById("input-min-de").value),
    reserve_gold: parseInt(document.getElementById("input-reserve-gold").value),
    preferred_strategy: document.getElementById("select-strategy").value,
    early_surrender: document.getElementById("check-early-surrender").checked,
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const msg = document.getElementById("save-status-msg");
    if (res.ok) {
      msg.textContent = "✓ Settings applied successfully!";
      setTimeout(() => { msg.textContent = ""; }, 3000);
    } else {
      msg.textContent = "Error saving settings.";
    }
  } catch (err) {
    alert("Failed to save configuration: " + err);
  }
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, m => map[m]);
}
