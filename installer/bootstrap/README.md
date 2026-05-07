# Bootstrap shim

This is the only file each LaboratoireSonore repo needs to commit to
ship the universal installer. Drop `install.py` at the root of the repo
+ point the README at it. Done.

## How it works

```
$ python install.py
[lab-installer] fetching latest installer…
[lab-installer] cache up to date
… (real GUI / CLI takes over)
```

The shim:
1. Looks up the master copy at
   `https://raw.githubusercontent.com/laboratoiresonore/laboratoiresonore/main/installer/`
2. Compares cached `VERSION` with remote `VERSION`. If stale, re-downloads
   the protocol files (`src/lab_installer.py`, `manifest.py`, `crypto.py`,
   `__init__.py`, plus optional asset PNGs).
3. Hands off to the cached `lab_installer.py` via `runpy`.

The cache lives at `~/.lab-installer/cache/`. Refreshing every 24 h
unless `--no-update` is passed.

## Properties

- **Identical across repos** — same file in beatweaver, spellcaster,
  ComfyUI-Spellcaster, voodoomancer, etc. Don't fork it.
- **No deps** — uses stdlib `urllib.request` only. Runs on any Python 3.10+.
- **Offline-tolerant** — if the network is down but the cache exists,
  uses the cache. Errors only when there's nothing cached AND no network.
- **Atomic downloads** — `.partial` rename pattern so a torn fetch can't
  corrupt the cache.
- **No state in the repo** — every install run hits a clean cache state
  derived from the master.

## Syncing to a new repo

```bash
# From the LaboratoireSonore repo root:
cp installer/bootstrap/install.py ../<other-repo>/install.py
cd ../<other-repo>
git add install.py
git commit -m "add lab-installer bootstrap"
```

Or as a one-liner (run from the target repo):
```bash
curl -sSL https://raw.githubusercontent.com/laboratoiresonore/laboratoiresonore/main/installer/bootstrap/install.py > install.py
git add install.py && git commit -m "add lab-installer bootstrap"
```

## When to update the shim

**Almost never.** New features land in the master copy and propagate
on next launch — the shim doesn't need touching. The only reasons to
re-sync:

1. The protocol changes (e.g. new required file, different cache layout).
   In that case the master will surface a clear error message asking
   the user to re-run the bootstrap-update steps.
2. A security issue in the shim itself (e.g. URL hijack mitigation).

For (1), bump the master's `installer/VERSION` major (1.x.x → 2.0.0)
to signal a breaking protocol change. Old shims can keep using the
last-cached compatible master.

## Compared to alternatives

| Approach | Why we didn't pick it |
|---|---|
| Git submodule | Adds a chore for every repo update; can't self-update on user side |
| Vendored copy | N copies to keep in sync; defeats the "one source of truth" point |
| pip install lab-installer | PyPI packaging overhead; doesn't ship pre-cooked private manifest |
| Curl-pipe-bash | Opaque to security-minded users; breaks Windows users |
| Standalone .exe per repo | Re-builds for every release; users don't trust unsigned exes from random repos |

The bootstrap shim hits the sweet spot: tiny, transparent, one-time
commit per repo, self-updating on every launch.
