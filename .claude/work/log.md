# Work Log
<!-- Entries prepended, newest first -->

## 2026-10-28 18:22

**Session Summary**: Investigated OrbStack disk usage by hand and found that buildx builders using the docker-container driver keep cache in a Docker volume that `docker builder prune` does not touch. On the user's setup these held tens of GB. Built a first flat-list version (orbclean), then rebuilt it as lazyorb, a lazygit-style UI organized per VM. Added a launcher message and in-app spinners to address a reported ~1 minute load time, fixed Pulumi detection and details-pane overflow, and moved the project into its own folder. The repo is now public on GitHub with README, .gitignore, and session files. Open items: the load-time cause, a real end-to-end cleanup, and a LICENSE.

**Decisions Made**:
- Python + Textual via `uv run --script`: no install step beyond uv, which the user already has. Textual gives lazygit-style panes cheaply.
- Machine-side commands use `sudo -n`: OrbStack provides passwordless sudo.
- buildx commands run without sudo: builders are per-user config, and root cannot see them.
- Risk tiers safe/caution/danger, with a confirm modal showing exact commands before anything runs: safety.
- Public repo hygiene (no machine names, work project names, or personal emails in committed files): the repo is public.
- Commits use the GitHub no-reply email from the repo's local git config: keeps the personal address out of the public history.
- Reported sizes use decimal units (GB = 1e9): matches docker and orb output.

**Actions Taken**:
- Investigated OrbStack disk usage with `orb list`, `docker system df`, ncdu inside machines, and `docker buildx ls` / `docker buildx du`.
- Built orbclean (flat cleanup list with a breakdown tree tab), then rebuilt it as lazyorb (Status and Machines panes, details pane, Cleanup table by category, Command log; keys 1/2/3, tab, j/k, space, a, esc, c, n, r, q).
- Fixed Pulumi detection: the scan checks ~/.pulumi/bin explicitly and uses resolved tool paths.
- Fixed details-pane overflow: top-4 lists, Docker summary on one line for Linux machines.
- Measured uv script startup at ~10 s cold / ~2.7 s warm and full scan at 7–17 s.
- Added the launcher message and in-app spinners ("scanning 1/4 · Ns", "scanned in Ns", per-machine spinner).
- Moved the project into its own folder; added README and .gitignore; created the public GitHub repo; scaffolded the session files.
- Tested the UI headlessly only (no end-to-end cleanup run).

**Context/Thoughts**:
- The reported ~1 minute load time is not reproduced. Measured totals were 10–20 s. Spinner numbers from a slow launch are needed.
- Mac-side space reclaim is unverified. The tool logs before/after Mac data-dir size (`~/Library/Group Containers/HUAQ24HBR6.dev.orbstack/data`), but no real cleanup has been observed yet.
- Textual TUIs hang under a non-TTY shell. Test with `App.run_test()` and `save_screenshot`.
- Learnings for OrbStack and buildx are in .claude/learnings/orbstack-docker.md.
