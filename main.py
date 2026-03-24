"""
X Timeline Reader - Main Entry Point
=====================================
Đọc Home Timeline từ X (Twitter) API v2 và hiển thị kết quả.

Cách sử dụng:
  1. Copy config.example.env -> .env
  2. Điền API keys vào file .env
  3. Chạy: python main.py
  4. Hoặc:  python main.py --count 50     (lấy 50 tweets)
           python main.py --user elonmusk (lấy tweets của 1 user)
"""

import os
import sys
import argparse
from datetime import datetime
from dotenv import load_dotenv

from x_api import XApiClient, format_tweet, build_users_map


def load_config() -> dict:
    """Load API keys từ file .env"""
    # Tìm file .env trong cùng thư mục với script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, ".env")
    
    if not os.path.exists(env_path):
        print("=" * 60)
        print("❌ Chưa tìm thấy file .env!")
        print("=" * 60)
        print()
        print("Hướng dẫn:")
        print("  1. Copy file 'config.example.env' thành '.env'")
        print("  2. Mở file '.env' và điền API keys vào")
        print("  3. Chạy lại script này")
        print()
        print(f"  Thư mục: {script_dir}")
        print()
        sys.exit(1)
    
    load_dotenv(env_path)
    
    config = {
        "api_key": os.getenv("X_API_KEY", ""),
        "api_secret": os.getenv("X_API_SECRET", ""),
        "access_token": os.getenv("X_ACCESS_TOKEN", ""),
        "access_token_secret": os.getenv("X_ACCESS_TOKEN_SECRET", ""),
    }
    
    # Kiểm tra keys
    missing = [k for k, v in config.items() if not v or v.startswith("your_")]
    if missing:
        print("=" * 60)
        print("❌ Thiếu API Keys trong file .env!")
        print("=" * 60)
        print()
        for key in missing:
            env_name = f"X_{key.upper()}"
            print(f"  ⚠️  {env_name} chưa được cấu hình")
        print()
        print("Lấy keys tại: https://developer.x.com")
        print()
        sys.exit(1)
    
    return config


def print_header():
    """In header đẹp."""
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║        🐦  X TIMELINE READER  (API v2)              ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()


def cmd_timeline(client: XApiClient, count: int = 20):
    """Lấy và hiển thị Home Timeline."""
    print(f"📡 Đang lấy Home Timeline ({count} tweets mới nhất)...")
    print()
    
    try:
        response = client.get_home_timeline(max_results=count)
    except Exception as e:
        print(f"\n{e}")
        return
    
    tweets = response.get("data", [])
    includes = response.get("includes", {})
    meta = response.get("meta", {})
    
    if not tweets:
        print("📭 Không có tweets nào trong timeline!")
        return
    
    # Build mapping author_id → user info
    users_map = build_users_map(includes)
    
    print(f"OK - Da lay duoc {len(tweets)} tweets")
    print("=" * 60)
    print()
    
    for i, tweet in enumerate(tweets, 1):
        print(f"[ Tweet #{i} ]")
        print(format_tweet(tweet, users_map))
        print()
        print()
    
    # Pagination info
    next_token = meta.get("next_token")
    if next_token:
        print(f"📄 Còn thêm tweets. Next token: {next_token[:20]}...")
    
    result_count = meta.get("result_count", len(tweets))
    print(f"\n📊 Tổng cộng: {result_count} tweets đã hiển thị")


def cmd_user_tweets(client: XApiClient, username: str, count: int = 10):
    """Lấy và hiển thị tweets của một user cụ thể."""
    print(f"📡 Đang lấy tweets của @{username} ({count} tweets)...")
    print()
    
    try:
        response = client.get_user_tweets(username=username, max_results=count)
    except Exception as e:
        print(f"\n{e}")
        return
    
    tweets = response.get("data", [])
    includes = response.get("includes", {})
    
    if not tweets:
        print(f"📭 Không tìm thấy tweets nào từ @{username}!")
        return
    
    users_map = build_users_map(includes)
    
    print(f"OK - Da lay duoc {len(tweets)} tweets tu @{username}")
    print("=" * 60)
    print()
    
    for i, tweet in enumerate(tweets, 1):
        print(f"[ Tweet #{i} ]")
        print(format_tweet(tweet, users_map))
        print()
        print()


def cmd_me(client: XApiClient):
    """Hiển thị thông tin tài khoản đang xác thực."""
    print("📡 Đang xác thực và lấy thông tin tài khoản...")
    print()
    
    try:
        response = client.get_me()
    except Exception as e:
        print(f"\n{e}")
        return
    
    user = response.get("data", {})
    metrics = user.get("public_metrics", {})
    
    print("Xac thuc thanh cong!")
    print("=" * 60)
    print(f"  Ten:       {user.get('name', 'N/A')}")
    print(f"  Username:  @{user.get('username', 'N/A')}")
    print(f"  User ID:   {user.get('id', 'N/A')}")
    print(f"  Bio:       {user.get('description', 'N/A')}")
    print(f"  Tham gia:  {user.get('created_at', 'N/A')}")
    print("-" * 52)
    print(f"  Followers:  {metrics.get('followers_count', 0):,}")
    print(f"  Following:  {metrics.get('following_count', 0):,}")
    print(f"  Tweets:     {metrics.get('tweet_count', 0):,}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="🐦 X Timeline Reader - Đọc tweets từ X API v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  python main.py                   → Hiển thị thông tin tài khoản + 20 tweets mới nhất
  python main.py --count 50        → Lấy 50 tweets trong home timeline
  python main.py --user elonmusk   → Lấy tweets của @elonmusk
  python main.py --me              → Chỉ hiển thị thông tin tài khoản
        """,
    )
    
    parser.add_argument(
        "--count", "-c",
        type=int,
        default=20,
        help="Số tweets tối đa cần lấy (10-100, mặc định: 20)",
    )
    parser.add_argument(
        "--user", "-u",
        type=str,
        default=None,
        help="Lấy tweets của một user cụ thể (nhập username, không cần @)",
    )
    parser.add_argument(
        "--me",
        action="store_true",
        help="Chỉ hiển thị thông tin tài khoản, không lấy timeline",
    )
    
    args = parser.parse_args()
    
    # Header
    print_header()
    
    # Load config
    config = load_config()
    
    # Tạo API client
    client = XApiClient(
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        access_token=config["access_token"],
        access_token_secret=config["access_token_secret"],
    )
    
    # Chạy lệnh phù hợp
    if args.me:
        cmd_me(client)
    elif args.user:
        cmd_user_tweets(client, args.user, args.count)
    else:
        # Mặc định: hiển thị info + home timeline
        cmd_me(client)
        print()
        cmd_timeline(client, args.count)
    
    print()
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    print(f"🕐 Thời gian chạy: {now}")
    print()


if __name__ == "__main__":
    main()
