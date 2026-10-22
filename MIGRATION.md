# UnLeash 2.0 Migration Plan

Evolving UnLeash-Lite + Canopy into **UnLeash** — a single tool to
unlock and manage Unitree robots.

## Thesis

UnLeash-Lite is popular but stops at "you have SSH." Canopy is capable
but nobody finds it. Merging them creates the complete journey:
**enroll → manage → deploy** in one package, positioned for labs and
academia instead of pentesters.

---

## 1. Package identity

| Field | Before (Lite) | Before (Canopy) | After |
|---|---|---|---|
| PyPI name | `unleash-lite` | `canopy` | `unleash` |
| Import | `unleash_lite` | `canopy` | `unleash` |
| CLI entry | `unleash-lite` | `canopy` | `unleash` |
| Repo | `a-bissell/UnLeash-Lite` | `a-bissell/canopy` | `a-bissell/UnLeash-Lite` (rename later) |
| Tagline | "WebRTC jailbreak for Unitree Go2" | "Enterprise fleet management…" | "Own your Unitree robot" |
| Python | ≥3.10 | ≥3.11 | ≥3.11 |

Keep the existing repo + stars. Rename on GitHub after 2.0 ships
(`UnLeash-Lite` → `UnLeash`), with redirect.

---

## 2. Directory layout

```
unleash/                        # was unleash_lite/
├── __init__.py
├── __main__.py                 # unified CLI dispatcher
├── config.py                   # env-based config (from canopy)
│
├── core/                       # WebRTC channel + signaling (from lite)
│   ├── __init__.py
│   ├── webrtc.py               # Go2DataChannel — untouched
│   ├── webrtc_sdp.py           # SDP jailbreak path — untouched
│   └── cloud.py                # Unitree cloud API (was unitree_cloud.py)
│
├── enroll/                     # the "jailbreak," reframed
│   ├── __init__.py
│   ├── payloads.py             # init-ssh + init-ssh-persist + bypass-hosts + custom
│   ├── orchestrator.py         # WebRTCJailbreakOrchestrator (was webrtc_jailbreak.py)
│   └── enrollctl.py            # NEW: `unleash enroll` — guided single-command flow
│
├── broker/                     # MQTT broker (from canopy, nearly verbatim)
│   ├── __init__.py
│   ├── server.py
│   ├── protocol.py
│   └── auth.py
│
├── packages/                   # OTA package builder (from canopy)
│   ├── __init__.py
│   ├── builder.py
│   ├── ota_protocol.py
│   ├── deployment.py
│   ├── file_server.py
│   ├── examples.py
│   └── schemas.py
│
├── fleet/                      # robot tracking (from canopy)
│   ├── __init__.py
│   ├── manager.py
│   └── schemas.py
│
├── certs/                      # TLS cert generator (from canopy)
│   ├── __init__.py
│   └── generator.py
│
├── auth/                       # JWT auth for dashboard (from canopy)
│   ├── __init__.py
│   ├── jwt_handler.py
│   └── dependencies.py
│
├── db/                         # database (from canopy)
│   ├── __init__.py
│   ├── engine.py
│   └── models.py
│
├── audit/                      # audit log (from canopy)
│   ├── __init__.py
│   └── logger.py
│
├── api/                        # REST + WebSocket API (from canopy)
│   ├── __init__.py
│   ├── app.py                  # FastAPI factory (was canopy/app.py)
│   ├── fleet_routes.py
│   ├── command_routes.py
│   ├── package_routes.py
│   ├── deployment_routes.py
│   ├── audit_routes.py
│   ├── auth_routes.py
│   ├── system_routes.py
│   └── websocket_routes.py
│
├── telemetry/                  # optional DDS telemetry (from canopy)
│   └── __init__.py
│
└── dashboard/                  # web UI assets
    └── ...                     # merged: React frontend from canopy
                                # (lite's dashboard.html becomes the
                                #  "Enroll" page in the React app)

frontend/                       # Vite/React source (from canopy)
├── src/
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── Enroll.tsx          # NEW: replaces lite's dashboard.html
│   │   ├── Packages.tsx
│   │   ├── PackageBuilder.tsx
│   │   ├── Deployments.tsx
│   │   ├── RobotDetail.tsx
│   │   ├── AuditLog.tsx
│   │   └── Login.tsx
│   └── ...

tests/
├── test_payloads.py            # existing (trimmed to kept payloads)
├── test_deployment.py          # from canopy
├── test_deployment_routes.py   # from canopy
├── test_websocket_auth.py      # from canopy
└── test_enroll.py              # NEW: enrollment flow tests
```

---

## 3. CLI design

```
unleash                             # no args → print help + quickstart
unleash enroll <robot-ip>           # THE happy path (see §5)
unleash enroll --list               # scan LAN for robots
unleash serve                       # start broker + API + dashboard
unleash deploy <package> <serial>   # push a .upk to a robot
unleash build <spec.json>           # build a .upk from commands

# Power-user / backward-compat subcommands
unleash jailbreak <mode> [opts]     # raw payload delivery (was: unleash-lite <mode>)
unleash fetch-key --email ...       # cloud key retrieval
unleash probe [--robot-ip ...]      # diagnostic DDS dump
```

`unleash enroll` is the front door. `unleash jailbreak` preserves the
raw capability for power users without cluttering the main UX.

---

## 4. What stays, what goes, what moves

### Payloads: KEEP
| Name | Why |
|---|---|
| `init-ssh` | Core enrollment technique (fw ≥1.1.14) |
| `init-ssh-persist` | Follow-up persistence |
| `bypass-hosts` | MQTT redirect — needed for enrollment |
| `bypass-ssh` | Alternate SSH path (cron-based, fw 1.1.14) |
| `custom` | Hidden under `jailbreak` subcommand for power users |

### Payloads: CUT from user-facing CLI
| Name | Why |
|---|---|
| `ssh` | Superseded by init-ssh on current firmware |
| `reverse-shell` | Wrong message for a lab tool. Keep the code in git history |
| `bypass-cron` | Primitive; init-ssh is the user-facing path |
| `bypass-escalate` | Primitive; init-ssh is the user-facing path |
| `bypass-file` | Primitive; custom covers this if needed |

### Modules: ADOPT from Canopy
| Module | Notes |
|---|---|
| `broker/` | Nearly verbatim. Rename internal refs from `canopy` to `unleash` |
| `packages/` | Verbatim. The UPK builder + deployment pipeline |
| `fleet/` | Verbatim |
| `certs/` | Verbatim |
| `auth/` | Verbatim |
| `db/` | Verbatim |
| `audit/` | Verbatim |
| `api/` | Verbatim, plus new enrollment routes |
| `config.py` | Merge: Canopy's pydantic settings + env prefix `UNLEASH_` |
| `frontend/` | Canopy's React app + new Enroll page |

### From Lite: RESTRUCTURE
| Old | New | Notes |
|---|---|---|
| `webrtc.py` | `core/webrtc.py` | Untouched |
| `webrtc_sdp.py` | `core/webrtc_sdp.py` | Untouched |
| `unitree_cloud.py` | `core/cloud.py` | Rename only |
| `webrtc_payloads.py` | `enroll/payloads.py` | Trim registry, keep internals |
| `webrtc_jailbreak.py` | `enroll/orchestrator.py` | Rename |
| `server.py` | dropped | Replaced by `api/app.py` (FastAPI) |
| `dashboard.html` | dropped | Replaced by React `Enroll.tsx` page |

---

## 5. `unleash enroll` — the flagship command

Single command that takes a robot from stock to managed:

```
$ unleash enroll 192.168.123.161
```

Steps (automated):
1. Connect via WebRTC on :9991
2. Detect firmware version from DDS handshake
3. If fw ≥1.1.15, prompt for AES key (or `--aes-key`)
4. Deliver combined payload:
   a. `init-ssh` (sitecustomize.py → sshd + deb_update.sh persist)
   b. Wait for SSH to come up (poll port 22, ~10s)
   c. SSH in, install `ssh_guard.sh` persistence
   d. Write `/etc/hosts` redirect → Canopy broker IP
   e. Install Canopy CA cert into system trust store
   f. Restart MQTT client service
5. Verify robot appears in broker's connected clients
6. Print summary: serial, IP, SSH password, dashboard URL

For fw <1.1.14 or when WebRTC isn't available, fall back to
`unleash jailbreak` with manual instructions.

### What the user sees

```
$ unleash enroll 192.168.123.161

  UnLeash — enrolling robot at 192.168.123.161

  [1/6] Connecting via WebRTC...              ✓  firmware 1.1.15.1
  [2/6] AES key required (fw ≥1.1.15)
        Enter key (or run `unleash fetch-key`): ********
  [3/6] Deploying SSH access...               ✓  sshd running
        ⚠  Press L1+Y on controller TWICE, then press Enter
  [4/6] Installing persistence...             ✓  ssh_guard.sh active
  [5/6] Redirecting to UnLeash broker...      ✓  /etc/hosts updated
  [6/6] Verifying enrollment...               ✓  robot online in fleet

  ┌─────────────────────────────────────────┐
  │  Serial:    GO2-XXXXXXXXXX              │
  │  SSH:       ssh root@192.168.123.161    │
  │  Password:  unleash                     │
  │  Dashboard: http://localhost:8080       │
  └─────────────────────────────────────────┘

  Run `unleash serve` to start the management dashboard.
```

---

## 6. Dependencies

```toml
[project]
dependencies = [
    # Core (from unleash-lite)
    "aiortc",
    "pycryptodome",
    "cryptography",
    "requests",
    "curl_cffi",
    # Server (from canopy)
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "alembic>=1.13",
    "python-jose[cryptography]>=3.3",
    "bcrypt>=4.0",
    "python-multipart>=0.0.9",
    "pydantic-settings>=2.0",
]

[project.optional-dependencies]
# For users who ONLY want enrollment (no server)
lite = [
    "aiortc",
    "pycryptodome",
    "cryptography",
    "requests",
    "curl_cffi",
]
sdp = ["cyclonedds==0.10.2"]
telemetry = ["cyclonedds>=0.10,<0.11"]
```

**Decision: fat install.** `pip install unleash` gets everything. Labs want
things that work, not dependency puzzles. The extra 30s of install is
nothing compared to "I ran `unleash serve` and it crashed."

---

## 7. Config unification

| Canopy env var | UnLeash env var | Notes |
|---|---|---|
| `CANOPY_*` | `UNLEASH_*` | Prefix change |
| `CANOPY_MQTT_PORT` | `UNLEASH_MQTT_PORT` | Same default: 17883 |
| `CANOPY_SECRET_KEY` | `UNLEASH_SECRET_KEY` | Auto-generated if absent |
| `CANOPY_UPK_ADVERTISE_HOST` | `UNLEASH_ADVERTISE_HOST` | Shortened |
| (none) | `UNLEASH_ROBOT_SUBNET` | NEW: default 192.168.123.0/24 |

---

## 8. Migration phases

### Phase 1: Restructure ✅
- [x] Rename `unleash_lite/` → `unleash/`
- [x] Move files into the new directory layout
- [x] Update all internal imports
- [x] Trim payload registry (cut reverse-shell, bypass-cron, bypass-escalate, bypass-file, old ssh)
- [x] Move cut payloads to `jailbreak` subcommand only
- [x] Update `pyproject.toml` (name, deps, entry points)
- [x] Update tests
- [x] Verify: `unleash jailbreak init-ssh` works (backward compat)

### Phase 2: Integrate Canopy ✅
- [x] Copy Canopy modules into `unleash/` (broker, packages, fleet, certs, auth, db, audit, api)
- [x] Update Canopy imports (`canopy.` → `unleash.`)
- [x] Merge config (`canopy.config` → `unleash.config`, env prefix `UNLEASH_`)
- [x] Wire up `unleash serve` to the FastAPI app
- [x] Verify: `unleash serve` starts broker + API + dashboard

### Phase 3: Enrollment flow ✅
- [x] Build `unleash/enroll/enrollctl.py` — the guided `unleash enroll` command
- [x] Combined payload: init-ssh + hosts redirect + CA install
- [x] Post-SSH automation: ssh_guard, cert install, MQTT restart
- [x] Verification: robot appears in broker
- [x] Enrollment API endpoint (for the web UI)

### Phase 4: Frontend merge ✅
- [x] Add `Enroll.tsx` page to the React app (replaces dashboard.html)
- [x] WebSocket-driven enrollment progress
- [x] Remove `dashboard.html`
- [x] Build + bundle frontend

### Phase 5: Polish ✅
- [x] README rewrite
- [ ] Archive `canopy` repo with pointer to UnLeash *(manual — owner)*
- [ ] Deprecation notice on `unleash-lite` PyPI (final release pointing to `unleash`) *(manual — owner)*
- [ ] GitHub repo rename *(manual — owner)*

---

## 9. What Canopy users get

- Everything they had, under a new import name
- `unleash enroll` eliminates the manual jailbreak prerequisite
- Same REST API, same React dashboard, same OTA pipeline
- Config migration: `CANOPY_*` → `UNLEASH_*` (document in changelog)

## 10. What UnLeash-Lite users get

- `unleash jailbreak init-ssh` still works (backward compat)
- `unleash enroll` does init-ssh + persistence + MQTT redirect in one shot
- `unleash serve` gives them a fleet dashboard they didn't know they needed
- OTA package builder for pushing config/scripts to their fleet
- Cleaner CLI without 11 payload modes to choose between

---

## Decisions (resolved)

1. **Dep weight**: fat install. `pip install unleash` includes everything.
2. **aiohttp**: killed. FastAPI replaces it entirely.
3. **Repo rename**: owner handles manually after 2.0 ships.
4. **Canopy shim**: skipped. Archive the repo with a pointer to UnLeash.
