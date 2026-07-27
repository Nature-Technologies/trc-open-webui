# TRC staging deploy — open-webui

Deploys this fork's image to the TRC staging host as its own compose project,
`trc-staging-open-webui`. This repo owns only open-webui; `trc-hermes-agent`
and `paperclip` deploy themselves the same way, and all three attach to the
shared external `poc-net` bridge.

## Host prerequisites

The deploy creates **only** `poc-net`, idempotently. It creates neither
`trc-shared` nor `trc-staging-open-webui-data`, and it fails if either is
missing:

- **`trc-shared`** is owned by whoever runs the trc-backend stack. The
  `Copy deploy artifacts` step fails early if it is absent, before any secret
  is written to the host. Create it on the backend side, not here.
- **`trc-staging-open-webui-data` must already exist and already hold the Open
  WebUI database.** The deploy deliberately does not run `docker volume
  create`: the volume is declared `external: true` precisely so Compose refuses
  to start without it. Pre-creating it would boot Open WebUI against a silently
  *empty* volume with every smoke test still passing — and because port 3000 is
  published on `0.0.0.0` with signup enabled, an empty volume means **the first
  visitor becomes admin**. See Phase 2 preconditions below.

The deploy user also needs all of:

- **write access to `/srv/trc`** (the deploy `mkdir -p`s
  `/srv/trc/staging/open-webui` and `/srv/trc/staging/fingerprints`);
- **membership of the `docker` group**, so `docker` works without `sudo`;
- **permission to create `/var/lock/trc-deploy.lock`.** `/var/lock` is
  root-owned `0755` on some images, in which case `flock` fails *after* the
  `.env` and the JWT fingerprint have already been copied to the host. Either
  grant write access to `/var/lock` or pre-create the lock file owned by the
  deploy user.

### Phase 2 preconditions

This repo's only stateful dependency is `trc-staging-open-webui-data`. Before
the first deploy, with the retired single-compose stack **stopped**, create the
volume and copy the old project-prefixed volume's contents into it — the old
name is the project-prefixed one Compose generated
(e.g. `trc-docker-paperclip-hermes_open-webui-data`), not `open-webui-data`.
Copy with the stack down so nothing is writing mid-copy. The deploy will refuse
to run until the volume exists.

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

Both secrets rendered into the host `.env` are charset-guarded: the workflow
rejects any value containing `$`, a backtick or `#`. Compose's `env_file` parser
interpolates the first two and treats `#` as a comment, so such a value would
reach the container as a *different* string with nothing erroring — a mangled
`HERMES_API_KEY` looks like a shared-secret mismatch, a mangled
`OPENWEBUI_JWT_SECRET` breaks only the identity-verified path. `openssl rand -hex
32` never produces any of them.

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
on every network and volume, plus each **service's** own `networks:` membership,
since a top-level network no service joins is silently ignored. It also bans two
things in the deploy workflow that would each fail open silently: any
`docker volume create` (see Host prerequisites), and a `flock -c` string that
does not begin with `set -e` — the `-c` string is a separate shell, so without
it a failed `pull` is ignored and `up -d` redeploys the old image while the run
goes green. It runs in the **TRC deploy checks** workflow. Read its docstring
before changing the compose file or the deploy workflow.
