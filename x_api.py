"""
X API v2 - Module giao tiếp với X (Twitter) API
================================================
Sử dụng OAuth 1.0a (4 keys) để xác thực user context.
Hỗ trợ lấy home timeline, user tweets, và thông tin user.
"""

import time
import logging
import requests
from requests_oauthlib import OAuth1
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


class XApiClient:
    """Client để giao tiếp với X API v2."""

    BASE_URL = "https://api.x.com/2"

    def __init__(self, api_key: str, api_secret: str, access_token: str, access_token_secret: str):
        self.auth = OAuth1(
            client_key=api_key,
            client_secret=api_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret,
        )
        self._user_id = None
        self._username = None

    def _make_request(self, method: str, endpoint: str, params: dict = None, max_retries: int = 2) -> dict:
        """
        Gửi HTTP request đến X API, tự retry khi bị rate limit (429).

        Args:
            method: "GET" hoặc "POST"
            endpoint: API endpoint path (vd: "/users/me")
            params: Query parameters
            max_retries: Số lần retry tối đa cho 429/5xx errors

        Returns:
            dict: JSON response từ API

        Raises:
            Exception: Nếu API trả về lỗi sau khi hết retry
        """
        url = f"{self.BASE_URL}{endpoint}"

        for attempt in range(max_retries + 1):
            response = requests.request(
                method=method,
                url=url,
                auth=self.auth,
                params=params,
            )

            if response.status_code == 200:
                return response.json()

            # Retry on rate limit or server errors
            if response.status_code in (429, 500, 502, 503) and attempt < max_retries:
                retry_after = int(response.headers.get("Retry-After", 5))
                wait = min(retry_after, 30)
                logger.warning(f"X API {response.status_code} on {endpoint}, retry in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue

            # Non-retryable errors
            if response.status_code == 401:
                raise Exception(
                    "Loi xac thuc (401). Kiem tra lai API keys. "
                    "Dam bao rang Access Token co quyen Read."
                )
            elif response.status_code == 403:
                raise Exception(
                    "Bi tu choi truy cap (403). Co the do: "
                    "chua nap credits, API Key khong co quyen, "
                    "hoac tai khoan Dev chua kich hoat."
                )
            elif response.status_code == 429:
                raise Exception(
                    "Rate limit exceeded (429). Da gui qua nhieu request. "
                    "Hay doi vai phut roi thu lai."
                )
            else:
                raise Exception(
                    f"Loi API ({response.status_code}): {response.text[:300]}"
                )

    # ─────────────────────────────────────────────
    # User Info
    # ─────────────────────────────────────────────

    def get_me(self) -> dict:
        """Lấy thông tin user đang xác thực."""
        params = {
            "user.fields": "id,name,username,description,profile_image_url,public_metrics,created_at",
        }
        result = self._make_request("GET", "/users/me", params=params)

        if "data" in result:
            self._user_id = result["data"]["id"]
            self._username = result["data"]["username"]

        return result

    def get_user_id(self) -> str:
        """Lấy user ID (tự động gọi get_me nếu chưa có)."""
        if self._user_id is None:
            self.get_me()
        return self._user_id

    # ─────────────────────────────────────────────
    # Home Timeline
    # ─────────────────────────────────────────────

    def get_home_timeline(self, max_results: int = 20, pagination_token: str = None) -> dict:
        """Lấy Home Timeline - tweets từ các accounts bạn follow."""
        user_id = self.get_user_id()

        params = {
            "max_results": min(max(max_results, 10), 100),
            "tweet.fields": "created_at,author_id,text,public_metrics,lang,source,conversation_id,referenced_tweets",
            "expansions": "author_id,referenced_tweets.id",
            "user.fields": "name,username,profile_image_url,verified",
        }

        if pagination_token:
            params["pagination_token"] = pagination_token

        return self._make_request(
            "GET",
            f"/users/{user_id}/timelines/reverse_chronological",
            params=params,
        )

    # ─────────────────────────────────────────────
    # User Tweets
    # ─────────────────────────────────────────────

    def get_user_tweets(self, user_id: str = None, username: str = None, max_results: int = 10) -> dict:
        """Lấy tweets của một user cụ thể."""
        if user_id is None and username is None:
            raise ValueError("Phai cung cap user_id hoac username")

        if user_id is None:
            user_info = self.get_user_by_username(username)
            user_id = user_info["data"]["id"]

        params = {
            "max_results": min(max(max_results, 5), 100),
            "tweet.fields": "created_at,author_id,text,public_metrics,lang,referenced_tweets",
            "expansions": "author_id",
            "user.fields": "name,username,profile_image_url",
        }

        return self._make_request("GET", f"/users/{user_id}/tweets", params=params)

    # ─────────────────────────────────────────────
    # User Lookup
    # ─────────────────────────────────────────────

    def get_user_by_username(self, username: str) -> dict:
        """Tìm thông tin user bằng username."""
        username = username.lstrip("@")
        params = {
            "user.fields": "id,name,username,description,public_metrics,profile_image_url",
        }
        return self._make_request("GET", f"/users/by/username/{username}", params=params)

    def get_users_by_usernames(self, usernames: list) -> dict:
        """
        Batch lookup nhiều users bằng usernames (tối đa 100).

        Endpoint: GET /2/users/by
        Returns:
            dict: {"data": [...], "errors": [...]}
        """
        cleaned = [u.lstrip("@") for u in usernames]
        params = {
            "usernames": ",".join(cleaned),
            "user.fields": "id,name,username,profile_image_url",
        }
        return self._make_request("GET", "/users/by", params=params)

    # ─────────────────────────────────────────────
    # Watchlist - Batch fetch from multiple users
    # ─────────────────────────────────────────────

    def get_watchlist_tweets(self, usernames: list, max_per_user: int = 10, since_ids: dict = None, user_id_cache: dict = None) -> dict:
        """
        Lấy tweets mới từ nhiều users (watchlist).
        Dùng user_id_cache để bỏ qua batch user lookup với accounts đã biết ID
        → tiết kiệm User: Read credits ($0.010/resource).
        Trả về new_cache_entries để caller lưu cache.
        """
        if since_ids is None:
            since_ids = {}
        if user_id_cache is None:
            user_id_cache = {}

        all_tweets = []
        users_map = {}
        new_since_ids = {}
        errors = {}
        new_cache_entries = {}  # Accounts fetched fresh this run (not in cache)

        # ── Bước 1: Ưu tiên dùng cache, chỉ lookup accounts thiếu ──
        uid_map = {}
        missing_usernames = []

        for username in usernames:
            uname_lower = username.lower()
            cached = user_id_cache.get(uname_lower)
            if cached and cached.get("id"):
                uid_map[uname_lower] = cached
                users_map[cached["id"]] = cached
            else:
                missing_usernames.append(username)

        # ── Bước 2: Batch lookup chỉ accounts chưa có trong cache ──
        if missing_usernames:
            BATCH_SIZE = 100
            for chunk_start in range(0, len(missing_usernames), BATCH_SIZE):
                chunk = missing_usernames[chunk_start:chunk_start + BATCH_SIZE]
                try:
                    batch_result = self.get_users_by_usernames(chunk)
                    for user_data in batch_result.get("data", []):
                        uname = user_data["username"].lower()
                        uid_map[uname] = user_data
                        users_map[user_data["id"]] = user_data
                        new_cache_entries[uname] = user_data  # trả về để caller cache

                    for api_err in batch_result.get("errors", []):
                        detail = api_err.get("detail", "")
                        resource_id = api_err.get("value", "")
                        if resource_id:
                            errors[resource_id] = detail or "User not found"
                except Exception as e:
                    logger.warning(f"Batch user lookup failed for chunk {chunk_start // BATCH_SIZE + 1} ({e}), falling back to individual lookups")
                    for username in chunk:
                        try:
                            user_info = self.get_user_by_username(username)
                            if "data" in user_info:
                                user_data = user_info["data"]
                                uid_map[username.lower()] = user_data
                                users_map[user_data["id"]] = user_data
                                new_cache_entries[username.lower()] = user_data
                            else:
                                errors[username] = "User not found"
                        except Exception as ue:
                            errors[username] = str(ue)

        # ── Bước 3: Xác định expansions cần dùng ──
        # Khi tất cả accounts đã có trong cache: bỏ author_id expansion → 0 User: Read charges
        # Khi có accounts mới: giữ expansion để lấy và cache user data
        if missing_usernames:
            expansions = "author_id,referenced_tweets.id,referenced_tweets.id.author_id,referenced_tweets.id.attachments.media_keys,attachments.media_keys"
        else:
            # Full cache hit: không cần author expansion, tiết kiệm User: Read credits
            expansions = "referenced_tweets.id,referenced_tweets.id.attachments.media_keys,attachments.media_keys"

        # ── Bước 4: Fetch tweets per user ──
        for username in usernames:
            uname_lower = username.lower()
            user_data = uid_map.get(uname_lower)
            if not user_data:
                if uname_lower not in errors:
                    errors[username] = "User not found"
                continue

            uid = user_data["id"]

            try:
                params = {
                    "max_results": min(max(max_per_user, 5), 100),
                    "exclude": "replies",
                    "tweet.fields": "created_at,author_id,text,public_metrics,lang,referenced_tweets,attachments,note_tweet",
                    "expansions": expansions,
                    "user.fields": "name,username,profile_image_url",
                    "media.fields": "type,url,preview_image_url,variants",
                }

                sid = since_ids.get(uname_lower)
                if sid:
                    params["since_id"] = sid

                response = self._make_request("GET", f"/users/{uid}/tweets", params=params)

                tweets = response.get("data", [])

                # Slice the list if user wants fewer than 5 tweets
                if tweets and max_per_user < 5:
                    tweets = tweets[:max_per_user]

                includes = response.get("includes", {})

                # Merge includes users
                if includes and "users" in includes:
                    for u in includes["users"]:
                        users_map[u["id"]] = u

                # Build a map of referenced (retweeted/quoted) tweet full content
                if includes and "tweets" in includes:
                    for ref_t in includes["tweets"]:
                        users_map[f"__tweet_{ref_t['id']}"] = ref_t

                # Build media map: media_key → media object
                if includes and "media" in includes:
                    for media_obj in includes["media"]:
                        users_map[f"__media_{media_obj['media_key']}"] = media_obj

                # Track newest tweet ID for dedup next time
                if tweets:
                    new_since_ids[uname_lower] = tweets[0]["id"]

                all_tweets.extend(tweets)

            except Exception as e:
                err_str = str(e)
                errors[username] = err_str
                # Hint admin about permanent failures that waste API quota
                if "403" in err_str or "404" in err_str or "not found" in err_str.lower():
                    logger.warning(
                        f"  @{username}: permanent error ({err_str[:80]}) — "
                        f"consider removing this account from the watchlist"
                    )
                else:
                    logger.warning(f"  @{username}: fetch error — {err_str[:80]}")

        # Sort all tweets by created_at descending (newest first)
        all_tweets.sort(
            key=lambda t: t.get("created_at", ""),
            reverse=True,
        )

        return {
            "tweets": all_tweets,
            "users_map": users_map,
            "new_since_ids": new_since_ids,
            "errors": errors,
            "new_cache_entries": new_cache_entries,  # username_lower → user_data
        }


def tweets_to_text(tweets: list, users_map: dict) -> str:
    """
    Convert list of tweets to plain text for AI summarization.
    Resolves full retweet content and appends media URLs.
    """
    if not tweets:
        return ""

    lines = []
    for i, tweet in enumerate(tweets, 1):
        author_id = tweet.get("author_id", "")
        author = "Unknown"
        if users_map and author_id in users_map:
            author = f"@{users_map[author_id].get('username', 'unknown')}"

        created_raw = tweet.get("created_at", "")
        created = created_raw
        if created_raw:
            try:
                # X API returns ISO 8601 with or without microseconds, always in UTC (Z)
                dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                dt_utc7 = dt + timedelta(hours=7)
                created = dt_utc7.strftime("%d/%m/%Y %H:%M:%S UTC+7")
            except Exception:
                pass

        metrics = tweet.get("public_metrics", {})
        likes = metrics.get("like_count", 0)

        # ── Resolve full text ──
        if tweet.get("note_tweet"):
            text = tweet["note_tweet"].get("text", tweet.get("text", ""))
        else:
            text = tweet.get("text", "")

        # ── Retweet: replace capped "RT @user: ..." with full content ──
        ref_tweets = tweet.get("referenced_tweets", [])
        rt_of = None
        qt_of = None
        for ref in (ref_tweets or []):
            if ref.get("type") == "retweeted":
                rt_of = ref["id"]
            elif ref.get("type") == "quoted":
                qt_of = ref["id"]

        # Local copy of attachments to avoid mutating the original tweet dict
        tweet_attachments = dict(tweet.get("attachments") or {})

        if rt_of and users_map:
            full_rt = users_map.get(f"__tweet_{rt_of}")
            if full_rt:
                orig_author_id = full_rt.get("author_id", "")
                orig_author = "@" + (users_map.get(orig_author_id, {}).get("username", "unknown"))
                if full_rt.get("note_tweet"):
                    full_text = full_rt["note_tweet"].get("text", full_rt.get("text", ""))
                else:
                    full_text = full_rt.get("text", "")
                text = f"[RT cua {orig_author} (ID: {rt_of})]: {full_text}"
                if "attachments" in full_rt and not tweet_attachments:
                    tweet_attachments = dict(full_rt["attachments"])

        if qt_of and users_map:
            full_qt = users_map.get(f"__tweet_{qt_of}")
            if full_qt:
                orig_author_id = full_qt.get("author_id", "")
                orig_author = "@" + (users_map.get(orig_author_id, {}).get("username", "unknown"))
                qt_text = full_qt.get("text", "")
                text += f"\n  [Trich dan {orig_author} (ID: {qt_of})]: {qt_text}"
                if "attachments" in full_qt and not tweet_attachments:
                    tweet_attachments = dict(full_qt["attachments"])

        # ── Media URLs ──
        media_urls = []
        for mk in (tweet_attachments.get("media_keys") or []):
            media_obj = users_map.get(f"__media_{mk}") if users_map else None
            if media_obj:
                mtype = media_obj.get("type", "media")
                url = media_obj.get("url") or media_obj.get("preview_image_url", "")
                if mtype == "video" and media_obj.get("variants"):
                    video_variants = [
                        v for v in media_obj["variants"]
                        if v.get("content_type", "").startswith("video")
                    ]
                    if video_variants:
                        best = max(video_variants, key=lambda v: v.get("bit_rate", 0))
                        url = best.get("url", url)
                if url:
                    media_urls.append(f"[{mtype.upper()}] {url}")

        media_str = "  " + " | ".join(media_urls) if media_urls else ""
        entry = f"[{i}] {author} ({created}): {text} [Likes: {likes}]"
        if media_str:
            entry += f"\n{media_str}"

        lines.append(entry)

    return "\n\n".join(lines)


# ─────────────────────────────────────────────────
# Helper Functions (used by main.py CLI)
# ─────────────────────────────────────────────────

def format_tweet(tweet: dict, users_map: dict = None) -> str:
    """Format 1 tweet thành chuỗi text dễ đọc (CLI only)."""
    author_id = tweet.get("author_id", "")
    text = tweet.get("text", "")
    created_at = tweet.get("created_at", "")
    metrics = tweet.get("public_metrics", {})

    author_name = "Unknown"
    author_username = ""
    if users_map and author_id in users_map:
        author_name = users_map[author_id].get("name", "Unknown")
        author_username = users_map[author_id].get("username", "")

    time_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            dt_vn = dt + timedelta(hours=7)
            time_str = dt_vn.strftime("%d/%m/%Y %H:%M")
        except Exception:
            time_str = created_at

    likes = metrics.get("like_count", 0)
    retweets = metrics.get("retweet_count", 0)
    replies = metrics.get("reply_count", 0)

    is_retweet = False
    ref_tweets = tweet.get("referenced_tweets", [])
    if ref_tweets:
        for ref in ref_tweets:
            if ref.get("type") == "retweeted":
                is_retweet = True
                break

    lines = []
    prefix = "RT boi" if is_retweet else ""
    lines.append(f"  {prefix} {author_name} (@{author_username})")
    lines.append(f"  {time_str}")
    lines.append(f"  {'-' * 55}")
    words = text.split()
    line_buf = "  "
    for word in words:
        if len(line_buf) + len(word) + 1 > 80:
            lines.append(line_buf)
            line_buf = "  " + word
        else:
            line_buf += (" " if line_buf.strip() else "") + word
    if line_buf.strip():
        lines.append(line_buf)
    lines.append(f"  {'-' * 55}")
    lines.append(f"  Likes: {likes}   Retweets: {retweets}   Replies: {replies}")

    return "\n".join(lines)


def build_users_map(includes: dict) -> dict:
    """Tạo dict mapping author_id → user info từ response includes."""
    users_map = {}
    if includes and "users" in includes:
        for user in includes["users"]:
            users_map[user["id"]] = user
    return users_map
