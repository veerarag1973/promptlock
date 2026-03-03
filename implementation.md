# promptlock — Phase-wise Implementation Plan

> Based on the Enterprise Product Specification v1.0 · February 2026  
> Build Strategy: **CLI First** → Cloud API → Web Dashboard

---

## Strategy

**Build order:** CLI (local, offline) → Cloud API (registry sync) → Web Dashboard → Enterprise features

**Why CLI first:**
- The CLI is what developers actually install and use on day one. It is the product's first impression.
- v0.1 works completely offline — no infra, no auth, no dependencies except Python. Zero friction to try.
- A working CLI with `git`-style UX is what drives PyPI downloads, GitHub stars, and word-of-mouth among engineers.
- The API is introduced in v0.2 as a cloud sync layer behind an already-proven command surface. Getting the UX right first means the API contract is informed by real usage.
- The web dashboard and enterprise features are layered on top of a stable API that developers already trust.

**OSS model:** CLI core is MIT-licensed on GitHub. Revenue comes from the **hosted cloud version** (promptlock.io). Users self-host for free; enterprises pay for the managed service. This is the Supabase / Grafana / Plausible playbook.

**Enterprise tier requirement:** Enterprise features (SSO, full RBAC, audit log) must be **designed correctly from v0.4** — retrofitting access control and audit trails onto an existing system is extremely painful. Get the data model right before v1.0 (spec §8, Scope Rule).

**Monetization tiers:**

| Tier | Pricing | Who |
|---|---|---|
| OSS (self-hosted) | Free | Individual devs, small teams |
| Pro (cloud-hosted) | $29/mo | Teams who do not want to self-host |
| Enterprise (cloud-hosted) | Custom ARR | Companies needing SSO, RBAC, audit, SLA |

---

## Architecture Stack

| Layer | Technology |
|---|---|
| CLI | Python, Click, installable via `pip install promptlock` |
| Local store | `.promptlock/` directory (content-addressed, SHA-256 keyed) |
| API | Python, FastAPI, REST, JWT auth |
| Database | PostgreSQL (metadata + versions) |
| Object Storage | S3-compatible (prompt content blobs) |
| Cache / Queues | Redis + Celery workers |
| Frontend | Next.js (App Router), Tailwind CSS |
| Auth (OSS) | Email + password, JWT (HttpOnly cookie) |
| Auth (Enterprise) | SAML 2.0 / OIDC via `python-saml` + `authlib` |
| Infrastructure | AWS ECS Fargate, RDS Postgres, S3, ElastiCache |
| IaC | Terraform |
| Observability | Prometheus, OpenTelemetry, Datadog / Grafana Tempo |

---

## Project Structure

```
promptlock/
├── cli/                      # Python CLI package (Phase 1)
│   ├── __init__.py
│   ├── main.py               # Click entry point
│   ├── commands/             # One file per command group
│   │   ├── init.py
│   │   ├── save.py
│   │   ├── log.py
│   │   ├── diff.py
│   │   ├── rollback.py
│   │   ├── tag.py
│   │   ├── push.py
│   │   ├── pull.py
│   │   ├── env.py
│   │   ├── promote.py
│   │   ├── validate.py
│   │   └── eval.py
│   ├── local/                # Local store engine
│   │   ├── store.py          # Read/write .promptlock/ directory
│   │   ├── hash.py           # SHA-256 content addressing
│   │   └── config.py         # .promptlock.toml parser
│   ├── api/                  # API client (added in v0.2)
│   │   └── client.py
│   └── auth.py               # JWT token storage in ~/.promptlock/config
├── api/                      # FastAPI application (Phase 2)
│   ├── main.py
│   ├── routers/
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── services/             # Business logic layer
│   ├── dependencies/         # Auth, DB session injection
│   └── migrations/           # Alembic migrations
├── web/                      # Next.js dashboard (Phase 6)
├── infra/                    # Terraform
├── docker-compose.yml        # Local dev: postgres, redis, minio, api, web
├── pyproject.toml            # CLI package definition
└── README.md
```

---

## Phase 1 — v0.1: OSS CLI Core

**Timeline:** Weeks 1–2  
**Goal:** A developer installs `promptlock` in seconds and has git-style prompt versioning working entirely offline. No account. No API. No config required beyond `promptlock init`.

**Spec reference:** §4.1 Core CLI · §9 NFR (CLI cold-start < 150 ms)

### 1.1 Package Setup

```toml
# pyproject.toml
[project]
name = "promptlock"
version = "0.1.0"
dependencies = ["click", "rich", "toml"]

[project.scripts]
promptlock = "promptlock.main:cli"
```

Published to PyPI on day one. One-line install:

```bash
pip install promptlock
```

### 1.2 Local `.promptlock/` Directory Structure

`promptlock init` creates this layout in any project directory:

```
.promptlock/
├── config                 # Local project config (project name, remote URL if set)
├── objects/               # Content-addressed blob store
│   └── <sha256[:2]>/
│       └── <sha256[2:]>   # Full prompt content, stored exactly once
├── versions/              # Version metadata per prompt
│   └── prompts/
│       └── summarize.txt/
│           ├── 0001.json  # {version_num, sha256, message, author, timestamp, tags}
│           ├── 0002.json
│           └── HEAD       # Points to the active version number
└── index                  # Maps prompt path to current active SHA-256
```

Design principles:
- **Content-addressed:** prompt text is stored keyed by its SHA-256 hash. Identical text across multiple versions is stored once.
- **Append-only locally:** version JSON files are never overwritten. Rollback updates `HEAD`, not the history.
- **Fully offline:** all Phase 1 commands read and write only this local directory. No network access required.

### 1.3 CLI Commands (v0.1)

All seven core commands work offline.

| Command | Description |
|---|---|
| `promptlock init` | Create `.promptlock/` in current directory |
| `promptlock save <file> -m "<message>"` | Save a new version of a prompt file |
| `promptlock log <file>` | View version history for a prompt |
| `promptlock diff <file> <v1> <v2>` | Show character/line diff between two versions |
| `promptlock rollback <file> <version>` | Activate a previous version (updates HEAD, preserves history) |
| `promptlock tag <file> <version> --name <tag>` | Attach a named tag to a specific version |
| `promptlock status` | Show changed prompt files not yet saved |

**Usage examples from spec §4.1:**

```bash
# Install
pip install promptlock

# Initialize a project (creates .promptlock/ directory)
promptlock init

# Save a new version of a prompt
promptlock save prompts/summarize.txt -m "Tighten instruction, reduce hallucinations"

# View version history
promptlock log prompts/summarize.txt

# Diff two versions
promptlock diff prompts/summarize.txt v3 v4

# Rollback to a previous version
promptlock rollback prompts/summarize.txt v3

# Tag a version for promotion
promptlock tag prompts/summarize.txt v4 --name stable-2026-02
```

### 1.4 Performance Target

- **CLI cold-start (offline, no network): < 150 ms**
- Achieved by: lazy imports, minimal dependencies (Click + Rich + toml), no startup network calls.

### 1.5 Rich Terminal Output

Use `rich` for all output:
- `promptlock log` → table with version number, timestamp, author, first line of commit message
- `promptlock diff` → side-by-side or unified diff with syntax highlighting
- `promptlock status` → color-coded changed/unchanged files

### 1.6 Deliverable

- `pip install promptlock` works
- All 7 commands work fully offline
- `.promptlock/` directory is human-readable (JSON + raw text blobs)
- GitHub repo is public and MIT-licensed from day one
- README has a 60-second quickstart (no account, no API key required)
- `promptlock --help` is polished and self-documenting

---

## Phase 2 — v0.2: Cloud Registry

**Timeline:** Weeks 3–4  
**Goal:** Teams can sync local prompt versions to a centralized cloud registry. Enable basic team sharing, user accounts, and `push`/`pull` commands.

**Spec reference:** §4.2 Prompt Registry · §6.1 System Overview · §6.2 API Design

### 2.1 New CLI Commands

| Command | Description |
|---|---|
| `promptlock login` | Authenticate; stores JWT in `~/.promptlock/config` |
| `promptlock logout` | Revoke token and clear local config |
| `promptlock push` | Sync local versions to the team registry |
| `promptlock pull` | Fetch latest registry state to local `.promptlock/` |

Push uses exponential backoff and retries on transient network errors. All offline-mode commands from Phase 1 continue to work without network access.

### 2.2 Core Data Model (PostgreSQL)

Design the full schema upfront — retrofitting RBAC and audit columns onto a populated schema is extremely painful. All RBAC/audit columns are added now even though enforcement begins at Phase 4.

```sql
-- Identity
orgs     (id, name, slug, plan, created_at)
users    (id, org_id, email, password_hash, created_at)
sessions (id, user_id, token_hash, expires_at, created_at)

-- Hierarchy
teams    (id, org_id, name, slug, created_at)
projects (id, team_id, org_id, name, slug, created_at)

-- Prompt registry
prompts  (id, project_id, org_id, name, path, description, created_at)
prompt_versions (
    id, prompt_id, version_num, sha256,
    content_url,         -- S3 key (content stored in object storage)
    author_id, message, model_target,
    environment_id, parent_version_id, created_at
)
tags     (id, prompt_version_id, name, created_at)

-- Environments (schema now; CLI enforcement in Phase 3)
environments (id, org_id, name, type, config_json, created_at)
prompt_environment_active (
    id, prompt_id, environment_id, prompt_version_id,
    activated_by, activated_at
)

-- RBAC (schema now; enforced from Phase 4)
roles            (id, name, scope_type)
role_assignments (id, user_id, role_id, scope_id, scope_type, created_by, created_at)
service_accounts (id, org_id, name, token_hash, scopes_json, expires_at)

-- Audit log (append-only writes start immediately in Phase 2)
audit_events (
    id, event_id,           -- ULIDv7 for time-ordering
    timestamp,              -- UTC microsecond precision
    event_type,
    actor_user_id, actor_email, actor_ip,
    resource_type, resource_id, resource_version,
    org_id, team_id, metadata_json,
    checksum                -- sha256 chained to previous entry
)
```

### 2.3 FastAPI Application Bootstrap

- OpenAPI 3.1 auto-generated docs at `/docs`
- `alembic` for schema migrations
- SQLAlchemy async ORM + Pydantic v2
- Cursor-based pagination on all list endpoints (enforced from day one)
- Structured JSON request logging middleware
- `GET /health` health check

Auth endpoints:

```
POST  /v1/auth/register
POST  /v1/auth/login
POST  /v1/auth/logout
POST  /v1/auth/refresh
GET   /v1/auth/me
```

### 2.4 Registry API Endpoints

```
POST  /v1/prompts                       -- create a prompt resource
GET   /v1/prompts                       -- list prompts (cursor-paginated)
POST  /v1/prompts/{id}/versions         -- push a new version (SHA-256 content hash)
GET   /v1/prompts/{id}/versions         -- list all versions
GET   /v1/prompts/{id}/versions/{v}     -- fetch a specific version
```

API design principles (spec §6.2):
- Versioned URLs (`/v1/`)
- Cursor-based pagination on all list endpoints
- Idempotency keys on all write operations
- Rate limiting: per-token limits

### 2.5 Object Storage (S3-compatible)

- S3 bucket (MinIO in `docker-compose.yml` for local dev)
- Content-addressed: files keyed by SHA-256 hash — same deduplication model as local store
- Identical prompt text stored once across all versions
- Large prompts compressed at rest

### 2.6 Hierarchical Namespace (spec §4.2)

```
org / team / project / prompt
```

- Every prompt belongs to `org → team → project` path
- Prompts queryable at any level in the hierarchy
- **Dual addressing:** file-based paths (like git) for local mode; registry UUIDs for API mode — support both (spec §13 Open Question)

### 2.7 Registry Features (spec §4.2)

- Full-text search across prompt content and metadata
- Prompt linking: track which prompts depend on or derive from others
- Immutable storage enforced at the API layer — versions are appended, never overwritten or deleted

### 2.8 Local Dev Environment

```yaml
# docker-compose.yml
postgres:  postgres:16
redis:     redis:7
minio:     minio/minio        # S3-compatible, local dev only
api:       ./api              # FastAPI, hot reload
```

One command to start everything: `docker compose up`

### 2.9 Performance Targets

- Save/push a prompt version: **< 500 ms p95**
- List 1,000 versions: **< 200 ms API response**

### 2.10 Deliverable

- `promptlock login`, `promptlock push`, `promptlock pull` work end-to-end
- Schema migrated; API boots
- `docker compose up` produces a running local environment in < 5 minutes
- All Phase 1 offline commands still work without network

---

## Phase 3 — v0.3: Environment Management

**Timeline:** Weeks 5–6  
**Goal:** Introduce `dev / staging / production` environments. Explicit promotion CLI between them. No approval gate yet — manual promotion, no review required.

**Spec reference:** §4.6 Environment Management

### 3.1 Environment Model (spec §4.6)

| Environment | Who Can Write | Who Can Read | Promotion Gate |
|---|---|---|---|
| `development` | Contributors+ | All team members | None — push freely |
| `staging` | Deployers (via promotion) | All team members + CI | 1 Reviewer approval (added in v0.5) |
| `production` | Deployers (via promotion) | Defined read-access list | 2 Reviewer approvals + Deployer action (added in v0.5) |
| `archived` | No one | Auditors + Admins | Automatic after retention |

- Custom environments supported (e.g., `canary`, `shadow`, `a-b-test`)
- Environment variables and secrets scoped per environment — dev and prod secrets never mix
- Environment-specific model configuration: a prompt can target different models per environment (`model_target` metadata field)

### 3.2 `.promptlock.toml` Configuration (spec §4.6)

```toml
[environments]
default = "dev"

[environments.dev]
model = "claude-3-5-sonnet"

[environments.staging]
model = "claude-3-5-sonnet"

[environments.production]
model = "claude-3-opus"
```

### 3.3 New CLI Commands

| Command | Description |
|---|---|
| `promptlock push --env dev` | Push to the development environment |
| `promptlock promote --from dev --to staging` | Manually promote a version (no approval gate yet) |
| `promptlock pull --env staging` | Pull the active version from staging |
| `promptlock env list` | List all configured environments |

### 3.4 API Endpoints Added

```
GET   /v1/environments       -- list org environments
POST  /v1/promotions         -- submit promotion request (auto-approves in v0.3; gates in v0.5)
PATCH /v1/promotions/{id}    -- approve / reject
```

### 3.5 Deliverable

- All environment commands work end-to-end
- Dev/staging/prod semantics enforced in `.promptlock.toml` and the API
- A version can be promoted from dev → staging → production via CLI without manual database edits

---

## Phase 4 — v0.4: Audit Log & RBAC

**Timeline:** Weeks 7–9  
**Goal:** Full immutable audit log and role-based access control. **This is the most critical phase for enterprise sales — must be designed correctly here. Retrofitting RBAC/audit later is extremely painful (spec §8 Scope Rule).**

**Spec reference:** §4.3 RBAC · §4.5 Audit Log · §5 Enterprise Compliance

### 4.1 Role-Based Access Control (spec §4.3)

Seven roles, each scoped at org / team / project level:

| Role | Scope | Permissions |
|---|---|---|
| `Viewer` | Org / Team / Project | Read prompt content and history only |
| `Contributor` | Team / Project | Save new versions in non-production environments |
| `Reviewer` | Team / Project | Approve/reject promotion requests; cannot self-approve |
| `Deployer` | Project | Promote approved versions to production; cannot approve own requests |
| `Admin` | Team | Manage team members, roles, project settings; cannot modify audit logs |
| `Org Admin` | Org | Manage SSO, billing, org-wide policies, retention rules; full read access |
| `Auditor` | Org | Read-only access to all audit logs across the entire org |

Enforcement rules (spec §4.3):
- Roles are additive and assigned at the most specific scope possible
- **Separation of duties enforced:** no user can both create a version AND approve it for production
- Service account tokens supported for CI/CD pipelines (scoped to specific projects and permissions)
- Emergency ("break-glass") access with mandatory high-severity audit notification

### 4.2 RBAC Data Model

```sql
roles            (id, name, scope_type)
role_assignments (id, user_id, role_id, scope_id, scope_type, created_by, created_at)
service_accounts (id, org_id, name, token_hash, scopes_json, expires_at)
```

(Columns already in schema from Phase 2; enforcement middleware added now.)

### 4.3 Authorization Middleware

- Every API request checks the caller's effective roles at the relevant scope before processing
- Role checks tested exhaustively — especially separation-of-duties constraints
- All existing endpoints from v0.1–v0.3 retrofitted with per-request authorization

### 4.4 Immutable Audit Log (spec §4.5)

Every action (read, write, approve, login, export) recorded in an append-only audit log.

**Audit event schema:**

```json
{
  "event_id":   "evt_01HX...",
  "timestamp":  "2026-02-15T14:32:01.442Z",
  "event_type": "PROMPT_PROMOTED",
  "actor": {
    "user_id": "usr_abc",
    "email":   "priya@acme.com",
    "ip":      "203.0.113.5"
  },
  "resource": {
    "type":    "prompt",
    "id":      "pmt_xyz",
    "version": "v7"
  },
  "org_id":   "org_123",
  "team_id":  "team_456",
  "metadata": {
    "environment": "production",
    "approver":    "usr_def"
  },
  "checksum": "sha256:a3f9..."
}
```

**Full list of audit event types (spec §4.5):**

- `PROMPT_VERSION_CREATED`
- `PROMPT_PROMOTED`, `PROMPT_ROLLED_BACK`
- `PROMOTION_REQUESTED`, `PROMOTION_APPROVED`, `PROMOTION_REJECTED`
- `REVIEW_STARTED`
- `EVAL_RUN_COMPLETED`
- `DEPLOYMENT_MONITORED`
- `USER_LOGIN`, `USER_LOGOUT`, `MFA_CHALLENGE`
- `SECRET_ACCESSED`, `SECRET_ROTATED`
- `APPROVAL_BYPASSED` *(high-severity)*
- `BULK_EXPORT`

**Enterprise enforcement requirements (spec §4.5):**

- **Append-only:** no row can be modified or deleted by any actor, including Org Admins
- **Tamper-evident:** each log entry includes a SHA-256 hash chained to the previous entry
- **Retention policy:** configurable minimum (default 2 years; up to 7 years for regulated industries)
- **Export:** full log export to SIEM systems (Splunk, Datadog, Elastic) via webhook or scheduled export
- **Search and filter:** queryable by actor, event type, resource, date range, environment
- **Real-time alerting:** configurable alerts on high-severity events (bypass, mass export, failed login attempts)

### 4.5 Audit Log Storage (spec §13 Open Question)

- **Recommended:** PostgreSQL append-only partition with WAL archiving for tamper detection
- Evaluate Amazon QLDB cost — if acceptable, use QLDB for cryptographic immutability proof
- **Query performance:** audit log query (30-day window) < 1 s
- **Write throughput target:** write-optimized for 10M+ events per org

### 4.6 New API Endpoints

```
GET    /v1/audit                            -- Auditor role required; query by actor, event, resource, date, env
GET    /v1/audit/export                     -- Full export (CSV/JSON); BULK_EXPORT event logged
POST   /v1/orgs/{id}/roles                  -- Assign a role
DELETE /v1/orgs/{id}/roles/{assignment_id}  -- Remove a role assignment
```

### 4.7 Begin SOC 2 Controls Documentation

- Start documenting controls at v0.4 per spec §5.2 recommendation
- Engage auditor early — target SOC 2 Type I at GA (v1.0)

### 4.8 Deliverable

- All API endpoints are authorization-gated
- Audit events written for every state-changing action from v0.1 forward
- Separation-of-duties constraints tested exhaustively
- Controls documentation begun

---

## Phase 5 — v0.5: Approval Workflows & CI/CD

**Timeline:** Weeks 10–12  
**Goal:** Mandatory review gates before prompt promotion. GitHub/GitLab CI integration. Automated PR diff comment posting.

**Spec reference:** §4.4 Approval Workflows · §4.9 CI/CD Integration

### 5.1 8-Step Promotion Workflow (spec §4.4)

| Step | Actor | System Action | Audit Event |
|---|---|---|---|
| 1. Save draft | Contributor | New version created in dev | `PROMPT_VERSION_CREATED` |
| 2. Run eval (optional) | Automated / CI | llm-diff checks pass | `EVAL_RUN_COMPLETED` |
| 3. Submit for review | Contributor | Promotion request created; reviewers notified | `PROMOTION_REQUESTED` |
| 4. Review | Reviewer | Diff shown; reviewer adds comments | `REVIEW_STARTED` |
| 5. Approve / Reject | Reviewer | Decision recorded with mandatory comment | `PROMOTION_APPROVED` / `PROMOTION_REJECTED` |
| 6. Promote | Deployer | Version activated in target environment | `PROMPT_PROMOTED` |
| 7. Monitor | System | Output quality metrics tracked post-deploy | `DEPLOYMENT_MONITORED` |
| 8. Rollback (if needed) | Deployer | Previous version reactivated instantly | `PROMPT_ROLLED_BACK` |

Workflow configuration:
- Configurable required approver count (default: 1; enterprise: 2+)
- Time-boxed approvals: auto-escalate if no action within configurable window
- Slack and email notifications for review requests (Celery async tasks)
- Approval bypass requires Org Admin role and generates `APPROVAL_BYPASSED` high-severity audit event
- **Mean time to rollback target: < 30 seconds**

### 5.2 New CLI Commands

| Command | Description |
|---|---|
| `promptlock validate --env staging` | Validate all tracked prompts against the registry |
| `promptlock diff --base main --head HEAD --format json` | Structured diff output for CI pipelines |
| `promptlock promote --from dev --to staging --auto-approve` | CI-mode promotion with service account token |

### 5.3 Promotion Data Model

```sql
promotion_requests (id, prompt_version_id, from_env, to_env, requested_by,
                    status, created_at, resolved_at)
promotion_reviews  (id, promotion_request_id, reviewer_id, decision,
                    comment, created_at)
```

### 5.4 CI/CD Integration (spec §4.9)

**GitHub Actions example:**

```yaml
- name: Validate prompts
  run: |
    promptlock validate --env staging
    promptlock diff --base main --head HEAD --format json | jq .

- name: Promote prompts to staging
  run: promptlock promote --from dev --to staging --auto-approve
  env:
    PROMPTLOCK_TOKEN: ${{ secrets.PROMPTLOCK_CI_TOKEN }}
```

Deliverables:
- Official `promptlock-action` published to **GitHub Actions Marketplace**
- Official **GitLab CI** component published
- **Prompt diff as PR comment:** automatically post a diff of changed prompts on every pull request
- **Promotion status checks:** block merges if prompts have unapproved staging changes
- **Webhook events:** trigger external systems on promotion, rollback, or approval (HMAC-SHA256 signed)
- **OpenTelemetry traces:** emit spans for all CLI and API operations for observability integration

### 5.5 Notification System (Celery Workers)

- Async task: on `PROMOTION_REQUESTED` → send Slack + email notifications to assigned Reviewers
- Async task: on approval timeout → escalate to Admin
- All notification events logged in audit log

### 5.6 Deliverable

- The full 8-step promotion workflow is enforced end-to-end
- A reviewer cannot approve their own request
- A deployer cannot approve and then promote the same version
- GitHub Actions + GitLab CI actions published and tested

---

## Phase 6 — v1.0: General Availability (Enterprise GA)

**Timeline:** Month 4  
**Goal:** Full enterprise feature set: SSO, secrets management, web dashboard, and SOC 2 Type I. This is the **public launch milestone**.

**Spec reference:** §4.7 Secrets · §4.8 SSO · §4.10 Web Dashboard · §5 Compliance · §6 Architecture · §7 Pricing

### 6.1 SSO & Identity Management (spec §4.8)

| Feature | Details |
|---|---|
| SAML 2.0 | IdP-initiated and SP-initiated SSO. Tested with Okta, Azure AD, Ping Identity, OneLogin |
| OIDC / OAuth 2.0 | Google Workspace, GitHub Enterprise, custom OIDC providers |
| SCIM 2.0 provisioning | Automated user provisioning/deprovisioning from IdP; groups sync to teams |
| MFA enforcement | Org Admins can require MFA for all users; TOTP and WebAuthn (hardware key) supported |
| Session management | Configurable session duration; force re-auth for sensitive actions (promote to prod) |
| Service account tokens | Short-lived JWT tokens for CI/CD, scoped to specific projects and permissions |
| IP allowlisting | Restrict access to corporate IP ranges per org or team |

Implementation:
- `python-saml` for SAML 2.0
- `authlib` for OIDC / OAuth 2.0
- SCIM 2.0 endpoints: `GET/POST/PATCH/DELETE /scim/v2/Users`, `/scim/v2/Groups`

### 6.2 Secrets & Variable Management (spec §4.7)

- **Variable templating:** `{{variable_name}}` syntax in prompt files; values injected at render time, never stored inline
- **Secret storage:** AES-256-GCM encryption at rest; keys managed per org (spec §5.1)
- **Vault integration:** native connectors for HashiCorp Vault, AWS Secrets Manager, Azure Key Vault
- **Secret scanning:** auto-detect and block accidental commit of API keys or credentials (regex + entropy analysis)
- **Access scoping:** secrets accessible only to explicitly granted environments and roles
- **Secret rotation:** rotation events recorded in audit log; old values remain in versioned history but flagged

Data model:

```sql
secrets (id, org_id, name, encrypted_value, key_ref, environment_id, created_by, created_at)
secret_access_logs (id, secret_id, accessed_by, accessed_at, action)
```

### 6.3 Security Architecture (spec §5.1)

| Layer | Implementation |
|---|---|
| Encryption at rest | AES-256-GCM for all prompt content, secrets, and metadata; keys in AWS KMS |
| Encryption in transit | TLS 1.3 enforced on all connections; HSTS preloaded; certificate pinning for CLI |
| Data isolation | Logically isolated schemas per org; Enterprise tier: dedicated database instance |
| Secrets management | Separate encrypted vault per org; secrets never returned in API responses — only injected at render time |
| Vulnerability management | Snyk dependency scanning on every build; annual pen test; bug bounty program |
| Network security | Private VPC; no public database endpoints; WAF on all API endpoints |

Key management decision at v1.0:
- **Anthropic-managed keys** at v1.0 (simpler to ship)
- **BYOK (AWS KMS)** deferred to v1.1 per spec §13

### 6.4 Web Dashboard (spec §4.10)

Full-featured Next.js dashboard for non-CLI users (team leads, compliance officers, PMs):

| Feature | Description |
|---|---|
| Prompt browser | Searchable, filterable view of all prompts by team, project, environment, status |
| Version timeline | Visual history of all versions with author, message, and diff on click |
| Approval queue | Reviewers see all pending promotion requests with one-click approve/reject; real-time via WebSocket |
| Audit log viewer | Searchable audit trail with export to CSV |
| Team management | Invite members, assign roles, manage SSO configuration |
| Usage analytics | Most active prompts, most frequent contributors, environment activity heatmap |
| Alert configuration | Set up real-time alerts for audit events, failed deployments, unusual activity |

Technical implementation:
- Next.js deployed on Vercel CDN
- Reads from the same REST API as the CLI
- Real-time updates via WebSocket for the approval queue
- **No client-side secrets** — JWT stored in HttpOnly cookie only
- Dashboard initial load: **< 2 s on 10 Mbps**

### 6.5 Infrastructure (Production-Grade, spec §6.1)

- **AWS ECS Fargate** for the API (stateless, horizontally scalable)
- **RDS PostgreSQL** with pgBouncer connection pooling
- **S3** for object storage (no practical size limit)
- **ElastiCache (Redis)** for session cache and Celery queues
- **Multi-region active-passive** for enterprise tier
- **Terraform** for all infrastructure as code
- Automated backups: continuous WAL archiving + daily snapshots
- **RTO: 1 hour | RPO: 5 minutes** (enterprise tier)

### 6.6 Observability Stack (spec §6.1 + §9)

- Structured JSON logs on all API requests
- Prometheus metrics: request latency, error rates, queue depth
- Distributed tracing: OpenTelemetry with Datadog / Grafana Tempo
- Alerting: PagerDuty integration for on-call rotation

### 6.7 Final v1.0 API Endpoint Surface (spec §6.2)

```
# Prompts
GET    /v1/prompts
POST   /v1/prompts
GET    /v1/prompts/{id}/versions
POST   /v1/prompts/{id}/versions
GET    /v1/prompts/{id}/versions/{v}

# Promotions
POST   /v1/promotions
PATCH  /v1/promotions/{id}

# Audit
GET    /v1/audit
GET    /v1/audit/export

# SCIM (enterprise)
GET/POST/PATCH/DELETE  /scim/v2/Users
GET/POST/PATCH/DELETE  /scim/v2/Groups
```

### 6.8 Compliance — SOC 2 Type I (spec §5.2)

- Complete controls documentation started at v0.4
- Submit for SOC 2 Type I audit at GA launch
- GDPR compliance ready: data processing agreements, EU data residency option
- Subprocessor list published; customers notified 30 days before new subprocessors added

### 6.9 Pricing Tiers Live at Launch (spec §7)

| Feature | OSS (Free) | Pro ($29/mo) | Enterprise (Custom) |
|---|---|---|---|
| CLI core versioning | Unlimited | Unlimited | Unlimited |
| Team registry | Local only | Up to 5 users | Unlimited users |
| Environments | dev only | dev + staging + prod | Custom environments |
| Audit log | None | 30-day retention | 7-year retention |
| RBAC | None | Basic owner/member | Full RBAC + Auditor role |
| Approval workflows | None | 1 required approver | Configurable (2+) |
| SSO (SAML / OIDC) | None | None | Full with SCIM |
| Secrets management | Local `.env` | Encrypted vault | BYOK + Vault integration |
| CI/CD actions | Community | Official actions | Priority support + SLA |
| Data residency | US only | US only | EU / US / custom |
| SLA | None | None | 99.95% uptime + dedicated CSM |
| SOC 2 report | None | On request | Full access |
| HIPAA BAA | No | No | Available (v1.2) |

### 6.10 Launch Success Metrics (spec §11)

| Metric | Target at v1.0 |
|---|---|
| GitHub stars | 500+ |
| PyPI downloads / month | 1,000+ |
| Enterprise design partners | 5 (pre-GA, no charge) |
| Mean time to rollback | < 30 seconds |
| SOC 2 Type I | Complete at GA |
| NPS (developer users) | 50+ |

---

## Phase 7 — v1.1: Eval Gates, SCIM & Advanced Alerting

**Timeline:** Months 5–6  
**Goal:** Semantic prompt evaluation gates on promotion, full SCIM provisioning, BYOK key management, and advanced alerting.

**Spec reference:** §4.11 llm-diff Integration · §4.8 SCIM · §5.1 BYOK

### 7.1 llm-diff Eval Gates Integration (spec §4.11)

- **Automatic diff on promotion request:** when a promotion is submitted, optionally run `llm-diff` against the previous active version; attach output diff to the review
- **Eval gates:** configurable minimum semantic similarity threshold — block promotion if similarity drops below e.g. 70%
- **Side-by-side in dashboard:** HTML diff report embedded directly in the approval UI
- **CLI shorthand:** `promptlock eval <prompt-file> --compare-env staging`
- `EVAL_RUN_COMPLETED` audit event with score and pass/fail result

### 7.2 BYOK Encryption — AWS KMS (spec §13)

- Customer-managed encryption keys via AWS KMS
- Key hierarchy: Master Key (customer KMS) → Data Encryption Key (per-org) → prompt content
- Key rotation support with old versions flagged in versioned history
- BYOK configuration via Org Admin dashboard

### 7.3 SCIM 2.0 Full Provisioning (spec §4.8)

- Complete SCIM 2.0 implementation: user create, update, deactivate, group sync
- Map IdP groups directly to promptlock teams and roles
- Deprovisioning: revoke all active sessions and tokens when a user is deprovisioned from IdP

### 7.4 Advanced Alerting (spec §4.5 + §4.10)

Real-time alerting on configurable audit event patterns:
- Approval bypass events
- Mass export events
- N failed login attempts within configurable window
- Any production write by a service account outside business hours

Alert channels: Slack, email, PagerDuty, webhook  
Alert rules stored per org, editable via dashboard

### 7.5 v1.1 Success Metrics (spec §11)

| Metric | Target at v1.1 |
|---|---|
| GitHub stars | 2,000+ |
| PyPI downloads / month | 10,000+ |
| Enterprise ARR | $250K+ |
| SOC 2 Type II (observation period) | In progress |

---

## Phase 8 — v1.2: Regulated Industry Support

**Timeline:** Months 7–9  
**Goal:** Unlock healthcare and financial services customers. HIPAA BAA, EU data residency, FedRAMP readiness.

**Spec reference:** §5.2 Compliance Roadmap · §5.3 Data Residency

### 8.1 HIPAA Business Associate Agreement (spec §5.2)

- Legal BAA available for healthcare customers handling PHI in prompt context
- Dedicated HIPAA-compliant infrastructure configuration (separate ECS cluster if needed)
- Audit log events include PHI-access indicators for HIPAA audit trail requirements

### 8.2 EU Data Residency (spec §5.3)

- All org data stored and processed in `eu-west-1` (AWS Ireland) upon customer request
- EU data residency toggle in Org Admin settings
- Separate RDS instance in `eu-west-1` for EU-opted orgs
- Data never leaves EU region — including backups, audit log exports, and Celery worker jobs

### 8.3 Data Privacy Enhancements (spec §5.3)

- **Right to deletion:** org data fully purged within 30 days of account closure (audit logs retained per legal hold if applicable)
- **DPA (Data Processing Agreement)** available for all paid plans
- **No model training on customer prompt data** — ever. Contractually guaranteed.
- Updated subprocessor list with EU-region subprocessors documented; customers notified 30 days before new subprocessors added

### 8.4 FedRAMP Readiness Preparation (spec §5.2)

- Begin FedRAMP documentation and control mapping (full certification is 18+ months out — deferred beyond v1.2)
- Ensure architecture supports FedRAMP High baseline requirements for future certification

### 8.5 ISO 27001 Certification (spec §5.2)

- Complete ISMS (Information Security Management System) certification
- Target: 12 months post-launch

### 8.6 SOC 2 Type II (spec §5.2)

- 12-month observation period of operating effectiveness started at v1.0 GA
- Target completion: ~6 months post-launch
- Controls documentation started at v0.4 provides the foundation

---

## Future Roadmap (v2.0+)

All items below are explicitly **out of scope before v1.0** (spec §12):

| Item | Notes |
|---|---|
| Prompt execution / LLM API proxy | promptlock stores prompts; does not run them |
| Fine-tuning dataset management | Future feature |
| Multi-modal prompt support (image, audio) | Future feature |
| Real-time collaboration (simultaneous editing) | Future feature |
| VS Code / IDE extensions | Future feature |
| **Self-hosted / on-premises deployment** | v2.0 — design architecture to support it from day one (spec §13) |
| Native integrations with LangChain, LlamaIndex | Community-built |
| Automated prompt optimization / suggestions | Future feature |
| FedRAMP certification | 18+ months out |

> **Architectural note on self-hosted (spec §13):** defer to v2.0 but design the architecture to support it. Keep configuration-driven infrastructure, avoid hard-coded cloud dependencies in business logic, and ensure the data model works in a single-tenant deployment.

---

## Open Architecture Decisions (spec §13)

| Question | Recommendation | Phase to Decide |
|---|---|---|
| Data model: files vs. named prompts | Support both — files in local mode, registry IDs in team mode | v0.2 |
| Encryption key management | Anthropic-managed at v1.0; BYOK (AWS KMS) at v1.1 | v1.0 |
| Audit log storage backend | Postgres with WAL archiving + tamper detection (evaluate QLDB cost first) | v0.4 |
| OSS license strategy | MIT for CLI; proprietary for SaaS platform. Enterprise features not in OSS repo | Before v0.1 publish |
| Self-hosted enterprise offering | Defer to v2.0; design architecture to support it from the start | v2.0 |

---

## Risk Register (spec §10)

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| GitHub / Anthropic ship native prompt versioning | High | Medium | Differentiate on compliance depth (RBAC, audit, SSO) — big labs will never prioritize enterprise governance |
| Enterprise sales cycle too long to sustain OSS momentum | High | Medium | Target 5 design partners pre-launch who co-build and provide case studies. Land and expand. |
| SOC 2 Type II takes longer than 12 months | Medium | Low | Start controls documentation at v0.4. Engage auditor early. |
| OSS community forks the project to avoid SaaS | Low | Low | Keep core CLI MIT licensed. Enterprise features (SSO, RBAC, audit) in SaaS only — not in OSS. |
| Security breach exposing customer prompt content | Critical | Low | BYOK, encryption at rest, penetration tests, bug bounty. Incident response plan ready at v1.0. |
| Prompt storage costs scale faster than revenue | Medium | Medium | Content-addressed deduplication — identical prompt text stored once. Compress large prompts at rest. |

---

## Non-Functional Requirements Summary (spec §9)

| Category | Requirement |
|---|---|
| CLI cold-start (offline, no network) | < 150 ms |
| Save / push a prompt version | < 500 ms p95 |
| List 1,000 versions | < 200 ms API response |
| Audit log query (30-day window) | < 1 s |
| Dashboard initial load | < 2 s on 10 Mbps |
| API availability (enterprise) | 99.95% |
| RTO | 1 hour (enterprise tier) |
| RPO | 5 minutes (enterprise tier) |
| Org scale | 10,000+ prompts, 1M+ versions |
| Audit log write throughput | 10M+ events per org |
| Mean time to rollback | < 30 seconds |
| CLI push retry | Exponential backoff on transient network errors |
| Horizontal scaling | Stateless API; pgBouncer connection pooling; S3 for unbounded object storage |

---

## Phase Summary

| Phase | Timeline | Milestone | Enterprise Features Included |
|---|---|---|---|
| **v0.1 — OSS CLI** | Weeks 1–2 | `pip install promptlock`; init, save, log, diff, rollback, tag · 100% offline | None — developer-only |
| **v0.2 — Cloud Registry** | Weeks 3–4 | Cloud sync, login, push, pull · API + data model · team sharing | None — still OSS-first |
| **v0.3 — Environments** | Weeks 5–6 | dev / staging / prod · manual promotion CLI · `.promptlock.toml` | Manual promotion, no approval gate |
| **v0.4 — Audit & RBAC** | Weeks 7–9 | Immutable audit log · 7-role RBAC · authorization middleware | Core enterprise requirements met |
| **v0.5 — Workflows & CI/CD** | Weeks 10–12 | 8-step approval workflow · PR diff comments · GitHub/GitLab CI actions | Full promotion governance |
| **v1.0 — GA** | Month 4 | SSO (SAML/OIDC) · secrets management · web dashboard · SOC 2 Type I | Full enterprise feature set |
| **v1.1** | Months 5–6 | llm-diff eval gates · SCIM · BYOK (AWS KMS) · advanced alerting | Eval-gated promotions |
| **v1.2** | Months 7–9 | HIPAA BAA · EU data residency · FedRAMP readiness · ISO 27001 | Regulated industry support |

---

*Implementation plan prepared March 2026 based on promptlock Enterprise Product Specification v1.0 (February 2026).*
