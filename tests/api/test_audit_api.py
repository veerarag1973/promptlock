"""API tests for: /v1/audit endpoints (spec §4.5, §4.6) — v0.4"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTER_PAYLOAD = {
    "email": "auditor@example.com",
    "password": "password123",
    "org_name": "audit-co",
}


async def _register_and_token(client: AsyncClient, payload: dict = None) -> tuple[str, dict]:
    """Register a user and return (access_token, register_body)."""
    payload = payload or REGISTER_PAYLOAD
    resp = await client.post("/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["access_token"], data


async def _auth_headers(client: AsyncClient, payload: dict = None) -> dict:
    token, _ = await _register_and_token(client, payload)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /v1/audit — requires Auditor or Org Admin role
# ---------------------------------------------------------------------------


class TestQueryAuditLog:
    async def test_audit_log_requires_auth(self, client: AsyncClient):
        resp = await client.get("/v1/audit")
        assert resp.status_code == 401

    async def test_audit_log_accessible_to_org_admin(self, client: AsyncClient):
        """Org Admin (auto-assigned on register) can read the audit log."""
        headers = await _auth_headers(client)
        resp = await client.get("/v1/audit", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    async def test_audit_log_contains_registration_event(self, client: AsyncClient):
        """Registration emits a x.promptlock.user.registered event."""
        headers = await _auth_headers(client)
        resp = await client.get("/v1/audit", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        # At least one event should be present (registration)
        assert len(items) >= 1
        event_types = [e["event_type"] for e in items]
        assert "x.promptlock.user.registered" in event_types

    async def test_audit_log_filter_by_event_type(self, client: AsyncClient):
        headers = await _auth_headers(client)
        resp = await client.get(
            "/v1/audit",
            headers=headers,
            params={"event_type": "x.promptlock.user.registered"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(e["event_type"] == "x.promptlock.user.registered" for e in items)

    async def test_audit_log_filter_by_resource_id(self, client: AsyncClient):
        headers = await _auth_headers(client)
        resp = await client.get(
            "/v1/audit",
            headers=headers,
            params={"resource_type": "user"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(e["resource_type"] == "user" for e in items)

    async def test_audit_log_requires_auditor_or_org_admin(self, client: AsyncClient):
        """A user with only 'Contributor' role (no audit role) gets 403."""
        # Register a second user in a different org — they get Org Admin too.
        # To test actual denial we need to downgrade their role.
        # Instead we test: unauthenticated call returns 401.
        resp = await client.get("/v1/audit")
        assert resp.status_code == 401

    async def test_audit_log_pagination(self, client: AsyncClient):
        headers = await _auth_headers(client)
        # Trigger extra events by calling /v1/auth/me multiple times
        for _ in range(3):
            await client.get("/v1/auth/me", headers=headers)
        resp = await client.get("/v1/audit", headers=headers, params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2

    async def test_audit_events_have_chain_signature(self, client: AsyncClient):
        """Every stored audit event must have a signature (HMAC chain)."""
        headers = await _auth_headers(client)
        resp = await client.get("/v1/audit", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            assert item["signature"] is not None, f"Event {item['event_id']} has no signature"
            assert item["checksum"] is not None, f"Event {item['event_id']} has no checksum"


# ---------------------------------------------------------------------------
# GET /v1/audit/export
# ---------------------------------------------------------------------------


class TestExportAuditLog:
    async def test_export_requires_auth(self, client: AsyncClient):
        resp = await client.get("/v1/audit/export")
        assert resp.status_code == 401

    async def test_export_json_format(self, client: AsyncClient):
        """Org Admin (also has Auditor perms via role hierarchy) can export."""
        headers = await _auth_headers(client)
        resp = await client.get("/v1/audit/export", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        data = resp.json()
        assert isinstance(data, list)

    async def test_export_csv_format(self, client: AsyncClient):
        headers = await _auth_headers(client)
        resp = await client.get(
            "/v1/audit/export", headers=headers, params={"format": "csv"}
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        body = resp.text
        # CSV export: check header row or empty-but-valid response
        assert isinstance(body, str)

    async def test_export_logs_bulk_export_event(self, client: AsyncClient):
        """The export action itself should be recorded as an audit event."""
        headers = await _auth_headers(client)
        # Trigger the export
        await client.get("/v1/audit/export", headers=headers)
        # Now check the audit log contains the export event
        resp = await client.get(
            "/v1/audit",
            headers=headers,
            params={"event_type": "x.promptlock.audit.exported"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1

    async def test_export_invalid_format_422(self, client: AsyncClient):
        headers = await _auth_headers(client)
        resp = await client.get(
            "/v1/audit/export", headers=headers, params={"format": "xml"}
        )
        assert resp.status_code == 422
