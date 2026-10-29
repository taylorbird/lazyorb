# Current Work State

## Project
lazyorb: a lazygit-style terminal UI (Python + Textual) that shows what is using disk space in OrbStack on macOS and runs cleanups. Single file `lazyorb.py`, run with `uv run --script` via a PEP 723 header. A bash launcher `lazyorb` prints "lazyorb starting…" and then execs uv. Public GitHub repo.

## Objective
A fast, safe "see why OrbStack is big and clean it up" tool. May later grow into a broader Mac dev-disk cleaner.

## Constraints
Full ledger: .claude/work/constraints.md. Path-scoped rules: .claude/rules/.
- Public repo: never commit machine names, work project names, personal paths, or work email.
- buildx commands run as the user, never with sudo (builders are per-user config).
- Every destructive action goes through the confirm modal listing exact commands; volume prune stays tagged danger.
- Keep the app a single file runnable by `uv run --script`; the launcher prints before uv starts.

## Current Focus
- Startup feel: measured uv startup ~10 s cold / ~2.7 s warm and full scan 7–17 s (slowest step is OrbStack's `docker system df`, ~6.5 s). Added launcher message and in-app spinners.
- Fixed Pulumi detection (non-login `sh -c` lacks ~/.pulumi/bin on PATH) and details-pane overflow.
- Repo made public on GitHub with README, .gitignore, and session files. No cleanup run end-to-end from the app yet (headless UI tests only).

## Last Checkpoint
2026-10-28 18:22 PDT

## Next Actions
1. Run lazyorb in a real terminal; capture spinner timing on a slow launch to find where the ~1 minute goes.
2. Run a real cleanup from the app and confirm the before/after Mac data-dir size changes.
3. Choose a LICENSE.
4. Consider caching the slow `docker system df` result or showing partial host data sooner.
