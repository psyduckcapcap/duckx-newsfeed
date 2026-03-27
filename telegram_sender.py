"""
Telegram Sender - Gui tin nhan den Telegram Bot
================================================
Su dung Telegram Bot API de gui ban tom tat.
Markdown Legacy: *bold*, _italic_, [link](url), `code`
"""

import os
import requests
import re
from concurrent.futures import ThreadPoolExecutor

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4000  # De mot khoang dem an toan (Telegram limit = 4096)


def get_telegram_config() -> dict:
    """Get Telegram bot token and chat ID from env."""
    return {
        "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    }


def convert_markdown_to_legacy(text: str) -> str:
    """
    Chuyen doi Markdown (AI gen) sang Telegram Markdown Legacy.

    Quy trinh xu ly (theo dung thu tu Code 1):
    1. Loai bo dinh dang khong ho tro (strikethrough, blockquotes, horizontal rules)
    2. Chuan hoa Italic ve dang _text_ TRUOC (tranh xung dot voi bold)
    3. Chuyen doi Headings (#, ##, ...) thanh IN DAM va VIET HOA
    4. Chuan hoa Bold ve dang *text* SAU khi da xu ly italic
    5. Chuan hoa Lists ve dang `- item`
    """
    # 1. Loai bo cac dinh dang khong duoc ho tro
    # Strikethrough: ~~text~~ -> text
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    # Blockquotes: > text -> text
    text = re.sub(r'^>\s+(.*)', r'\1', text, flags=re.MULTILINE)
    # Horizontal rules: --- hoac ***
    text = re.sub(r'^(---|\*\*\*)$', '', text, flags=re.MULTILINE)

    # 2. Chuan hoa Italic ve dang _text_ TRUOC TIEN
    # Chuyen doi *text* (single asterisk) thanh _text_
    # Regex dam bao khong anh huong den cac cap ** (double asterisk)
    text = re.sub(r'(?<!\*|\w)\*([^* \n][^*]*?)\*(?!\*|\w)', r'_\1_', text)

    # 3. Chuyen doi Headings thanh IN DAM va VIET HOA
    # Vi du: "## Tieu de chinh" -> "*TIEU DE CHINH*"
    def heading_replacer(match):
        heading_text = match.group(1)
        return f'*{heading_text.upper()}*'

    text = re.sub(r'^#+\s+(.*)', heading_replacer, text, flags=re.MULTILINE)

    # 4. Chuan hoa Bold ve dang *text* SAU KHI da xu ly italic
    # **text** -> *text*
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    # __text__ -> *text*
    text = re.sub(r'__(.*?)__', r'*\1*', text)

    # 5. Chuan hoa Lists ve dang `- item`
    # Thay the cac bullet point * hoac + bang -
    text = re.sub(r'^\s*[*+]\s+', '    - ', text, flags=re.MULTILINE)

    return text


def convert_markdown_to_plaintext(text: str) -> str:
    """
    Chuyen doi Markdown sang Plain Text (fallback khi parse Markdown Legacy that bai).

    Quy trinh xu ly (theo dung thu tu Code 2):
    1. Xu ly lien ket: [text](url) -> text (url)
    2. Loai bo dinh dang cap do dong (headings, list markers, blockquotes)
    3. Loai bo tat ca ky tu dinh dang inline
    4. Don dep cac dong trong thua
    """
    # 1. Xu ly lien ket: [text](url) -> text (url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)

    # 2. Loai bo cac dinh dang cap do dong (block-level)
    # Headings (#), list markers (*, -, +), blockquotes (>)
    text = re.sub(r'^#+\s*|^\s*[*\-+]+\s*|^>\s*', '', text, flags=re.MULTILINE)

    # 3. Loai bo tat ca cac ky tu dinh dang inline
    # Bao gom: **, __, ~~, `, *, _
    text = re.sub(r'(\*\*|__|~~|`|\*|_)', '', text)

    # 4. Don dep cac dong trong thua
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def convert_twitter_mentions(text: str) -> str:
    """
    Chuyen doi @username thanh link Markdown tro den Twitter/X.
    Vi du: @elonmusk -> [elonmusk](https://x.com/elonmusk)

    Quy tac:
    - Chi thay the @username dung mot minh (khong nam trong link Markdown da co).
    - @username phai bat dau bang chu cai chu khong phai la mot phan cua URL khac.
    """
    # Truoc tien, bao ve cac mention nam trong link Markdown [text](url) khoi bi thay the
    # Bang cach thay the tam thoi noi dung trong () cua link
    protected = []

    def protect_links(m):
        placeholder = f"\x00LINK{len(protected)}\x00"
        protected.append(m.group(0))
        return placeholder

    # Bao ve [text](url) hien co
    text = re.sub(r'\[[^\]]*\]\([^)]*\)', protect_links, text)

    # Thay the @username con lai thanh link Twitter
    # Username Twitter hop le: chu cai, so, dau gach duoi, 1-50 ky tu
    text = re.sub(
        r'(?<![\w/])@([A-Za-z0-9_]{1,50})(?![\w])',
        lambda m: f'[{m.group(1)}](https://x.com/{m.group(1)})',
        text
    )

    # Khoi phuc cac link da bao ve
    for i, original in enumerate(protected):
        text = text.replace(f"\x00LINK{i}\x00", original)

    return text


def split_message(text: str) -> list:
    """
    Chia tin nhan thanh cac phan nho hon MAX_MESSAGE_LENGTH ky tu.
    Uu tien cat tai: dau ngat doan van (\n\n) -> xuong dong (\n) -> khoang trang ( )
    """
    if not text or len(text) <= MAX_MESSAGE_LENGTH:
        return [text] if text else []

    chunks = []
    remaining = text

    while len(remaining) > 0:
        if len(remaining) <= MAX_MESSAGE_LENGTH:
            chunks.append(remaining)
            break

        chunk_candidate = remaining[:MAX_MESSAGE_LENGTH]
        slice_index = -1

        # Uu tien 1: Tim dau ngat doan van cuoi cung
        slice_index = chunk_candidate.rfind('\n\n')

        # Uu tien 2: Neu khong co, tim dau xuong dong cuoi cung
        if slice_index == -1:
            slice_index = chunk_candidate.rfind('\n')

        # Uu tien 3: Neu khong co, tim khoang trang cuoi cung
        if slice_index == -1:
            slice_index = chunk_candidate.rfind(' ')

        # Truong hop cuoi: Cat cung neu khong tim thay diem ngat nao
        if slice_index == -1 or slice_index == 0:
            slice_index = MAX_MESSAGE_LENGTH

        # Lay doan van ban va them vao mang chunks
        chunks.append(remaining[:slice_index])

        # Cap nhat phan tin nhan con lai
        remaining = remaining[slice_index:].strip()

    return chunks


def _send_to_chats(text: str, chat_ids: list, bot_token: str, parse_mode: str = "Markdown") -> dict:
    """
    Core send logic: convert markdown, chunk message, send to each chat ID.
    Fallback: neu Markdown Legacy that bai -> thu lai voi plain text.

    Returns:
        dict: {"success": bool, "message": str}
    """
    if not bot_token:
        return {"success": False, "message": "TELEGRAM_BOT_TOKEN chua duoc cau hinh"}
    if not chat_ids:
        return {"success": False, "message": "Khong co chat ID nao"}

    # Buoc 0: Chuyen @username -> link Twitter truoc khi xu ly markdown
    text = convert_twitter_mentions(text)

    # Chuyen doi markdown sang Markdown Legacy truoc khi gui
    if parse_mode == "Markdown":
        formatted_text = convert_markdown_to_legacy(text)
    else:
        formatted_text = text

    chunks = split_message(formatted_text)
    total_sent = 0
    errors = []

    for chat_id in chat_ids:
        for chunk in chunks:
            url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    total_sent += 1
                else:
                    error_data = response.json()
                    error_desc = error_data.get("description", "Unknown error")

                    # Fallback: neu Markdown parse that bai -> chuyen sang plain text
                    if "can't parse" in error_desc.lower():
                        plaintext_chunk = convert_markdown_to_plaintext(chunk)
                        payload["text"] = plaintext_chunk
                        payload["parse_mode"] = ""
                        retry = requests.post(url, json=payload, timeout=10)
                        if retry.status_code == 200:
                            total_sent += 1
                        else:
                            retry_error = retry.json().get("description", "Unknown error")
                            errors.append(f"Chat {chat_id}: Markdown & plaintext failed: {retry_error}")
                    else:
                        errors.append(f"Chat {chat_id} (HTTP {response.status_code}): {error_desc}")
            except Exception as e:
                errors.append(f"Chat {chat_id} Exception: {str(e)}")

    if errors:
        return {"success": False, "message": " | ".join(errors)}

    return {
        "success": True,
        "message": f"Da gui thanh cong {total_sent} tin nhan den {len(chat_ids)} chats",
    }


def send_message(text: str, parse_mode: str = "Markdown") -> dict:
    """Gui tin nhan den tat ca Telegram chats trong TELEGRAM_CHAT_ID."""
    config = get_telegram_config()
    if not config["chat_id"]:
        return {"success": False, "message": "TELEGRAM_CHAT_ID chua duoc cau hinh"}
    chat_ids = [cid.strip() for cid in config["chat_id"].split(",") if cid.strip()]
    return _send_to_chats(text, chat_ids, config["bot_token"], parse_mode)


def send_message_to_targets(text: str, target_ids: list, parse_mode: str = "Markdown") -> dict:
    """Gui tin nhan den danh sach chat IDs cu the (per-watchlist)."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return _send_to_chats(text, target_ids, bot_token, parse_mode)


def test_connection() -> dict:
    """Test ket noi Telegram bot."""
    config = get_telegram_config()
    if not config["bot_token"]:
        return {"success": False, "bot_name": "", "message": "TELEGRAM_BOT_TOKEN chua cau hinh"}

    url = f"{TELEGRAM_API}/bot{config['bot_token']}/getMe"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            bot_info = data.get("result", {})
            return {
                "success": True,
                "bot_name": bot_info.get("username", "unknown"),
                "message": "Ket noi thanh cong",
            }
        else:
            return {"success": False, "bot_name": "", "message": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "bot_name": "", "message": str(e)}


def get_chat_names(chat_ids: list) -> dict:
    """Lay ten chat that tu Telegram API."""
    config = get_telegram_config()
    token = config.get("bot_token")
    if not token or not chat_ids:
        return {}

    names = {}

    def fetch_name(cid):
        url = f"{TELEGRAM_API}/bot{token}/getChat"
        try:
            r = requests.post(url, json={"chat_id": cid}, timeout=5)
            if r.status_code == 200:
                chat = r.json().get("result", {})
                title = chat.get("title")
                if not title:
                    first = chat.get("first_name", "")
                    last = chat.get("last_name", "")
                    title = f"{first} {last}".strip()
                return cid, title
        except Exception:
            pass
        return cid, None

    with ThreadPoolExecutor(max_workers=5) as ex:
        for cid, title in ex.map(fetch_name, chat_ids):
            if title:
                names[cid] = title

    return names
