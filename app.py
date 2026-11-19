import asyncio
import io
import time
from typing import AsyncGenerator
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont

app = FastAPI(
    title="BisaGym ESP32-CAM Cloud Relay",
    description="Cloud Gateway untuk streaming dan capture ESP32-CAM via Railway",
    version="1.0.0"
)

# CORS Middleware agar bisa diakses langsung dari fitfacely.com (HTTPS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage untuk frame terbaru
latest_frame: bytes | None = None
latest_frame_time: float = 0.0
total_frames_received: int = 0
fps_counter: int = 0
current_fps: float = 0.0
last_fps_calc_time: float = time.time()
new_frame_event = asyncio.Event()


def generate_placeholder_image(text: str = "ESP32-CAM Menunggu Koneksi...") -> bytes:
    """Membuat placeholder JPEG saat ESP32-CAM belum mengirim gambar."""
    img = Image.new("RGB", (640, 480), color=(20, 20, 25))
    draw = ImageDraw.Draw(img)
    
    # Header box
    draw.rectangle([0, 0, 640, 50], fill=(30, 30, 38))
    draw.text((20, 16), "BisaGym ESP32-CAM Cloud Gateway", fill=(204, 255, 0))
    
    # Message center
    draw.text((160, 220), text, fill=(240, 240, 240))
    draw.text((150, 260), "Pastikan ESP32-CAM menyala dan terhubung ke Wi-Fi", fill=(140, 140, 150))
    
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


placeholder_bytes = generate_placeholder_image()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "esp32cam-relay", "time": time.time()}


@app.post("/upload")
async def upload_frame(request: Request):
    """
    Menerima frame dari ESP32-CAM.
    Mendukung raw binary JPEG body atau multipart form-data.
    """
    global latest_frame, latest_frame_time, total_frames_received
    global fps_counter, current_fps, last_fps_calc_time

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("file") or form.get("image")
        if isinstance(uploaded_file, UploadFile):
            data = await uploaded_file.read()
        else:
            raise HTTPException(status_code=400, detail="Form file 'file' atau 'image' diperlukan")
    else:
        data = await request.body()

    if not data or len(data) < 200:
        raise HTTPException(status_code=400, detail="Frame data kosong atau tidak valid")

    # Update state
    latest_frame = data
    latest_frame_time = time.time()
    total_frames_received += 1
    fps_counter += 1

    # Hitung FPS
    now = time.time()
    elapsed = now - last_fps_calc_time
    if elapsed >= 1.0:
        current_fps = round(fps_counter / elapsed, 1)
        fps_counter = 0
        last_fps_calc_time = now

    # Notifikasi viewer yang sedang streaming
    new_frame_event.set()
    new_frame_event.clear()

    return {
        "status": "ok",
        "bytes": len(data),
        "total_frames": total_frames_received,
        "fps": current_fps
    }


@app.get("/capture")
async def get_capture():
    """
    Mengembalikan 1 snapshot JPEG frame terbaru.
    Digunakan oleh Laravel (fitfacely.com) untuk dikirim ke AI Facial Recognition.
    """
    global latest_frame, latest_frame_time

    frame = latest_frame
    # Jika frame terakhir sudah lebih dari 20 detik atau belum pernah ada, pakai placeholder
    if frame is None or (time.time() - latest_frame_time > 20):
        frame = placeholder_bytes

    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
            "X-Frame-Time": str(latest_frame_time),
        }
    )


async def mjpeg_generator() -> AsyncGenerator[bytes, None]:
    """Generator multipart MJPEG stream untuk browser & Kiosk Absensi."""
    global latest_frame, latest_frame_time

    boundary = "frame"
    while True:
        try:
            # Tunggu frame baru dengan timeout 1 detik
            try:
                await asyncio.wait_for(new_frame_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

            frame = latest_frame
            is_offline = (frame is None or (time.time() - latest_frame_time > 15))
            if is_offline:
                frame = placeholder_bytes

            header = (
                f"\r\n--{boundary}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n\r\n"
            ).encode("utf-8")

            yield header + frame + b"\r\n"

            # Batasi framerate max ~20 FPS untuk efisiensi bandwidth
            await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            break
        except Exception:
            break


@app.get("/stream")
async def get_stream():
    """
    Live MJPEG stream URL.
    Bisa langsung dipasang di <img src="/stream"> di web fitfacely.com.
    """
    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace;boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
            "Connection": "close",
        }
    )


@app.get("/status")
async def get_status():
    """Status JSON koneksi ESP32-CAM."""
    global latest_frame, latest_frame_time, total_frames_received, current_fps

    now = time.time()
    diff = round(now - latest_frame_time, 2) if latest_frame_time > 0 else -1
    is_online = (latest_frame is not None) and (diff >= 0 and diff < 12)

    return {
        "online": is_online,
        "status": "ready" if is_online else "waiting_esp32",
        "last_frame_seconds_ago": diff,
        "current_fps": current_fps if is_online else 0.0,
        "total_frames_received": total_frames_received,
        "frame_bytes": len(latest_frame) if latest_frame else 0,
        "stream_url": "/stream",
        "capture_url": "/capture"
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Halaman Dashboard Web BisaGym ESP32-CAM Relay."""
    html_content = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BisaGym — ESP32-CAM Cloud Gateway</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://unpkg.com/@phosphor-icons/web@2.1.1/src/bold/style.css">
        <style>
            .neon-btn {
                background-color: #ccff00;
                color: #111;
            }
            .neon-btn:hover {
                background-color: #b5e600;
            }
        </style>
    </head>
    <body class="bg-gray-950 text-gray-100 min-h-screen flex flex-col items-center justify-center p-4">
        <div class="max-w-2xl w-full bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-2xl space-y-6">
            <div class="flex items-center justify-between border-b border-gray-800 pb-4">
                <div class="flex items-center space-x-3">
                    <span class="p-2.5 rounded-xl bg-lime-400/10 text-lime-400 border border-lime-400/20">
                        <i class="ph-bold ph-broadcast text-2xl"></i>
                    </span>
                    <div>
                        <h1 class="text-xl font-bold text-white tracking-wide">BisaGym ESP32-CAM Cloud Gateway</h1>
                        <p class="text-xs text-gray-400">Railway Public Relay Server untuk Absensi Wajah</p>
                    </div>
                </div>
                <div id="badge-status" class="flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-semibold bg-gray-800 text-gray-400 border border-gray-700">
                    <span id="dot" class="w-2 h-2 rounded-full bg-gray-500"></span>
                    <span id="status-text">Memeriksa...</span>
                </div>
            </div>

            <!-- Video Player Stage -->
            <div class="relative bg-black rounded-xl overflow-hidden aspect-[4/3] flex items-center justify-center border border-gray-800">
                <img id="stream-img" src="/stream" alt="ESP32 Stream" class="w-full h-full object-contain">
                <div class="absolute bottom-3 right-3 bg-black/70 backdrop-blur px-3 py-1 rounded-lg text-xs font-mono text-lime-400 border border-lime-400/20">
                    FPS: <span id="fps-val">0.0</span>
                </div>
            </div>

            <!-- Informasi URL untuk dimasukkan ke Website BisaGym -->
            <div class="space-y-3 bg-gray-950/80 p-4 rounded-xl border border-gray-800/80">
                <label class="text-xs font-semibold text-gray-300 block">URL ESP32-CAM untuk Halaman Absensi BisaGym:</label>
                <div class="flex gap-2">
                    <input id="gateway-url" type="text" readonly class="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-lime-400 font-mono text-sm focus:outline-none" value="">
                    <button onclick="copyUrl()" class="px-4 py-2 neon-btn font-bold rounded-lg text-sm shrink-0 flex items-center gap-1.5 transition">
                        <i class="ph-bold ph-copy"></i> Salin
                    </button>
                </div>
                <p class="text-[11px] text-gray-400">
                    Masukkan URL di atas ke menu <strong>Absensi BisaGym</strong> (<a href="https://fitfacely.com/attendance" target="_blank" class="text-lime-400 hover:underline">fitfacely.com/attendance</a>) pada tab <strong>ESP32-CAM</strong>.
                </p>
            </div>

            <div class="grid grid-cols-2 gap-3 text-xs">
                <a href="/capture" target="_blank" class="p-3 rounded-lg bg-gray-800/60 hover:bg-gray-800 border border-gray-700 text-center text-gray-300 hover:text-white transition flex items-center justify-center gap-2">
                    <i class="ph-bold ph-camera"></i> Test Capture Foto (/capture)
                </a>
                <a href="/status" target="_blank" class="p-3 rounded-lg bg-gray-800/60 hover:bg-gray-800 border border-gray-700 text-center text-gray-300 hover:text-white transition flex items-center justify-center gap-2">
                    <i class="ph-bold ph-info"></i> Cek Status JSON (/status)
                </a>
            </div>
        </div>

        <script>
            document.getElementById('gateway-url').value = window.location.origin;

            function copyUrl() {
                const el = document.getElementById('gateway-url');
                el.select();
                navigator.clipboard.writeText(el.value);
                alert('URL berhasil disalin: ' + el.value);
            }

            async function checkStatus() {
                try {
                    const res = await fetch('/status');
                    const data = await res.json();
                    const badge = document.getElementById('badge-status');
                    const dot = document.getElementById('dot');
                    const text = document.getElementById('status-text');
                    const fps = document.getElementById('fps-val');

                    fps.textContent = data.current_fps || '0.0';

                    if (data.online) {
                        badge.className = 'flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-semibold bg-lime-400/10 text-lime-400 border border-lime-400/30';
                        dot.className = 'w-2 h-2 rounded-full bg-lime-400 animate-pulse';
                        text.textContent = 'ESP32 Online (' + data.current_fps + ' FPS)';
                    } else {
                        badge.className = 'flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-semibold bg-amber-400/10 text-amber-400 border border-amber-400/30';
                        dot.className = 'w-2 h-2 rounded-full bg-amber-400';
                        text.textContent = 'Menunggu ESP32 (' + Math.round(data.last_frame_seconds_ago) + 's lalu)';
                    }
                } catch (e) {
                    console.error(e);
                }
            }

            setInterval(checkStatus, 2000);
            checkStatus();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
