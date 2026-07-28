# TRC staging deploy — open-webui

Deploys this fork's image to the TRC staging host as its own compose project,
`trc-staging-open-webui`. This repo owns only open-webui; `trc-hermes-agent`
and `paperclip` deploy themselves the same way, and all three attach to the
shared external `poc-net` bridge.

**Build and deploy are one workflow, one dispatch.** There is no separate
publish step — `trc-publish.yml` is gone.

## The build runs on the deploy host

This is the single most important thing to know about this workflow, and it is
the same arrangement `trc-backend` and `trc-hermes-agent` use.

`DOCKER_HOST: ssh://…` is set as **job-level** `env:`, so **every** docker
command in the job — the build included — talks to the staging host's daemon
over SSH. Only the source context crosses the network; no image ever does.

The reason is cache. buildx's default `docker-container` driver creates a fresh
builder container whose layer cache starts **empty on every dispatch**, which
made every deploy a cold 15–45 minute build. The deploy host's own daemon holds
the only layer cache that persists between dispatches, so the build is moved to
where that cache lives. Two settings follow directly from that and are not
optional:

- **`driver: docker`** on `docker/setup-buildx-action` — the remote daemon's own
  builder, rather than a container whose cache dies with the run.
- **no `cache-from`/`cache-to`** — the daemon's layer store *is* the cache now,
  and the `docker` driver cannot use an external backend like `type=gha` at all.
- **no `platforms`** — the build is native to the server. Naming a platform
  there risks buildx silently switching on QEMU emulation, turning a build that
  was fast only because it was native into a very slow one.

The workflow runs on a **self-hosted runner** because the staging host is
internal and unreachable from a GitHub-hosted runner. The job requests only the
bare **`self-hosted`** label: the runner is shared with sibling repos and
requesting extra labels it does not carry would strand the job in the queue
forever. That means the label alone does not guarantee the machine is suitable —
it must be **Linux with `docker`, the compose plugin, `buildx` and an OpenSSH
client**, and that is an operational requirement on runner registration rather
than something the workflow can assert.

**Never a `docker context`.** A context is *persistent state* on a self-hosted
runner: `docker context create` fails "already exists" on the second run against
the same runner, and `docker context use` repoints that runner's **default**
daemon for every later job that lands on it — including sibling repos' deploys
and unrelated workflows. A job-level `DOCKER_HOST` achieves the same redirection
scoped to this job alone, and disappears with it.

`DOCKER_HOST` must not be **workflow**-level either. That would apply to any job
added later that is not this deploy, so a future lint or validation job would
start dialling the staging host for every docker call it makes.

### Preconditions are checked before the build, not after

Because the build happens on the deploy host, a reachable daemon and free disk
are preconditions of the **build**, not merely of the deploy. `Verify host
preconditions` therefore runs *before* the build step and reads free space on
`/var/lib/docker`: it **fails** below 10 GB and warns below 25 GB. BuildKit's
out-of-space failures name everything except the cause, so without this gate an
out-of-space host fails obscurely most of an hour into a cold build instead of
in seconds. The validator asserts the ordering, not just the presence of both
steps.

`Verify the shared gateway key` runs before the build for the same reason: a
`HERMES_API_KEY` under 16 characters cannot produce a working deploy, and
finding that out after a cold build wastes the entire run.

## There is no registry

`push: false`. Both tags land straight in the deploy host's image store — which
is the same daemon `docker compose up -d` talks to. Nothing is pushed to GHCR,
nothing is pulled from it, and the workflow has no `docker login` and no
`packages: write` permission.

The `ghcr.io/nature-technologies/trc-open-webui` prefix survives in the tag
names, but it is now **only a local tag name**, kept so run logs and rollback
tags read the same as they did under the retired publish-then-pull scheme.

The compose service sets **`pull_policy: never`**. Compose's default
(`missing`) would pull whenever the tag is absent locally, which is wrong in two
ways here: on a routine deploy it would hide a build that never landed behind a
registry round trip, and on a rollback dispatch naming an older `:git-<7>` tag
it could start whatever GHCR still has under that tag instead of the copy in
this host's image store. `never` fails closed.

**The consequence is that rollback is host-local — see "Rolling back".**

## No env file, anywhere

There is no `.env.staging` and nothing is rendered to disk. The `Deploy` step
binds the secrets as its own `env:`, and Compose resolves the compose file's
`${…}` references straight from that process environment. Two things follow:

- **No secret touches disk**, on the runner or on the server.
- **Nothing is dotenv-parsed**, so values are taken literally. A `$`, backtick
  or `#` in a secret survives instead of being interpolated or truncated. The
  workflow used to *reject* those three characters outright, because Compose's
  `env_file` parser mangled them; that guard is gone because the failure it
  guarded against is gone. The **length** guard on `HERMES_API_KEY` remains — it
  is about the gateway, not about parsing.

Because that step's environment is the only source for those variables, an
omission there would be **silent**: Compose substitutes an empty string with a
mere warning for a plain `${VAR}`, and only the `${VAR:?}` spellings fail loudly.
`deploy/trc/validate_compose.py` asserts that the `Deploy` step's `env:` declares
every `${…}` the compose file references.

This repo has **no bind mount** — unlike `trc-hermes-agent`'s `config.yaml`,
nothing needs to be copied onto the host for compose to start. The only thing
this deploy writes to the server is the JWT fingerprint (see "Publish the
shared-key fingerprint"), and that goes over plain `scp`, not through
`DOCKER_HOST`.

## The runner is persistent and SHARED

Unlike a GitHub-hosted runner, this machine is reused by later jobs — including
`trc-hermes-agent` and `paperclip`'s deploys, which can run **concurrently**
with this one on the same `$HOME`.

- **The private key is a hard collision, so it is structurally isolated.** It is
  written to `$RUNNER_TEMP/id_rsa` — **never** `~/.ssh/id_rsa` — and loaded into
  a per-job `ssh-agent` whose socket is exported via `$GITHUB_ENV` for every
  later step in that job. A shared `~/.ssh/id_rsa` would let one job's cleanup
  delete the key a sibling job is mid-deploy with; `$RUNNER_TEMP` is scoped to
  the individual job, which makes that impossible. The agent authenticates both
  the explicit `ssh`/`scp` calls and — load-bearing here — the `ssh` the Docker
  CLI spawns internally for `DOCKER_HOST`, which now carries the build too.
- **`~/.docker/config.json` is no longer a concern.** There is no `docker login`
  in this workflow, so nothing here mutates it. The per-job `DOCKER_CONFIG`
  directory that used to isolate it — and the `docker logout` that made that
  isolation necessary — are both gone with the registry.
- **`~/.ssh/known_hosts` is genuinely shared, and that is a documented
  operational requirement rather than something fixed structurally.** The risk
  is lower (worst case under a race is a redundant rescan, not a hard auth
  failure) and there is no per-job equivalent of `$RUNNER_TEMP` for a file every
  job needs to read. The host-key scan writes into `$RUNNER_TEMP` first, removes
  any stale entry for *this* host with `ssh-keygen -R` (both the bare-host and
  `[host]:port` spellings), and only then **appends** (`>>`) to the real file —
  never a bare `>` or a `tee` without `-a`, either of which would truncate
  entries other jobs rely on.

### There is no cleanup step — and what that costs

This workflow has **no `if: always()` cleanup step**, matching
`trc-hermes-agent`'s deploy. Most of what the old one did became moot with this
flow: there is no `.env.staging` to delete and no registry session to log out
of. One thing did not, and it is a deliberate trade rather than an oversight:

- The key **file** is fine. It lives only under `$RUNNER_TEMP`, which the runner
  clears at the start of each job.
- The per-job **`ssh-agent` is left running.** It holds the **decrypted**
  private key in memory on this persistent runner — reachable by anything that
  can read its socket path — until the machine reboots, and a new one is started
  on **every dispatch**. Reap them with `pkill ssh-agent` on the runner if that
  accumulation matters to you.

## Host prerequisites

### One-time host preparation (before the FIRST dispatch)

`bootstrap: true` cannot stand up a host on its own from nothing, and the list
below is what the workflow genuinely cannot do for itself. Run this **once per
host, as root or with sudo, before any dispatch** — including a `bootstrap:
true` one:

```
sudo install -d -o <deploy-user> -g <deploy-user> /srv/trc /srv/trc/staging
```

Both levels are needed, not just the leaf: the deploy `mkdir -p`s under
`/srv/trc/staging`, which needs write on that directory, and creating
`/srv/trc/staging` itself needs write on `/srv` — neither of which a non-root
deploy user has on a fresh host. The deploy never uses `sudo`, by design, so
this cannot be folded into the workflow.

The deploy creates **only** `poc-net`, idempotently, on every run. Outside
`bootstrap` mode (see below) it creates neither `trc-shared` nor
`trc-staging-open-webui-data`, and fails if either is missing:

- **`trc-shared`** is owned by whoever runs the trc-backend stack. The `Verify
  host preconditions` step fails early if it is absent, before the build starts.
  Create it on the backend side, not here — or dispatch with `bootstrap: true`
  on a genuinely fresh host (below).
- **`trc-staging-open-webui-data` must already exist and already hold the Open
  WebUI database.** The deploy does not run `docker volume create` on a routine
  deploy: the volume is declared `external: true` precisely so Compose refuses
  to start without it, and pre-creating it would boot Open WebUI against a
  silently *empty* volume — no chats, no users, no settings — with every smoke
  test still passing. **Worse here than anywhere else in this stack:** Open
  WebUI is published on `0.0.0.0:3000` with signup enabled, so an empty data
  volume means **the first visitor becomes admin**, and every automated check
  still goes green. See Phase 2 preconditions below.

### Disk space

The host now carries the **build** as well as the running stack, so free space
on `/var/lib/docker` is a hard requirement rather than a nicety:

| Free space | Behaviour |
|---|---|
| < 10 GB | `Verify host preconditions` **fails** the run |
| 10–25 GB | warns: enough for a cached build, tight for a cold one |
| > 25 GB | fine |

See "Pruning the deploy host" below before freeing space — some prunes destroy
every rollback target.

### Memory, and the frontend build's V8 heap

This is the precondition that actually bit when the build moved onto the deploy
host. The frontend stage failed with:

```
FATAL ERROR: Ineffective mark-compacts near heap limit
Allocation failed - JavaScript heap out of memory
```

That is **V8's own limit**, not the kernel's — `SIGABRT`, where a kernel
OOM-kill would be `SIGKILL`/exit 137. V8 sizes its default heap from the memory
it can *see*, so the identical `npm run build` passes with no setting at all on
the 16 GB `ubuntu-latest` runner in `frontend.yaml` and dies on a smaller host.
Nothing about the build changed; the machine did.

The deploy pins the cap explicitly. **`NODE_HEAP_MB` in the workflow's top-level
`env:` is the single source of truth**: the build step passes it as the
`NODE_OPTIONS` build-arg, and `Verify host preconditions` derives its memory
thresholds from the same number, so tuning it retunes the gate that guards it.
The `Dockerfile` declares its own `ARG NODE_OPTIONS` default of **4096** so
local builds on an ordinary developer machine work unchanged; staging overrides
it with the workflow's value, which is lower on purpose — see below.

**Pinning the cap inverts the risk, which is why the gate exists.** A heap cap
is not a reservation — it stops V8 self-limiting below what vite needs, but it
does not make memory appear. With the cap pinned, V8 will *try* to use it, and a
host that cannot spare it gets an OOM-kill instead of a clean build failure —
possibly of a **running staging container**, because unlike the old
build-on-the-runner arrangement the build now competes with the serving stack for
the same RAM. BuildKit ignores `--memory`, so there is no container-level cap to
fall back on: the heap number is the only lever, and the gate is what keeps it
honest.

### What the host actually has

Measured on the first dispatch that reached the gate:

```
MemTotal:      5529200 kB   ~5.3 GiB   -- the entire VM
MemAvailable:  4327900 kB   ~4.1 GiB   -- after the running stack
SwapTotal:     4194300 kB   ~4.0 GiB
```

**The deploy host cannot give this build a 4 GB heap.** Even with the whole
stack stopped, 4 GB of heap plus node's non-heap allocations is essentially the
entire machine. `NODE_HEAP_MB` is therefore **3072** — the largest cap that fits
in *physical* memory here.

Treat 3072 as an interim value tied to this host's size, not a tuned optimum.
4096 is what the CI runner effectively gets and is the only cap this build is
*proven* to complete in; **raise it back to 4096 on a host with 8 GB or more.**
If 3072 still hits the heap limit, the requirement is provably above 3 GB and
the answer is more RAM, not a smaller number.

Worth knowing why this repo is the outlier: `trc-hermes-agent` and `paperclip`
build fine on the same host because their builds are light. open-webui is the
only one of the three with a heavy SvelteKit/vite frontend build, so it is the
only one that runs into the host's memory ceiling.

### What the gate checks

It reads `/proc/meminfo` over SSH and logs
`MemTotal`/`MemAvailable`/`SwapTotal`/`SwapFree` on every run. It models **two
different risks**, which an earlier version wrongly conflated by testing the
heap against physical memory alone:

| Condition | Result | Why |
|---|---|---|
| `MemAvailable + SwapFree` < `NODE_HEAP_MB` + 1 GB | **fails the run** | OOM-kill risk. The kernel has nothing left to reclaim and will kill something — possibly a running staging container |
| `MemAvailable` < `NODE_HEAP_MB` + 1 GB | warns | The build will swap. Swap averts the OOM-kill but not GC thrash — mark-compact walks the whole heap — so the build may be very slow or exhaust the 45-minute job timeout |
| otherwise | OK | The heap fits in physical memory |

`MemAvailable` rather than `MemTotal`, and `SwapFree` rather than `SwapTotal`,
because only those account for what the running stack already holds. The 1 GB
of slack over the cap is for node, esbuild's native allocations and vite's
workers, which all live **outside** the V8 heap the cap governs.

If the gate fails: add RAM to the host, or add swap (disk is not the constraint
— there is 124 GB free), or lower `NODE_HEAP_MB` with the caveat above.

### The `bootstrap` input

`workflow_dispatch` takes a `bootstrap` boolean input, default `false`. When
`true`, the `Verify host preconditions` step **creates** `trc-shared` and
`trc-staging-open-webui-data` instead of failing when they are missing, and logs
an `::warning::` for each one it creates. Use this **only** when standing up a
genuinely fresh host in one dispatch — it lets that first deploy succeed without
a human pre-creating the network and volume by hand over SSH. A volume created
this way is empty; it is not a substitute for the Phase 2 migration below on a
host that is supposed to already have data, and because signup is enabled, do
not leave a freshly bootstrapped instance unattended before claiming the first
admin account.

Leave `bootstrap` at its default `false` on every routine deploy. With it
`false`, both checks stay fail-closed exactly as before.

The deploy user (`USERNAME`) also needs:

- **write access to `/srv/trc/staging/fingerprints`** (the deploy `mkdir -p`s it
  before scp-ing the JWT fingerprint there);
- **membership of the `docker` group** (or root) on the host, so the SSH session
  backing `DOCKER_HOST` can reach the daemon socket without `sudo`. This now
  covers the **build** as well as the deploy.

### Runner prerequisites

- **Linux, with `docker`, the compose plugin, `buildx` and an OpenSSH client.**
  The job requests only the bare `self-hosted` label (see above), so nothing in
  the workflow can enforce this.
- **It must process one job at a time.** `~/.ssh/known_hosts` is genuinely
  shared across jobs, and the non-destructive scan-then-append pattern assumes
  no other job is touching that file concurrently. If more than one self-hosted
  runner is registered on the same machine — e.g. to let trc-hermes-agent,
  trc-open-webui and paperclip deploy in parallel — each runner **must run as a
  separate OS user**, so they do not share `$HOME` and therefore do not share
  `~/.ssh/known_hosts`. The private key does not have this constraint: it lives
  under the job-scoped `$RUNNER_TEMP`.
- Note that the runner no longer needs much disk or CPU of its own — it uploads
  a build context and waits. The **deploy host** is where the build resources
  are consumed.

### Phase 2 preconditions

This repo's only stateful dependency is `trc-staging-open-webui-data`. Before
the first deploy, with the retired single-compose stack **stopped**, create the
volume and copy the old project-prefixed volume's contents into it — the old
name is the project-prefixed one Compose generated (e.g.
`trc-docker-paperclip-hermes_open-webui-data`), not `open-webui-data`. Copy with
the stack down so nothing is writing mid-copy. The deploy will refuse to run
until the volume exists (unless dispatched with `bootstrap: true`, which is for
a fresh host with no prior data to migrate).

## Running a deploy

1. Actions → **TRC staging deploy (open-webui)** → Run workflow.
2. Leave `bootstrap` unchecked (default `false`) unless this is the first deploy
   to a brand-new host.
3. The workflow builds the image from the checked-out ref **on the deploy host**
   and starts the `:git-<7-char-sha>` tag it just built.

The workflow builds two tags on every dispatch, both **local to the deploy
host's image store**:

- `…/trc-open-webui:staging` — a **moving** pointer, overwritten by every run.
  Kept for human convenience when poking at the host's image list, but
  **nothing in this workflow ever deploys it.**
- `…/trc-open-webui:git-<7-char-sha>` — an **immutable** tag naming the exact
  commit that was built. **This is what gets deployed.** The `Deploy` step sets
  `OPENWEBUI_IMAGE: ${{ steps.tags.outputs.sha }}` in its own `env:`, so the
  deploy runs exactly what this run built — "what is running" is unambiguous,
  and never depends on `:staging` having been overwritten by a later, unrelated
  run between build and deploy.

The `Deploy` step logs the tag it is deploying and then the local **image id**
that actually landed. There is no digest to record any more: `RepoDigests` is
only ever populated for an image that went through a registry, so `(no digest)`
is the expected state and the image id is the record.

## Pruning the deploy host

The `Verify host preconditions` failure message points here. **The order below
matters** — the cheap, safe reclaims come first.

1. **`docker builder prune`** — clears BuildKit's layer cache. Safe: destroys no
   rollback target and no data. It does make the *next* build cold, which is the
   very cost this whole arrangement exists to avoid, so prefer step 2 first if
   it frees enough.
2. **`docker image prune`** (no `-a`) — removes only *dangling* (untagged)
   images. Safe: every `:git-<7>` build is tagged, so no rollback target is
   dangling.
3. **Delete specific old `:git-<7>` tags by hand, oldest first**, keeping the
   last handful:
   ```
   docker images 'ghcr.io/nature-technologies/trc-open-webui' \
     --format '{{.Tag}}\t{{.CreatedAt}}' | sort -k2
   docker rmi ghcr.io/nature-technologies/trc-open-webui:git-<old-sha>
   ```

**Never, on this host:**

- **`docker image prune -a`** — removes every image not currently in use, which
  is **every rollback target this stack has**. There is no registry copy to
  restore them from.
- **`docker volume prune`** — `trc-staging-open-webui-data` is external, so if
  the stack happens to be down it counts as unused and this deletes every chat,
  user and setting.
- **`docker system prune -a --volumes`** — both of the above at once, plus
  `trc-shared` and `poc-net`.

## Rolling back

**Rollback is HOST-LOCAL now, and that is a real reduction in safety net.** The
`:git-<7>` tags exist only in one machine's image store. A `docker image prune
-a` there, or a host rebuild, destroys **every** rollback target with no
registry copy to fall back on. If you need a build to remain recoverable
independently of that host, save it deliberately:

```
docker save ghcr.io/nature-technologies/trc-open-webui:git-<sha> | zstd -o <somewhere-safe>
```

**There is no digest input.** Because every routine deploy already runs the
immutable tag it just built, rolling back to an *older* build means
re-dispatching the workflow from a branch where the **`Deploy`** step has its
`OPENWEBUI_IMAGE` env line hardcoded to an older tag instead of the dynamic
`${{ steps.tags.outputs.sha }}` expression:

1. Confirm the tag you want is still on the host:
   `docker images 'ghcr.io/nature-technologies/trc-open-webui'` over SSH. With
   `pull_policy: never`, a tag that is gone fails the deploy loudly rather than
   silently fetching something else — but you want to know *before* dispatching.
2. Branch off the current `dev` (name it anything that is not `dev`, e.g.
   `rollback/2026-07-27`).
3. In `.github/workflows/trc-staging-deploy.yml` on that branch, find the
   `Deploy` step and change its `OPENWEBUI_IMAGE: ${{ steps.tags.outputs.sha }}`
   line to a hardcoded
   `OPENWEBUI_IMAGE: ghcr.io/nature-technologies/trc-open-webui:git-<short-sha>`.
   Commit and push the branch.
4. Actions → **TRC staging deploy (open-webui)** → Run workflow, and select
   **that branch** as the workflow ref (the "Use workflow from" selector). The
   deploy is `workflow_dispatch`-only, so it runs the workflow definition from
   whichever ref you pick.
5. Delete the branch once you are done. To roll forward again, dispatch from
   `dev` as normal, which builds fresh and deploys its own new `:git-<sha>`.

Because build and deploy are unified, a rollback dispatch **still rebuilds** from
that branch's source and still tags the result — but with `OPENWEBUI_IMAGE`
hardcoded as above, the deploy starts the specific **older** tag you named, not
the one it just built. A plain re-dispatch from an old branch, without that edit,
is not a rollback — it would build and deploy a fresh image from old source
under a new sha.

## Required repository secrets (environment: `staging`)

The environment name is lowercase `staging` — GitHub Actions matches environment
names case-sensitively, so a `Staging` environment's secrets will not resolve
here, and every one of them would arrive as the empty string.

| Secret | Notes |
|---|---|
| `SSH_PRIVATE_KEY_DEV` | Deploy user's private key |
| `HOST` | Staging host, used for `ssh-keyscan`, for the job-level `DOCKER_HOST`, and by the plain `ssh`/`scp` calls |
| `USERNAME` | Deploy user on the host. Needs `docker` group membership — the **build** runs through this account now, not just the deploy |
| `SSH_PORT` | Optional, defaults to 22. Threaded through every consumer: the `ssh-keyscan` that seeds `known_hosts`, the job-level `DOCKER_HOST`, and the plain `ssh`/`scp` calls — a mismatch would scan one endpoint and then dial another |
| `HERMES_API_KEY` | **Shared value.** Must be identical to `trc-hermes-agent`'s copy and to Paperclip's third copy in its instance `config.json`. Must be ≥16 characters — below that the gateway refuses to start the API server, so the symptom is connection-refused on :8642, not a 401. Checked before the build |
| `OPENWEBUI_JWT_SECRET` | **Two-repo secret.** trc-backend calls the same value `IDENTITY_JWT_SECRET` and also needs `ENFORCE_VERIFIED_IDENTITY=true`. Verified by fingerprint comparison, warn-only |

Host keys are **scanned at deploy time**
(`ssh-keyscan -T 10 -p "$SSH_PORT" -H "$HOST" > "$RUNNER_TEMP/known_hosts"`)
rather than pinned in advance, then merged into `~/.ssh/known_hosts`
non-destructively. Trust-on-first-use has the same trade-off it always did:

- It still protects against a passive attacker who cannot intercept the very
  first connection of a run — `StrictHostKeyChecking` is never disabled, so if
  the host key changes *after* the scan (mid-run, or on a later run against a
  key swapped since the last scan) the connection aborts rather than silently
  trusting a new key.
- It does **not** protect against an active machine-in-the-middle present at the
  moment `ssh-keyscan` runs, since there is no prior pinned key to compare
  against. This is a deliberate trade against the operational cost of
  maintaining a pinned-key secret in step with any host-key rotation.

Note that the blast radius of that trade is larger now than it was: the SSH
channel carries the **build context** as well as the deploy, and the daemon on
the far end builds and runs whatever arrives.

## Known behaviour changes

From the retired single-compose stack:

- **No `depends_on: hermes-agent`.** It is a separate compose project now, and
  `depends_on` cannot cross projects. `restart: unless-stopped` plus the smoke
  gate covers ordering.
- **`ENABLE_PERSISTENT_CONFIG` stays `"False"`.** With it on, a stale connection
  row in the carried-over data volume outranks
  `OPENAI_API_BASE_URL`/`OPENAI_API_KEY` and chat stays broken after a recreate.
  The validator enforces this.

From the retired build-on-runner, publish-to-GHCR scheme:

- **The build runs on the deploy host**, off a job-level `DOCKER_HOST`, using
  that daemon's persistent layer cache. Deploys go from a 15–45 minute cold
  build to a warm one.
- **Nothing is pushed to or pulled from GHCR.** No `docker login`, no
  `packages: write`, `pull_policy: never` on the service.
- **Rollback targets are host-local** and are destroyed by `docker image prune
  -a` or a host rebuild. This is the main cost of the change.
- **The build competes with the running stack for RAM and disk.** On the runner
  it was isolated. `Dockerfile` now pins the frontend stage's V8 heap (upstream
  ships that line commented out) and the deploy gates on `MemAvailable` before
  building — see "Memory, and the frontend build's V8 heap".
- **No env file.** Secrets are the `Deploy` step's process environment; the
  `$`/backtick/`#` charset guard is gone with the dotenv parsing that needed it.
- **No cleanup step**, which leaks one `ssh-agent` per dispatch on the runner.

## Checks

`deploy/trc/validate_compose.py` asserts the invariants that make three
independent compose projects add up to one stack — above all `external: true`
on every network and volume, plus each **service's** own `networks:` membership,
since a top-level network no service joins is silently ignored. It also asserts
`pull_policy: never`, without which Compose would fall back to GHCR for a tag
this host is supposed to own.

For the deploy workflow specifically it asserts:

- the job requests the **`self-hosted`** runner label (all three `runs-on`
  spellings understood: scalar, list, and the `{group, labels}` mapping) —
  `ubuntu-latest` cannot reach the internal staging host at all;
- `environment` is exactly **`staging`**, lowercase;
- **every** `DOCKER_HOST` value references both `secrets.HOST` and
  `secrets.USERNAME`. Of all the assertions here this is the one that catches a
  **silent** failure: a hardcoded `ssh://root@10.0.0.9:22` would build and
  deploy on whatever machine that literal names, with every secret and every
  smoke test following it there;
- `DOCKER_HOST` is set at **job** level — not step level, which would leave the
  build on the runner and its cache empty; and not workflow level, which would
  apply to unrelated jobs added later. No step may shadow it with its own;
- `Verify host preconditions` runs **before** the build step, by position — not
  merely that both exist;
- the build step sets **`push: false`** and sets no `cache-from`, `cache-to` or
  `platforms`; `setup-buildx-action` uses **`driver: docker`**;
- the `Deploy` step's own `env:` declares **every** `${…}` the compose file
  references — with no env file, that step's environment is the only source, and
  Compose substitutes an empty string with a mere warning for a plain `${VAR}`;
- compose is **not** invoked with `--env-file`, `.env.staging` appears nowhere,
  and there is no `compose pull` — all three were *requirements* under the old
  scheme and are defects under this one, so each inverted check carries its
  history inline;
- the `Write SSH key and scan the host key` step **positively** contains the
  whole non-destructive `known_hosts` merge: an `ssh-keyscan` into
  `$RUNNER_TEMP`, a `test -s` on it, `ssh-keygen -R` **twice** (the bare-host
  and `[host]:port` spellings), and an append (`>>`) onto `~/.ssh/known_hosts`.
  The "never truncate" rule is negative-only, and on its own it passes a
  workflow with no host-key handling at all;
- `docker context create` appears **nowhere**;
- the private key is never written to `~/.ssh/id_rsa` — only under
  `$RUNNER_TEMP`, so sibling jobs on the same runner can never collide over it;
- `docker volume create` is only reachable from inside a branch whose
  **enclosing** `if`/`elif` condition tests the `bootstrap` input — checked with
  an if/elif/else/fi-aware scan, so an unconditional create placed *after* that
  branch's `fi` is still rejected;
- shell tracing (`set -x` and its spellings) is never enabled, and
  `StrictHostKeyChecking` is never disabled;
- every heredoc-fed `docker exec` passes `-i`, and no `docker exec` that is
  *not* heredoc-fed passes `-i` — a heredoc without `-i` gets no stdin, so the
  smoke test's body never runs and the step still exits 0.

There is deliberately **no** assertion about a cleanup step; see "There is no
cleanup step" above for what that costs and why.

It runs in the **TRC deploy checks** workflow. Read its docstring before
changing the compose file or the deploy workflow.
