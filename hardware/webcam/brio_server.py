"""
Brio Server - Local FastAPI endpoint for agent-controlled MX Brio 4K.

    python3 brio_server.py          # starts on port 8420
    curl localhost:8420/info
    curl localhost:8420/capture -o /tmp/frame.jpg
    curl -X POST localhost:8420/morse -d '{"text":"HELLO"}' -H 'Content-Type: application/json'
"""

import io
import os
import sys
import base64
import wave
import tempfile
import numpy as np
import requests as http_req

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brio_sdk import Brio

app = FastAPI(title="MX Brio Agent API", version="1.0")
cam: Brio = None


def get_cam() -> Brio:
    global cam
    if cam is None:
        cam = Brio()
    return cam


# ── Request models ────────────────────────────────────────────

class MorseReq(BaseModel):
    text: str = "HELLO"
    wpm: int = 12

class LEDReq(BaseModel):
    on: bool = True

class PartyReq(BaseModel):
    pattern: str = "disco"

class EffectReq(BaseModel):
    name: str = "normal"
    intensity: Optional[float] = None

class ControlsReq(BaseModel):
    zoom: Optional[float] = None
    effect: Optional[str] = None
    intensity: Optional[float] = None

class SnapshotReq(BaseModel):
    path: Optional[str] = "/tmp/brio_snapshot.jpg"
    effect: Optional[str] = None

class WhisperMorseReq(BaseModel):
    seconds: float = 3.0
    wpm: int = 12


# ── Endpoints ─────────────────────────────────────────────────

@app.get("/info")
def info():
    return get_cam().info()


@app.get("/status")
def status():
    return get_cam().status()


@app.get("/capture")
def capture(effect: Optional[str] = None, intensity: Optional[float] = None):
    """Return a JPEG frame. Optional query params: ?effect=thermal&intensity=1.5"""
    import cv2
    b = get_cam()
    frame = b.capture(effect=effect, intensity=intensity)
    if frame is None:
        return JSONResponse({"error": "no frame"}, status_code=500)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@app.get("/capture/base64")
def capture_base64(effect: Optional[str] = None):
    """Return frame as base64-encoded JPEG (for agents that prefer JSON)."""
    import cv2
    b = get_cam()
    frame = b.capture(effect=effect)
    if frame is None:
        return JSONResponse({"error": "no frame"}, status_code=500)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(buf.tobytes()).decode()
    return {"image_base64": b64, "format": "jpeg", "resolution": f"{frame.shape[1]}x{frame.shape[0]}"}


@app.post("/snapshot")
def snapshot(req: SnapshotReq = SnapshotReq()):
    b = get_cam()
    path = b.snapshot(path=req.path, effect=req.effect)
    return {"path": path, "saved": os.path.exists(path)}


@app.post("/effect")
def set_effect(req: EffectReq):
    b = get_cam()
    name = b.effect(req.name, req.intensity)
    return {"effect": name, "intensity": b._intensity}


@app.get("/effects")
def list_effects():
    return {"effects": get_cam().effects()}


@app.post("/controls")
def set_controls(req: ControlsReq):
    b = get_cam()
    result = {}
    if req.zoom is not None:
        result["zoom"] = b.zoom(req.zoom)
    if req.effect is not None:
        result["effect"] = b.effect(req.effect, req.intensity)
    elif req.intensity is not None:
        b._intensity = req.intensity
        result["intensity"] = b._intensity
    return result


@app.post("/morse")
def morse(req: MorseReq):
    b = get_cam()
    encoded = b.morse_encode(req.text)
    b.morse(req.text, wpm=req.wpm)
    return {"text": req.text, "morse": encoded, "wpm": req.wpm, "status": "flashing"}


@app.post("/led")
def led(req: LEDReq):
    b = get_cam()
    b.led(req.on)
    return {"led": req.on}


@app.post("/led/stop")
def led_stop():
    get_cam().led_stop()
    return {"led": False, "status": "stopped"}


@app.post("/party")
def party(req: PartyReq):
    b = get_cam()
    b.party_mode(req.pattern)
    return {"pattern": req.pattern, "status": "playing"}


@app.get("/party/patterns")
def party_patterns():
    return {"patterns": list(get_cam().info()["party_patterns"])}


@app.get("/mic/level")
def mic_level():
    level = get_cam().mic_level()
    return {"level_dbfs": level}


@app.get("/mic/capture")
def mic_capture(seconds: float = 2.0):
    """Capture audio and return as WAV."""
    b = get_cam()
    audio = b.mic_capture(seconds=seconds)
    if audio is None:
        return JSONResponse({"error": "no mic"}, status_code=500)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())
    buf.seek(0)
    return StreamingResponse(buf, media_type="audio/wav",
                             headers={"Content-Disposition": "attachment; filename=brio_mic.wav"})


WHISPER_URL = "https://tetracorp--brio-whisper-whisperservice-web.modal.run/transcribe"


@app.post("/whisper/morse")
def whisper_morse(req: WhisperMorseReq = WhisperMorseReq()):
    """Record from Brio mic, transcribe with Whisper on Modal, flash as Morse."""
    b = get_cam()
    # Capture audio
    audio = b.mic_capture(seconds=req.seconds)
    if audio is None:
        return JSONResponse({"error": "no mic"}, status_code=500)
    # Convert to WAV bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())
    buf.seek(0)
    # Send to Modal Whisper
    resp = http_req.post(WHISPER_URL, files={"file": ("audio.wav", buf, "audio/wav")}, timeout=60)
    if resp.status_code != 200:
        return JSONResponse({"error": f"whisper failed: {resp.text}"}, status_code=502)
    result = resp.json()
    text = result.get("text", "").strip()
    if not text:
        return {"text": "", "morse": "", "status": "no speech detected"}
    # Flash as Morse
    encoded = b.morse_encode(text)
    b.morse(text, wpm=req.wpm)
    return {
        "text": text,
        "language": result.get("language", "unknown"),
        "morse": encoded,
        "wpm": req.wpm,
        "status": "flashing",
    }


@app.get("/tools")
def tools():
    """Return Claude tool-use JSON schema for all endpoints."""
    return [
        {
            "name": "brio_capture",
            "description": "Take a photo with the MX Brio 4K webcam. Returns JPEG image.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "effect": {"type": "string", "description": "Visual effect to apply (thermal, edges, sepia, sketch, etc.)"},
                },
            },
        },
        {
            "name": "brio_snapshot",
            "description": "Capture a photo and save to disk.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to save JPEG"},
                    "effect": {"type": "string", "description": "Visual effect to apply"},
                },
            },
        },
        {
            "name": "brio_morse",
            "description": "Flash a message in Morse code on the camera's LED.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to flash in Morse code"},
                    "wpm": {"type": "integer", "description": "Words per minute (default 12)"},
                },
                "required": ["text"],
            },
        },
        {
            "name": "brio_party",
            "description": "Flash the LED in a party pattern (strobe, pulse, heartbeat, disco, countdown, sos).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "enum": ["strobe", "pulse", "heartbeat", "disco", "countdown", "sos"]},
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "brio_led",
            "description": "Turn the camera LED on or off.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "on": {"type": "boolean", "description": "True=on, False=off"},
                },
                "required": ["on"],
            },
        },
        {
            "name": "brio_controls",
            "description": "Adjust camera settings: zoom (1.0-4.0), effect, intensity.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "zoom": {"type": "number", "description": "Digital zoom level 1.0-4.0"},
                    "effect": {"type": "string", "description": "Visual effect name"},
                    "intensity": {"type": "number", "description": "Effect intensity"},
                },
            },
        },
        {
            "name": "brio_mic_level",
            "description": "Read the current microphone level in dBFS.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "brio_info",
            "description": "Get full device info: resolution, sensor, controls, available effects and patterns.",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]


@app.on_event("shutdown")
def shutdown():
    global cam
    if cam:
        cam.close()
        cam = None


if __name__ == "__main__":
    import uvicorn
    print("Starting MX Brio Agent Server on http://localhost:8420")
    print("Docs: http://localhost:8420/docs")
    print("Tools: http://localhost:8420/tools")
    uvicorn.run(app, host="0.0.0.0", port=8420, log_level="info")
