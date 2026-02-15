"""
Whisper on Modal - GPU-accelerated speech-to-text endpoint.

Deploy:  modal deploy whisper_modal.py
Test:    curl -X POST https://tetracorp--brio-whisper-web.modal.run/transcribe \
              -F "file=@/tmp/brio_mic.wav"
"""

import modal

app = modal.App("brio-whisper")

whisper_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install("openai-whisper", "torch", "numpy", "python-multipart", "fastapi")
    .run_commands("python3 -c \"import whisper; whisper.load_model('base')\"")
)


@app.cls(
    image=whisper_image,
    gpu="T4",
    timeout=120,
    scaledown_window=120,
)
class WhisperService:
    @modal.enter()
    def load_model(self):
        import whisper
        self.model = whisper.load_model("base")

    @modal.asgi_app()
    def web(self):
        from fastapi import FastAPI, UploadFile, File, Request
        from fastapi.responses import JSONResponse
        import tempfile
        import os

        api = FastAPI(title="Brio Whisper")
        svc = self

        @api.post("/transcribe")
        async def transcribe(file: UploadFile = File(...)):
            audio_bytes = await file.read()
            suffix = ".wav"
            if file.filename and "." in file.filename:
                suffix = "." + file.filename.rsplit(".", 1)[-1]

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            try:
                result = svc.model.transcribe(tmp_path, fp16=True)
                return {
                    "text": result["text"].strip(),
                    "language": result.get("language", "unknown"),
                    "segments": len(result.get("segments", [])),
                }
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            finally:
                os.unlink(tmp_path)

        @api.post("/transcribe/raw")
        async def transcribe_raw(request: Request):
            audio_bytes = await request.body()
            if len(audio_bytes) < 44:
                return JSONResponse({"error": "empty or invalid audio"}, status_code=400)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            try:
                result = svc.model.transcribe(tmp_path, fp16=True)
                return {
                    "text": result["text"].strip(),
                    "language": result.get("language", "unknown"),
                    "segments": len(result.get("segments", [])),
                }
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            finally:
                os.unlink(tmp_path)

        @api.get("/health")
        def health():
            return {"status": "ok", "model": "whisper-base", "gpu": "T4"}

        return api
