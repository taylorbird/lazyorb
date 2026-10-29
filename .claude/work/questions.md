# Open Questions

- Where does the reported ~1 minute load time actually go? Measured only 10–20 s total (uv cold ~10 s, warm ~2.7 s; scan 7–17 s, slowest step OrbStack `docker system df` ~6.5 s). Need the spinner's numbers from a slow launch.
- Does OrbStack return freed space to macOS immediately, or lazily? The tool logs before/after Mac data-dir size; not yet observed after a real cleanup.
- No cleanup action has been run end-to-end from the app yet (only headless UI tests).
- No LICENSE chosen yet for the public repo.
- Should lazyorb grow into a broader cleaner (Mac-side caches, Xcode, Homebrew, etc.)?

## Resolved
- Builder name for buildx prune: node name minus trailing 0; run without sudo (resolved 2026-10-28).
