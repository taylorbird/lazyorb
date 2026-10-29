# OrbStack & Docker learnings

- `docker buildx ls --format json` emits one JSON object per line. Builders with Driver "docker-container" keep cache in volume `buildx_buildkit_<node>_state`. The node name is the builder name plus "0", so the builder name is the node name without the trailing 0.
- Prune buildx cache with `docker buildx prune -f --builder <name>`. `docker buildx rm <name>` also deletes the state volume.
- `docker buildx du --builder <name>` prints "Reclaimable:" and "Total:" lines.
- `orb list --format json` lacks disk size. Plain `orb list` text has a size column (split on 2+ spaces).
- `df /` inside any OrbStack machine reports the single shared Linux disk for all machines.
- Ghostty sets TERM=xterm-ghostty, which Debian lacks. Use `env TERM=xterm-256color`, or `infocmp -x xterm-ghostty | orb -m <m> sudo tic -x -`.
- OrbStack data on the Mac lives in `~/Library/Group Containers/HUAQ24HBR6.dev.orbstack/data`. `du -sk` on it measures actual allocated size.
- `docker volume prune` needs `-a` to include named volumes (Docker 23+).
- Textual TUIs hang under a non-TTY shell. Test with `App.run_test()` and `save_screenshot`.
