/**
 * AutoFarm CoC Dashboard Controller
 */

let pollInterval = null;
let frameRefreshInterval = null;

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  fetchLogs();
  loadConfigIntoUI();

  // Polling timers
  pollInterval = setInterval(() => {
    fetchStatus();
    fetchLogs();
  }, 1200);

  frameRefreshInterval = setInterval(() => {
    refreshFrame();
  }, 1800);
});

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

// Refresh viewport screen frame
function refreshFrame() {
  const img = document.getElementById("live-screen-img");
  img.src = "/api/frame?t=" + new Date().getTime();
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
