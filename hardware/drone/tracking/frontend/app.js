// DOM
const video = document.getElementById('video');
const capture = document.getElementById('capture');
const capCtx = capture.getContext('2d');
const btnCamera = document.getElementById('btnCamera');
const btnStream = document.getElementById('btnStream');
const btnStop = document.getElementById('btnStop');
const cX = document.getElementById('cX');
const cY = document.getElementById('cY');
const cZ = document.getElementById('cZ');
const fpsBadge = document.getElementById('fpsBadge');
const latBadge = document.getElementById('latBadge');
const statusBadge = document.getElementById('statusBadge');
const depthTag = document.getElementById('depthTag');
const fxDisp = document.getElementById('fxDisp');
const fyDisp = document.getElementById('fyDisp');
const chartCanvas = document.getElementById('chart');
const chartCtx = chartCanvas.getContext('2d');
const logEl = document.getElementById('log');

// Calibration DOM
const calibClass = document.getElementById('calibClass');
const calibWidth = document.getElementById('calibWidth');
const calibDist = document.getElementById('calibDist');
const btnCalib = document.getElementById('btnCalib');
const btnCalibCancel = document.getElementById('btnCalibCancel');
const calibResult = document.getElementById('calibResult');

let ws = null;
let stream = null;
let sendTimer = null;
const FPS = 10;

// Default object widths (mirrors backend)
const OBJ_WIDTHS = {
    'cup': 0.08, 'bottle': 0.07, 'cell phone': 0.075,
    'person': 0.45, 'laptop': 0.35, 'keyboard': 0.40,
    'book': 0.15, 'chair': 0.45,
};

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
function log(msg) {
    const d = document.createElement('div');
    d.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    logEl.prepend(d);
    while (logEl.children.length > 40) logEl.lastChild.remove();
}
log('Ready.');

// ---------------------------------------------------------------------------
// Ring buffer for chart
// ---------------------------------------------------------------------------
const BUF = 200;
class Ring {
    constructor(n) { this.n = n; this.d = []; }
    push(v) { this.d.push(v); if (this.d.length > this.n) this.d.shift(); }
    clear() { this.d = []; }
    get length() { return this.d.length; }
    get(i) { return this.d[i]; }
    last() { return this.d[this.d.length - 1]; }
}
const bX = new Ring(BUF), bY = new Ring(BUF), bZ = new Ring(BUF);

// ---------------------------------------------------------------------------
// Chart rendering
// ---------------------------------------------------------------------------
function sizeCanvas() {
    const r = chartCanvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(r.width * dpr);
    const h = Math.round(r.height * dpr);
    if (chartCanvas.width !== w || chartCanvas.height !== h) {
        chartCanvas.width = w;
        chartCanvas.height = h;
    }
}
new ResizeObserver(() => sizeCanvas()).observe(document.getElementById('chartWrap'));

function drawChart() {
    sizeCanvas();
    const dpr = window.devicePixelRatio || 1;
    const W = chartCanvas.width / dpr;
    const H = chartCanvas.height / dpr;
    chartCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

    chartCtx.fillStyle = '#111';
    chartCtx.fillRect(0, 0, W, H);

    const p = { t: 10, r: 48, b: 6, l: 42 };
    const pw = W - p.l - p.r;
    const ph = H - p.t - p.b;
    const n = bX.length;

    if (n < 2) {
        chartCtx.fillStyle = '#444';
        chartCtx.font = '11px monospace';
        chartCtx.textAlign = 'center';
        chartCtx.fillText('waiting for data...', W / 2, H / 2);
        requestAnimationFrame(drawChart);
        return;
    }

    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < n; i++) {
        for (const v of [bX.get(i), bY.get(i), bZ.get(i)]) {
            if (v != null && isFinite(v)) {
                if (v < lo) lo = v;
                if (v > hi) hi = v;
            }
        }
    }
    if (!isFinite(lo)) { requestAnimationFrame(drawChart); return; }
    const span = (hi - lo) || 1;
    lo -= span * 0.1;
    hi += span * 0.1;

    const xOf = (i) => p.l + (i / (BUF - 1)) * pw;
    const yOf = (v) => p.t + ph - ((v - lo) / (hi - lo)) * ph;

    // Grid
    chartCtx.strokeStyle = '#1a1a1a'; chartCtx.lineWidth = 1;
    for (let g = 0; g <= 4; g++) {
        const y = p.t + (g / 4) * ph;
        chartCtx.beginPath(); chartCtx.moveTo(p.l, y); chartCtx.lineTo(W - p.r, y); chartCtx.stroke();
        chartCtx.fillStyle = '#555'; chartCtx.font = '9px monospace'; chartCtx.textAlign = 'right';
        chartCtx.fillText((hi - (g / 4) * (hi - lo)).toFixed(2), p.l - 4, y + 3);
    }

    // Zero line
    if (lo < 0 && hi > 0) {
        chartCtx.strokeStyle = '#333'; chartCtx.setLineDash([3, 3]);
        chartCtx.beginPath(); chartCtx.moveTo(p.l, yOf(0)); chartCtx.lineTo(W - p.r, yOf(0)); chartCtx.stroke();
        chartCtx.setLineDash([]);
    }

    function trace(buf, color) {
        if (buf.length < 2) return;
        chartCtx.strokeStyle = color; chartCtx.lineWidth = 2; chartCtx.setLineDash([]);
        chartCtx.beginPath();
        let on = false;
        const off = BUF - buf.length;
        for (let i = 0; i < buf.length; i++) {
            const v = buf.get(i);
            if (v == null || !isFinite(v)) continue;
            const x = xOf(i + off), y = yOf(v);
            if (!on) { chartCtx.moveTo(x, y); on = true; } else chartCtx.lineTo(x, y);
        }
        chartCtx.stroke();
    }

    trace(bX, '#ef4444');
    trace(bY, '#22c55e');
    trace(bZ, '#3b82f6');

    // Right-edge labels
    chartCtx.font = '10px monospace'; chartCtx.textAlign = 'left';
    for (const [buf, col, lbl] of [[bX, '#ef4444', 'X'], [bY, '#22c55e', 'Y'], [bZ, '#3b82f6', 'Z']]) {
        const v = buf.last();
        if (v != null && isFinite(v)) {
            chartCtx.fillStyle = col;
            chartCtx.fillText(`${lbl}:${v.toFixed(2)}m`, W - p.r + 4,
                Math.min(H - p.b - 2, Math.max(p.t + 10, yOf(v))) + 3);
        }
    }

    chartCtx.strokeStyle = '#222'; chartCtx.lineWidth = 1;
    chartCtx.strokeRect(p.l, p.t, pw, ph);
    requestAnimationFrame(drawChart);
}
requestAnimationFrame(drawChart);

// ---------------------------------------------------------------------------
// FPS
// ---------------------------------------------------------------------------
let fc = 0, lastT = performance.now();
setInterval(() => {
    const dt = (performance.now() - lastT) / 1000;
    if (dt > 0) fpsBadge.textContent = `${Math.round(fc / dt)} fps`;
    fc = 0; lastT = performance.now();
}, 1000);

// ---------------------------------------------------------------------------
// Camera
// ---------------------------------------------------------------------------
btnCamera.addEventListener('click', async () => {
    log('Requesting camera...');
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: 'environment' }, width: 640, height: 480 },
            audio: false,
        });
        video.srcObject = stream;
        btnCamera.disabled = true;
        btnStream.disabled = false;
        log('Camera active.');
    } catch (err) {
        log('Camera error: ' + err.message);
        alert('Camera error: ' + err.message);
    }
});

// ---------------------------------------------------------------------------
// Send command over WebSocket
// ---------------------------------------------------------------------------
function sendCmd(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(obj));
    }
}

// ---------------------------------------------------------------------------
// Stream to GPU via WebSocket
// ---------------------------------------------------------------------------
btnStream.addEventListener('click', () => {
    btnStream.disabled = true;
    statusBadge.textContent = 'connecting...';
    statusBadge.className = 'badge';

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
        log('WebSocket connected. Streaming frames...');
        statusBadge.textContent = 'streaming';
        statusBadge.className = 'badge stream';
        btnStop.disabled = false;
        btnCalib.disabled = false;
        sendTimer = setInterval(sendFrame, 1000 / FPS);
    };

    ws.onmessage = (evt) => {
        try {
            const data = JSON.parse(evt.data);

            // Handle command results (calibration, etc.)
            if (data.type === 'command_result') {
                handleCommandResult(data);
                return;
            }

            // Frame result
            fc++;

            // Latency
            if (data.timestamp) {
                const ms = Math.round((Date.now() / 1000 - data.timestamp) * 1000);
                if (ms >= 0 && ms < 10000) latBadge.textContent = `${ms}ms`;
            }

            // Intrinsics display
            if (data.intrinsics) {
                fxDisp.textContent = `fx: ${data.intrinsics.fx}`;
                fyDisp.textContent = `fy: ${data.intrinsics.fy}`;
            }

            const objs = data.objects || [];
            if (objs.length > 0) {
                const pri = objs.reduce((a, b) => a.confidence > b.confidence ? a : b);
                cX.textContent = pri.x.toFixed(3);
                cY.textContent = pri.y.toFixed(3);
                cZ.textContent = pri.has_depth ? pri.z.toFixed(2) : '?';
                bX.push(pri.x);
                bY.push(pri.y);
                bZ.push(pri.has_depth ? pri.z : null);

                // Depth indicator
                if (pri.has_depth) {
                    depthTag.textContent = `[3D] ${pri.class}`;
                    depthTag.className = 'depth-tag d3';
                } else {
                    depthTag.textContent = `[2D] ${pri.class}`;
                    depthTag.className = 'depth-tag d2';
                }

                // Check for calibration result in any object
                for (const obj of objs) {
                    if (obj.calibration_result) {
                        const cr = obj.calibration_result;
                        calibResult.textContent = `Calibrated! fx=${cr.fx} (bbox=${cr.bbox_width_px}px)`;
                        calibResult.style.display = 'block';
                        statusBadge.textContent = 'streaming';
                        statusBadge.className = 'badge stream';
                        btnCalibCancel.disabled = true;
                        log(`Calibrated: fx=${cr.fx} from ${cr.class}`);
                    }
                }
            } else {
                cX.textContent = '--';
                cY.textContent = '--';
                cZ.textContent = '--';
                depthTag.textContent = '';
                depthTag.className = 'depth-tag';
            }
        } catch (e) {
            // ignore parse errors
        }
    };

    ws.onclose = () => {
        log('WebSocket closed.');
        stopStreaming();
    };

    ws.onerror = (e) => {
        log('WebSocket error.');
        stopStreaming();
    };
});

function handleCommandResult(data) {
    if (data.status === 'calibrating') {
        log(`Calibrating: hold ${data.class} steady...`);
        statusBadge.textContent = 'calibrating';
        statusBadge.className = 'badge calib';
    } else if (data.status === 'cancelled') {
        log('Calibration cancelled.');
        statusBadge.textContent = 'streaming';
        statusBadge.className = 'badge stream';
        btnCalibCancel.disabled = true;
    } else if (data.intrinsics) {
        fxDisp.textContent = `fx: ${data.intrinsics.fx}`;
        fyDisp.textContent = `fy: ${data.intrinsics.fy}`;
    }
}

function sendFrame() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!video.videoWidth) return;

    capture.width = 640;
    capture.height = 480;
    capCtx.drawImage(video, 0, 0, 640, 480);

    capture.toBlob((blob) => {
        if (blob && ws && ws.readyState === WebSocket.OPEN) {
            blob.arrayBuffer().then(buf => ws.send(buf));
        }
    }, 'image/jpeg', 0.7);
}

// ---------------------------------------------------------------------------
// Calibration
// ---------------------------------------------------------------------------
calibClass.addEventListener('change', () => {
    const w = OBJ_WIDTHS[calibClass.value];
    if (w) calibWidth.value = w;
});

btnCalib.addEventListener('click', () => {
    sendCmd({
        cmd: 'calibrate_start',
        class: calibClass.value,
        width: parseFloat(calibWidth.value),
        distance: parseFloat(calibDist.value),
    });
    btnCalibCancel.disabled = false;
    calibResult.style.display = 'none';
});

btnCalibCancel.addEventListener('click', () => {
    sendCmd({ cmd: 'calibrate_cancel' });
    btnCalibCancel.disabled = true;
});

// ---------------------------------------------------------------------------
// Stop
// ---------------------------------------------------------------------------
function stopStreaming() {
    if (sendTimer) { clearInterval(sendTimer); sendTimer = null; }
    if (ws) { ws.close(); ws = null; }
    statusBadge.textContent = 'off';
    statusBadge.className = 'badge';
    btnStream.disabled = false;
    btnStop.disabled = true;
    btnCalib.disabled = true;
    btnCalibCancel.disabled = true;
    cX.textContent = '--'; cY.textContent = '--'; cZ.textContent = '--';
    depthTag.textContent = '';
    depthTag.className = 'depth-tag';
    bX.clear(); bY.clear(); bZ.clear();
}

btnStop.addEventListener('click', stopStreaming);
window.addEventListener('beforeunload', stopStreaming);
