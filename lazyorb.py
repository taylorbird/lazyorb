#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["textual>=1.0"]
# ///
"""lazyorb: a lazygit-style TUI for seeing and cleaning OrbStack disk usage.

Left: machines. Right: where the selected machine's space goes, and its
cleanups grouped by category. Bottom: command log.

Keys: 1/2/3 or tab focus pane · j/k move · space select (on a machine: its
safe items; on a category: the whole group) · a select safe in this machine
· esc clear selection · c clean selected · n ncdu in this machine
· r rescan · q quit
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Label, OptionList, RichLog, Static
from textual.widgets.option_list import Option

DATA_DIR = Path.home() / "Library/Group Containers/HUAQ24HBR6.dev.orbstack/data"
HOST = "OrbStack Docker"  # OrbStack's own Docker engine (the Mac's `docker`)

CATEGORIES = [
    "Build caches",
    "Images & containers",
    "System caches",
    "Dev tool caches",
    "Data (destructive)",
]
RISK_STYLE = {"safe": "green", "caution": "yellow", "danger": "bold red"}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# ---------------------------------------------------------------- helpers

UNITS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def parse_size(s: str | None) -> int:
    """Parse docker/orb sizes like '20.66GB (79%)' or '19.3 GB' into bytes."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGT]?B)", s or "")
    if not m:
        return 0
    return int(float(m.group(1)) * UNITS[m.group(2).upper()])


def human(n: int | None) -> str:
    if n is None:
        return "?"
    for unit, div in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{int(n)} B"


def bar(frac: float, width: int) -> str:
    filled = max(0, min(width, round(frac * width)))
    return "█" * filled + "░" * (width - filled)


async def run(*args: str, timeout: float = 600) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return 127, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, ""
    return proc.returncode or 0, out.decode(errors="replace")


# ---------------------------------------------------------------- model


@dataclass
class Builder:
    name: str
    running: bool
    reclaim: int | None


@dataclass
class Machine:
    """A Linux machine, or OrbStack's Docker engine when is_host is set."""

    name: str
    state: str
    size: int
    distro: str = ""
    is_host: bool = False
    scanned: bool = False
    home: str = ""
    tools: dict[str, str] = field(default_factory=dict)  # name -> path inside the machine
    root: list[tuple[str, int]] = field(default_factory=list)
    homedirs: list[tuple[str, int]] = field(default_factory=list)
    paths: dict[str, int] = field(default_factory=dict)
    docker: dict[str, tuple[int, int]] | None = None  # type -> (size, reclaimable)
    builders: list[Builder] = field(default_factory=list)
    disk: tuple[int, int] | None = None  # (total, used) of the shared Linux disk

    @property
    def running(self) -> bool:
        return self.state == "running"


@dataclass
class Scan:
    host: Machine
    machines: list[Machine] = field(default_factory=list)
    data_dir: int | None = None
    mac_free: int | None = None

    @property
    def targets(self) -> list[Machine]:
        return [self.host, *self.machines]

    @property
    def disk(self) -> tuple[int, int] | None:
        return next((m.disk for m in self.machines if m.disk), None)


@dataclass
class Action:
    key: str
    where: str
    category: str
    what: str
    est: int | None
    risk: str  # safe | caution | danger
    cmd: list[str]
    note: str = ""


# ---------------------------------------------------------------- scanning

MACHINE_SCAN = r"""
echo "@@home $HOME"
echo "@@tools"
for t in docker npm pulumi ncdu journalctl apt-get; do p=$(command -v "$t" 2>/dev/null) && echo "$t $p"; done
[ -x "$HOME/.pulumi/bin/pulumi" ] && echo "pulumi $HOME/.pulumi/bin/pulumi"
echo "@@root"
sudo -n du -xk -d1 / 2>/dev/null
echo "@@homedirs"
du -xk -d1 "$HOME" 2>/dev/null
echo "@@paths"
for p in /var/cache/apt /var/log/journal "$HOME/.cache" "$HOME/.npm/_cacache" "$HOME/.pulumi/plugins"; do
  [ -e "$p" ] && sudo -n du -xsk "$p" 2>/dev/null
done
echo "@@disk"
df -k / | tail -1
"""


def parse_du(lines: list[str], skip: str) -> list[tuple[str, int]]:
    rows = []
    for line in lines:
        kb, _, path = line.partition("\t")
        if path and path != skip and kb.isdigit():
            rows.append((path, int(kb) * 1024))
    return sorted(rows, key=lambda r: -r[1])


async def docker_df(prefix: list[str]) -> dict[str, tuple[int, int]] | None:
    code, out = await run(*prefix, "docker", "system", "df", "--format", "{{json .}}")
    if code:
        return None
    usage = {}
    for line in out.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage[row["Type"]] = (parse_size(row["Size"]), parse_size(row["Reclaimable"]))
    return usage


async def buildx_builders(prefix: list[str]) -> list[Builder]:
    """Builders using the docker-container driver keep their own cache that
    `docker builder prune` never touches."""
    _, out = await run(*prefix, "docker", "buildx", "ls", "--format", "json")
    builders = []
    for line in out.splitlines():
        try:
            b = json.loads(line)
        except json.JSONDecodeError:
            continue
        if b.get("Driver") != "docker-container":
            continue
        running = any(n.get("Status") == "running" for n in b.get("Nodes") or [])
        reclaim = None
        if running:
            _, du = await run(*prefix, "docker", "buildx", "du", "--builder", b["Name"])
            m = re.search(r"Reclaimable:\s*(\S+)", du)
            if m:
                reclaim = parse_size(m.group(1))
        builders.append(Builder(b["Name"], running, reclaim))
    return builders


async def list_machines() -> list[Machine]:
    _, out = await run("orb", "list")
    machines = []
    for line in out.splitlines():
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) < 2 or cols[0] == "NAME":
            continue
        size = next((parse_size(c) for c in cols if re.fullmatch(r"[\d.]+ [kKMGT]?B", c)), 0)
        distro = " ".join(cols[2:4]) if len(cols) > 3 else ""
        machines.append(Machine(cols[0], cols[1], size, distro=distro))
    return machines


async def scan_machine(m: Machine) -> None:
    _, out = await run("orb", "-m", m.name, "sh", "-c", MACHINE_SCAN)
    sections: dict[str, list[str]] = {}
    current = None
    for line in out.splitlines():
        if line.startswith("@@"):
            current, _, rest = line[2:].partition(" ")
            sections[current] = []
            if current == "home":
                m.home = rest
        elif current:
            sections[current].append(line)
    for line in sections.get("tools", []):
        name, _, path = line.partition(" ")
        m.tools.setdefault(name, path)
    m.root = parse_du(sections.get("root", []), "/")
    m.homedirs = parse_du(sections.get("homedirs", []), m.home)
    m.paths = dict(parse_du(sections.get("paths", []), ""))
    disk = (sections.get("disk") or [""])[0].split()
    if len(disk) >= 4 and disk[1].isdigit():
        m.disk = (int(disk[1]) * 1024, int(disk[2]) * 1024)
    if "docker" in m.tools:
        m.docker, m.builders = await asyncio.gather(
            docker_df(["orb", "-m", m.name, "sudo", "-n"]),
            buildx_builders(["orb", "-m", m.name]),
        )
    m.scanned = True


async def scan_host(scan: Scan) -> None:
    async def dir_size() -> int | None:
        code, out = await run("du", "-sk", str(DATA_DIR))
        return int(out.split()[0]) * 1024 if code == 0 and out else None

    async def mac_free() -> int | None:
        _, out = await run("df", "-k", str(Path.home()))
        parts = out.splitlines()[-1].split() if out else []
        return int(parts[3]) * 1024 if len(parts) > 3 and parts[3].isdigit() else None

    h = scan.host
    scan.data_dir, scan.mac_free, h.docker, h.builders = await asyncio.gather(
        dir_size(), mac_free(), docker_df([]), buildx_builders([])
    )
    h.size = sum(v[0] for v in (h.docker or {}).values())
    h.scanned = True


# ---------------------------------------------------------------- actions


def docker_actions(m: Machine) -> list[Action]:
    root = [] if m.is_host else ["orb", "-m", m.name, "sudo", "-n"]
    user = [] if m.is_host else ["orb", "-m", m.name]
    usage = m.docker or {}

    def free(kind: str) -> int:
        return usage.get(kind, (0, 0))[1]

    def act(key, cat, what, est, risk, cmd, note=""):
        return Action(f"{m.name}:{key}", m.name, cat, what, est, risk, cmd, note)

    acts = [
        act("buildcache", "Build caches", "Default build cache", free("Build Cache"), "safe",
            [*root, "docker", "builder", "prune", "-f"], "rebuilt on next build"),
        act("containers", "Images & containers", "Stopped containers", free("Containers"), "safe",
            [*root, "docker", "container", "prune", "-f"]),
        act("dangling", "Images & containers", "Untagged <none> images", None, "safe",
            [*root, "docker", "image", "prune", "-f"], "old build leftovers"),
        act("images", "Images & containers", "All images no container uses", free("Images"), "caution",
            [*root, "docker", "image", "prune", "-a", "-f"], "re-pull / rebuild later"),
        act("volumes", "Data (destructive)", "Unused volumes", free("Local Volumes"), "danger",
            [*root, "docker", "volume", "prune", "-a", "-f"], "DELETES DATA in detached volumes"),
    ]
    for b in m.builders:
        acts.append(act(
            f"buildx:{b.name}", "Build caches", f"buildx '{b.name}'", b.reclaim, "safe",
            [*user, "docker", "buildx", "prune", "-f", "--builder", b.name],
            "" if b.running else "builder stopped; size unknown",
        ))
    return acts


def machine_actions(m: Machine) -> list[Action]:
    if not m.scanned:
        return []
    if m.is_host:
        acts = docker_actions(m) if m.docker is not None else []
    else:
        orb, sudo = ["orb", "-m", m.name], ["orb", "-m", m.name, "sudo", "-n"]
        p, t, home = m.paths, m.tools, m.home
        acts = []

        def act(key, cat, what, est, risk, cmd, note=""):
            acts.append(Action(f"{m.name}:{key}", m.name, cat, what, est, risk, cmd, note))

        if "apt-get" in t and p.get("/var/cache/apt", 0) > 10e6:
            act("apt", "System caches", "apt package cache", p["/var/cache/apt"], "safe",
                [*sudo, "apt-get", "clean"])
        if "journalctl" in t and p.get("/var/log/journal", 0) > 100e6:
            act("journal", "System caches", "systemd journal (keep 50 MB)",
                p["/var/log/journal"] - 50_000_000, "safe", [*sudo, "journalctl", "--vacuum-size=50M"])
        if "npm" in t and p.get(f"{home}/.npm/_cacache", 0) > 10e6:
            act("npm", "Dev tool caches", "npm cache", p[f"{home}/.npm/_cacache"], "safe",
                [*orb, t["npm"], "cache", "clean", "--force"])
        if "pulumi" in t and p.get(f"{home}/.pulumi/plugins", 0) > 10e6:
            act("pulumi", "Dev tool caches", "Pulumi provider plugins", p[f"{home}/.pulumi/plugins"],
                "caution", [*orb, t["pulumi"], "plugin", "rm", "--all", "--yes"],
                "re-downloaded on next pulumi run")
        if p.get(f"{home}/.cache", 0) > 10e6:
            act("cache", "Dev tool caches", "~/.cache (pip, uv, browsers…)", p[f"{home}/.cache"],
                "caution", [*orb, "find", f"{home}/.cache", "-mindepth", "1", "-delete"],
                "apps re-download as needed")
        if m.docker is not None:
            acts += docker_actions(m)
    acts = [a for a in acts if a.est is None or a.est > 0]
    return sorted(acts, key=lambda a: (CATEGORIES.index(a.category), -(a.est or 0)))


# ---------------------------------------------------------------- screens


class Confirm(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, actions: list[Action]) -> None:
        super().__init__()
        self.actions = actions

    def compose(self) -> ComposeResult:
        total = sum(a.est or 0 for a in self.actions)
        danger = any(a.risk == "danger" for a in self.actions)
        cmds = Text()
        where = None
        for a in self.actions:
            if a.where != where:
                where = a.where
                cmds.append(f"{where}\n", style="bold cyan")
            cmds.append(f"  {a.what}  ", style=RISK_STYLE[a.risk])
            cmds.append(f"{human(a.est)}\n", style="dim")
            cmds.append(f"    $ {shlex.join(a.cmd)}\n", style="dim")
        with Vertical(id="dialog"):
            yield Label(f"Run {len(self.actions)} cleanup action(s), freeing about {human(total)}?")
            yield Static(cmds, id="cmds")
            if danger:
                yield Label(Text("Includes actions that permanently delete data.", style="bold red"))
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="no")
                yield Button("Run", id="yes", variant="error" if danger else "primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


# ---------------------------------------------------------------- app


class LazyOrb(App):
    TITLE = "lazyorb"
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #left { width: 46; }
    #right { width: 1fr; }
    #status, #details, #machines, #actions, #log {
        border: round #5c5c5c;
        border-title-color: $text;
        border-title-style: bold;
        background: $background;
        padding: 0 1;
    }
    #status { height: auto; }
    #machines { height: 1fr; }
    #details { height: auto; max-height: 50%; }
    #actions { height: 1fr; }
    #log { height: 9; }
    #machines:focus, #actions:focus, #log:focus { border: round $success; }
    Confirm { align: center middle; }
    #dialog { width: 96; height: auto; max-height: 85%; border: thick $accent;
              background: $surface; padding: 1 2; }
    #cmds { margin: 1 0; }
    #buttons { height: auto; align-horizontal: right; margin-top: 1; }
    #buttons Button { margin-left: 2; }
    """
    BINDINGS = [
        Binding("1", "focus_pane('machines')", "Machines", show=False),
        Binding("2", "focus_pane('actions')", "Cleanup", show=False),
        Binding("3", "focus_pane('log')", "Log", show=False),
        Binding("j", "move(1)", "Down", show=False),
        Binding("k", "move(-1)", "Up", show=False),
        Binding("space", "toggle", "Select"),
        Binding("a", "select_safe", "Select safe"),
        Binding("escape", "clear", "Clear"),
        Binding("c", "clean", "Clean"),
        Binding("n", "ncdu", "ncdu"),
        Binding("r", "rescan", "Rescan"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.scan: Scan | None = None
        self.actions: dict[str, list[Action]] = {}
        self.selected: set[str] = set()
        self.current = HOST
        self.rows: list[str | Action] = []  # table rows: category name (header) or Action
        self.scanning = False
        self.pending: set[str] = set()  # targets still being scanned
        self.scan_total = 0
        self.scan_t0 = 0.0
        self.frame = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("Scanning…", id="status")
                yield OptionList(id="machines")
            with Vertical(id="right"):
                yield Static("", id="details")
                yield DataTable(id="actions", cursor_type="row", zebra_stripes=True)
        yield RichLog(id="log", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#status").border_title = "Status"
        self.query_one("#machines").border_title = "[1] Machines"
        self.query_one("#actions").border_title = "[2] Cleanup"
        self.query_one("#log").border_title = "[3] Command log"
        table = self.query_one(DataTable)
        table.add_column("", key="sel", width=3)
        table.add_column("What", key="what")
        table.add_column("Frees", key="est")
        table.add_column("Risk", key="risk")
        table.add_column("Notes", key="note")
        self.query_one("#machines").focus()
        self.set_interval(0.1, self.tick)
        self.rescan()

    def tick(self) -> None:
        """Animate scan progress so a slow scan never looks frozen."""
        if not self.scanning:
            return
        self.frame = (self.frame + 1) % len(SPINNER)
        spin = SPINNER[self.frame]
        elapsed = time.monotonic() - self.scan_t0
        status = self.query_one("#status", Static)
        if self.scan_total:
            done = self.scan_total - len(self.pending)
            status.border_subtitle = f"{spin} scanning {done}/{self.scan_total} · {elapsed:.0f}s"
        else:
            status.border_subtitle = f"{spin} finding machines · {elapsed:.0f}s"
            status.update(Text(f"{spin} Starting scan…", style="italic"))
        t = self.target()
        if t is not None and t.running and not t.scanned:
            self.query_one("#details", Static).update(
                Text(f"{spin} Scanning {t.name}… ({elapsed:.0f}s)", style="italic"))

    # ---- scanning

    def log_line(self, msg: str | Text) -> None:
        self.query_one(RichLog).write(msg)

    async def _scan(self) -> None:
        self.log_line("Scanning… (du inside each machine can take a little while)")
        self.scanning, self.scan_total, self.scan_t0 = True, 0, time.monotonic()
        scan = Scan(host=Machine(HOST, "running", 0, is_host=True))
        scan.machines = await list_machines()
        self.pending = {HOST} | {m.name for m in scan.machines if m.running}
        self.scan_total = len(self.pending)
        self.scan = scan
        self.refresh_all()

        async def one(coro, name):
            await coro
            return name

        jobs = [one(scan_host(scan), HOST)]
        jobs += [one(scan_machine(m), m.name) for m in scan.machines if m.running]
        for done in asyncio.as_completed(jobs):
            name = await done
            self.pending.discard(name)
            self.refresh_all()
            self.log_line(Text(f"  scanned {name}: {len(self.actions.get(name, []))} cleanup options",
                               style="dim"))
        self.scanning = False
        elapsed = time.monotonic() - self.scan_t0
        self.query_one("#status", Static).border_subtitle = f"scanned in {elapsed:.0f}s"
        self.log_line(f"Scan complete in {elapsed:.0f}s.")

    @work(exclusive=True, group="busy")
    async def rescan(self) -> None:
        await self._scan()

    # ---- rendering

    def target(self, name: str | None = None) -> Machine | None:
        name = name or self.current
        return next((t for t in self.scan.targets if t.name == name), None) if self.scan else None

    def refresh_all(self) -> None:
        assert self.scan
        self.actions = {t.name: machine_actions(t) for t in self.scan.targets}
        self.selected &= {a.key for acts in self.actions.values() for a in acts}
        self.render_status()
        self.render_machines()
        self.render_right()

    def chosen(self) -> list[Action]:
        return [a for acts in self.actions.values() for a in acts if a.key in self.selected]

    def render_status(self) -> None:
        s = self.scan
        assert s
        t = Text()
        t.append("OrbStack on Mac  ", style="bold")
        t.append(f"{human(s.data_dir)}\n", style="bold magenta")
        t.append("Mac free         ", style="bold")
        t.append(f"{human(s.mac_free)}\n")
        if s.disk:
            total, used = s.disk
            t.append("Linux disk       ", style="bold")
            t.append(f"{bar(used / total, 10)} {used / total:.0%}\n", style="magenta")
        chosen = self.chosen()
        t.append("Selected         ", style="bold")
        t.append(f"{len(chosen)} · {human(sum(a.est or 0 for a in chosen))}",
                 style="bold green" if chosen else "dim")
        self.query_one("#status", Static).update(t)

    def render_machines(self) -> None:
        s = self.scan
        assert s
        ol = self.query_one("#machines", OptionList)
        keep = ol.highlighted
        biggest = max((t.size for t in s.targets), default=1) or 1
        options = []
        for t in s.targets:
            acts = self.actions.get(t.name, [])
            nsel = sum(a.key in self.selected for a in acts)
            free = sum(a.est or 0 for a in acts if a.risk != "danger")
            line = Text()
            line.append(f"{t.name:<16}", style="bold cyan" if t.is_host else "cyan")
            line.append(f"{human(t.size) if t.scanned or not t.is_host else '…':>9}\n")
            line.append(f"{bar(t.size / biggest, 16)} ", style="magenta")
            if not t.running:
                line.append("stopped", style="dim")
            elif not t.scanned:
                line.append("scanning…", style="dim italic")
            else:
                line.append(f"↓ {human(free)}", style="green")
            if nsel:
                line.append(f"  ● {nsel}", style="bold green")
            options.append(Option(line, id=t.name))
        with ol.prevent(OptionList.OptionHighlighted):
            ol.clear_options()
            ol.add_options(options)
            ol.highlighted = keep if keep is not None else 0

    def render_right(self) -> None:
        t = self.target()
        if t is None:
            return
        self.render_details(t)
        self.render_table(t)

    def render_details(self, t: Machine) -> None:
        details = self.query_one("#details", Static)
        size = human(t.size) if t.scanned or not t.is_host else "…"
        details.border_title = f"{t.name} · {size}" + (f" · {t.distro}" if t.distro else "")
        out = Text()
        if not t.running:
            out.append(f"Stopped. Start it with `orb start {t.name}` and press r to scan.", style="dim")
            details.update(out)
            return
        if not t.scanned:
            out.append("Scanning…", style="dim italic")
            details.update(out)
            return

        acts = self.actions.get(t.name, [])
        by_risk = {r: sum(a.est or 0 for a in acts if a.risk == r) for r in RISK_STYLE}
        out.append("Can free  ", style="bold")
        for r, n in by_risk.items():
            if n:
                out.append(f"{human(n)} {r}   ", style=RISK_STYLE[r])
        out.append("\n")

        def rows(title: str, items: list[tuple[str, int]]) -> None:
            items = [i for i in items if i[1] >= 1e6][:4]
            if not items:
                return
            out.append(f"\n{title}\n", style="bold")
            top = items[0][1] or 1
            for label, size in items:
                out.append(f"  {human(size):>9} ", style="bold")
                out.append(f"{bar(size / top, 18)} ", style="magenta")
                out.append(f"{label}\n")

        if t.is_host:
            out.append("The Docker engine built into OrbStack (`docker` on your Mac).\n", style="dim")
            if t.docker:
                rows("Docker", [(f"{k}  ({human(v[1])} reclaimable)", v[0]) for k, v in t.docker.items()])
        else:
            rows("Where it goes", t.root)
            rows("Home", [(p.replace(t.home, "~", 1), n) for p, n in t.homedirs])
            if t.docker:
                out.append("\nDocker  ", style="bold")
                out.append("  ·  ".join(f"{k.lower()} {human(v[0])}" for k, v in t.docker.items()))
        details.update(out)

    def sel_cell(self, row: str | Action) -> Text:
        if isinstance(row, Action):
            on = row.key in self.selected
            return Text("[x]", style="bold green") if on else Text("[ ]", style="dim")
        keys = [a.key for a in self.group(row)]
        n = sum(k in self.selected for k in keys)
        if n == 0:
            return Text("[ ]", style="dim")
        return Text("[x]" if n == len(keys) else "[-]", style="bold green")

    def group(self, category: str) -> list[Action]:
        return [a for a in self.actions.get(self.current, []) if a.category == category]

    def row_key(self, row: str | Action) -> str:
        return row.key if isinstance(row, Action) else f"hdr:{row}"

    def render_table(self, t: Machine) -> None:
        table = self.query_one(DataTable)
        acts = self.actions.get(t.name, [])
        table.border_subtitle = f"{len(acts)} options" if t.scanned else ""
        cursor = table.cursor_row
        table.clear()
        self.rows = []
        for cat in CATEGORIES:
            items = [a for a in acts if a.category == cat]
            if not items:
                continue
            self.rows.append(cat)
            subtotal = sum(a.est or 0 for a in items)
            table.add_row(
                self.sel_cell(cat),
                Text(cat, style="bold red" if cat.startswith("Data") else "bold"),
                Text(human(subtotal), style="bold", justify="right"),
                "",
                Text(f"{len(items)} item(s)", style="dim"),
                key=self.row_key(cat),
            )
            for a in items:
                self.rows.append(a)
                table.add_row(
                    self.sel_cell(a),
                    f"  {a.what}",
                    Text(human(a.est), justify="right"),
                    Text(a.risk, style=RISK_STYLE[a.risk]),
                    Text(a.note, style="dim"),
                    key=a.key,
                )
        if self.rows:
            table.move_cursor(row=min(max(cursor, 0), len(self.rows) - 1))

    def refresh_selection(self) -> None:
        table = self.query_one(DataTable)
        for row in self.rows:
            table.update_cell(self.row_key(row), "sel", self.sel_cell(row))
        self.render_status()
        self.render_machines()

    # ---- events

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id and event.option.id != self.current:
            self.current = event.option.id
            self.query_one(DataTable).move_cursor(row=0)
            self.render_right()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.query_one(DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_toggle()

    # ---- key actions

    def action_focus_pane(self, pane: str) -> None:
        self.query_one(f"#{pane}").focus()

    def action_move(self, step: int) -> None:
        w = self.focused
        if isinstance(w, (OptionList, DataTable)):
            (w.action_cursor_down if step > 0 else w.action_cursor_up)()
        elif isinstance(w, RichLog):
            w.scroll_relative(y=step)

    def action_toggle(self) -> None:
        if isinstance(self.focused, OptionList):
            keys = {a.key for a in self.actions.get(self.current, []) if a.risk == "safe"}
        else:
            row = self.query_one(DataTable).cursor_row
            if not (0 <= row < len(self.rows)):
                return
            item = self.rows[row]
            keys = {item.key} if isinstance(item, Action) else {a.key for a in self.group(item)}
        if keys <= self.selected:
            self.selected -= keys
        else:
            self.selected |= keys
        self.refresh_selection()

    def action_select_safe(self) -> None:
        self.selected |= {a.key for a in self.actions.get(self.current, []) if a.risk == "safe"}
        self.refresh_selection()

    def action_clear(self) -> None:
        self.selected.clear()
        self.refresh_selection()

    def action_rescan(self) -> None:
        self.rescan()

    def action_clean(self) -> None:
        chosen = self.chosen()
        if not chosen:
            self.notify("Nothing selected: press space on an item, category or machine.",
                        severity="warning")
            return
        self.push_screen(Confirm(chosen), lambda ok: self.run_actions(chosen) if ok else None)

    @work(exclusive=True, group="busy")
    async def run_actions(self, chosen: list[Action]) -> None:
        before = self.scan.data_dir if self.scan else None
        self.query_one("#log").focus()
        for a in chosen:
            self.log_line(Text(f"$ {shlex.join(a.cmd)}", style="bold cyan"))
            proc = await asyncio.create_subprocess_exec(
                *a.cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout
            async for line in proc.stdout:
                self.log_line(line.decode(errors="replace").rstrip())
            code = await proc.wait()
            self.log_line(Text(f"  → {'ok' if code == 0 else f'failed (exit {code})'}",
                               style="green" if code == 0 else "red"))
        self.selected.clear()
        await self._scan()
        after = self.scan.data_dir if self.scan else None
        self.log_line(Text(f"OrbStack data on Mac: {human(before)} → {human(after)}", style="bold magenta"))
        self.log_line(Text("macOS can lag in showing freed space; press r to rescan in a minute.",
                           style="dim"))

    def action_ncdu(self) -> None:
        t = self.target()
        if t is None or t.is_host or not t.running:
            self.notify("Pick a running Linux machine on the left to open ncdu.", severity="warning")
            return
        script = ("command -v ncdu >/dev/null 2>&1 || sudo apt-get install -y ncdu; "
                  "sudo env TERM=xterm-256color ncdu -x /")
        with self.suspend():
            subprocess.run(["orb", "-m", t.name, "sh", "-c", script])


if __name__ == "__main__":
    LazyOrb().run()
