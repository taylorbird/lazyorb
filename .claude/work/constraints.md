# Constraints Ledger

Entries carry a date and rationale; one-line summaries live in current.md.

## Repo hygiene

### Public repo: no machine, work, or personal identifiers (2026-10-28)
- **Rule:** Never commit machine names, work project names, personal paths, or work email into any file in the repo.
- **Why:** The repo is public on GitHub. Commits use the GitHub no-reply email from the repo's local git config.

## Commands & safety

### buildx commands run as the user, never with sudo (2026-10-28)
- **Rule:** `docker buildx` commands run without sudo.
- **Why:** Buildx builders are stored per user in ~/.docker/buildx. `sudo docker buildx prune --builder X` fails with "no builder found".

### Destructive actions go through the confirm modal (2026-10-28)
- **Rule:** Every destructive action goes through a confirm modal that lists the exact commands. Volume prune stays tagged danger.
- **Why:** Safety. Nothing runs without the user seeing the exact commands first.

## Packaging

### Single file, runnable by `uv run --script` (2026-10-28)
- **Rule:** Keep the app a single file runnable by `uv run --script`. The launcher must print its message before uv starts.
- **Why:** Zero-setup, since uv is already installed. The user wanted immediate feedback on launch, because uv cold start takes ~10 s.
