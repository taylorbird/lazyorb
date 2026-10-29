# lazyorb

A lazygit-style terminal UI for seeing what's eating disk space in
[OrbStack](https://orbstack.dev) and cleaning it up.

- **Left:** status (OrbStack's size on your Mac, Mac free space, shared Linux
  disk) and a list of targets: OrbStack's built-in Docker engine plus every
  Linux machine, each with a size bar and how much it could free.
- **Right:** where the selected machine's space goes (top folders, home
  folders, Docker), and its cleanups grouped by category with subtotals.
- **Bottom:** live output of every command it runs.

Cleanups it knows about: Docker build cache, per-builder buildx caches (which
`docker builder prune` and `docker system df` miss), stopped containers,
untagged / unused images, unused volumes, apt cache, systemd journal, npm
cache, Pulumi plugins, and `~/.cache`. Each is tagged **safe**, **caution**
(you'll re-download later), or **danger** (deletes data), and nothing runs
until you confirm the exact commands.

## Install

Requires macOS with OrbStack and [uv](https://docs.astral.sh/uv/). uv installs
the one dependency ([Textual](https://textual.textualize.io)) on first run.

```sh
git clone git@github.com:taylorbird/lazyorb.git
ln -s "$PWD/lazyorb/lazyorb" ~/.local/bin/lazyorb   # any directory on your PATH
lazyorb
```

## Keys

| Key | Action |
| --- | --- |
| `1` `2` `3` / `tab` | focus Machines / Cleanup / Command log |
| `j` `k` / arrows | move |
| `space` / `enter` | select (on a machine: its safe items; on a category: the whole group) |
| `a` | select everything safe in this machine |
| `esc` | clear selection |
| `c` | clean selected (shows the commands and asks first) |
| `n` | open `ncdu` in the highlighted machine (installs it if missing) |
| `r` | rescan |
| `q` | quit |

## How it works

Everything is read from standard tools: `orb list`, `docker system df`,
`docker buildx ls` / `du`, and `du` / `df` run inside each machine via
`orb -m <machine>`. Machine-side commands use `sudo -n`, which works with
OrbStack's default passwordless sudo.
