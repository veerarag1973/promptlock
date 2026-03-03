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

    def _get(self, endpoint: str, **params: Any) -> Any:
        resp = httpx.get(
            f"{self._base}{endpoint}",
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
    # Environments (v0.3)
    # ------------------------------------------------------------------

    def list_environments(self, cursor: Optional[str] = None, limit: int = 50) -> dict:
        """``GET /v1/environments`` — list org environments."""
        return self._get("/v1/environments", cursor=cursor, limit=limit)

    def create_environment(self, name: str, env_type: str = "custom", config: Optional[dict] = None) -> dict:
        """``POST /v1/environments`` — create a new environment."""
        return self._post(
            "/v1/environments",
            json={"name": name, "type": env_type, "config_json": config or {}},
        )

    # ------------------------------------------------------------------
    # Promotions (v0.3)
    # ------------------------------------------------------------------

    def create_promotion(
        self,
        prompt_path: str,
        from_env: str,
        to_env: str,
        version_num: int,
        sha256: str = "",
    ) -> dict:
        """``POST /v1/promotions`` — submit a promotion request (auto-approved in v0.3)."""
        return self._post(
            "/v1/promotions",
            json={
                "prompt_path": prompt_path,
                "from_environment": from_env,
                "to_environment": to_env,
                "version_num": version_num,
                "sha256": sha256,
            },
        )

    def list_promotions(
        self,
        prompt_path: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """``GET /v1/promotions`` — list promotions."""
        return self._get("/v1/promotions", prompt_path=prompt_path, cursor=cursor, limit=limit)

    def _patch(self, path: str, json: Any = None) -> Any:
        resp = httpx.patch(
            f"{self._base}{path}",
            json=json,
            headers=self._headers({"Content-Type": "application/json"}),
            timeout=self._timeout,
        )
        self._raise_for_status(resp)
        return resp.json()

    def update_promotion(self, promotion_id: str, status: str, comment: str = "") -> dict:
        """``PATCH /v1/promotions/{id}`` — approve or reject a promotion."""
        return self._patch(
            f"/v1/promotions/{promotion_id}",
            json={"status": status, "comment": comment},
        )

    # ------------------------------------------------------------------
    # Approval Workflow (v0.5)
    # ------------------------------------------------------------------

    def get_active_versions(self, env_name: str) -> dict:
        """``GET /v1/environments/{name}/active`` — active prompt versions."""
        return self._get(f"/v1/environments/{env_name}/active")

    def submit_review(self, promotion_id: str, decision: str, comment: str) -> dict:
        """``POST /v1/promotions/{id}/reviews`` — reviewer approve / reject."""
        return self._post(
            f"/v1/promotions/{promotion_id}/reviews",
            json={"decision": decision, "comment": comment},
        )

    def execute_promotion(self, promotion_id: str, comment: str = "") -> dict:
        """``POST /v1/promotions/{id}/execute`` — Deployer executes an approved promotion."""
        return self._post(
            f"/v1/promotions/{promotion_id}/execute",
            json={"comment": comment},
        )

    def bypass_approval(self, promotion_id: str, reason: str) -> dict:
        """``POST /v1/promotions/{id}/bypass`` — Org Admin emergency bypass."""
        return self._post(
            f"/v1/promotions/{promotion_id}/bypass",
            json={"reason": reason},
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """``GET /health`` — liveness probe."""
        return self._get("/health")
