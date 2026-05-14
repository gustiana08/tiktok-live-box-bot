# TikTok Live Lucky Box Bot 🎁

Bot otomatis yang mendeteksi **kotak keberuntungan (lucky box / treasure box)** di TikTok Live dan mengirim notifikasi ke Telegram secara real-time.

## Fitur

- **Auto-discovery**: Otomatis mencari live stream yang sedang trending di TikTok
- **Lucky box detection**: Mendeteksi kotak keberuntungan via `EnvelopeEvent`, gift events, dan raw event scanning
- **Telegram notifikasi**: Kirim alert instan ke channel/group Telegram dengan link langsung ke live stream
- **Multi-stream monitoring**: Monitor banyak live stream secara bersamaan
- **Anti-spam**: Cooldown system untuk mencegah notifikasi berulang
- **Auto-retry**: Reconnect otomatis jika koneksi terputus
- **Manual + Auto**: Bisa monitor username tertentu dan/atau auto-discover trending lives

## Cara Kerja

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  TikTok Live    │────▶│  Lucky Box       │────▶│  Telegram       │
│  Discovery      │     │  Detector        │     │  Notifier       │
│                 │     │                  │     │                 │
│ - Trending scan │     │ - EnvelopeEvent  │     │ - Format pesan  │
│ - Manual list   │     │ - GiftEvent      │     │ - Kirim ke chat │
│ - Explore page  │     │ - Raw scanning   │     │ - Cooldown      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Requirements

- Python 3.10+
- Telegram Bot Token (dari [@BotFather](https://t.me/BotFather))
- Telegram Chat ID (channel/group/personal chat)

## Instalasi

### 1. Clone repo

```bash
git clone https://github.com/gustiana08/tiktok-live-box-bot.git
cd tiktok-live-box-bot
```

### 2. Buat virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# atau
.venv\Scripts\activate     # Windows
```

### 3. Install dependencies

```bash
pip install -e .
```

### 4. Konfigurasi

Copy file `.env.example` ke `.env` dan isi dengan konfigurasi kamu:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Wajib
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=-1001234567890

# Opsional - monitor username tertentu (pisahkan dengan koma)
TIKTOK_USERNAMES=user1,user2,user3

# Opsional - tuning
SCAN_INTERVAL=60
MAX_CONCURRENT_STREAMS=10
NOTIFICATION_COOLDOWN=300
```

### 5. Jalankan bot

```bash
python run.py
```

## Mendapatkan Telegram Bot Token

1. Buka Telegram, cari **@BotFather**
2. Kirim `/newbot`
3. Ikuti instruksi untuk memberi nama bot
4. Copy token yang diberikan

## Mendapatkan Telegram Chat ID

### Untuk personal chat:
1. Kirim pesan apapun ke bot kamu
2. Buka: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Cari `"chat":{"id":` — angka itu adalah Chat ID kamu

### Untuk group/channel:
1. Tambahkan bot ke group/channel
2. Kirim pesan di group
3. Buka URL di atas dan cari Chat ID (biasanya dimulai dengan `-100`)

## Konfigurasi Lengkap

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `TELEGRAM_BOT_TOKEN` | (wajib) | Token dari @BotFather |
| `TELEGRAM_CHAT_ID` | (wajib) | ID chat tujuan notifikasi |
| `TIKTOK_USERNAMES` | (kosong) | Username TikTok yang dimonitor, pisahkan koma |
| `SCAN_INTERVAL` | `60` | Interval scan dalam detik |
| `MAX_CONCURRENT_STREAMS` | `10` | Maks live stream yang dimonitor bersamaan |
| `NOTIFICATION_COOLDOWN` | `300` | Cooldown notifikasi per stream (detik) |
| `NOTIFY_ON_START` | `true` | Kirim notifikasi saat bot mulai/berhenti |
| `LOG_LEVEL` | `INFO` | Level logging (DEBUG, INFO, WARNING, ERROR) |

## Catatan Penting

- **Unofficial API**: Bot ini menggunakan library `TikTokLive` yang bersifat unofficial. TikTok bisa mengubah API mereka kapan saja yang bisa membuat bot berhenti bekerja.
- **Rate Limiting**: TikTok mungkin membatasi akses jika terlalu banyak request. Sesuaikan `SCAN_INTERVAL` dan `MAX_CONCURRENT_STREAMS`.
- **Deteksi Lucky Box**: Deteksi bergantung pada event yang tersedia dari TikTok Live WebSocket. Tidak semua tipe lucky box dijamin terdeteksi.
- **Trending Discovery**: Karena TikTok tidak punya API resmi untuk list live streams, fitur auto-discovery bersifat best-effort.

## Struktur Project

```
tiktok-live-box-bot/
├── bot/
│   ├── __init__.py
│   ├── config.py          # Konfigurasi (env vars)
│   ├── detector.py         # Lucky box detection logic
│   ├── discovery.py        # Live stream discovery
│   ├── main.py             # Main orchestrator
│   └── telegram_notifier.py # Telegram notification
├── .env.example            # Template konfigurasi
├── .gitignore
├── pyproject.toml          # Project metadata & dependencies
├── run.py                  # Entry point
├── LICENSE
└── README.md
```

## License

MIT
