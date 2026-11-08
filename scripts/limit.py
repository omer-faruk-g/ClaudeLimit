#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""ClaudeLimit: startup-floor audit and a reversible lean mode (stdlib only).

  limit.py audit [--days 30]          CLAUDE.md / MEMORY.md size, plugins, skill listing cost (read-only)
  limit.py lean on --skills a,b --tools X,Y [--dry-run]
                                      back up settings.json, set skillOverrides "off" for the skills and
                                      add the tools to permissions.deny; prints the diff
  limit.py lean off [--dry-run]       remove exactly what `lean on` added (state: ~/.claude/claudelimit-lean.json)
  limit.py lean status

Lean mode is the approved exception to MinToken B2 ("never deny a bare tool name"): it is temporary
and `lean off` undoes it. Whether a denied tool also leaves the request's tool list is unverified [I]:
check with drain_detail.py in a new session. Plugin skills ignore skillOverrides (use /plugin).
Run `lean on --dry-run` first and apply only after the user approves the diff.
"""
import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ctx"))
from _common import home_dir, long_path  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLAUDE_MD_MAX = 200   # lines; the article's and the docs' guideline for always-loaded instructions
MEMORY_MD_MAX = 200   # lines of MEMORY.md that are loaded at session start


def paths(home=None):
    h = home_dir(home)
    return (os.path.join(h, ".claude", "settings.json"), os.path.join(h, ".claude", "claudelimit-lean.json"))


def read_text(p):
    try:
        with open(long_path(p), encoding="utf-8", newline="") as f:  # keep the file's own line endings
            return f.read()
    except OSError:
        return None


def audit(home=None, cwd=None, days=30):
    h = home_dir(home)
    out = ["== ALWAYS-LOADED TEXT =="]
    for p in (os.path.join(h, ".claude", "CLAUDE.md"), os.path.join(cwd or os.getcwd(), "CLAUDE.md")):
        t = read_text(p)
        if t is not None:
            n = t.count("\n") + 1
            out.append(f"  {p}: {n} lines, ~{len(t) // 4} tok" + ("  > 200 lines: trim" if n > CLAUDE_MD_MAX else ""))
    mems = []
    for dp, _dn, fn in os.walk(long_path(os.path.join(h, ".claude", "projects"))):
        if "MEMORY.md" in fn and os.path.basename(dp) == "memory":
            t = read_text(os.path.join(dp, "MEMORY.md")) or ""
            mems.append((len(t), t.count("\n") + 1, dp))
    for size, n, dp in sorted(mems, reverse=True)[:5]:
        out.append(f"  MEMORY.md {n} lines, ~{size // 4} tok  ...{dp[-60:]}" + ("  > 200 lines: only the first 200 load" if n > MEMORY_MD_MAX else ""))
    st = read_text(paths(home)[0])
    try:
        plugins = (json.loads(st or "{}").get("enabledPlugins") or {})
    except ValueError:
        plugins = {}
    out.append("== PLUGINS (each adds skills/tools to every request; uninstall unused ones with /plugin) ==")
    out += [f"  {k}: {'on' if v else 'off'}" for k, v in plugins.items()] or ["  (none)"]
    state = load_state(home)
    out.append("== LEAN MODE == " + ("on since " + time.strftime("%Y-%m-%d %H:%M", time.localtime(state["at"])) if state else "off"))
    print("\n".join(out))
    print("== SKILL LISTING ==", flush=True)
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "ctx", "skill_audit.py"), "--days", str(days),
                    "--cwd", cwd or os.getcwd()], check=False)
    return 0


def load_state(home=None):
    try:
        with open(paths(home)[1], encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) and "at" in s else None
    except (OSError, ValueError):
        return None


def show_diff(before_text, after, path):
    nl = "\r\n" if before_text and "\r\n" in before_text else "\n"
    after_text = json.dumps(after, indent=2, ensure_ascii=False).replace("\n", nl) + nl
    d = list(difflib.unified_diff((before_text or "").splitlines(True), after_text.splitlines(True),
                                  path, path + " (new)"))
    print("".join(d) if d else "(no change)")
    return after_text, bool(d)


def lean_on(skills, tools, dry, home=None):
    sp, statep = paths(home)
    if load_state(home):
        print("lean mode is already on; run `lean off` first")
        return 1
    before = read_text(sp)
    cfg = json.loads(before) if before else {}
    added = {"skills": {}, "deny": [], "made_overrides": "skillOverrides" not in cfg,
             "made_permissions": "permissions" not in cfg, "made_deny": "deny" not in (cfg.get("permissions") or {})}
    ov = cfg.setdefault("skillOverrides", {})
    for s in skills:
        if s in ov:
            print(f"skip skill {s}: already has skillOverrides {ov[s]!r}")
        else:
            ov[s] = "off"; added["skills"][s] = "off"
    deny = cfg.setdefault("permissions", {}).setdefault("deny", [])
    for t in tools:
        if t in deny:
            print(f"skip tool {t}: already denied")
        else:
            deny.append(t); added["deny"].append(t)
    if not added["skills"]:
        cfg.pop("skillOverrides") if added["made_overrides"] else None
    if not added["deny"]:
        if added["made_deny"]: cfg["permissions"].pop("deny")
        if added["made_permissions"]: cfg.pop("permissions")
    text, changed = show_diff(before, cfg, sp)
    if dry or not changed:
        return 0
    bak = sp + ".bak-claudelimit-" + time.strftime("%Y%m%d-%H%M%S")
    if before is not None:
        shutil.copy2(sp, bak)
    with open(sp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    added.update(at=int(time.time()), backup=bak if before is not None else None)
    with open(statep, "w", encoding="utf-8") as f:
        json.dump(added, f, indent=2)
    print(f"lean on. backup {added['backup']}. Takes effect in a new session; `lean off` undoes it.")
    return 0


def lean_off(dry, home=None):
    sp, statep = paths(home)
    st = load_state(home)
    if not st:
        print("lean mode is off")
        return 0
    before = read_text(sp)
    cfg = json.loads(before) if before else {}
    ov = cfg.get("skillOverrides") or {}
    for s, v in (st.get("skills") or {}).items():
        if ov.get(s) == v:
            ov.pop(s)
        else:
            print(f"leave skill {s}: changed since lean on ({ov.get(s)!r})")
    if st.get("made_overrides") and "skillOverrides" in cfg and not ov:
        cfg.pop("skillOverrides")
    perm = cfg.get("permissions") or {}
    deny = perm.get("deny") or []
    for t in st.get("deny") or []:
        if t in deny:
            deny.remove(t)
    if st.get("made_deny") and "deny" in perm and not deny:
        perm.pop("deny")
    if st.get("made_permissions") and "permissions" in cfg and not perm:
        cfg.pop("permissions")
    text, changed = show_diff(before, cfg, sp)
    if dry:
        return 0
    if changed:
        with open(sp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    os.remove(statep)
    print("lean off. Takes effect in a new session.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit"); a.add_argument("--days", type=int, default=30); a.add_argument("--cwd")
    lp = sub.add_parser("lean"); lp.add_argument("mode", choices=["on", "off", "status"])
    lp.add_argument("--skills", default=""); lp.add_argument("--tools", default="")
    lp.add_argument("--dry-run", action="store_true")
    o = p.parse_args(argv)
    if o.cmd == "audit":
        return audit(cwd=o.cwd, days=o.days)
    if o.mode == "status":
        st = load_state()
        print(json.dumps(st, indent=2) if st else "lean mode is off")
        return 0
    if o.mode == "off":
        return lean_off(o.dry_run)
    sk = [s.strip() for s in o.skills.split(",") if s.strip()]
    tl = [t.strip() for t in o.tools.split(",") if t.strip()]
    if not sk and not tl:
        p.error("lean on needs --skills and/or --tools")
    return lean_on(sk, tl, o.dry_run)


if __name__ == "__main__":
    sys.exit(main())
