let controller = null;
let historyData = [];

function $(id) {
    return document.getElementById(id);
}

function modeLabel(mode) {
    if (mode === "bidi") return "双向流式";
    if (mode === "bidi_async") return "异步双向";
    return "单向流式";
}

function modeDesc(mode) {
    if (mode === "bidi_async") return "异步双向：边说边返还，长句连续";
    return "单向流式：延迟低，短句快返";
}

function updateStatus() {
    if (!controller) return;
    const statusText = controller.statusText;
    const pill = $("status-pill");
    const label = $("status-text");
    label.textContent = statusText || "未连接";
    pill.textContent = statusText || "未连接";
    const connected = controller.isConnected;
    const busy = controller.isSending || controller.isConnecting;
    pill.style.borderColor = connected ? "rgba(125,211,252,0.5)" : "rgba(255,255,255,0.08)";
    pill.style.color = connected ? "#7dd3fc" : "#f4f4f5";
    pill.style.background = busy
        ? "rgba(255,157,0,0.12)"
        : connected
          ? "rgba(125,211,252,0.12)"
          : "rgba(255,255,255,0.05)";
    $("mode-text").textContent = modeLabel(controller.mode);
    $("mode-desc").textContent = modeDesc(controller.mode);
    $("mode-tip").textContent = modeDesc(controller.mode);
}

function updateStats() {
    if (!controller) return;
    $("stat-minutes").textContent = controller.statsDurationText || controller.statsMinutes;
    $("stat-chars").textContent = controller.statsChars;
    $("stat-speed").textContent = controller.statsSpeed;
}

function updateButton() {
    if (!controller) return;
    const btn = $("toggle-btn");
    const busy = controller.isSending || controller.isConnecting;
    btn.textContent = busy ? "停止识别" : "开始识别";
    btn.classList.toggle("danger", busy);
}

function updateForms() {
    if (!controller) return;
    $("app-id").value = controller.appId || "";
    $("access-token").value = controller.accessToken || "";
    $("use-gzip").checked = !!controller.useGzip;

    document.querySelectorAll(".seg-btn[data-mode]").forEach((btn) => {
        if (btn.dataset.target) return;
        const active = btn.dataset.mode === controller.mode;
        btn.classList.toggle("active", active);
    });

    $("primary-keys").value = controller.primaryHotkeyText || "";
    $("primary-enabled").checked = !!controller.primaryHotkeyEnabled;
    setSegActive("primary", controller.primaryHotkeyMode);

    $("freehand-keys").value = controller.freehandHotkeyText || "";
    $("freehand-enabled").checked = !!controller.freehandHotkeyEnabled;
    setSegActive("freehand", controller.freehandHotkeyMode);

    $("mouse-enabled").checked = !!controller.mouseModeEnabled;
    setSegActive("mouse", controller.mouseHotkeyMode);
}

function setSegActive(target, mode) {
    document.querySelectorAll(`.seg-btn[data-target='${target}']`).forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.mode === mode);
    });
}

function updateTutorial() {
    if (!controller) return;
    $("tutorial-hold").textContent = controller.tutorialHoldText || "按住快捷键说话";
    $("tutorial-toggle").textContent = controller.tutorialToggleText || "按下开始/再次按下结束";
    $("tutorial-mouse").textContent = controller.tutorialMouseText || "支持鼠标中键语音";
}

function splitTimestamp(ts) {
    const raw = (ts || "").trim();
    if (!raw) return { time: "--:--:--", date: "" };
    const parts = raw.split(" ");
    if (parts.length < 2) return { time: raw, date: "" };
    return { date: parts[0], time: parts.slice(1).join(" ") };
}

function renderHistory(list) {
    historyData = Array.isArray(list) ? list.slice() : [];
    const container = $("history-list");
    container.innerHTML = "";
    historyData.forEach((item, idx) => {
        const row = document.createElement("div");
        row.className = "history-row";
        if (item.partial) row.classList.add("partial");

        const time = document.createElement("div");
        time.className = "history-time";
        const ts = splitTimestamp(item.timestamp);
        const timeMain = document.createElement("div");
        timeMain.className = "history-time-main";
        timeMain.textContent = ts.time || "--:--:--";
        time.appendChild(timeMain);
        if (ts.date) {
            const timeDate = document.createElement("div");
            timeDate.className = "history-time-date";
            timeDate.textContent = ts.date;
            time.appendChild(timeDate);
        }

        const text = document.createElement("div");
        text.className = "history-text";
        text.contentEditable = "true";
        text.textContent = item.text || "";
        row.title = item.text || "";
        text.addEventListener("blur", () => {
            const val = text.textContent.trim();
            historyData[idx].text = val;
            controller && controller.updateHistoryText(idx, val);
        });

        row.addEventListener("click", (e) => {
            if (e.target === text) return;
            copyText(item.text);
        });

        row.appendChild(time);
        row.appendChild(text);
        container.appendChild(row);
    });
}

function insertHistoryRow(row, item) {
    if (typeof row !== "number") return;
    historyData.splice(row, 0, item);
    renderHistory(historyData);
}

function updateHistoryRow(row, item) {
    if (typeof row !== "number") return;
    if (row < 0 || row >= historyData.length) return;
    historyData[row] = item;
    renderHistory(historyData);
}

function removeHistoryRow(row) {
    if (typeof row !== "number") return;
    historyData.splice(row, 1);
    renderHistory(historyData);
}

async function copyText(text) {
    if (!text) return;
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
        } else if (controller && controller.copyText) {
            controller.copyText(text);
        }
    } catch (err) {
        if (controller && controller.copyText) controller.copyText(text);
    }
}

function bindInputs() {
    $("toggle-btn").addEventListener("click", () => controller && controller.toggleRecognition());
    $("clear-history").addEventListener("click", () => controller && controller.clearHistory());

    $("app-id").addEventListener("change", (e) => controller && (controller.appId = e.target.value));
    $("access-token").addEventListener("change", (e) => controller && (controller.accessToken = e.target.value));
    $("use-gzip").addEventListener("change", (e) => controller && (controller.useGzip = e.target.checked));

    document.querySelectorAll(".seg-btn[data-mode]").forEach((btn) => {
        if (btn.dataset.target) return;
        btn.addEventListener("click", () => {
            const mode = btn.dataset.mode;
            document.querySelectorAll(".seg-btn[data-mode]").forEach((b) => {
                if (!b.dataset.target) b.classList.remove("active");
            });
            btn.classList.add("active");
            controller && (controller.mode = mode);
            updateStatus();
        });
    });

    $("primary-enabled").addEventListener("change", (e) => controller && (controller.primaryHotkeyEnabled = e.target.checked));
    $("freehand-enabled").addEventListener("change", (e) => controller && (controller.freehandHotkeyEnabled = e.target.checked));
    $("mouse-enabled").addEventListener("change", (e) => controller && (controller.mouseModeEnabled = e.target.checked));

    document.querySelectorAll(".seg-btn[data-target]").forEach((btn) => {
        if (!btn.dataset.target) return;
        btn.addEventListener("click", () => {
            const target = btn.dataset.target;
            const mode = btn.dataset.mode;
            document.querySelectorAll(`.seg-btn[data-target='${target}']`).forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            if (!controller) return;
            if (target === "primary") controller.primaryHotkeyMode = mode;
            if (target === "freehand") controller.freehandHotkeyMode = mode;
            if (target === "mouse") controller.mouseHotkeyMode = mode;
        });
    });

    document.querySelectorAll(".capture-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            if (!controller) return;
            document.querySelectorAll(".capture-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            controller.startHotkeyCapture(btn.dataset.target);
        });
    });
}

function bindSignals() {
    if (!controller) return;
    controller.statusTextChanged.connect(updateStatus);
    controller.isConnectingChanged.connect(updateButton);
    controller.isSendingChanged.connect(updateButton);
    controller.isConnectedChanged.connect(updateStatus);
    controller.statsChanged.connect(updateStats);

    controller.modeChanged.connect(() => {
        updateStatus();
        updateForms();
    });
    controller.appIdChanged.connect(updateForms);
    controller.accessTokenChanged.connect(updateForms);
    controller.useGzipChanged.connect(updateForms);
    controller.primaryHotkeyTextChanged.connect(updateForms);
    controller.primaryHotkeyModeChanged.connect(updateForms);
    controller.primaryHotkeyEnabledChanged.connect(updateForms);
    controller.freehandHotkeyTextChanged.connect(updateForms);
    controller.freehandHotkeyModeChanged.connect(updateForms);
    controller.freehandHotkeyEnabledChanged.connect(updateForms);
    controller.mouseHotkeyModeChanged.connect(updateForms);
    controller.mouseModeEnabledChanged.connect(updateForms);
    controller.hotkeysEnabledChanged.connect(updateForms);

    controller.tutorialHoldTextChanged.connect(updateTutorial);
    controller.tutorialToggleTextChanged.connect(updateTutorial);
    controller.tutorialMouseTextChanged.connect(updateTutorial);

    controller.historyReset.connect(renderHistory);
    controller.historyRowInserted.connect(insertHistoryRow);
    controller.historyRowUpdated.connect(updateHistoryRow);
    controller.historyRowRemoved.connect(removeHistoryRow);
    controller.hotkeyCaptured.connect(onHotkeyCaptured);
}

function hydrate() {
    updateStatus();
    updateStats();
    updateForms();
    updateButton();
    updateTutorial();
    controller.historySnapshot((list) => renderHistory(list));
}

function initChannel() {
    if (!window.qt || !window.qt.webChannelTransport) {
        console.error("Qt WebChannel transport missing");
        return;
    }
    new QWebChannel(qt.webChannelTransport, (channel) => {
        controller = channel.objects.controller;
        bindSignals();
        hydrate();
    });
}

document.addEventListener("DOMContentLoaded", () => {
    bindInputs();
    initChannel();
});

function onHotkeyCaptured(target, combo) {
    const input = $(`${target}-keys`);
    if (input) input.value = combo;
    document.querySelectorAll(".capture-btn").forEach((btn) => btn.classList.remove("active"));
    updateForms();
}
