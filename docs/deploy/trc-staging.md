# TRC staging deploy — open-webui

Deploys this fork's image to the TRC staging host as its own compose project,
`trc-staging-open-webui`. This repo owns only open-webui; `trc-hermes-agent`
and `paperclip` deploy themselves the same way, and all three attach to the
shared external `poc-net` bridge.

The deploy runs `docker compose` **from the GitHub Actions runner**, against
the host's Docker daemon over a remote Docker context
(`docker context create ... --docker "host=ssh://${USERNAME}@${HOST}:${SSH_PORT}"`).
It never opens an interactive SSH shell on the host to run compose commands.
Three consequences of that:

- The rendered `.env.staging` file is read by the **local** Compose CLI via
  `--env-file` and is never copied to the server. Its values reach the
  containers as container environment, sent over the Docker API through the
  SSH tunnel — there is no plaintext secret file on the staging host.
  `.env.staging` is the only file this workflow ever writes to disk on the
  runner, and the final `Remove the deploy context` step deletes it (with
  `if: always()`, so a failed run still cleans up).
- This repo has **no bind mount** — unlike `trc-hermes-agent`'s `config.yaml`,
  nothing needs to be copied onto the host for compose to start. The only
  thing this deploy still writes to the server is the JWT fingerprint (see
  "Publish the shared-key fingerprint" below), and that goes over plain `scp`,
  not through the Docker context.
- `docker compose pull` sends the **runner's** registry credentials to the
  remote daemon (`X-Registry-Auth`), not the host's — the staging host never
  **stores** a credential of its own. Its daemon does receive the
  `GITHUB_TOKEN` (on pull, and via `/auth` when `docker login` runs under the
  active remote context), but never persists it; the token dies with the run.
  The workflow logs in to `ghcr.io` on the runner with the built-in
  `GITHUB_TOKEN` before pulling; this is what replaces the old host-side
  `docker login` + `GHCR_READ_TOKEN` secret, and it works whether the package
  is public (as it is today) or private.

## Host prerequisites

The deploy creates **only** `poc-net`, idempotently. It creates neither
`trc-shared` nor `trc-staging-open-webui-data`, and it fails if either is
missing:

- **`trc-shared`** is owned by whoever runs the trc-backend stack. The
  `Verify host preconditions` step fails early if it is absent, before any
  secret is rendered. Create it on the backend side, not here.
- **`trc-staging-open-webui-data` must already exist and already hold the Open
  WebUI database.** The deploy deliberately does not run `docker volume
  create`: the volume is declared `external: true` precisely so Compose
  refuses to start without it, and pre-creating it would boot Open WebUI
  against a silently *empty* volume — no chats, no users, no settings — with
  every smoke test still passing. Worse here than elsewhere: Open WebUI is
  published on `0.0.0.0:3000` with signup enabled, so an empty data volume
  means **the first visitor becomes admin**. See Phase 2 preconditions below.

The deploy user (`USERNAME`) also needs:

- **write access to `/srv/trc/staging/fingerprints`** (the deploy `mkdir -p`s
  it before scp-ing the JWT fingerprint there);
- **membership of the `docker` group** (or root) on the host, so the SSH
  session backing the Docker context can reach the daemon socket without
  `sudo`.

### Phase 2 preconditions

This repo's only stateful dependency is `trc-staging-open-webui-data`. Before
the first deploy, with the retired single-compose stack **stopped**, create the
volume and copy the old project-prefixed volume's contents into it — the old
name is the project-prefixed one Compose generated
(e.g. `trc-docker-paperclip-hermes_open-webui-data`), not `open-webui-data`.
Copy with the stack down so nothing is writing mid-copy. The deploy will refuse
to run until the volume exists.

## Running a deploy

The workflow tracks a **moving tag**, not a digest. `trc-publish.yml` builds
and publishes `ghcr.io/nature-technologies/trc-open-webui:dev` (plus an
immutable `sha-<short-sha>` tag) on every push to `dev` (and to
`chore/new-ci`, while that branch carries CI on its own). The deploy workflow's
`env:` block pins which tag it rolls out:

```yaml
env:
  IMAGE_TAG: dev
```

Change that one line to follow a different branch tag; nothing else in the
workflow needs to change.

1. Actions → **TRC staging deploy (open-webui)** → Run workflow.
2. The workflow pulls `${IMAGE_REPO}:${IMAGE_TAG}` and deploys it.

### Rolling back

**There is no digest input.** Rolling back means pointing `IMAGE_TAG` at the
`sha-<short-sha>` tag of the build you want (visible in the `trc-publish.yml`
run history or in the GHCR package's tag list). Those immutable `sha-` tags
exist precisely to make this possible — `:dev` moves, so it cannot name a
previous build.

`IMAGE_TAG` is workflow-level `env`, not a dispatch input, so changing it
requires a **commit**. Do **not** make that commit on `dev`:

> Pushing an `IMAGE_TAG` change to `dev` re-triggers `trc-publish.yml`, which
> **republishes `:dev` from the same source** — you would rebuild the very
> image you are trying to roll away from, and overwrite the tag in the process.

Instead, dispatch the deploy from a throwaway branch:

1. Branch off the current `dev` (name it anything that is not `dev`, e.g.
   `rollback/2026-07-27`).
2. Edit the one line — `IMAGE_TAG: sha-<short-sha>` — commit, and push the
   branch. No publish is triggered, because `trc-publish.yml` only fires on
   `dev` and `chore/new-ci`.
3. Actions → **TRC staging deploy (open-webui)** → Run workflow, and select
   **that branch** as the workflow ref (the "Use workflow from" selector). The
   deploy is `workflow_dispatch`-only, so it runs the workflow definition from
   whichever ref you pick, including its `IMAGE_TAG`.
4. Delete the branch once you are done. To roll forward again, dispatch the
   deploy from `dev` as normal.

The `Pull and deploy` step still prints the digest that actually landed, so
every run log records what is now running.

## Required repository secrets (environment: `Staging`)

| Secret | Notes |
|---|---|
| `SSH_PRIVATE_KEY_DEV` | Deploy user's private key |
| `HOST` | Staging host, used both for `ssh-keyscan` and as the Docker context target (`ssh://${USERNAME}@${HOST}:${SSH_PORT}`) |
| `USERNAME` | Deploy user on the host |
| `TRC_SSH_PORT` | Optional, defaults to 22. Threaded through all three consumers that need it: the `ssh-keyscan` that seeds `known_hosts`, the Docker context's `ssh://${USERNAME}@${HOST}:${SSH_PORT}` target, and the plain `ssh`/`scp` calls -- a mismatch between the first two would scan the wrong endpoint and then dial a different one |
| `HERMES_API_KEY` | **Shared value.** Must be identical to `trc-hermes-agent`'s copy and to Paperclip's third copy in its instance `config.json`. Must be ≥16 characters — below that the gateway refuses to start the API server, so the symptom is connection-refused on :8642, not a 401 |
| `OPENWEBUI_JWT_SECRET` | **Two-repo secret.** trc-backend calls the same value `IDENTITY_JWT_SECRET` and also needs `ENFORCE_VERIFIED_IDENTITY=true`. Verified by fingerprint comparison, warn-only (see below) |

`TRC_SSH_KNOWN_HOSTS` no longer exists as a secret, and neither do
`TRC_SSH_HOST`/`TRC_SSH_USER`/`TRC_SSH_KEY`/`GHCR_READ_TOKEN` from the retired
scp-based deploy. Host keys are **scanned at deploy time**
(`ssh-keyscan -p "$SSH_PORT" -H "$HOST" > ~/.ssh/known_hosts`) rather than
pinned in advance:

- This still protects against a passive attacker who cannot intercept the very
  first connection of a run — `StrictHostKeyChecking` is never disabled, so if
  the host key changes *after* the scan (e.g. mid-run, or on a subsequent run
  against a key that was swapped since the last scan and cached nowhere) the
  connection still aborts rather than silently trusting a new key.
- It does **not** protect against an active machine-in-the-middle present at
  the moment `ssh-keyscan` runs, since there is no prior pinned key to compare
  against — trust-on-first-use accepts whatever key answers on that first
  connection. This is a deliberate trade against the operational cost of
  maintaining a `TRC_SSH_KNOWN_HOSTS` secret in step with any host-key
  rotation; the previous pinned-key model traded the other way.

Every secret rendered into `.env.staging` is charset-guarded: the workflow
rejects any value containing `$`, a backtick or `#`. Compose's `env_file` parser
interpolates the first two and treats `#` as a comment, so such a value would
reach the container as a *different* string with nothing erroring — a mangled
`HERMES_API_KEY` looks like a 401, a mangled `OPENWEBUI_JWT_SECRET` breaks only
the identity-verified path. `openssl rand -hex 32` never produces any of them.
`.env.staging` itself is written on the runner and passed to Compose with
`--env-file`; it is never copied to the host.

## Known behaviour changes from the retired single-compose stack

- **No `depends_on: hermes-agent`.** It is a separate compose project now, and
  `depends_on` cannot cross projects. `restart: unless-stopped` plus the smoke
  gate covers ordering.
- **`ENABLE_PERSISTENT_CONFIG` stays `"False"`.** With it on, a stale
  connection row in the carried-over data volume outranks
  `OPENAI_API_BASE_URL`/`OPENAI_API_KEY` and chat stays broken after a
  recreate. The validator enforces this.
- **Deploys are tag-based, not digest-based.** The retired workflow required a
  `sha256:...` `image_digest` input on every dispatch. This one tracks the
  moving `IMAGE_TAG` env value instead — see "Running a deploy" above.

## Checks

`deploy/trc/validate_compose.py` asserts the invariants that make three
independent compose projects add up to one stack — above all `external: true`
on every network and volume, plus each **service's** own `networks:` membership,
since a top-level network no service joins is silently ignored. For the deploy
workflow specifically it also asserts:

- the deploy runs against a remote Docker context (`docker context create`),
  never a raw SSH shell — that is what keeps the rendered `.env.staging` off
  the server;
- the deploy verifies `trc-staging-open-webui-data` with
  `docker volume inspect` and refuses to run if it is absent, rather than
  ever running `docker volume create` (see Host prerequisites);
- specifically the step that runs `docker context create` sources its `HOST`
  and `USERNAME` from those secrets and actually references them in its
  script — scoped to that one step, so hardcoding the host there while
  `secrets.HOST` is merely referenced somewhere else in the file (e.g. the
  host-key-scan step) does not pass;
- Compose is invoked with `--env-file`, so secret values are never
  interpolated into a shell command string;
- `compose pull` precedes `compose up -d` (same-line `pull && up -d` counts,
  compared by position within the line), so a deploy can never silently
  redeploy an image already on the host.

It runs in the **TRC deploy checks** workflow. Read its docstring before
changing the compose file or the deploy workflow.
