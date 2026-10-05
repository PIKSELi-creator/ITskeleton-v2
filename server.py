import json
import os
import secrets
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from mcp.server import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from capcut_adapter import CapCutAdapter
from pipeline import (
    create_edit_plan as pipeline_create_edit_plan,
    create_script as pipeline_create_script,
    create_storyboard as pipeline_create_storyboard,
    ffprobe,
    render_from_plan,
    run_pipeline as pipeline_run_pipeline,
    video_dir,
)
from renderer import render_video_file
from storage import token_storage_ready
from tiktok_api import TikTokAPI

load_dotenv()

APP_NAME = "ITskeleton"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", os.getenv("BASE_URL", "")).rstrip("/")
API_KEY = os.getenv("MCP_API_KEY", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", API_KEY or secrets.token_urlsafe(32))
DEFAULT_REDIRECT = (
    f"{PUBLIC_BASE_URL}/auth/tiktok/callback"
    if PUBLIC_BASE_URL
    else ""
)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def tiktok_client_key() -> str:
    return env("TIKTOK_CLIENT_KEY")


def tiktok_client_secret() -> str:
    return env("TIKTOK_CLIENT_SECRET")


def tiktok_redirect_uri_value() -> str:
    return env("TIKTOK_REDIRECT_URI", DEFAULT_REDIRECT)


def tiktok_scopes() -> str:
    return env(
        "TIKTOK_SCOPES",
        "user.info.basic,user.info.stats,video.list,video.publish",
    )


VIDEO_OUTPUT_DIR = video_dir()
VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

capcut = CapCutAdapter()
tiktok = TikTokAPI()

mcp = MCPServer(
    "ITskeleton MCP",
    instructions=(
        "Claude controls ITskeleton: script, storyboard, edit plan, FFmpeg render, "
        "safe TikTok Direct Post, status, stats and analytics. "
        "Never publish unless confirm=true."
    ),
)


def external_base_url(request: Request) -> str:
    return PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


def oauth_redirect_uri(request: Request) -> str:
    return (
        tiktok_redirect_uri_value()
        or f"{external_base_url(request)}/auth/tiktok/callback"
    )


def require_key(value: Optional[str]) -> None:
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail="MCP_API_KEY is not configured",
        )

    if not value or not secrets.compare_digest(value, API_KEY):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )


def setup_status(request: Request | None = None) -> dict[str, Any]:
    storage_ok, storage_msg = token_storage_ready()
    base = (
        PUBLIC_BASE_URL
        or (external_base_url(request) if request else "")
    )

    return {
        "mcp": {
            "configured": bool(API_KEY),
            "endpoint": (
                f"{base}/mcp"
                if base
                else "/mcp"
            ),
        },
        "oauth": {
            "client_key_configured": bool(
                tiktok_client_key()
            ),
            "client_secret_configured": bool(
                tiktok_client_secret()
            ),
            "redirect_uri": (
                tiktok_redirect_uri_value()
                or (
                    f"{base}/auth/tiktok/callback"
                    if base
                    else "not configured"
                )
            ),
            "scopes": tiktok_scopes(),
            "token_storage_ready": storage_ok,
            "token_storage_message": storage_msg,
        },
        "tiktok": tiktok.status(),
        "video": {
            "output_dir": str(VIDEO_OUTPUT_DIR),
            "exists": VIDEO_OUTPUT_DIR.exists(),
            "renderer": "ffmpeg",
        },
        "capcut": capcut.status(),
        "publish_safety": (
            "publish_video and run_pipeline require "
            "confirm=true for TikTok publication"
        ),
    }


def latest_video() -> Path | None:
    files = sorted(
        VIDEO_OUTPUT_DIR.glob("*.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def publish_preview(
    path: Path,
    title: str,
    description: str = "",
    privacy_level: str = "SELF_ONLY",
    disable_duet: bool = False,
    disable_comment: bool = False,
    disable_stitch: bool = False,
) -> dict[str, Any]:
    probe = ffprobe(path)

    return {
        "requires_confirmation": True,
        "confirm_required_value": True,
        "title": title,
        "description": description,
        "privacy_level": privacy_level,
        "interaction_settings": {
            "disable_duet": disable_duet,
            "disable_comment": disable_comment,
            "disable_stitch": disable_stitch,
        },
        "file": str(path),
        "duration_seconds": probe.get("duration_seconds"),
        "size_bytes": probe.get("size_bytes"),
    }


@mcp.tool()
def project_status() -> dict:
    """Return production readiness, TikTok, MCP, CapCut and rendered video status."""
    return {
        **setup_status(),
        "videos": [
            p.name
            for p in sorted(
                VIDEO_OUTPUT_DIR.glob("*.mp4")
            )
        ],
    }


@mcp.tool()
def create_script(
    topic: str,
    tone: str = "clear, witty, practical",
    seconds: int = 40,
) -> dict:
    """Create an ITskeleton script for a short Python video."""
    return pipeline_create_script(
        topic,
        tone=tone,
        seconds=seconds,
    )


@mcp.tool()
def create_storyboard(script: dict) -> dict:
    """Create a 9:16 1080x1920 storyboard from a script."""
    return pipeline_create_storyboard(script)


@mcp.tool()
def create_edit_plan(
    script: dict,
    storyboard: dict,
) -> dict:
    """Create FFmpeg timeline plus CapCut-compatible manifest path."""
    return pipeline_create_edit_plan(
        script,
        storyboard,
    )


@mcp.tool()
def render_video(
    edit_plan: dict | None = None,
    output_name: str | None = None,
    image_files: list[str] | None = None,
    audio_file: Optional[str] = None,
    topic: str = "Python debugging",
) -> dict:
    """Render a real vertical MP4. Uses edit_plan, or images, or creates a topic video."""

    if edit_plan:
        return render_from_plan(edit_plan)

    if image_files:
        output = VIDEO_OUTPUT_DIR / (
            output_name or "itskeleton.mp4"
        )

        if output.suffix.lower() != ".mp4":
            output = output.with_suffix(".mp4")

        return render_video_file(
            image_files,
            audio_file,
            output,
        )

    script = pipeline_create_script(topic)
    storyboard = pipeline_create_storyboard(script)
    plan = pipeline_create_edit_plan(
        script,
        storyboard,
    )

    return render_from_plan(plan)


@mcp.tool()
def connect_tiktok() -> dict:
    """Return OAuth start URL and setup status for connecting TikTok."""

    base = (
        PUBLIC_BASE_URL
        or "https://itskeleton-skeleton.mia0.amvera.tech"
    )

    return {
        "connected": tiktok.connected(),
        "start_url": f"{base}/auth/tiktok/start",
        "status_url": f"{base}/auth/tiktok/status",
        "setup": setup_status(),
    }


@mcp.tool()
def publish_video(
    video_file: str,
    title: str,
    description: str = "",
    confirm: bool = False,
    is_aigc: bool = True,
    privacy_level: str = "SELF_ONLY",
    disable_duet: bool = False,
    disable_comment: bool = False,
    disable_stitch: bool = False,
) -> dict:
    """Publish a finished MP4 to TikTok Direct Post only when confirm=true."""

    path = Path(video_file)

    if not path.is_absolute():
        path = VIDEO_OUTPUT_DIR / video_file

    if not path.exists():
        raise ValueError(
            f"Video not found: {path}"
        )

    preview = publish_preview(
        path,
        title,
        description,
        privacy_level,
        disable_duet,
        disable_comment,
        disable_stitch,
    )

    if not confirm:
        return {
            "published": False,
            **preview,
            "message": (
                "Publication blocked. "
                "Ask the user to confirm with confirm=true."
            ),
        }

    result = tiktok.publish_video(
        path,
        title=title,
        description=description,
        is_aigc=is_aigc,
        privacy_level=privacy_level,
        disable_duet=disable_duet,
        disable_comment=disable_comment,
        disable_stitch=disable_stitch,
    )

    return {
        "preview": preview,
        "tiktok": result,
    }


@mcp.tool()
def publish_status(
    publish_id: str,
) -> dict:
    """Check TikTok Direct Post publish status using official status endpoint."""
    return tiktok.publish_status(publish_id)


@mcp.tool()
def get_account_stats() -> dict:
    """Get TikTok creator/user statistics provided by TikTok user.info."""
    return tiktok.get_account_stats()


@mcp.tool()
def get_videos(
    max_count: int = 20,
) -> dict:
    """Get TikTok video list and available per-video statistics."""
    return tiktok.get_videos(
        max_count=max_count
    )


@mcp.tool()
def analyze_performance(
    max_count: int = 20,
) -> dict:
    """Analyze real TikTok video stats and recommend the next ITskeleton topic."""

    data = tiktok.get_videos(
        max_count=max_count
    )

    videos = data.get(
        "videos",
        []
    )

    enriched = []

    for v in videos:
        views = int(
            v.get("view_count") or 0
        )

        likes = int(
            v.get("like_count") or 0
        )

        comments = int(
            v.get("comment_count") or 0
        )

        shares = int(
            v.get("share_count") or 0
        )

        engagement = (
            None
            if views <= 0
            else round(
                (
                    likes
                    + comments
                    + shares
                )
                / views,
                4,
            )
        )

        item = dict(v)
        item["engagement_rate"] = engagement
        enriched.append(item)

    ranked = sorted(
        enriched,
        key=lambda x: (
            x.get("view_count") or 0,
            x.get("engagement_rate") or 0,
        ),
        reverse=True,
    )

    weak = sorted(
        enriched,
        key=lambda x: (
            x.get("view_count") or 0,
            x.get("engagement_rate") or 0,
        ),
    )[:3]

    best_titles = [
        x.get("title")
        or x.get("video_description")
        or x.get("id")
        for x in ranked[:3]
    ]

    return {
        "count": len(enriched),
        "best_videos": ranked[:5],
        "weak_videos": weak,
        "recommendations": [
            "Use the hook pattern from the best videos listed above.",
            (
                "Repeat topics with high engagement_rate; "
                "avoid topics with low views and low engagement."
            ),
            (
                "For the next ITskeleton video, open with "
                "a concrete Python pain point, then show one "
                "tiny runnable example."
            ),
        ],
        "best_topic_signals": best_titles,
        "note": (
            "Only metrics returned by TikTok API are used; "
            "missing metrics are not invented."
        ),
    }


@mcp.tool()
def run_pipeline(
    topic: str,
    publish: bool = False,
    confirm: bool = False,
    title: str | None = None,
    description: str = "",
    privacy_level: str = "SELF_ONLY",
) -> dict:
    """Run script->storyboard->edit plan->render->optional confirmed TikTok publish->analytics."""

    options = {
        "title": title or f"ITskeleton: {topic}",
        "description": description,
        "privacy_level": privacy_level,
    }

    result = pipeline_run_pipeline(
        topic,
        publish=publish,
        confirm=confirm,
        publisher=lambda path, **opts: (
            tiktok.publish_video(
                path,
                **opts,
            )
        ),
        publish_options=options,
    )

    if tiktok.connected():
        try:
            result["analytics"] = analyze_performance(
                max_count=10
            )
        except Exception as exc:
            result["analytics_error"] = str(exc)

    return result


app = FastAPI(
    title=APP_NAME
)


app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=bool(
        PUBLIC_BASE_URL
        and PUBLIC_BASE_URL.startswith(
            "https://"
        )
    ),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [PUBLIC_BASE_URL]
        if PUBLIC_BASE_URL
        else []
    ),
    allow_methods=[
        "GET",
        "POST",
    ],
    allow_headers=[
        "X-API-Key",
        "Content-Type",
    ],
    allow_credentials=True,
)


class MCPAuthMiddleware(
    BaseHTTPMiddleware
):
    async def dispatch(
        self,
        request,
        call_next,
    ):
        if (
            request.url.path == "/mcp"
            or request.url.path.startswith("/mcp/")
        ):
            if not API_KEY:
                return JSONResponse(
                    {
                        "detail": (
                            "MCP_API_KEY is not configured"
                        )
                    },
                    status_code=503,
                )

            supplied = request.headers.get(
                "X-API-Key"
            )

            if (
                not supplied
                or not secrets.compare_digest(
                    supplied,
                    API_KEY,
                )
            ):
                return JSONResponse(
                    {
                        "detail": (
                            "Invalid API key"
                        )
                    },
                    status_code=401,
                )

        return await call_next(request)


app.add_middleware(
    MCPAuthMiddleware
)

mcp_app = mcp.streamable_http_app()


def page(
    title: str,
    body: str,
) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<meta name='viewport'
content='width=device-width,initial-scale=1'>
<title>{title} — ITskeleton</title>
<style>
body{{
    font-family:
        system-ui,
        -apple-system,
        sans-serif;
    background:#111;
    color:#eee;
    max-width:1050px;
    margin:0 auto;
    padding:28px;
    line-height:1.55
}}

a{{
    color:#c8a7ff
}}

.card{{
    background:#1c1c1c;
    border:1px solid #333;
    border-radius:16px;
    padding:22px;
    margin:16px 0
}}

.btn{{
    display:inline-block;
    margin:6px 8px 6px 0;
    padding:12px 18px;
    background:#7c4dff;
    color:#fff;
    border-radius:10px;
    text-decoration:none;
    font-weight:700;
    border:0
}}

.danger{{
    background:#b3261e
}}

code,pre{{
    background:#0b0b0b;
    padding:3px 6px;
    border-radius:6px
}}

small{{
    color:#aaa
}}

.ok{{
    color:#8df0a4
}}

.bad{{
    color:#ffb4ab
}}
</style>
</head>
<body>
<h1>ITskeleton</h1>
{body}
<hr>
<small>
<a href='/privacy'>Privacy Policy</a>
 ·
<a href='/terms'>Terms of Service</a>
 ·
<a href='/health'>Health</a>
</small>
</body>
</html>"""


@app.exception_handler(Exception)
async def unhandled_exception(
    request: Request,
    exc: Exception,
):
    """Keep unexpected errors from becoming an opaque proxy 500 page; log details to Uvicorn."""

    import traceback

    traceback.print_exc()

    if (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/mcp")
    ):
        return JSONResponse(
            {
                "ok": False,
                "error": type(exc).__name__,
                "detail": str(exc),
            },
            status_code=500,
        )

    return HTMLResponse(
        page(
            "ITskeleton error",
            (
                "<div class='card'>"
                "<h2>ITskeleton is running</h2>"
                "<p class='bad'>"
                "An internal error occurred while processing this page."
                "</p>"
                f"<p><code>"
                f"{type(exc).__name__}: {exc}"
                f"</code></p>"
                "<p>"
                "Open <a href='/health'>/health</a> "
                "to verify the server and check Amvera logs "
                "for the full traceback."
                "</p>"
                "</div>"
            ),
        ),
        status_code=500,
    )


@app.get(
    "/",
    response_class=HTMLResponse,
)
def root(
    request: Request,
):
    """Render the dashboard without allowing optional subsystem failures to cause HTTP 500."""

    errors: list[str] = []

    try:
        status = setup_status(
            request
        )
    except Exception as exc:
        status = {
            "error": "setup_status failed"
        }
        errors.append(
            "Setup status error: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        connected = bool(
            tiktok.connected()
        )
    except Exception as exc:
        connected = False
        errors.append(
            "TikTok status error: "
            f"{type(exc).__name__}: {exc}"
        )

    mcp_state = (
        "Configured"
        if API_KEY
        else "Not configured: add MCP_API_KEY"
    )

    try:
        latest = latest_video()
    except Exception as exc:
        latest = None
        errors.append(
            "Video scan error: "
            f"{type(exc).__name__}: {exc}"
        )

    if latest:
        try:
            probe = ffprobe(latest)

            size = probe.get(
                "size_bytes",
                "unknown",
            )

            latest_html = (
                f"<p>Latest video: "
                f"<code>{latest.name}</code> "
                f"({size} bytes)</p>"
            )

        except Exception as exc:
            latest_html = (
                f"<p>Latest video: "
                f"<code>{latest.name}</code></p>"
                f"<p class='bad'>"
                f"Video probe error: "
                f"{type(exc).__name__}: {exc}"
                f"</p>"
            )

            errors.append(
                "Video probe error: "
                f"{type(exc).__name__}: {exc}"
            )
    else:
        latest_html = (
            "<p>No rendered videos yet.</p>"
        )

    missing = []

    try:
        if not tiktok_client_key():
            missing.append(
                "TIKTOK_CLIENT_KEY"
            )

        if not tiktok_client_secret():
            missing.append(
                "TIKTOK_CLIENT_SECRET"
            )

    except Exception as exc:
        errors.append(
            "TikTok environment error: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        storage_ok, _storage_msg = (
            token_storage_ready()
        )

        if not storage_ok:
            missing.append(
                "TOKEN_ENCRYPTION_KEY"
            )

    except Exception as exc:
        errors.append(
            "Token storage error: "
            f"{type(exc).__name__}: {exc}"
        )

    missing_html = (
        ""
        if not missing
        else (
            "<p class='bad'>"
            "Missing for OAuth/publishing: "
            f"{', '.join(missing)}"
            "</p>"
        )
    )

    errors_html = ""

    if errors:
        safe_errors = "<br>".join(errors)

        errors_html = (
            "<div class='card'>"
            "<h3>Non-fatal diagnostics</h3>"
            f"<p class='bad'>{safe_errors}</p>"
            "</div>"
        )

    try:
        capcut_status = capcut.status()

    except Exception as exc:
        capcut_status = {
            "error": (
                f"{type(exc).__name__}: {exc}"
            )
        }

        errors.append(
            "CapCut status error: "
            f"{type(exc).__name__}: {exc}"
        )

    body = f"""
<div class='card'>
<h2>
TikTok status:
<span class='{"ok" if connected else "bad"}'>
{"Connected" if connected else "Not connected"}
</span>
</h2>

{missing_html}

<a class='btn'
href='/auth/tiktok/start'>
Connect TikTok
</a>

<form
style='display:inline'
method='post'
action='/auth/tiktok/disconnect'>
<button
class='btn danger'
type='submit'>
Disconnect TikTok
</button>
</form>

<a class='btn'
href='/api/create-video?topic=Python%20debugging'>
Create Video
</a>

<a class='btn'
href='/api/render-video?topic=Python%20debugging'>
Render Video
</a>

<a class='btn'
href='/api/publish-preview'>
Publish Video
</a>

<a class='btn'
href='/api/statistics'>
Statistics
</a>

<a class='btn'
href='/api/analytics'>
Analytics
</a>
</div>

<div class='card'>
<h3>MCP status</h3>
<p>{mcp_state}</p>
<p>
Endpoint:
<code>
{external_base_url(request)}/mcp
</code>
</p>
</div>

<div class='card'>
<h3>Video pipeline</h3>
<p>
Renderer: real FFmpeg MP4,
1080x1920, H.264, subtitles,
transitions plan, saved in
<code>{VIDEO_OUTPUT_DIR}</code>.
</p>

{latest_html}

<p>
CapCut: {capcut_status}
</p>
</div>

<div class='card'>
<h3>Configuration</h3>
<pre>
{json.dumps(
    status,
    ensure_ascii=False,
    indent=2,
    default=str
)}
</pre>
</div>

{errors_html}
"""

    return page(
        "Dashboard",
        body,
    )


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": APP_NAME,
        "video_dir": str(
            VIDEO_OUTPUT_DIR
        ),
    }


@app.get(
    "/privacy",
    response_class=HTMLResponse,
)
def privacy():
    return page(
        "Privacy Policy",
        (
            "<div class='card'>"
            "<h2>Privacy Policy</h2>"

            "<p>"
            "ITskeleton uses TikTok APIs only for "
            "account connection, video publishing "
            "and statistics requested by the operator."
            "</p>"

            "<p>"
            "OAuth tokens are stored server-side encrypted "
            "with TOKEN_ENCRYPTION_KEY. "
            "Client secrets and tokens are not shown in the UI "
            "and must not be committed to Git."
            "</p>"

            "<p>"
            "We do not sell personal data. "
            "You can disconnect TikTok from this dashboard "
            "or revoke access in TikTok settings."
            "</p>"

            "<p>"
            "<small>"
            "Last updated: 2026-10-04"
            "</small>"
            "</p>"

            "</div>"
        ),
    )


@app.get(
    "/terms",
    response_class=HTMLResponse,
)
def terms():
    return page(
        "Terms of Service",
        (
            "<div class='card'>"
            "<h2>Terms of Service</h2>"

            "<p>"
            "ITskeleton creates, renders, publishes and analyzes "
            "short educational programming videos only after "
            "explicit operator actions."
            "</p>"

            "<p>"
            "You are responsible for the TikTok account, scopes, "
            "app approval and content. "
            "Publishing requires confirm=true and uses "
            "TikTok official APIs."
            "</p>"

            "<p>"
            "The service is provided as-is and depends on "
            "third-party API availability and approval."
            "</p>"

            "<p>"
            "<small>"
            "Last updated: 2026-10-04"
            "</small>"
            "</p>"

            "</div>"
        ),
    )


@app.get("/auth/tiktok/start")
def auth_tiktok_start(
    request: Request,
):
    ready, msg = token_storage_ready()

    if not ready:
        raise HTTPException(
            status_code=500,
            detail=msg,
        )

    if (
        not tiktok_client_key()
        or not tiktok_client_secret()
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "TIKTOK_CLIENT_KEY and "
                "TIKTOK_CLIENT_SECRET "
                "are not configured"
            ),
        )

    redirect_uri = oauth_redirect_uri(
        request
    )

    if not redirect_uri.startswith(
        "https://"
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "TIKTOK_REDIRECT_URI must be HTTPS "
                "and must match TikTok Developer settings"
            ),
        )

    state = secrets.token_urlsafe(
        32
    )

    request.session[
        "tiktok_oauth_state"
    ] = state

    params = {
        "client_key": tiktok_client_key(),
        "response_type": "code",
        "scope": tiktok_scopes(),
        "redirect_uri": redirect_uri,
        "state": state,
    }

    return RedirectResponse(
        "https://www.tiktok.com/v2/auth/authorize/?"
        + urlencode(params)
    )


@app.get(
    "/auth/tiktok/callback",
    response_class=HTMLResponse,
)
def auth_tiktok_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    if error:
        return page(
            "TikTok connection",
            (
                "<div class='card'>"
                "<h2>Authorization failed</h2>"
                f"<p>{error}: "
                f"{error_description or ''}</p>"
                "</div>"
            ),
        )

    expected = request.session.pop(
        "tiktok_oauth_state",
        None,
    )

    if (
        not code
        or not state
        or not expected
        or not secrets.compare_digest(
            state,
            expected,
        )
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid OAuth state or "
                "missing authorization code"
            ),
        )

    try:
        tiktok.exchange_code(
            code,
            oauth_redirect_uri(request),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "TikTok token exchange failed: "
                f"{exc}"
            ),
        )

    return page(
        "TikTok connected",
        (
            "<div class='card'>"
            "<h2>TikTok connected</h2>"
            "<p>"
            "The account is connected and encrypted "
            "tokens were saved in /data."
            "</p>"
            "<a class='btn' href='/'>"
            "Back to dashboard"
            "</a>"
            "</div>"
        ),
    )


@app.get(
    "/auth/tiktok/status"
)
def auth_tiktok_status(
    request: Request,
):
    return setup_status(request)


@app.post(
    "/auth/tiktok/disconnect"
)
def auth_tiktok_disconnect():
    tiktok.disconnect()

    return RedirectResponse(
        "/",
        status_code=303,
    )


@app.get(
    "/tiktok/connect"
)
def old_tiktok_connect():
    return RedirectResponse(
        "/auth/tiktok/start"
    )


@app.get(
    "/tiktok/callback"
)
def old_tiktok_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    return auth_tiktok_callback(
        request,
        code,
        state,
        error,
        error_description,
    )


@app.get(
    "/api/create-video"
)
def api_create_video(
    topic: str = "Python debugging",
):
    script = pipeline_create_script(
        topic
    )

    storyboard = pipeline_create_storyboard(
        script
    )

    plan = pipeline_create_edit_plan(
        script,
        storyboard,
    )

    Path(
        plan["metadata_file"]
    ).write_text(
        json.dumps(
            {
                "script": script,
                "storyboard": storyboard,
                "edit_plan": plan,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "script": script,
        "storyboard": storyboard,
        "edit_plan": plan,
    }


@app.get(
    "/api/render-video"
)
def api_render_video(
    topic: str = "Python debugging",
):
    script = pipeline_create_script(
        topic
    )

    storyboard = pipeline_create_storyboard(
        script
    )

    plan = pipeline_create_edit_plan(
        script,
        storyboard,
    )

    return {
        "script": script,
        "storyboard": storyboard,
        "edit_plan": plan,
        "render": render_from_plan(
            plan
        ),
    }


@app.get(
    "/api/publish-preview"
)
def api_publish_preview(
    title: str = "ITskeleton video",
    description: str = "",
    privacy_level: str = "SELF_ONLY",
):
    path = latest_video()

    if not path:
        raise HTTPException(
            status_code=404,
            detail=(
                "No rendered MP4 found. "
                "Render a video first."
            ),
        )

    return publish_preview(
        path,
        title,
        description,
        privacy_level,
    )


@app.get(
    "/api/statistics"
)
def api_statistics():
    if not tiktok.connected():
        return {
            "connected": False,
            "message": (
                "Complete TikTok OAuth first. "
                "No fake statistics are returned."
            ),
        }

    return tiktok.get_account_stats()


@app.get(
    "/api/analytics"
)
def api_analytics():
    if not tiktok.connected():
        return {
            "connected": False,
            "message": (
                "Complete TikTok OAuth first. "
                "No fake analytics are returned."
            ),
        }

    return analyze_performance(
        max_count=20
    )


@app.get(
    "/mcp"
)
async def mcp_get(
    x_api_key: Optional[str] = Header(None),
):
    require_key(
        x_api_key
    )

    return HTMLResponse(
        "MCP endpoint is active. "
        "Use an MCP-compatible client with X-API-Key."
    )


app.mount(
    "/mcp",
    mcp_app,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "3000",
            )
        ),
    )