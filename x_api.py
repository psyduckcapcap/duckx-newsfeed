"""
X API v2 - Module giao tiếp với X (Twitter) API
================================================
Sử dụng OAuth 1.0a (4 keys) để xác thực user context.
Hỗ trợ lấy home timeline, user tweets, và thông tin user.
"""

import requests
from requests_oauthlib import OAuth1
from datetime import datetime, timezone


class XApiClient:
    """Client để giao tiếp với X API v2."""

    BASE_URL = "https://api.x.com/2"

    def __init__(self, api_key: str, api_secret: str, access_token: str, access_token_secret: str):
        """
        Khởi tạo client với OAuth 1.0a credentials.
        
        Args:
            api_key: API Key (Consumer Key)
            api_secret: API Key Secret (Consumer Secret)
            access_token: Access Token
            access_token_secret: Access Token Secret
        """
        self.auth = OAuth1(
            client_key=api_key,
            client_secret=api_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret,
        )
        self._user_id = None
        self._username = None

    def _make_request(self, method: str, endpoint: str, params: dict = None) -> dict:
        """
        Gửi HTTP request đến X API.
        
        Args:
            method: "GET" hoặc "POST"
            endpoint: API endpoint path (vd: "/users/me")
            params: Query parameters
            
        Returns:
            dict: JSON response từ API
            
        Raises:
            Exception: Nếu API trả về lỗi
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        response = requests.request(
            method=method,
            url=url,
            auth=self.auth,
            params=params,
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            raise Exception(
                "❌ Lỗi xác thực (401). Kiểm tra lại API keys.\n"
                "   Đảm bảo rằng Access Token có quyền Read."
            )
        elif response.status_code == 403:
            raise Exception(
                "❌ Bị từ chối truy cập (403). Có thể do:\n"
                "   - Chưa nạp credits (pay-per-use)\n"
                "   - API Key không có quyền truy cập endpoint này\n"
                "   - Tài khoản Dev chưa được kích hoạt đầy đủ"
            )
        elif response.status_code == 429:
            raise Exception(
                "⏳ Rate limit exceeded (429). Bạn đã gửi quá nhiều request.\n"
                "   Hãy đợi vài phút rồi thử lại."
            )
        else:
            error_detail = response.text
            raise Exception(
                f"❌ Lỗi API ({response.status_code}): {error_detail}"
            )

    # ─────────────────────────────────────────────
    # User Info
    # ─────────────────────────────────────────────

    def get_me(self) -> dict:
        """
        Lấy thông tin user đang xác thực (bạn).
        
        Endpoint: GET /2/users/me
        Cost: $0.010 per request (User: Read)
        
        Returns:
            dict: Thông tin user (id, name, username, ...)
        """
        params = {
            "user.fields": "id,name,username,description,profile_image_url,public_metrics,created_at",
        }
        result = self._make_request("GET", "/users/me", params=params)
        
        # Cache user ID cho các request khác
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
        """
        Lấy Home Timeline - tweets từ các accounts bạn follow.
        
        Endpoint: GET /2/users/:id/timelines/reverse_chronological
        Cost: $0.005 per post (Posts: Read)
        
        Args:
            max_results: Số tweets tối đa (10-100, mặc định 20)
            pagination_token: Token để lấy trang tiếp theo
            
        Returns:
            dict: Danh sách tweets với thông tin chi tiết
        """
        user_id = self.get_user_id()
        
        params = {
            "max_results": min(max(max_results, 10), 100),  # Giới hạn 10-100
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
        """
        Lấy tweets của một user cụ thể.
        
        Endpoint: GET /2/users/:id/tweets
        Cost: $0.005 per post (Posts: Read)
        
        Args:
            user_id: User ID (ưu tiên dùng)
            username: Username (sẽ tự tìm user_id nếu không có user_id)
            max_results: Số tweets tối đa (5-100, mặc định 10)
            
        Returns:
            dict: Danh sách tweets
        """
        if user_id is None and username is None:
            raise ValueError("Phải cung cấp user_id hoặc username")
        
        # Nếu chỉ có username, tìm user_id
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
        """
        Tìm thông tin user bằng username.
        
        Endpoint: GET /2/users/by/username/:username
        Cost: $0.010 per request (User: Read)
        
        Args:
            username: Username (không có @)
            
        Returns:
            dict: Thông tin user
        """
        # Bỏ @ nếu có
        username = username.lstrip("@")
        
        params = {
            "user.fields": "id,name,username,description,public_metrics,profile_image_url",
        }
        
        return self._make_request("GET", f"/users/by/username/{username}", params=params)

    # ─────────────────────────────────────────────
    # Watchlist - Batch fetch from multiple users
    # ─────────────────────────────────────────────

    def get_watchlist_tweets(self, usernames: list, max_per_user: int = 10, since_ids: dict = None) -> dict:
        """
        Lấy tweets mới từ nhiều users (watchlist).
        
        Args:
            usernames: Danh sách usernames
            max_per_user: Số tweets tối đa mỗi user (1-100)
            since_ids: Dict {username: last_tweet_id} để chỉ lấy tweets mới
            
        Returns:
            dict: {
                "tweets": [list of all tweets sorted by time],
                "users_map": {author_id: user_info},
                "new_since_ids": {username: newest_tweet_id},
                "errors": {username: error_message}
            }
        """
        if since_ids is None:
            since_ids = {}

        all_tweets = []
        users_map = {}
        new_since_ids = {}
        errors = {}

        for username in usernames:
            try:
                # Lookup user ID
                user_info = self.get_user_by_username(username)
                if "data" not in user_info:
                    errors[username] = "User not found"
                    continue

                uid = user_info["data"]["id"]
                users_map[uid] = user_info["data"]

                # Build params
                params = {
                    "max_results": min(max(max_per_user, 5), 100), # Twitter API requires between 5 and 100
                    # Only original tweets + retweets (no replies)
                    "exclude": "replies",
                    "tweet.fields": "created_at,author_id,text,public_metrics,lang,referenced_tweets,attachments,note_tweet",
                    # author_id        → expand user info
                    # referenced_tweets.id → expand full content of retweeted tweets
                    # attachments.media_keys → expand media (photo/video)
                    "expansions": "author_id,referenced_tweets.id,referenced_tweets.id.author_id,referenced_tweets.id.attachments.media_keys,attachments.media_keys",
                    "user.fields": "name,username,profile_image_url",
                    # Get media URL, type, preview
                    "media.fields": "type,url,preview_image_url,variants",
                }

                sid = since_ids.get(username.lower())
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
                # key: tweet_id → full tweet object from includes.tweets
                if includes and "tweets" in includes:
                    for ref_t in includes["tweets"]:
                        users_map[f"__tweet_{ref_t['id']}"] = ref_t

                # Build media map: media_key → media object
                if includes and "media" in includes:
                    for media_obj in includes["media"]:
                        users_map[f"__media_{media_obj['media_key']}"] = media_obj

                # Track newest tweet ID for dedup next time
                if tweets:
                    new_since_ids[username.lower()] = tweets[0]["id"]

                all_tweets.extend(tweets)

            except Exception as e:
                errors[username] = str(e)

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
        }


def tweets_to_text(tweets: list, users_map: dict) -> str:
    """
    Convert list of tweets to plain text for AI summarization.
    Resolves full retweet content and appends media URLs.

    Returns:
        str: All tweets as formatted text block
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
                # Convert "2026-03-23T12:10:01.000Z" to datetime
                from datetime import datetime, timedelta
                dt = datetime.strptime(created_raw, "%Y-%m-%dT%H:%M:%S.%fZ")
                # Add 7 hours for UTC+7
                dt_utc7 = dt + timedelta(hours=7)
                created = dt_utc7.strftime("%d/%m/%Y %H:%M:%S UTC+7")
            except Exception:
                pass

        metrics = tweet.get("public_metrics", {})
        likes = metrics.get("like_count", 0)

        # ── Resolve full text ──────────────────────────────────────
        # If note_tweet exists, prefer it (supports > 280 chars)
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

        rt_label = ""
        if rt_of and users_map:
            full_rt = users_map.get(f"__tweet_{rt_of}")
            if full_rt:
                # Get original author name
                orig_author_id = full_rt.get("author_id", "")
                orig_author = "@" + (users_map.get(orig_author_id, {}).get("username", "unknown"))
                # Prefer note_tweet for long posts
                if full_rt.get("note_tweet"):
                    full_text = full_rt["note_tweet"].get("text", full_rt.get("text", ""))
                else:
                    full_text = full_rt.get("text", "")
                text = f"[RT của {orig_author} (ID: {rt_of})]: {full_text}"
                rt_label = f" (RT @{orig_author_id})"
                # Map attachments from original tweet to the wrapper tweet
                if "attachments" in full_rt:
                    tweet["attachments"] = full_rt["attachments"]

        if qt_of and users_map:
            full_qt = users_map.get(f"__tweet_{qt_of}")
            if full_qt:
                orig_author_id = full_qt.get("author_id", "")
                orig_author = "@" + (users_map.get(orig_author_id, {}).get("username", "unknown"))
                qt_text = full_qt.get("text", "")
                text += f"\n  [Trích dẫn {orig_author} (ID: {qt_of})]: {qt_text}"
                # Map attachments from quoted tweet if wrapper doesn't have its own
                if "attachments" in full_qt and "attachments" not in tweet:
                    tweet["attachments"] = full_qt["attachments"]

        # ── Media URLs ─────────────────────────────────────────────
        media_urls = []
        attachments = tweet.get("attachments", {})
        for mk in (attachments.get("media_keys") or []):
            media_obj = users_map.get(f"__media_{mk}") if users_map else None
            if media_obj:
                mtype = media_obj.get("type", "media")
                url = media_obj.get("url") or media_obj.get("preview_image_url", "")
                # For video, pick the highest bitrate variant
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
# Helper Functions
# ─────────────────────────────────────────────────

def format_tweet(tweet: dict, users_map: dict = None) -> str:
    """
    Format 1 tweet thành chuỗi text dễ đọc.
    
    Args:
        tweet: Tweet data từ API
        users_map: Dict mapping author_id → user info
        
    Returns:
        str: Tweet đã format đẹp
    """
    author_id = tweet.get("author_id", "")
    text = tweet.get("text", "")
    created_at = tweet.get("created_at", "")
    metrics = tweet.get("public_metrics", {})
    
    # Tìm tên tác giả
    author_name = "Unknown"
    author_username = ""
    if users_map and author_id in users_map:
        author_name = users_map[author_id].get("name", "Unknown")
        author_username = users_map[author_id].get("username", "")

    # Format thời gian
    time_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            # Chuyển sang giờ Việt Nam (UTC+7)
            from datetime import timedelta
            dt_vn = dt + timedelta(hours=7)
            time_str = dt_vn.strftime("%d/%m/%Y %H:%M")
        except Exception:
            time_str = created_at

    # Format metrics
    likes = metrics.get("like_count", 0)
    retweets = metrics.get("retweet_count", 0)
    replies = metrics.get("reply_count", 0)

    # Kiểm tra retweet
    is_retweet = False
    ref_tweets = tweet.get("referenced_tweets", [])
    if ref_tweets:
        for ref in ref_tweets:
            if ref.get("type") == "retweeted":
                is_retweet = True
                break

    # Build output
    lines = []
    prefix = "🔁 RT bởi" if is_retweet else "👤"
    lines.append(f"  {prefix} {author_name} (@{author_username})")
    lines.append(f"  🕐 {time_str}")
    lines.append(f"  {'-' * 55}")
    # Wrap text nếu quá dài
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
    """
    Tạo dict mapping author_id → user info từ response includes.
    
    Args:
        includes: "includes" section từ API response
        
    Returns:
        dict: {user_id: user_data}
    """
    users_map = {}
    if includes and "users" in includes:
        for user in includes["users"]:
            users_map[user["id"]] = user
    return users_map
