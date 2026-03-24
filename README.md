# 🦆 DuckX Newsfeed

Ứng dụng tự động theo dõi các tài khoản X (Twitter), tóm tắt nội dung bằng AI (Gemini) và gửi bản tin đến Telegram theo lịch định sẵn.

---

## ✨ Tính năng

| Tính năng | Mô tả |
|---|---|
| 📋 **Watchlists** | Tạo nhiều nhóm theo dõi (Crypto, AI Tech, News...) riêng biệt |
| ⏰ **Scheduler** | Tự động chạy theo giờ đặt sẵn (UTC+7), nhiều khung giờ mỗi ngày |
| 🤖 **AI Summarize** | Gemini tóm tắt tweets nhóm theo chủ đề, in đậm thông tin quan trọng |
| 📱 **Telegram** | Gửi bản tin đến nhiều Chat ID / Group cùng lúc |
| 🌐 **Web UI** | Giao diện quản lý trực quan, không cần chỉnh file config thủ công |
| 📊 **Execution Log** | Lịch sử chi tiết từng lần chạy (Fetch → AI → Telegram) |
| 🔁 **Dedup** | Chỉ lấy tweets mới kể từ lần chạy trước (tránh trùng lặp) |

---

## 📋 Yêu cầu

- Python 3.10+
- X (Twitter) Developer Account (Free Basic là đủ)
- Google AI Studio account (Gemini API key - miễn phí)
- Telegram Bot (tạo qua @BotFather)

---

## 🚀 Cài đặt & Khởi động

### 1. Clone repository

```bash
git clone https://github.com/psyduckcapcap/duckx-newsfeed.git
cd duckx-newsfeed
```

### 2. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

### 3. Cấu hình API keys

```bash
# Windows
copy config.example.env .env

# Linux / Mac
cp config.example.env .env
```

Mở file `.env` và điền đầy đủ các API keys (xem hướng dẫn bên trong file).

### 4. Chạy ứng dụng

```bash
python app.py
```

Mở trình duyệt và vào: **http://127.0.0.1:5000**

---

## ⚙️ Cấu hình API Keys

### X (Twitter) API
1. Truy cập [developer.x.com](https://developer.x.com/en/portal/dashboard)
2. Tạo Project và App mới
3. Quyền **Read** là đủ (không cần Write)
4. Copy `API Key`, `API Secret`, `Access Token`, `Access Token Secret`

### Gemini AI (miễn phí)
1. Truy cập [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Tạo API Key mới
3. **Tip:** Tạo 3 key từ 3 tài khoản Google khác nhau để tăng quota tổng cộng

### Telegram Bot
1. Mở Telegram, tìm **@BotFather** → gõ `/newbot`
2. Đặt tên và lấy **Bot Token**
3. Lấy **Chat ID**: Nhắn tin cho bot rồi mở `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. **Gửi đến nhiều group:** Điền nhiều Chat ID cách nhau bằng dấu phẩy

```env
TELEGRAM_CHAT_ID=123456789, -1009876543210, -1001234567890
```

---

## 🗂️ Cấu trúc dự án

```
duckx-newsfeed/
├── app.py               # Flask server + APScheduler
├── config_manager.py    # Quản lý config & execution log (JSON)
├── ai_summarizer.py     # Tích hợp Google Gemini API
├── telegram_sender.py   # Gửi tin nhắn Telegram (single/multi chat)
├── x_api.py             # X (Twitter) API v2 client
├── main.py              # CLI tool để test X API trực tiếp
├── templates/
│   └── index.html       # Giao diện Web UI (vanilla JS)
├── static/
│   └── style.css        # Dark theme CSS
├── config.example.env   # Mẫu cấu hình (copy thành .env)
├── requirements.txt     # Thư viện Python cần cài
└── .gitignore
```

---

## 🖥️ Sử dụng Web UI

| Tab | Chức năng |
|---|---|
| **Dashboard** | Thống kê tổng quan, tỷ lệ thành công, lần chạy tiếp theo |
| **Settings** | Quản lý Watchlists: thêm/xoá accounts, đặt lịch, chọn AI model, viết prompt |
| **Execution Log** | Lịch sử chi tiết: xem raw tweets, AI summary, lỗi nếu có |

### Quản lý Watchlist

- **New Watchlist:** Đặt tên nhóm (VD: "Crypto News", "AI Tech")
- **Add Account:** Thêm username X không cần ký tự `@`
- **Schedule:** Đặt nhiều khung giờ tự động chạy trong ngày (UTC+7)
- **Max tweets per account:** Số tweet tối đa lấy mỗi lần (1–100, mặc định 10)
- **AI Model:** Chọn 1 trong 4 Gemini models đã cấu hình key
- **Prompt:** Tùy chỉnh cách AI tóm tắt (có thể dùng tiếng Việt)

---

## 📝 Ghi chú định dạng Telegram

App sử dụng **Markdown Legacy** của Telegram. Trong Prompt, yêu cầu Gemini:
- Dùng `*chữ in đậm*` (một dấu sao) thay vì `**hai dấu sao**`
- Dùng `_chữ in nghiêng_` thay vì `__hai gạch dưới__`

---

## 🔧 Tùy chỉnh nâng cao

### Chạy trên port khác

```bash
python app.py --port 8080
```

### Dùng CLI tool để test X API

```bash
python main.py                     # Hiển thị thông tin tài khoản + 20 tweets
python main.py --count 50          # Lấy 50 tweets từ home timeline
python main.py --user elonmusk     # Lấy tweets của @elonmusk
```

---

## 📦 Dependencies

| Thư viện | Mục đích |
|---|---|
| `flask` | Web server |
| `apscheduler` | Tự động chạy theo lịch |
| `google-genai` | Gemini AI API |
| `requests` + `requests-oauthlib` | X API, Telegram API |
| `python-dotenv` | Đọc file `.env` |
| `pytz` | Timezone UTC+7 |

---

## 📄 License

MIT License — free to use, modify and distribute.
