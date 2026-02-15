import { ModalWebRtcClient } from './modal_webrtc.js';

const client = new ModalWebRtcClient();

// DOM refs
const localVideo = document.getElementById('localVideo');
const remoteVideo = document.getElementById('remoteVideo');
const btnCamera = document.getElementById('btnCamera');
const btnStream = document.getElementById('btnStream');
const btnStop = document.getElementById('btnStop');
const coordX = document.getElementById('coordX');
const coordY = document.getElementById('coordY');
const coordZ = document.getElementById('coordZ');
const objectList = document.getElementById('objectList');
const logEl = document.getElementById('log');
const statusBadge = document.getElementById('statusBadge');
const fpsDisplay = document.getElementById('fpsDisplay');
const latencyDisplay = document.getElementById('latencyDisplay');

// FPS tracking
let frameCount = 0;
let lastFpsTime = performance.now();

setInterval(() => {
    const now = performance.now();
    const elapsed = (now - lastFpsTime) / 1000;
    if (elapsed > 0) {
        fpsDisplay.textContent = `${Math.round(frameCount / elapsed)} fps`;
        frameCount = 0;
        lastFpsTime = now;
    }
}, 1000);

function log(msg) {
    const entry = document.createElement('div');
    entry.className = 'entry';
    const ts = new Date().toLocaleTimeString();
    entry.textContent = `[${ts}] ${msg}`;
    logEl.prepend(entry);
    // Keep last 50 entries
    while (logEl.children.length > 50) logEl.lastChild.remove();
}

function setStatus(text, cls) {
    statusBadge.textContent = text;
    statusBadge.className = `status ${cls || ''}`;
}

// Events
client.addEventListener('status', (e) => log(e.detail.message));
client.addEventListener('localStream', (e) => { localVideo.srcObject = e.detail.stream; });
client.addEventListener('remoteStream', (e) => { remoteVideo.srcObject = e.detail.stream; });

client.addEventListener('connectionStateChange', (e) => {
    const state = e.detail.state;
    if (state === 'connected') {
        setStatus('connected', 'connected');
        btnStream.disabled = true;
        btnStop.disabled = false;
    } else if (state === 'failed' || state === 'closed') {
        setStatus('disconnected');
        btnStream.disabled = false;
        btnStop.disabled = true;
    }
});

client.addEventListener('dataChannelOpen', () => {
    setStatus('streaming', 'streaming');
    log('Coordinate stream active');
});

client.addEventListener('coordinates', (e) => {
    const data = e.detail;
    frameCount++;

    // Latency estimate (server timestamp vs local time)
    const latencyMs = Math.round((Date.now() / 1000 - data.timestamp) * 1000);
    if (latencyMs >= 0 && latencyMs < 10000) {
        latencyDisplay.textContent = `latency: ${latencyMs}ms`;
    }

    const objects = data.objects || [];

    // Update primary target (highest confidence detection)
    if (objects.length > 0) {
        const primary = objects.reduce((a, b) => a.confidence > b.confidence ? a : b);
        coordX.textContent = primary.x.toFixed(3);
        coordY.textContent = primary.y.toFixed(3);
        coordZ.textContent = primary.z.toFixed(2);
    } else {
        coordX.textContent = '--';
        coordY.textContent = '--';
        coordZ.textContent = '--';
    }

    // Update object list
    if (objects.length === 0) {
        objectList.innerHTML = '<div style="color: #444; font-size: 12px;">No detections</div>';
    } else {
        objectList.innerHTML = objects.map((o) => `
            <div class="object-item">
                <span class="name">${o.class} (${(o.confidence * 100).toFixed(0)}%)</span>
                <span class="coords">${o.x.toFixed(2)}, ${o.y.toFixed(2)}, ${o.z.toFixed(1)}m</span>
            </div>
        `).join('');
    }
});

client.addEventListener('stopped', () => {
    setStatus('disconnected');
    remoteVideo.srcObject = null;
    btnCamera.disabled = false;
    btnStream.disabled = true;
    btnStop.disabled = true;
    coordX.textContent = '--';
    coordY.textContent = '--';
    coordZ.textContent = '--';
});

// Button handlers
btnCamera.addEventListener('click', async () => {
    try {
        await client.startWebcam();
        btnCamera.disabled = true;
        btnStream.disabled = false;
        log('Camera ready');
    } catch (err) {
        log(`Camera error: ${err.message}`);
    }
});

btnStream.addEventListener('click', async () => {
    btnStream.disabled = true;
    setStatus('connecting...');
    await client.startStreaming();
});

btnStop.addEventListener('click', async () => {
    await client.stop();
});

window.addEventListener('beforeunload', () => client.stop());
