# TRC staging deploy — open-webui

Deploys this fork's image to the TRC staging host as its own compose project,
`trc-staging-open-webui`. This repo owns only open-webui; `trc-hermes-agent`
and `paperclip` deploy themselves the same way, and all three attach to the
shared external `poc-net` bridge.

## Host prerequisites

The deploy creates `poc-net` and its own volume idempotently, but **not**
`trc-shared` — that bridge is owned by whoever runs the trc-backend stack.
The `Copy deploy artifacts` step fails early if it is missing, before any
secret is written to the host. Create it on the backend side, not here.

## Running a deploy

1. Find the digest:
   `docker buildx imagetools inspect ghcr.io/nature-technologies/trc-open-webui:<tag> --format '{{.Manifest.Digest}}'`
2. Actions → **TRC staging deploy (open-webui)** → Run workflow → paste the
   `sha256:...` digest.

Deploys are digest-pinned, never tag-based. **To roll back, re-dispatch with
the previous digest** — the deploy step prints the currently-running digest
before replacing it.

## Required repository secrets (environment: `staging`)

| Secret | Notes |
|---|---|
| `TRC_SSH_HOST`, `TRC_SSH_USER`, `TRC_SSH_KEY` | Deploy user and its private key |
| `TRC_SSH_KNOWN_HOSTS` | Pinned host key. The workflow fails if empty |
| `TRC_SSH_PORT` | Optional, defaults to 22 |
| `HERMES_API_KEY` | **Shared value**, must equal `trc-hermes-agent`'s copy. The smoke test calls the gateway from *inside* the container, so a mismatch fails the deploy |
| `OPENWEBUI_JWT_SECRET` | **Two-repo secret.** trc-backend calls it `IDENTITY_JWT_SECRET` and also needs `ENFORCE_VERIFIED_IDENTITY=true`. Verified by fingerprint comparison, warn-only |
| `GHCR_READ_TOKEN` | Optional. Only if the GHCR package is private |

## Known behaviour changes from the retired single-compose stack

- **No `depends_on: hermes-agent`.** It is a separate compose project now, and
  `depends_on` cannot cross projects. `restart: unless-stopped` plus the smoke
  gate covers ordering.
- **`ENABLE_PERSISTENT_CONFIG` stays `"False"`.** With it on, a stale
  connection row in the carried-over data volume outranks
  `OPENAI_API_BASE_URL`/`OPENAI_API_KEY` and chat stays broken after a
  recreate. The validator enforces this.

## Checks

`deploy/trc/validate_compose.py` asserts the invariants that make three
independent compose projects add up to one stack — above all `external: true`
on every network and volume. It runs in the **TRC deploy checks** workflow.
Read its docstring before changing the compose file.
