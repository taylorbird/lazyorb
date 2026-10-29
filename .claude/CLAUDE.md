# Project Instructions

## Session Management
Active work state: @.claude/work/current.md

On session start, read .claude/work/current.md to understand current state.
Use /session-checkpoint before ending sessions. Use /session-resume to continue work.

## Durable knowledge
- .claude/work/constraints.md — durable decisions and hard rules (full ledger)
- .claude/rules/ — path-scoped rules, auto-loaded when matching files are touched
- .claude/learnings/ — technical gotchas by topic

## Project-Specific Context
<!-- Project-specific instructions only. No generic best practices. -->
- Public repo. Keep machine names, work project names, and personal paths out of
  committed files (code, docs, and .claude/work/).
- Single-file Python app run via `uv run --script` (PEP 723 header). The `lazyorb`
  bash launcher prints feedback before uv starts, then execs the script.
- Test headlessly with Textual's `App.run_test()` pilot; the TUI needs a real TTY
  otherwise and will hang under a non-interactive shell.
