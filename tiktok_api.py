import json
import os
from pathlib import Path
from typing import Any, Optional

import requests

from storage import (
    delete_tokens,
    load_tokens,
    save_tokens,
)


class TikTokAPI:
    AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
    VIDEO_LIST_URL = "https://open.tiktokapis.com/v2/video/list/"
    VIDEO_INIT_URL = (
        "https://open.tiktokapis.com/v2/post/publish/video/init/"
    )
    PUBLISH_STATUS_URL = (
        "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
    )

    def __init__(self):
        self.client_key = os.getenv(
            "TIKTOK_CLIENT_KEY",
            "",
        )

        self.client_secret = os.getenv(
            "TIKTOK_CLIENT_SECRET",
            "",
        )

        self.redirect_uri = os.getenv(
            "TIKTOK_REDIRECT_URI",
            "",
        )

        self.timeout = int(
            os.getenv(
                "TIKTOK_HTTP_TIMEOUT",
                "60",
            )
        )

    def status(self) -> dict[str, Any]:
        tokens = load_tokens()

        return {
            "configured": bool(
                self.client_key
                and self.client_secret
            ),
            "connected": bool(tokens),
            "client_key_configured": bool(
                self.client_key
            ),
            "client_secret_configured": bool(
                self.client_secret
            ),
            "redirect_uri": self.redirect_uri,
        }

    def connected(self) -> bool:
        return bool(load_tokens())

    def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> requests.Response:
        kwargs.setdefault(
            "timeout",
            self.timeout,
        )

        response = requests.request(
            method,
            url,
            **kwargs,
        )

        return response

    def exchange_code(
        self,
        code: str,
        redirect_uri: Optional[str] = None,
    ) -> dict[str, Any]:

        if not self.client_key:
            raise RuntimeError(
                "TIKTOK_CLIENT_KEY is not configured"
            )

        if not self.client_secret:
            raise RuntimeError(
                "TIKTOK_CLIENT_SECRET is not configured"
            )

        redirect = (
            redirect_uri
            or self.redirect_uri
        )

        if not redirect:
            raise RuntimeError(
                "TIKTOK_REDIRECT_URI is not configured"
            )

        response = self._request(
            "POST",
            self.TOKEN_URL,
            headers={
                "Content-Type":
                    "application/x-www-form-urlencoded",
            },
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect,
            },
        )

        try:
            data = response.json()
        except Exception:
            data = {
                "raw": response.text
            }

        if not response.ok:
            raise RuntimeError(
                "TikTok token exchange failed: "
                f"HTTP {response.status_code}: "
                f"{data}"
            )

        if data.get("error"):
            raise RuntimeError(
                "TikTok OAuth error: "
                f"{data}"
            )

        save_tokens(data)

        return {
            "ok": True,
            "saved": True,
            "scope": data.get("scope"),
            "expires_in": data.get(
                "expires_in"
            ),
        }

    def disconnect(self) -> None:
        delete_tokens()

    def _access_token(self) -> str:
        tokens = load_tokens()

        if not tokens:
            raise RuntimeError(
                "TikTok is not connected"
            )

        token = tokens.get(
            "access_token"
        )

        if not token:
            raise RuntimeError(
                "TikTok access token is missing"
            )

        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization":
                f"Bearer {self._access_token()}",
            "Content-Type":
                "application/json",
        }

    def get_account_stats(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            self.USER_INFO_URL,
            headers=self._headers(),
            params={
                "fields": (
                    "open_id,"
                    "union_id,"
                    "avatar_url,"
                    "display_name,"
                    "follower_count,"
                    "following_count,"
                    "likes_count,"
                    "video_count"
                )
            },
        )

        return self._json_response(
            response,
            "TikTok user info",
        )

    def get_videos(
        self,
        max_count: int = 20,
    ) -> dict[str, Any]:

        max_count = max(
            1,
            min(
                int(max_count),
                20,
            ),
        )

        response = self._request(
            "POST",
            self.VIDEO_LIST_URL,
            headers=self._headers(),
            params={
                "fields": (
                    "id,"
                    "create_time,"
                    "cover_image_url,"
                    "share_url,"
                    "video_description,"
                    "duration,"
                    "height,"
                    "width,"
                    "title,"
                    "like_count,"
                    "comment_count,"
                    "share_count,"
                    "view_count"
                )
            },
            json={
                "max_count": max_count,
            },
        )

        return self._json_response(
            response,
            "TikTok video list",
        )

    def publish_video(
        self,
        path: Path,
        title: str,
        description: str = "",
        is_aigc: bool = True,
        privacy_level: str = "SELF_ONLY",
        disable_duet: bool = False,
        disable_comment: bool = False,
        disable_stitch: bool = False,
    ) -> dict[str, Any]:

        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(
                f"Video not found: {path}"
            )

        if path.suffix.lower() != ".mp4":
            raise ValueError(
                "TikTok Direct Post requires an MP4 file"
            )

        file_size = path.stat().st_size

        if file_size <= 0:
            raise ValueError(
                "Video file is empty"
            )

        payload = {
            "post_info": {
                "title": title,
                "description": description,
                "privacy_level": privacy_level,
                "disable_duet": disable_duet,
                "disable_comment": disable_comment,
                "disable_stitch": disable_stitch,
                "is_aigc": is_aigc,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            },
        }

        response = self._request(
            "POST",
            self.VIDEO_INIT_URL,
            headers=self._headers(),
            json=payload,
        )

        data = self._json_response(
            response,
            "TikTok video initialization",
        )

        upload_url = (
            data.get("data", {})
            .get("upload_url")
        )

        publish_id = (
            data.get("data", {})
            .get("publish_id")
        )

        if not upload_url:
            return {
                "initialized": True,
                "publish_id": publish_id,
                "response": data,
                "message": (
                    "TikTok initialized the post "
                    "but did not return an upload URL."
                ),
            }

        with path.open(
            "rb"
        ) as video_file:

            upload_response = self._request(
                "PUT",
                upload_url,
                headers={
                    "Content-Type":
                        "video/mp4",
                    "Content-Length":
                        str(file_size),
                    "Content-Range":
                        (
                            f"bytes 0-{file_size - 1}/"
                            f"{file_size}"
                        ),
                },
                data=video_file,
            )

        if not upload_response.ok:
            raise RuntimeError(
                "TikTok video upload failed: "
                f"HTTP "
                f"{upload_response.status_code}: "
                f"{upload_response.text}"
            )

        return {
            "initialized": True,
            "uploaded": True,
            "publish_id": publish_id,
            "status": (
                "/auth/tiktok/status"
            ),
        }

    def publish_status(
        self,
        publish_id: str,
    ) -> dict[str, Any]:

        if not publish_id:
            raise ValueError(
                "publish_id is required"
            )

        response = self._request(
            "POST",
            self.PUBLISH_STATUS_URL,
            headers=self._headers(),
            json={
                "publish_id": publish_id,
            },
        )

        return self._json_response(
            response,
            "TikTok publish status",
        )

    @staticmethod
    def _json_response(
        response: requests.Response,
        operation: str,
    ) -> dict[str, Any]:

        try:
            data = response.json()
        except Exception:
            data = {
                "raw": response.text
            }

        if not response.ok:
            raise RuntimeError(
                f"{operation} failed: "
                f"HTTP {response.status_code}: "
                f"{data}"
            )

        if isinstance(data, dict):
            error = data.get("error")

            if error:
                raise RuntimeError(
                    f"{operation} returned an error: "
                    f"{data}"
                )

        return data