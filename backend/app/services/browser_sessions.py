import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict

import httpx
from fastapi import HTTPException

from app.core.config import settings


def browser_profile_key(user_id: str) -> str:
    return hashlib.sha256(f"uniflow-claude-profile:{user_id}".encode("utf-8")).hexdigest()


def _viewer_token(profile_key: str, lifetime_seconds: int = 600) -> str:
    if not settings.browser_viewer_secret:
        raise HTTPException(status_code=503, detail="The hosted browser viewer secret is not configured.")
    payload = json.dumps(
        {"profile": profile_key, "exp": int(time.time()) + lifetime_seconds},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        settings.browser_viewer_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


class BrowserSessionClient:
    def __init__(self) -> None:
        self.base_url = settings.browser_service_url.rstrip("/")
        self.timeout = httpx.Timeout(35.0, connect=3.0)

    def _request(self, method: str, user_id: str, **kwargs: Any) -> Dict[str, Any]:
        if not settings.browser_service_token:
            raise HTTPException(status_code=503, detail="The hosted Claude browser service is not configured.")
        url = f"{self.base_url}/internal/sessions/{browser_profile_key(user_id)}"
        try:
            response = httpx.request(
                method,
                url,
                headers={"Authorization": f"Bearer {settings.browser_service_token}"},
                timeout=self.timeout,
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=503,
                detail=f"The hosted Claude browser service is unavailable: {error}",
            ) from error
        if not response.is_success:
            try:
                detail = response.json().get("detail", response.text)
            except (ValueError, AttributeError):
                detail = response.text
            raise HTTPException(status_code=response.status_code, detail=detail)
        return response.json()

    def open(self, user_id: str) -> Dict[str, Any]:
        profile_key = browser_profile_key(user_id)
        result = self._request("POST", user_id, json={"start_url": "https://claude.ai/new"})
        viewer_url = settings.browser_viewer_base_url.rstrip("/") + f"/viewer/{profile_key}#{_viewer_token(profile_key)}"
        return {
            "status": "ready",
            "active": bool(result.get("active")),
            "viewer_url": viewer_url,
            "message": "Your private Claude browser is ready. Sign in to Claude in the browser window to finish setup.",
        }

    def status(self, user_id: str) -> Dict[str, Any]:
        result = self._request("GET", user_id)
        result["viewer_url"] = None
        if result.get("active"):
            key = browser_profile_key(user_id)
            result["viewer_url"] = (
                settings.browser_viewer_base_url.rstrip("/")
                + f"/viewer/{key}#{_viewer_token(key)}"
            )
        return result

    def cdp_endpoint(self, user_id: str) -> str:
        state = self.status(user_id)
        port = state.get("cdp_port")
        if not state.get("active") or not port:
            raise RuntimeError("Your private Claude browser is not running. Connect Claude from settings and retry.")
        host = settings.browser_cdp_host
        try:
            import socket
            host_ip = socket.gethostbyname(host)
        except Exception:
            host_ip = host
        return f"http://{host_ip}:{port}"

    def disconnect(self, user_id: str) -> None:
        self._request("DELETE", user_id, params={"delete_profile": "true"})

    def stop(self, user_id: str) -> None:
        self._request("DELETE", user_id)

    def delete_profile(self, user_id: str) -> None:
        self._request("DELETE", user_id, params={"delete_profile": "true"})
