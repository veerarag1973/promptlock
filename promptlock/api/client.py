"""promptlock.api.client — HTTP wrapper for the promptlock Cloud Registry.

All requests are synchronous (the CLI is a single-threaded process).
``httpx`` is used instead of ``requests`` for its modern timeout handling,
built-in JSON support, and eventual async reuse in the API tests.

Usage::

    client = RegistryClient(base_url="http://localhost:8000", token="<jwt>")
    versions = client.list_versions(prompt_id="<uuid>")
"""

from __future__ import annotations

from typing import Any, Optional

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False


class RegistryClientError(Exception):
    """Raised for non-2xx HTTP responses from the registry API."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


def _require_httpx() -> None:
    if not _HTTPX_AVAILABLE:  # pragma: no cover
        from rich.console import Console

        Console().print(
            "[red]httpx is not installed.[/red] Run: pip install httpx"
        )
        raise SystemExit(1)


class RegistryClient:
    """Thin synchronous HTTP client for the promptlock Registry API.

    Parameters
    ----------
    base_url:
        Root URL of the registry, e.g. ``https://api.promptlock.io`` or
        ``http://localhost:8000``.
    token:
        JWT bearer token (optional for unauthenticated endpoints).
    timeout:
        Request timeout in seconds (default: 30).
    """

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        _require_httpx()
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, extra: Optional[dict] = None) -> dict:
        h: dict = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if extra:
            h.update(extra)
        return h

    def _raise_for_status(self, resp: "httpx.Response") -> None:
        if resp.is_error:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RegistryClientError(resp.status_code, str(detail))

    def _get(self, path: str, **params: Any) -> Any:
        resp = httpx.get(
            f"{self._base}{path}",
            params={k: v for k, v in params.items() if v is not None},
            headers=self._headers(),
            timeout=self._timeout,
        )
        self._raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, json: Any = None, files: Any = None) -> Any:
        headers = self._headers()
        if files is not None:
            # multipart/form-data — httpx handles Content-Type automatically
            headers.pop("Accept", None)
            resp = httpx.post(
                f"{self._base}{path}",
                files=files,
                headers=headers,
                timeout=self._timeout,
            )
        else:
            resp = httpx.post(
                f"{self._base}{path}",
                json=json,
                headers=self._headers({"Content-Type": "application/json"}),
                timeout=self._timeout,
            )
        self._raise_for_status(resp)
        return resp.json()

    def _delete(self, path: str) -> None:
        resp = httpx.delete(
            f"{self._base}{path}",
            headers=self._headers(),
            timeout=self._timeout,
        )
        self._raise_for_status(resp)

    # ------------------------------------------------------------------
    # Auth endpoints
    # ------------------------------------------------------------------

    def register(self, email: str, password: str, org_name: str) -> dict:
        """``POST /v1/auth/register``"""
        return self._post(
            "/v1/auth/register",
            json={"email": email, "password": password, "org_name": org_name},
        )

    def login(self, email: str, password: str) -> dict:
        """``POST /v1/auth/login`` — returns ``{access_token, org_id, email}``."""
        return self._post(
            "/v1/auth/login",
            json={"email": email, "password": password},
        )

    def logout(self) -> None:
        """``POST /v1/auth/logout``"""
        self._post("/v1/auth/logout")

    def me(self) -> dict:
        """``GET /v1/auth/me``"""
        return self._get("/v1/auth/me")

    # ------------------------------------------------------------------
    # Prompt endpoints
    # ------------------------------------------------------------------

    def create_prompt(self, name: str, path: str, description: str = "") -> dict:
        """``POST /v1/prompts`` — create or return existing prompt resource."""
        return self._post(
            "/v1/prompts",
            json={"name": name, "path": path, "description": description},
        )

    def list_prompts(
        self,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """``GET /v1/prompts`` — cursor-paginated prompt list."""
        return self._get("/v1/prompts", cursor=cursor, limit=limit)

    def push_version(
        self,
        prompt_id: str,
        sha256: str,
        version_num: int,
        message: str,
        author: str,
        environment: str,
        content: bytes,
        tags: Optional[list] = None,
    ) -> dict:
        """``POST /v1/prompts/{id}/versions`` — push a new version blob.

        The content is sent as a multipart file upload so that large
        prompts stream efficiently without buffering the full body as
        JSON.
        """
        return self._post(
            f"/v1/prompts/{prompt_id}/versions",
            files={
                "content": ("prompt.txt", content, "text/plain"),
                "sha256": (None, sha256),
                "version_num": (None, str(version_num)),
                "message": (None, message),
                "author": (None, author),
                "environment": (None, environment),
                "tags": (None, ",".join(tags) if tags else ""),
            },
        )

    def list_versions(
        self,
        prompt_id: str,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """``GET /v1/prompts/{id}/versions``"""
        return self._get(
            f"/v1/prompts/{prompt_id}/versions",
            cursor=cursor,
            limit=limit,
        )

    def get_version(self, prompt_id: str, version: str) -> dict:
        """``GET /v1/prompts/{id}/versions/{version}``"""
        return self._get(f"/v1/prompts/{prompt_id}/versions/{version}")

    def get_prompt_by_path(self, path: str) -> Optional[dict]:
        """Return the prompt record whose ``path`` matches, or ``None``."""
        result = self._get("/v1/prompts", path=path, limit=1)
        items = result.get("items", [])
        return items[0] if items else None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """``GET /health``"""
        resp = httpx.get(
            f"{self._base}/health",
            timeout=5.0,
        )
        self._raise_for_status(resp)
        return resp.json()
