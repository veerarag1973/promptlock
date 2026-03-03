"""API tests for v0.5: Approval Workflow (spec §4.4).

Tests cover the full 8-step promotion workflow:
1. Submit (pending) → 2. Review (approve/reject) → 3. Execute (promote) | 4. Bypass

Separation-of-duties rules enforced:
- Reviewer ≠ requester
- Executor ≠ any reviewer
- Bypass requires Org Admin and emits a high-severity audit event
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Tuple

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTER_PAYLOAD = {
    "email": "approver_main@wf.io",
    "password": "password123",
    "org_name": "Workflow Corp",
}

_PROMO_BODY = {
    "prompt_path": "prompts/chat.txt",
    "from_environment": "development",
    "to_environment": "staging",
    "version_num": 1,
    "sha256": "deadbeef01234567",
}


async def _register(client: AsyncClient, email: str, org: str) -> Tuple[str, str, str]:
    """Register a new user and return (token, user_id, org_id)."""
    resp = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": "password123", "org_name": org},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["access_token"], data.get("user_id", ""), data["org_id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_user_in_org(
    db: AsyncSession, org_id: str, email: str, role_name: str
) -> str:
    """Directly insert a user into an existing org and assign them a role.

    Returns a Bearer token for the new user that the test client can use.
    """
    from jose import jwt as jose_jwt
    from passlib.context import CryptContext

    from api.models import Session, User
    from api.rbac import assign_role

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        org_id=org_id,
        email=email,
        password_hash=pwd_ctx.hash("password123"),
    )
    db.add(user)
    await db.flush()

    # Assign the requested role
    await assign_role(
        user_id=user_id,
        role_name=role_name,
        scope_id=org_id,
        scope_type="org",
        db=db,
        created_by=user_id,
    )

    # Create a valid session token recognised by the auth middleware
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    token = jose_jwt.encode(
        {
            "sub": user_id,
            "org": org_id,
            "exp": expire,
            "jti": secrets.token_hex(16),
        },
        "test-secret",   # matches os.environ["JWT_SECRET"] in root conftest
        algorithm="HS256",
    )
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.add(
        Session(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expire,
        )
    )
    await db.flush()
    return token


# ---------------------------------------------------------------------------
# Submit a promotion request
# ---------------------------------------------------------------------------


class TestSubmitPromotion:
    async def test_promotion_starts_pending(self, client: AsyncClient):
        token, _, _ = await _register(client, "submit1@wf.io", "Submit Corp 1")
        resp = await client.post("/v1/promotions", json=_PROMO_BODY, headers=_auth(token))
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending"

    async def test_promotion_stores_required_approvals(self, client: AsyncClient):
        token, _, _ = await _register(client, "submit2@wf.io", "Submit Corp 2")
        body = {**_PROMO_BODY, "required_approvals": 2}
        resp = await client.post("/v1/promotions", json=body, headers=_auth(token))
        assert resp.status_code == 201
        assert resp.json()["required_approvals"] == 2


# ---------------------------------------------------------------------------
# Reviewer submits decision
# ---------------------------------------------------------------------------


class TestSubmitReview:
    async def test_review_own_promotion_is_forbidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Requester cannot review their own promotion request."""
        token, _, _ = await _register(client, "selfreview@wf.io", "SelfReview Corp")
        promo_resp = await client.post("/v1/promotions", json=_PROMO_BODY, headers=_auth(token))
        promo_id = promo_resp.json()["id"]

        resp = await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "approved", "comment": "Looks good"},
            headers=_auth(token),
        )
        assert resp.status_code == 403
        assert "own" in resp.json()["detail"].lower()

    async def test_reviewer_approves_advances_to_approved(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A Reviewer approving a pending promo with required_approvals=1 advances it."""
        requester_token, _, org_id = await _register(
            client, "req_approve@wf.io", "Approve Corp"
        )
        reviewer_token = await _create_user_in_org(
            db_session, org_id, "reviewer_approve@wf.io", "Reviewer"
        )

        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        assert promo_resp.status_code == 201
        promo_id = promo_resp.json()["id"]

        # Reviewer approves
        review_resp = await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "approved", "comment": "Looks great"},
            headers=_auth(reviewer_token),
        )
        assert review_resp.status_code == 201
        data = review_resp.json()
        assert data["decision"] == "approved"

        # Check promotion status advanced to "approved"
        list_resp = await client.get("/v1/promotions", headers=_auth(requester_token))
        items = list_resp.json()["items"]
        promo = next(p for p in items if p["id"] == promo_id)
        assert promo["status"] == "approved"

    async def test_reviewer_reject_sets_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A Reviewer rejecting a pending promo sets status to 'rejected'."""
        requester_token, _, org_id = await _register(
            client, "req_reject@wf.io", "Reject Corp"
        )
        reviewer_token = await _create_user_in_org(
            db_session, org_id, "reviewer_reject@wf.io", "Reviewer"
        )

        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        promo_id = promo_resp.json()["id"]

        review_resp = await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "rejected", "comment": "Not ready"},
            headers=_auth(reviewer_token),
        )
        assert review_resp.status_code == 201

        list_resp = await client.get("/v1/promotions", headers=_auth(requester_token))
        items = list_resp.json()["items"]
        promo = next(p for p in items if p["id"] == promo_id)
        assert promo["status"] == "rejected"

    async def test_duplicate_review_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Same reviewer cannot submit two decisions for the same promotion."""
        requester_token, _, org_id = await _register(
            client, "req_dup@wf.io", "Dup Corp"
        )
        reviewer_token = await _create_user_in_org(
            db_session, org_id, "reviewer_dup@wf.io", "Reviewer"
        )

        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        promo_id = promo_resp.json()["id"]

        body = {"decision": "approved", "comment": "Good"}
        await client.post(f"/v1/promotions/{promo_id}/reviews", json=body, headers=_auth(reviewer_token))
        resp = await client.post(
            f"/v1/promotions/{promo_id}/reviews", json=body, headers=_auth(reviewer_token)
        )
        assert resp.status_code == 409

    async def test_review_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/v1/promotions/some-id/reviews",
            json={"decision": "approved", "comment": "x"},
        )
        assert resp.status_code == 401

    async def test_cannot_review_rejected_promotion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Cannot review a promotion that is already rejected."""
        requester_token, _, org_id = await _register(
            client, "req_alreadyrej@wf.io", "AlreadyRej Corp"
        )
        reviewer1_token = await _create_user_in_org(
            db_session, org_id, "reviewer_rej1@wf.io", "Reviewer"
        )
        reviewer2_token = await _create_user_in_org(
            db_session, org_id, "reviewer_rej2@wf.io", "Reviewer"
        )

        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        promo_id = promo_resp.json()["id"]

        # First reviewer rejects
        await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "rejected", "comment": "Rejected"},
            headers=_auth(reviewer1_token),
        )

        # Second reviewer tries to review again — should be 409
        resp = await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "approved", "comment": "Actually looks fine"},
            headers=_auth(reviewer2_token),
        )
        assert resp.status_code == 409

    async def test_review_emits_audit_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Approve/reject actions appear in the audit log."""
        requester_token, _, org_id = await _register(
            client, "req_audit_review@wf.io", "AuditReview Corp"
        )
        reviewer_token = await _create_user_in_org(
            db_session, org_id, "reviewer_audit@wf.io", "Reviewer"
        )

        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        promo_id = promo_resp.json()["id"]

        await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "approved", "comment": "All good"},
            headers=_auth(reviewer_token),
        )

        audit_resp = await client.get(
            "/v1/audit",
            params={"event_type": "llm.prompt.approved"},
            headers=_auth(requester_token),
        )
        assert audit_resp.status_code == 200
        assert len(audit_resp.json()["items"]) >= 1


# ---------------------------------------------------------------------------
# Deployer executes an approved promotion
# ---------------------------------------------------------------------------


class TestExecutePromotion:
    async def test_cannot_execute_pending_promotion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Execute is only allowed on 'approved' promotions."""
        requester_token, _, org_id = await _register(
            client, "exec_pending@wf.io", "ExecPending Corp"
        )
        deployer_token = await _create_user_in_org(
            db_session, org_id, "deployer_pending@wf.io", "Deployer"
        )

        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        promo_id = promo_resp.json()["id"]

        resp = await client.post(
            f"/v1/promotions/{promo_id}/execute",
            json={"comment": "Deploying"},
            headers=_auth(deployer_token),
        )
        assert resp.status_code == 409

    async def test_executor_cannot_have_reviewed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A user who reviewed the promotion cannot also execute it."""
        requester_token, _, org_id = await _register(
            client, "exec_selfdeploy@wf.io", "SelfDeploy Corp"
        )
        # This user is both Reviewer and Deployer (Org Admin has both)
        reviewer_deployer_token = await _create_user_in_org(
            db_session, org_id, "reviewerdeploy@wf.io", "Org Admin"
        )

        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        promo_id = promo_resp.json()["id"]

        # This user approves the promotion
        await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "approved", "comment": "LGTM"},
            headers=_auth(reviewer_deployer_token),
        )

        # Then tries to execute it — must be forbidden
        resp = await client.post(
            f"/v1/promotions/{promo_id}/execute",
            json={"comment": "Executing"},
            headers=_auth(reviewer_deployer_token),
        )
        assert resp.status_code == 403
        assert "reviewed" in resp.json()["detail"].lower()

    async def test_full_workflow_approve_then_execute(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Full happy path: requester → reviewer → deployer → promoted."""
        requester_token, _, org_id = await _register(
            client, "req_full@wf.io", "FullFlow Corp"
        )
        reviewer_token = await _create_user_in_org(
            db_session, org_id, "reviewer_full@wf.io", "Reviewer"
        )
        deployer_token = await _create_user_in_org(
            db_session, org_id, "deployer_full@wf.io", "Deployer"
        )

        # Step 1: Submit promotion request
        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(requester_token)
        )
        assert promo_resp.status_code == 201
        promo_id = promo_resp.json()["id"]
        assert promo_resp.json()["status"] == "pending"

        # Step 2: Reviewer approves
        review_resp = await client.post(
            f"/v1/promotions/{promo_id}/reviews",
            json={"decision": "approved", "comment": "Reviewed and approved"},
            headers=_auth(reviewer_token),
        )
        assert review_resp.status_code == 201

        # Step 3: Deployer executes
        exec_resp = await client.post(
            f"/v1/promotions/{promo_id}/execute",
            json={"comment": "Deploying to staging"},
            headers=_auth(deployer_token),
        )
        assert exec_resp.status_code == 200
        assert exec_resp.json()["status"] == "promoted"

    async def test_execute_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/v1/promotions/some-id/execute",
            json={"comment": ""},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Admin bypass
# ---------------------------------------------------------------------------


class TestBypassApproval:
    async def test_bypass_immediately_promotes(self, client: AsyncClient):
        """Org Admin can bypass review and immediately set status to promoted."""
        token, _, _ = await _register(client, "bypass1@wf.io", "Bypass Corp 1")
        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(token)
        )
        assert promo_resp.status_code == 201
        promo_id = promo_resp.json()["id"]

        resp = await client.post(
            f"/v1/promotions/{promo_id}/bypass",
            json={"reason": "Emergency hotfix — P0 incident"},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "promoted"
        assert "BYPASSED" in resp.json()["comment"]

    async def test_bypass_requires_reason(self, client: AsyncClient):
        """The bypass reason is mandatory (min_length=1)."""
        token, _, _ = await _register(client, "bypass2@wf.io", "Bypass Corp 2")
        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(token)
        )
        promo_id = promo_resp.json()["id"]

        resp = await client.post(
            f"/v1/promotions/{promo_id}/bypass",
            json={"reason": ""},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    async def test_bypass_emits_high_severity_audit_event(self, client: AsyncClient):
        """Bypass generates x.promptlock.approval.bypassed audit event."""
        token, _, _ = await _register(client, "bypass3@wf.io", "Bypass Corp 3")
        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(token)
        )
        promo_id = promo_resp.json()["id"]

        await client.post(
            f"/v1/promotions/{promo_id}/bypass",
            json={"reason": "Incident response"},
            headers=_auth(token),
        )

        audit_resp = await client.get(
            "/v1/audit",
            params={"event_type": "x.promptlock.approval.bypassed"},
            headers=_auth(token),
        )
        assert audit_resp.status_code == 200
        items = audit_resp.json()["items"]
        assert len(items) >= 1
        # Confirm payload carries severity marker
        payload = items[0]["payload_json"].get("payload", {})
        assert payload.get("severity") == "high"

    async def test_bypass_on_already_promoted_is_409(self, client: AsyncClient):
        """Cannot bypass a promotion that is already promoted."""
        token, _, _ = await _register(client, "bypass4@wf.io", "Bypass Corp 4")
        promo_resp = await client.post(
            "/v1/promotions", json=_PROMO_BODY, headers=_auth(token)
        )
        promo_id = promo_resp.json()["id"]

        # First bypass succeeds
        await client.post(
            f"/v1/promotions/{promo_id}/bypass",
            json={"reason": "First bypass"},
            headers=_auth(token),
        )

        # Second bypass on an already-promoted promo is rejected
        resp = await client.post(
            f"/v1/promotions/{promo_id}/bypass",
            json={"reason": "Second bypass"},
            headers=_auth(token),
        )
        assert resp.status_code == 409

    async def test_bypass_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/v1/promotions/some-id/bypass",
            json={"reason": "x"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/environments/{name}/active
# ---------------------------------------------------------------------------


class TestGetActiveVersions:
    async def test_active_versions_empty_by_default(self, client: AsyncClient):
        """No active versions before any execution or bypass."""
        token, _, _ = await _register(client, "active1@wf.io", "Active Corp 1")
        resp = await client.get("/v1/environments/staging/active", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["environment"] == "staging"

    async def test_active_versions_requires_auth(self, client: AsyncClient):
        resp = await client.get("/v1/environments/staging/active")
        assert resp.status_code == 401

    async def test_bypass_populates_active_versions(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """After a bypass, the active version is queryable for the org."""
        token, _, org_id = await _register(client, "active2@wf.io", "Active Corp 2")

        # Register a prompt first so prompt_id is resolved
        prompt_resp = await client.post(
            "/v1/prompts",
            json={"name": "Chat Prompt", "path": "prompts/chat.txt"},
            headers=_auth(token),
        )
        assert prompt_resp.status_code == 201

        # Push a version  
        from api.models import PromptVersion
        prompt_id = prompt_resp.json()["id"]
        pv = PromptVersion(
            id=str(uuid.uuid4()),
            prompt_id=prompt_id,
            version_num=1,
            sha256="deadbeef01234567",
            content_url="mock://content",
            author_email="active2@wf.io",
            message="Initial",
            environment="development",
        )
        db_session.add(pv)
        await db_session.flush()

        # Submit and bypass a promotion
        promo_resp = await client.post(
            "/v1/promotions",
            json={**_PROMO_BODY, "prompt_path": "prompts/chat.txt"},
            headers=_auth(token),
        )
        promo_id = promo_resp.json()["id"]

        await client.post(
            f"/v1/promotions/{promo_id}/bypass",
            json={"reason": "Test bypass"},
            headers=_auth(token),
        )

        active_resp = await client.get(
            "/v1/environments/staging/active", headers=_auth(token)
        )
        assert active_resp.status_code == 200
        items = active_resp.json()["items"]
        assert len(items) >= 1
        paths = [i["prompt_path"] for i in items]
        assert "prompts/chat.txt" in paths
