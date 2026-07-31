#!/usr/bin/env python3
"""Stall detector for long-running CREST work. Prints a verdict per job; exits 1 if anything stalled.

Why it exists: liveness keeps getting misdiagnosed, five times now, always by measuring a PROXY for
work instead of the work itself.
  * `ps aux | grep -c` reported 2 processes for a run that had already finished;
  * `pgrep -fc` reported 0 for a run that was very much alive (PID confirmed);
  * this module then counted PYTHON processes and printed "0 background jobs" for four consecutive
    cycles while a dozen agents were working;
  * the fix for that counted `claude` processes, which also match the daemon, the pty host, the
    spare and every `--resume` session -- so it read 9 when the truth was ~2 and could never read 0;
  * and a hand-rolled `stat -f %z` on a task .output file measured the SYMLINK (a constant 138
    bytes) rather than its 1 MB target, which read as a 14-minute stall on an agent that was
    writing continuously.
Every one of those was a false reading in a direction that would have caused the wrong action. The
rule this module now follows: measure the artifact the work produces -- records written, log lines,
transcript bytes -- never the existence of a process. Verdicts:

  ALIVE+ADVANCING  process present and its record count grew since the last snapshot
  ALIVE+STALLED    process present but no new records and log untouched for > --stall-min
  DEAD+INCOMPLETE  no process, output short of target  -> needs restart or skip
  DONE             manifest written (finalize_run writes it last, so it marks true completion)

Snapshots land in .stall_state.json next to the run dir, so consecutive calls can tell "slow" from
"stuck" — a single sample cannot.

Usage:  python -m crest.analysis.stall_check [--stall-min 10] [--target 250]
"""
from __future__ import annotations
import argparse, json, subprocess, time, glob, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "crest/result/.stall_state.json"


def _procs(pattern: str) -> list[int]:
    """PIDs whose full command line contains `pattern`. Uses ps directly: pgrep -f/-c proved
    unreliable here, and the bracket trick in a grep pipeline matched shell wrappers."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,command="], capture_output=True, text=True).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, cmd = line.partition(" ")
        if pattern in cmd and "stall_check" not in cmd and "ps -A" not in cmd:
            try:
                pids.append(int(pid))
            except ValueError:
                pass
    return pids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stall-min", type=float, default=10.0, help="minutes of no progress = stalled")
    ap.add_argument("--target", type=int, default=250)
    a = ap.parse_args()
    now = time.time()
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    state, problems = {}, []

    # ---- eval / re-judge runs: newest run dir wins
    runs = sorted(glob.glob(str(REPO / "crest/result/runs/*/")))
    if runs:
        rd = Path(runs[-1])
        recs = rd / "records.jsonl"
        n = sum(1 for _ in recs.open()) if recs.exists() else 0
        done = (rd / "run_manifest.json").exists()
        pids = _procs("run_eval.py")
        age_min = (now - recs.stat().st_mtime) / 60 if recs.exists() else 999
        key = f"run:{rd.name}"
        state[key] = n
        seen_before = key in prev
        grew = seen_before and n > prev[key]   # a FIRST sample cannot show growth; treating
                                               # it as ADVANCING is the single-sample
                                               # misdiagnosis this module exists to prevent
        if done:
            verdict = f"DONE ({n}/{a.target} records, manifest written)"
        elif pids and not seen_before:
            verdict = f"ALIVE pid={pids} n={n}/{a.target} (first sample -- no baseline yet)"
        elif pids and grew:
            verdict = f"ALIVE+ADVANCING pid={pids} {prev.get(key,'?')}->{n}/{a.target}"
        elif pids and age_min > a.stall_min:
            verdict = f"ALIVE+STALLED pid={pids} stuck at {n}/{a.target}, no write for {age_min:.0f}min"
            problems.append(verdict)
        elif pids:
            verdict = f"ALIVE (n={n}/{a.target}, last write {age_min:.0f}min ago; within tolerance)"
        else:
            verdict = f"DEAD+INCOMPLETE n={n}/{a.target}, no manifest -> restart or skip"
            problems.append(verdict)
        print(f"  eval run {rd.name[:34]}: {verdict}")

    # ---- ablation
    ab = _procs("ablate_fields")
    log = Path("/tmp/ablate.log")
    if ab or log.exists():
        age = (now - log.stat().st_mtime) / 60 if log.exists() else 999
        lines = sum(1 for _ in log.open()) if log.exists() else 0
        state["ablate"] = lines
        if not ab and log.exists() and "wrote " in log.read_text():
            print(f"  ablation: DONE ({lines} log lines)")
        elif ab and lines > prev.get("ablate", -1):
            print(f"  ablation: ALIVE+ADVANCING pid={ab} ({prev.get('ablate','?')}->{lines} lines)")
        elif ab and age > a.stall_min:
            v = f"ALIVE+STALLED pid={ab}, no log write for {age:.0f}min"
            print(f"  ablation: {v}"); problems.append(v)
        elif ab:
            print(f"  ablation: ALIVE (last write {age:.0f}min ago)")
        else:
            v = f"DEAD+INCOMPLETE ({lines} lines, no 'wrote' marker)"
            print(f"  ablation: {v}"); problems.append(v)

    # ---- background agents: measured by TRANSCRIPT WRITES, not by process name.
    #
    # Two counting bugs preceded this, both the same class the module exists to prevent:
    #   * counting PYTHON processes reported "0" for four cycles while a dozen agents worked;
    #   * counting `claude` processes reported 9 when the real number was ~2 -- the pattern also
    #     matches the daemon, bg-pty-host, bg-spare and every `claude --resume` session, so it can
    #     never read zero and "agents are alive" became a constant.
    # A process name says nothing about progress anyway. A subagent writes its transcript
    # continuously, so mtime is the direct signal: advancing, idle, or absent.
    #
    # NB stat the TARGET, not the link. The task .output files are symlinks into
    # ~/.claude/projects/.../subagents/, and measuring the link gave a constant 138 bytes -- read as
    # "stalled at 138 bytes for 14 minutes" for an agent that was in fact writing 1 MB. Path.stat()
    # follows symlinks; Path.lstat() would not.
    agent_dirs = sorted(Path.home().glob(".claude/projects/*/*/subagents"))
    live, idle = [], []
    for d in agent_dirs:
        for f in d.glob("agent-*.jsonl"):
            try:
                age = (now - f.stat().st_mtime) / 60      # stat() follows symlinks
            except OSError:
                continue
            if age < a.stall_min:
                live.append((f.name[6:23], age, f.stat().st_size))
            elif age < 120:                                # older than 2h: finished long ago, ignore
                idle.append((f.name[6:23], age))
    if live:
        for name, age, size in sorted(live, key=lambda x: x[1]):
            print(f"  agent {name}: ADVANCING (wrote {age*60:.0f}s ago, {size/1024:.0f} KB)")
    elif idle:
        newest = min(idle, key=lambda x: x[1])
        print(f"  agents: none advancing; newest transcript {newest[0]} idle {newest[1]:.0f}min "
              f"(> --stall-min {a.stall_min:g}) -- treat any in_progress task as STALLED")
    else:
        print("  agents: none running")
    print(f"  runs on disk: {len(list((REPO/'crest/result/runs').glob('*/')))}")

    # ---- release gate: the single number that says whether this is shippable
    g = subprocess.run(["bash", str(REPO / "crest/analysis/ci_check.sh")],
                       capture_output=True, text=True)
    line = [l for l in g.stdout.splitlines() if "PRE-RELEASE GATE" in l]
    print(f"  gate: {line[0].split(':')[-1].strip() if line else '?'}"
          f"  ({sum(1 for l in g.stdout.splitlines() if l.strip().startswith('OK'))} ok, "
          f"{sum(1 for l in g.stdout.splitlines() if l.strip().startswith('FAIL'))} fail)")

    # ---- uncommitted work: this session has lost track of finished work before
    st = subprocess.run(["git", "status", "--porcelain", "crest/"], capture_output=True,
                        text=True, cwd=str(REPO)).stdout.strip()
    n_dirty = len(st.splitlines()) if st else 0
    if n_dirty:
        print(f"  UNCOMMITTED: {n_dirty} changed file(s) -- commit before they are lost")

    print("\n  TASK RECONCILIATION (the task list lives in the harness, not on disk -- check it "
          "manually):\n    * close any task whose work is committed\n    * a task 'in_progress' with "
          "no running job is stalled\n    * work with no task is untracked")

    STATE.write_text(json.dumps({**prev, **state}))   # keep other runs' counters, don't drop them
    if problems:
        print(f"\nSTALLED/DEAD: {len(problems)} — fix or skip, and record the skip.")
        raise SystemExit(1)
    print("\nall tracked jobs healthy")


if __name__ == "__main__":
    main()
