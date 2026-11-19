# 📹 BisaGym ESP32-CAM Cloud Gateway (Railway)

Gateway relay cloud untuk menghubungkan modul hardware **ESP32-CAM** langsung ke internet publik melalui **Railway**, sehingga stream video dan capture snapshot dapat digunakan pada website **BisaGym** (`https://fitfacely.com`) tanpa memerlukan ngrok, localtunnel, atau menyalakan laptop sebagai server perantara.

---

## 🏗️ Arsitektur Sistem

```
[ ESP32-CAM (OV2640) ]
        │  (Mengunggah JPEG frame via Wi-Fi otomatis)
        ▼  POST https://<domain-railway>.up.railway.app/upload
[ Server Railway ini (FastAPI / Uvicorn) ]
        │
        ├─► GET /stream   ──► Stream MJPEG untuk Kiosk Absensi BisaGym (fitfacely.com)
        ├─► GET /capture  ──► 1 Foto JPEG resolusi penuh untuk Face Recognition AI
        ├─► GET /status   ──► Status koneksi real-time, FPS, & latency
        └─► GET /         ──► Dashboard monitoring live kamera
```

---

## 🚀 Cara Deploy ke Railway

1. Buka [Railway Dashboard](https://railway.app/dashboard).
2. Klik tombol **New Project** → **Deploy from GitHub repo**.
3. Pilih repository ini (`FadilPrasetyo/esp32cam`).
4. Railway akan otomatis mendeteksi `Dockerfile` dan melakukan build container Python 3.12.
5. Setelah status menjadi **Active**, buka tab **Settings** → **Networking** → klik **Generate Domain**.
6. Kamu akan mendapatkan URL publik HTTPS resmi, contoh:
   ```text
   https://esp32cam-production-xxxx.up.railway.app
   ```

---

## ⚡ Konfigurasi Modul ESP32-CAM

1. Buka file Arduino sketch di folder:
   `arduino/CameraWebServer_Railway/CameraWebServer_Railway.ino`
2. Sesuaikan nama Wi-Fi dan URL Railway kamu:
   ```cpp
   const char *ssid     = "NAMA_WIFI_KAMU";
   const char *password = "PASSWORD_WIFI";

   // Ganti dengan domain Railway yang kamu dapatkan di langkah sebelumnya:
   const char *railwayUploadUrl = "https://esp32cam-production-xxxx.up.railway.app/upload";
   ```
3. Upload sketch ke ESP32-CAM melalui Arduino IDE (Board: `AI Thinker ESP32-CAM`).
4. Buka Serial Monitor (115200 baud). Modul akan langsung terhubung ke Wi-Fi dan mulai mengirim frame ke Railway!

---

## 🎯 Cara Pakai di Website BisaGym

1. Buka menu Absensi BisaGym di **[fitfacely.com/attendance](https://fitfacely.com/attendance)**.
2. Masuk ke tab **Kiosk Wajah** → pilih sumber kamera **ESP32-CAM**.
3. Masukkan domain Railway kamu ke kotak input:
   ```text
   https://esp32cam-production-xxxx.up.railway.app
   ```
4. Klik tombol **Uji**. Stream kamera akan langsung muncul dan siap digunakan untuk absensi wajah member!

---

## 📡 Daftar Endpoint API

| Endpoint | Method | Keterangan |
| :--- | :---: | :--- |
| `/` | `GET` | Dashboard web monitoring live preview kamera |
| `/upload` | `POST` | Menerima frame gambar JPEG dari modul ESP32-CAM |
| `/stream` | `GET` | Live stream MJPEG untuk dipasang di tag `<img>` browser |
| `/capture` | `GET` | Mengambil 1 frame foto JPEG terbaru untuk model AI |
| `/status` | `GET` | Cek status koneksi ESP32, FPS, dan ukuran frame |
| `/health` | `GET` | Health check endpoint untuk Railway deploy monitoring |
