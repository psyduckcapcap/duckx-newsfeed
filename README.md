# 🦆 DuckX Newsfeed

Ứng dụng tự động theo dõi tài khoản X (Twitter), tóm tắt nội dung bằng AI (Gemini) và gửi bản tin đến Telegram theo lịch định sẵn.

---

## Tính năng

| Tính năng | Mô tả |
|---|---|
| **Watchlists** | Tạo nhiều nhóm theo dõi riêng biệt (Crypto, AI Tech, News...) |
| **Scheduler** | Tự động chạy theo giờ đặt sẵn (UTC+7), nhiều khung giờ mỗi ngày |
| **AI Summarize** | Gemini tóm tắt tweets nhóm theo chủ đề, in đậm thông tin quan trọng |
| **Telegram** | Gửi bản tin đến nhiều Chat ID / Group cùng lúc |
| **Web UI** | Giao diện quản lý trực quan, không cần chỉnh file config thủ công |
| **Execution Log** | Lịch sử chi tiết từng lần chạy (Fetch → AI → Telegram) |
| **Dedup** | Chỉ lấy tweets mới kể từ lần chạy trước, tránh trùng lặp |

---

## Yêu cầu

- Python 3.10+
- [X Developer Account](https://developer.x.com/en/portal/dashboard) — X API tính phí theo số tweets truy xuất (pay-per-usage)
- [Google AI Studio](https://aistudio.google.com/apikey) — Gemini API key (miễn phí)
- Telegram Bot — tạo qua @BotFather (miễn phí)

---

## Cài đặt & Khởi động

**1. Clone repository**

```bash
git clone https://github.com/psyduckcapcap/duckx-newsfeed.git
cd duckx-newsfeed
```

**2. Cài đặt thư viện**

```bash
pip install -r requirements.txt
```

**3. Cấu hình API keys**

```bash
# Linux / Mac
cp config.example.env .env

# Windows
copy config.example.env .env
```

Mở `.env` và điền đầy đủ các API keys (xem hướng dẫn trong file).

**4. Chạy ứng dụng**

```bash
python app.py
```

Truy cập **http://127.0.0.1:5000** để mở Web UI.

> Chạy trên port khác: `python app.py --port 8080`

---

## Cấu hình API Keys

### X (Twitter) API

1. Vào [developer.x.com](https://developer.x.com/en/portal/dashboard) → tạo Project và App mới
2. Chỉ cần quyền **Read**
3. Copy `API Key`, `API Secret`, `Access Token`, `Access Token Secret`

### Gemini AI (miễn phí)

1. Vào [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → tạo API Key
2. **Tip:** Tạo 3 key từ 3 tài khoản Google khác nhau để tăng tổng quota

### Telegram Bot

1. Tìm **@BotFather** trên Telegram → gõ `/newbot` → đặt tên → lấy **Bot Token**
2. Lấy **Chat ID**: Nhắn tin cho bot, rồi mở `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Hỗ trợ nhiều Chat ID, phân cách bằng dấu phẩy:

```env
TELEGRAM_CHAT_ID=123456789, -1009876543210, -1001234567890
```

---

## Biến môi trường

| Biến | Mục đích |
|------|---------|
| `X_API_KEY` | X OAuth consumer key |
| `X_API_SECRET` | X OAuth consumer secret |
| `X_ACCESS_TOKEN` | X OAuth access token |
| `X_ACCESS_TOKEN_SECRET` | X OAuth access token secret |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `TELEGRAM_CHAT_ID` | Chat IDs nhận bản tin (phân cách bằng dấu phẩy) |
| `GEMINI_API_KEY_1` | Gemini free key #1 |
| `GEMINI_API_KEY_2` | Gemini free key #2 |
| `GEMINI_API_KEY_3` | Gemini free key #3 |
| `GEMINI_API_KEY_PAID` | Gemini paid key |

---

## Sử dụng Web UI

| Tab | Chức năng |
|---|---|
| **Dashboard** | Thống kê tổng quan, tỷ lệ thành công, lần chạy tiếp theo |
| **Settings** | Quản lý Watchlists: thêm/xoá accounts, đặt lịch, chọn AI model, viết prompt |
| **Execution Log** | Lịch sử chi tiết: raw tweets, AI summary, lỗi nếu có |

### Quản lý Watchlist

- **New Watchlist:** Đặt tên nhóm (VD: "Crypto News", "AI Tech")
- **Add Account:** Thêm username X (có ký tự `@` hay không có đều được)
- **Schedule:** Đặt nhiều khung giờ tự động chạy trong ngày (UTC+7)
- **Max tweets per account:** Số tweet tối đa lấy mỗi lần cho từng account (1–100, mặc định 10)
- **AI Model:** Chọn 1 trong 4 Gemini models đã cấu hình key
- **Prompt:** Tùy chỉnh prompt cho AI xử lý nội dung (có thể dùng tiếng Việt)

---

## Cấu trúc dự án

```
duckx-newsfeed/
├── app.py                    # Flask server + APScheduler (~160 LOC)
├── pipeline.py               # Core ETL pipeline: fetch→summarize→send (~580 LOC)
├── config_manager.py         # Quản lý config & execution log (JSON) (~700 LOC)
├── ai_summarizer.py          # Tích hợp Google Gemini API (~100 LOC)
├── telegram_sender.py        # Gửi tin nhắn Telegram (~390 LOC)
├── x_api.py                  # X (Twitter) API v2 client (~750 LOC)
├── scheduler_manager.py      # APScheduler singleton (~50 LOC)
├── main.py                   # CLI tool để test X API (~244 LOC)
├── routes.py                 # Flask REST API routes (21 endpoints) (~270 LOC)
├── templates/
│   └── index.html            # Web UI (vanilla JS) (~724 LOC)
├── static/
│   └── style.css             # Dark theme CSS (~798 LOC)
├── tests/                    # Test directory (NEW)
├── app_config.json           # Watchlist config (runtime)
├── execution_log.json        # Execution history (runtime)
├── telegram_targets.json     # Cached Telegram targets (runtime)
├── config.example.env        # Mẫu cấu hình
├── start.sh                  # macOS daemon management
└── requirements.txt          # Dependencies
```

---

## CLI Tool

Test X API trực tiếp mà không cần chạy scheduler:

```bash
python main.py                     # Thông tin tài khoản + 20 tweets
python main.py --count 50          # Lấy 50 tweets từ home timeline
python main.py --user elonmusk     # Lấy tweets của @elonmusk
```

---

## Dependencies

| Thư viện | Mục đích |
|---|---|
| `flask` | Web server |
| `apscheduler` | Tự động chạy theo lịch |
| `google-genai` | Gemini AI API |
| `requests` + `requests-oauthlib` | X API, Telegram API |
| `python-dotenv` | Đọc file `.env` |
| `pytz` | Timezone UTC+7 |

---

## License

MIT License — free to use, modify and distribute.
