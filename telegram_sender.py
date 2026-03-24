"""
Telegram Sender - Gui tin nhan den Telegram Bot
================================================
Su dung Telegram Bot API de gui ban tom tat.
"""

import os
import requests
import re
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096


def get_telegram_config() -> dict:
    """Get Telegram bot token and chat ID from .env"""
    return {
        "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    }


def escape_telegram_markdown(text: str) -> str:
    r"""
    Sàng lọc và chèn ký tự \\ để ngăn Telegram nuốt thẻ định dạng (Markdown Legacy).
    Vẫn bảo toàn cấu trúc *in đậm* và _in nghiêng_.
    """

    # Escape ký tự '_' và '*' nếu nằm giữa 2 chữ cái/số (như username @cz_binance)
    text = re.sub(r'(?<=\w)_(?=\w)', r'\_', text)
    text = re.sub(r'(?<=\w)\*(?=\w)', r'\*', text)
    
    return text


def send_message(text: str, parse_mode: str = "Markdown") -> dict:
    """
    Gui tin nhan den Telegram chat.

    Args:
        text: Noi dung tin nhan
        parse_mode: "Markdown" hoac "HTML"

    Returns:
        dict: {"success": bool, "message": str}
    """
    if parse_mode == "Markdown":
        text = escape_telegram_markdown(text)

    config = get_telegram_config()

    if not config["bot_token"]:
        return {"success": False, "message": "TELEGRAM_BOT_TOKEN chua duoc cau hinh"}
    if not config["chat_id"]:
        return {"success": False, "message": "TELEGRAM_CHAT_ID chua duoc cau hinh"}

    # Ho trinh gui nhieu group cach nhau bang dau phay
    chat_ids = [cid.strip() for cid in config["chat_id"].split(",") if cid.strip()]

    # Chia nho tin nhan neu qua dai (Telegram limit: 4096 chars)
    chunks = split_message(text)
    total_sent = 0
    errors = []

    for chat_id in chat_ids:
        for chunk in chunks:
            url = f"{TELEGRAM_API}/bot{config['bot_token']}/sendMessage"
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
                    # If Markdown fails, retry without parse_mode
                    if "can't parse" in error_desc.lower():
                        payload["parse_mode"] = ""
                        retry = requests.post(url, json=payload, timeout=10)
                        if retry.status_code == 200:
                            total_sent += 1
                        else:
                            errors.append(f"Chat {chat_id}: {error_desc}")
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


def split_message(text: str) -> list:
    """
    Chia tin nhan thanh cac phan nho hon 4096 ky tu.
    Co gang cat tai dau dong de giu nguyen noi dung.
    """
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    chunks = []
    while text:
        if len(text) <= MAX_MESSAGE_LENGTH:
            chunks.append(text)
            break

        # Tim vi tri xuong dong gan nhat truoc gioi han
        cut_pos = text.rfind("\n", 0, MAX_MESSAGE_LENGTH)
        if cut_pos == -1:
            # Khong co xuong dong, cat tai khoang trang
            cut_pos = text.rfind(" ", 0, MAX_MESSAGE_LENGTH)
        if cut_pos == -1:
            # Khong co khoang trang, cat cung
            cut_pos = MAX_MESSAGE_LENGTH

        chunks.append(text[:cut_pos])
        text = text[cut_pos:].lstrip()

    return chunks


def test_connection() -> dict:
    """
    Test ket noi Telegram bot.

    Returns:
        dict: {"success": bool, "bot_name": str}
    """
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
