#!/usr/bin/env python3
"""Cross-agent outcome run: Claude Code and Codex, each with and without the catalog.

`claude plugin eval` runs Claude only. This runner runs the same evals/outcome cases on both
agents through their subscription logins, then grades every run with one blind judge, so the
four configurations are comparable:

    claude-skills  Claude Code with a snapshot of the catalog (--plugin-dir)
    claude-none    Claude Code with no catalog skill
    codex-skills   Codex with the same snapshot in $HOME/.agents/skills
    codex-none     Codex with no catalog skill

Each agent runs from its own login home, so the user's skills, plugins, hooks, memory files, and
MCP servers do not reach a run. Log in once per home:

    CLAUDE_CONFIG_DIR=~/.claude-eval claude auth login
    CODEX_HOME=~/.codex-eval codex login

Then, with one output directory for all steps:

    python3 evals/outcome/cross_agent.py preflight --out DIR   # offline: logins, routes, homes
    python3 evals/outcome/cross_agent.py run --dry-run         # offline: commands and workspaces
    python3 evals/outcome/cross_agent.py probe --out DIR       # short live calls: what each arm sees
    python3 evals/outcome/cross_agent.py run --out DIR         # the agent runs (live); needs the probe
    python3 evals/outcome/cross_agent.py grade --out DIR       # the blind judge (live)
    python3 evals/outcome/cross_agent.py report --out DIR      # offline: the tables

`run` and `grade` skip finished work, so a rerun after a quota stop continues where it stopped.
A run that ends in an error, or stalls on a usage limit, is retried; a timeout is a result.

The child processes get a built environment: no API key, no base-URL override, no cloud-provider
route, and a neutral git identity. `preflight` refuses a shell that has a route. The runner never
reads, prints, or copies a credential. Cost fields are the CLIs' own estimates; they do not
measure subscription quota.

Two choices differ from `claude plugin eval` on purpose. `tool_used` graders see shell commands
only, as {"command": ...}, because that is the one tool both agents share; a `tool_used` with no
min and no max means "at least once". The judge sees the final diff of the workspace, not the
content of each edit, because Codex reports an edit by path only.

What a finished report proves: on these agents, models, homes, and catalog snapshot, the cases
scored as shown, graded by one Claude judge that saw no agent or arm label. It does not prove
that the judge is unbiased (it is a Claude model) or that a one-grader difference is real.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import difflib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SKILLS = ROOT / "skills"
TOOLCHAIN = ROOT / "checks" / "rust-toolchain.toml"
CASES = HERE / "cases.toml"

CONFIGS = {
    "claude-skills": ("claude", True),
    "claude-none": ("claude", False),
    "codex-skills": ("codex", True),
    "codex-none": ("codex", False),
}
DEFAULT_CLAUDE_HOME = Path.home() / ".claude-eval"
DEFAULT_CODEX_HOME = Path.home() / ".codex-eval"
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_JUDGE_MODEL = "claude-opus-5-5"
FORBIDDEN_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL",
)
PASSED_ENV = ("PATH", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "LC_ALL")
CLAUDE_TOOLS = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Skill"]
PREAMBLE = "You work in the current directory, a local checkout. Change no file outside it.\n\n"
PROBE_PROMPT = (
    "List the name of every skill you can load in this session, one per line, and nothing else. "
    "If you can load no skill, reply with the single word NONE. Do not run any command."
)
MEMORY_NAMES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude", ".agents", ".codex")
LIMIT_HINT = re.compile(r"usage limit|rate limit|rate_limit|quota|429|too many requests|limit reached", re.I)
TRACE_LIMIT = 60_000
OUTPUT_LIMIT = 2_500
FILE_LIMIT = 40_000
DIFF_LIMIT = 30_000

_print_lock = threading.Lock()
_live_groups: set[int] = set()
_live_lock = threading.Lock()


def say(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


# --- inputs --------------------------------------------------------------------------------------

def yaml_module():
    try:
        import yaml  # local-only harness; check.py stays dependency-free for CI
    except ImportError:
        sys.exit("cross_agent.py needs PyYAML: run it with `uv run --with pyyaml python3 ...`")
    return yaml


def load_toml(path: Path) -> dict:
    import tomllib
    with path.open("rb") as handle:
        return tomllib.load(handle)


def catalog_names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))


GRADER_TYPES = {"regex", "tool_used", "llm", "tool_order", "file_exists", "baseline"}
RUNNER_TYPES = {"regex", "tool_used", "llm"}


def load_case(name: str) -> dict:
    """Returns case.yaml with the graders of graders/*.md appended. Fails on any it cannot read."""
    yaml = yaml_module()
    case_dir = HERE / name
    case = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
    graders = list(case.get("graders", []))
    for path in sorted((case_dir / "graders").glob("*.md")):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
        if not match:
            raise ValueError(f"{path}: no frontmatter between --- lines")
        front = yaml.safe_load(match.group(1)) or {}
        graders.append({"name": path.stem, **front, "criteria": match.group(2).strip()})
    for grader in graders:
        if grader.get("type") not in GRADER_TYPES:
            raise ValueError(f"{name}/{grader.get('name')}: unknown grader type {grader.get('type')!r}")
        if grader in scored_graders({"graders": [grader]}) and grader["type"] not in RUNNER_TYPES:
            raise ValueError(f"{name}/{grader['name']}: this runner cannot score type {grader['type']!r}")
    case["graders"] = graders
    case["dir"] = case_dir
    return case


def case_names(pattern: str) -> list[str]:
    names = sorted(load_toml(CASES)["cases"])
    return [n for n in names if fnmatch.fnmatch(n, pattern)]


def toolchain() -> str:
    return load_toml(TOOLCHAIN)["toolchain"]["channel"]


def catalog_commit() -> str:
    done = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    return done.stdout.strip()


def catalog_dirty() -> str:
    done = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "skills"],
                          capture_output=True, text=True)
    return done.stdout.strip()


# --- the catalog snapshot ------------------------------------------------------------------------

def snapshot(out: Path) -> Path:
    """Copies the plugin manifest and skills/ once per output directory. Every run uses the copy,
    so an edit in the checkout during the run reaches no agent, and no agent sees the repository
    (with its graders and reference fixes) through the plugin path."""
    catalog = out / "catalog"
    if not catalog.is_dir():
        staging = out / "catalog.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        (staging / ".claude-plugin").mkdir(parents=True)
        # A manifest of its own: the repository's plugin layout can change, the snapshot's cannot.
        manifest = {"name": "rust-skills", "description": "rust-skills catalog snapshot", "skills": ["./skills"]}
        (staging / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=1))
        shutil.copytree(SKILLS, staging / "skills")
        (staging / "COMMIT").write_text(catalog_commit() + "\n")
        staging.rename(catalog)
    return catalog


# --- environment ---------------------------------------------------------------------------------

def base_env(run_dir: Path, workspace: Path) -> dict[str, str]:
    """A built environment: only what the agents and cargo need, no inherited routing."""
    env = {k: os.environ[k] for k in PASSED_ENV if k in os.environ}
    env.update({
        "HOME": str(Path.home()),
        "TERM": "dumb",
        "NO_COLOR": "1",
        "CARGO_HOME": str(run_dir / "cargo-home"),
        "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(Path.home() / ".rustup")),
        "RUSTUP_TOOLCHAIN": toolchain(),
        "CARGO_TARGET_DIR": str(workspace / "target"),
        "CARGO_TERM_COLOR": "never",
        "GIT_CONFIG_GLOBAL": str(run_dir / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    })
    return env


def agent_command(config: str, case: dict, run_dir: Path, args: argparse.Namespace,
                  prompt: str) -> tuple[list[str], dict[str, str]]:
    agent, with_skills = CONFIGS[config]
    workspace = run_dir / "workspace"
    env = base_env(run_dir, workspace)
    env.update({k: str(v) for k, v in (case.get("execution", {}).get("env") or {}).items()})
    if agent == "claude":
        env["CLAUDE_CONFIG_DIR"] = str(args.claude_home)
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        cmd = [
            "claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--model", args.claude_model,
            "--permission-mode", "dontAsk", "--tools", *CLAUDE_TOOLS,
            "--allowedTools", *CLAUDE_TOOLS, "--strict-mcp-config",
        ]
        settings = args.out / "claude-settings.json"
        if settings.is_file():
            cmd += ["--settings", str(settings)]
        if with_skills:
            cmd += ["--plugin-dir", str(args.out / "catalog")]
        return cmd, env
    env["HOME"] = str(run_dir / "home")
    env["CODEX_HOME"] = str(args.codex_home)
    cmd = [
        "codex", "exec", "--json", "--output-last-message", str(run_dir / "final.txt"),
        "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
        "--sandbox", "workspace-write", "--add-dir", str(run_dir / "cargo-home"),
        # The ChatGPT account prefetches curated plugins into CODEX_HOME and loads their skills;
        # the probe caught about 50 of them on 2026-11-02. None of them belongs in a run.
        "--disable", "apps", "--disable", "hooks", "--disable", "plugins", "--disable", "remote_plugin",
        "--disable", "plugin_discovery_prefetch", "--disable", "skill_search",
        "-c", 'approval_policy="never"', "--cd", str(workspace),
    ]
    if args.codex_model:
        cmd += ["--model", args.codex_model]
    return cmd + [prompt], env


def scaffold(case: dict, directory: Path) -> None:
    directory.mkdir(parents=True)
    done = subprocess.run(["bash", str(case["dir"] / "scaffold.sh")], cwd=directory,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"scaffold failed for {case['name']}:\n{done.stdout}")


def prepare_run_dir(config: str, case: dict, run_dir: Path, catalog: Path) -> None:
    """Builds the workspace, a pristine copy for the final diff, and the per-run homes."""
    agent, with_skills = CONFIGS[config]
    if run_dir.exists():
        shutil.rmtree(run_dir)
    scaffold(case, run_dir / "workspace")
    scaffold(case, run_dir / "pristine")
    (run_dir / "cargo-home").mkdir()
    (run_dir / "gitconfig").write_text(
        "[user]\n\tname = Eval Agent\n\temail = agent@example.invalid\n[commit]\n\tgpgsign = false\n"
        "[tag]\n\tgpgsign = false\n"
    )
    skills_home = run_dir / "home" / ".agents" / "skills"
    skills_home.mkdir(parents=True)
    if with_skills and agent == "codex":
        for path in sorted((catalog / "skills").iterdir()):
            shutil.copytree(path, skills_home / path.name)


def install_interrupt_handler() -> None:
    def stop(signum, frame):  # noqa: ARG001
        with _live_lock:
            groups = list(_live_groups)
        for pgid in groups:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        say(f"interrupted: stopped {len(groups)} running agent(s); rerun to continue")
        os._exit(130)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)


def run_process(cmd: list[str], env: dict[str, str], cwd: Path, timeout: int,
                stdout_path: Path, stderr_path: Path) -> tuple[int | None, bool, float]:
    """Runs a child in its own process group and always kills the group at the end, so no agent
    or hung test outlives it. Returns (exit code, timed out, seconds)."""
    start = time.monotonic()
    with stdout_path.open("w") as out, stderr_path.open("w") as err:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        with _live_lock:
            _live_groups.add(proc.pid)
        timed_out = False
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out, code = True, None
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            with _live_lock:
                _live_groups.discard(proc.pid)
    return code, timed_out, time.monotonic() - start


# --- trace normalization -------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    events = []
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def clip(text: str, limit: int) -> str:
    """Keeps the head and the tail: a test summary and the last run live at the end."""
    text = text or ""
    if len(text) <= limit:
        return text
    head = limit // 3
    tail = limit - head
    return f"{text[:head]}\n[... {len(text) - limit} characters cut ...]\n{text[-tail:]}"


def tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def normalize_claude(events: list[dict]) -> dict:
    """Claude stream-json -> {actions, final, usage, failed}."""
    actions: list[dict] = []
    pending: dict[str, dict] = {}
    final, usage, failed = "", {}, False
    for event in events:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            usage["model"] = event.get("model")
        if kind == "assistant":
            for item in event.get("message", {}).get("content", []) or []:
                if item.get("type") == "text" and item.get("text", "").strip():
                    actions.append({"kind": "message", "text": item["text"]})
                elif item.get("type") == "tool_use":
                    action = claude_action(item.get("name", ""), item.get("input") or {})
                    actions.append(action)
                    pending[item.get("id", "")] = action
        elif kind == "user":
            for item in event.get("message", {}).get("content", []) or []:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    action = pending.get(item.get("tool_use_id", ""))
                    if action is not None and action["kind"] == "command":
                        action["output"] = tool_result_text(item.get("content"))
                        action["error"] = bool(item.get("is_error"))
        elif kind == "result":
            final = event.get("result") or ""
            failed = bool(event.get("is_error")) or event.get("subtype") not in (None, "success")
            usage.update({
                "cost_usd_estimate": event.get("total_cost_usd"),
                "turns": event.get("num_turns"),
                "model_usage": event.get("modelUsage"),
            })
    return {"actions": actions, "final": final, "usage": usage, "failed": failed}


def claude_action(name: str, data: dict) -> dict:
    if name == "Bash":
        return {"kind": "command", "command": data.get("command", ""), "output": "", "error": False}
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return {"kind": "edit", "path": data.get("file_path") or data.get("notebook_path", "")}
    if name == "Read":
        return {"kind": "read", "path": data.get("file_path", "")}
    if name in ("Glob", "Grep"):
        return {"kind": "search", "path": data.get("path", "") or data.get("pattern", "")}
    if name == "Skill":
        return {"kind": "skill", "name": str(data.get("skill", "")).split(":")[-1]}
    return {"kind": "tool", "name": name}


SHELL_WRAPPER = re.compile(r"""^(?:/\S*/)?(?:ba|z)?sh\s+-l?c\s+(['"])(.*)\1\s*$""", re.S)


def unwrap_command(command) -> str:
    """Codex reports a command as a string or an argv list, often wrapped in `zsh -lc '...'`."""
    if isinstance(command, list):
        if len(command) >= 3 and re.fullmatch(r"(?:/\S*/)?(?:ba|z)?sh", command[0]) and command[1] in ("-lc", "-c"):
            return command[2]
        return " ".join(str(part) for part in command)
    command = str(command or "")
    match = SHELL_WRAPPER.match(command)
    return match.group(2) if match else command


def normalize_codex(events: list[dict], final_text: str) -> dict:
    """Codex exec --json -> {actions, final, usage, failed}."""
    actions: list[dict] = []
    usage: dict = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    failed = False
    for event in events:
        kind = event.get("type")
        if kind in ("turn.failed", "error"):
            failed = True
        if kind == "turn.completed":
            for key in usage:
                usage[key] += int((event.get("usage") or {}).get(key) or 0)
        if kind != "item.completed":
            continue
        item = event.get("item") or {}
        item_kind = item.get("type") or item.get("item_type")
        if item_kind == "command_execution":
            actions.append({
                "kind": "command", "command": unwrap_command(item.get("command", "")),
                "output": item.get("aggregated_output", ""),
                "error": item.get("exit_code") not in (0, None),
            })
        elif item_kind == "file_change":
            for change in item.get("changes") or []:
                actions.append({"kind": "edit", "path": change.get("path", "")})
        elif item_kind == "agent_message" and (item.get("text") or "").strip():
            actions.append({"kind": "message", "text": item["text"]})
        elif item_kind in ("mcp_tool_call", "web_search"):
            actions.append({"kind": "tool", "name": item_kind})
    final = final_text or next((a["text"] for a in reversed(actions) if a["kind"] == "message"), "")
    return {"actions": actions, "final": final, "usage": usage, "failed": failed}


SKILL_PATH = re.compile(r"(?:\.agents/skills|/skills)/([a-z0-9-]+)/(?:SKILL\.md|references/)")


def skills_loaded(actions: list[dict], names: set[str]) -> list[str]:
    """Catalog skills that a run loaded: a Skill tool call, or a read of a skill file."""
    found = []
    for action in actions:
        if action["kind"] == "skill":
            found.append(action["name"])
        text = action.get("command", "") + " " + action.get("path", "")
        found += SKILL_PATH.findall(text)
    return sorted({n for n in found if n in names})


AGENT_WORDS = re.compile(
    r"\b(?:claude(?:[ -]code)?|codex|chatgpt|openai|anthropic|gpt-[\w.-]+|opus|sonnet|haiku)\b"
    r"|\b(?:CLAUDE|AGENTS)\.md\b|\.(?:claude|codex|agents)\b",
    re.I,
)


def redact(text: str, run_dir: Path, names: list[str]) -> str:
    """Removes what would tell the judge the agent or the arm: paths, homes, names, skill names."""
    for base in {run_dir, run_dir.resolve()}:
        text = text.replace(str(base / "workspace"), "<workspace>").replace(str(base), "<run>")
    text = text.replace(str(ROOT), "<run>").replace(str(Path.home()), "<run>")
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(rf"(?:\b(?:the|a)\s+)?(?<![\w-]){re.escape(name)}(?![\w-])(?:\s+skill\b)?",
                      "a guideline", text, flags=re.I)
    # The word itself tells the arm: only the skills arm talks about loading one.
    text = re.sub(r"\bskills\b", "guidelines", text, flags=re.I)
    text = re.sub(r"\bskill\b", "guideline", text, flags=re.I)
    return AGENT_WORDS.sub("[agent]", text)


def hidden(action: dict) -> bool:
    """Skill loads and reads of skill files: they would reveal the arm."""
    text = action.get("command", "") + action.get("path", "")
    return action["kind"] == "skill" or "SKILL.md" in text or bool(SKILL_PATH.search(text)) \
        or ".agents/skills" in text or "/catalog/" in text


def render_trace(actions: list[dict]) -> str:
    lines = []
    for action in actions:
        if hidden(action):
            continue
        if action["kind"] == "command":
            status = "failed" if action.get("error") else "ok"
            lines.append(f"$ {action['command']}\n[{status}]\n{clip(action.get('output', ''), OUTPUT_LIMIT)}")
        elif action["kind"] == "edit":
            lines.append(f"[changed file] {action['path']}")
        elif action["kind"] in ("read", "search"):
            lines.append(f"[looked at] {action['path']}")
        elif action["kind"] == "message":
            lines.append(f"[assistant] {action['text']}")
        else:
            lines.append("[other tool]")
    return "\n\n".join(lines)


def tree_diff(before: Path, after: Path, budget: int = 200_000) -> str:
    """A unified diff of the workspace without build output and git internals.

    Source files come first: an agent can leave a large tree behind (one run copied a cargo
    registry into its workspace), so binary and large files are only counted, and the diff stops
    at `budget` characters with a count of what it did not show."""
    def files(root: Path) -> dict[str, Path]:
        found = {}
        for path in root.rglob("*"):
            rel = path.relative_to(root)
            if rel.parts[0] in ("target", ".git") or not path.is_file() or path.is_symlink():
                continue
            found[str(rel)] = path
        return found

    def text(path: Path | None) -> list[str] | None:
        if path is None:
            return []
        if path.stat().st_size > 256_000:
            return None
        data = path.read_bytes()
        if b"\0" in data:
            return None
        return data.decode("utf-8", errors="replace").splitlines(keepends=True)

    old, new = files(before), files(after)
    order = sorted(old.keys() | new.keys(), key=lambda rel: (rel.startswith("."), rel.count("/"), rel))
    chunks: list[str] = []
    size, skipped = 0, {}
    for rel in order:
        a, b = text(old.get(rel)), text(new.get(rel))
        if a is not None and b is not None and a == b:
            continue
        if a is None or b is None or size > budget:
            top = rel.split("/")[0] + ("/" if "/" in rel else "")
            if not (a is not None and b is not None) or size > budget:
                skipped[top] = skipped.get(top, 0) + 1
                continue
        piece = "".join(difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}"))
        chunks.append(piece)
        size += len(piece)
    for top, count in sorted(skipped.items()):
        chunks.append(f"[{count} more changed file(s) under {top} not shown: binary, large, or over budget]\n")
    return "".join(chunks) or "(no file changed)"


# --- deterministic graders -----------------------------------------------------------------------

def py_flags(flags: str) -> int:
    value = 0
    for flag, bit in (("i", re.I), ("m", re.M), ("s", re.S)):
        if flag in (flags or ""):
            value |= bit
    return value


def target_text(target, norm: dict, workspace: Path) -> str:
    if isinstance(target, dict) and target.get("source") == "file":
        path = workspace / target["path"]
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if target == "trace":
        return json.dumps(norm["actions"])
    return norm["final"]


def grade_regex(grader: dict, norm: dict, workspace: Path) -> bool:
    text = target_text(grader.get("target", "last_message"), norm, workspace)
    hits = len(re.findall(grader["pattern"], text, py_flags(grader.get("flags", ""))))
    match = grader.get("match", "contains")
    if match == "contains":
        return hits > 0
    if match == "not_contains":
        return hits == 0
    return hits == int(match.split(":", 1)[1])


def grade_tool_used(grader: dict, norm: dict) -> bool:
    """Counts shell commands for tool Bash; no other tool exists in both agents."""
    if grader.get("tool") != "Bash":
        raise ValueError(f"tool_used on {grader.get('tool')!r} has no cross-agent meaning")
    pattern = grader.get("input_match")
    count = sum(
        1 for a in norm["actions"] if a["kind"] == "command"
        and (pattern is None or re.search(pattern, json.dumps({"command": a["command"]})))
    )
    low, high = grader.get("min"), grader.get("max")
    if low is None and high is None:
        low = 1
    return (low is None or count >= low) and (high is None or count <= high)


def scored_graders(case: dict) -> list[dict]:
    """Every grader except the skill-fired indicator, which this runner records separately."""
    return [g for g in case["graders"] if not (g.get("type") == "tool_used" and g.get("tool") == "Skill")]


# --- preflight -----------------------------------------------------------------------------------

def check(ok: bool, label: str, problems: list[str]) -> None:
    say(f"  [{'ok' if ok else 'FAIL'}] {label}")
    if not ok:
        problems.append(label)


def empty_dir(path: Path, ignore: tuple[str, ...] = ()) -> bool:
    return not path.exists() or (path.is_dir() and not [p for p in path.iterdir() if p.name not in ignore])


def preflight(args: argparse.Namespace) -> int:
    problems: list[str] = []
    say("Routes in this shell (the children get a built environment, but refuse a risky shell):")
    for name in FORBIDDEN_ENV:
        check(name not in os.environ, f"{name} is not set", problems)
    base = os.environ.get("ANTHROPIC_BASE_URL")
    check(base in (None, "https://api.anthropic.com"), "ANTHROPIC_BASE_URL is unset or first-party", problems)

    say(f"Claude login home {args.claude_home}:")
    status = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, check=False,
                            env={**os.environ, "CLAUDE_CONFIG_DIR": str(args.claude_home)})
    try:
        info = json.loads(status.stdout)
    except json.JSONDecodeError:
        info = {}
    check(info.get("loggedIn") is True and info.get("authMethod") == "claude.ai",
          "logged in through a claude.ai subscription", problems)
    check(info.get("apiProvider") == "firstParty", "first-party provider", problems)
    settings_path = args.claude_home / "settings.json"
    keys: set[str] = set()
    if settings_path.is_file():
        try:
            data = json.loads(settings_path.read_text())
            keys = set(data) | {f"env.{k}" for k in (data.get("env") or {})}
        except (json.JSONDecodeError, AttributeError):
            keys = {"<unreadable>"}
    risky = {k for k in keys if re.search(r"apiKeyHelper|hooks|enabledPlugins|extraKnownMarketplaces|"
                                           r"ANTHROPIC_|BEDROCK|VERTEX|FOUNDRY|unreadable", k)}
    check(not risky, f"no route, hook, or plugin key in its settings.json {sorted(risky) or ''}", problems)
    # The account syncs its plugins and skills into the login home on its own schedule, so one
    # arm can get them and the other not. Turn both syncs off in the login home's settings.json:
    #   {"syncClaudeAiPlugins": false, "syncClaudeAiSkills": false}
    sync = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
    check(sync.get("syncClaudeAiPlugins") is False and sync.get("syncClaudeAiSkills") is False,
          "account plugin and skill sync are off in its settings.json", problems)
    # skills/synced holds the account's own skills; they reach both Claude arms alike (the probe
    # checks that), the way Codex's built-in .system set does.
    check(empty_dir(args.claude_home / "skills", ignore=("synced",)),
          "no skills in the login home besides the account-synced set", problems)
    for extra in ("CLAUDE.md", "agents", "commands", "rules"):
        check(empty_dir(args.claude_home / extra), f"no {extra} in the login home", problems)

    say(f"Codex login home {args.codex_home}:")
    status = subprocess.run(["codex", "login", "status"], capture_output=True, text=True, check=False,
                            env={**os.environ, "CODEX_HOME": str(args.codex_home)})
    check("ChatGPT" in (status.stdout + status.stderr), "logged in through ChatGPT", problems)
    check(empty_dir(args.codex_home / "skills", ignore=(".system",)),
          "no skills in the login home besides the built-in .system set", problems)
    for extra in ("AGENTS.md", "rules", "hooks"):
        check(empty_dir(args.codex_home / extra), f"no {extra} in the login home", problems)

    say("Output, catalog, and toolchain:")
    out = args.out
    memory = [str(p / f) for p in [out, *out.parents] for f in MEMORY_NAMES if (p / f).exists()]
    check(not memory, f"no memory or skill files in any parent of {out} {memory or ''}", problems)
    check(ROOT not in [out, *out.parents], "the output directory is outside this repository", problems)
    check(not catalog_dirty() or (out / "catalog").is_dir(),
          "skills/ is committed (or the snapshot exists)", problems)
    rustup = subprocess.run(["rustup", "run", toolchain(), "cargo", "--version"], capture_output=True,
                            text=True, check=False)
    check(rustup.returncode == 0, f"toolchain {toolchain()} is installed", problems)
    for name in case_names(args.case):
        load_case(name)
    check(True, f"{len(case_names(args.case))} case(s) parse with every grader", problems)

    if problems:
        say(f"preflight: {len(problems)} problem(s). Fix them before a live run.")
        return 1
    say("preflight: OK")
    return 0


# --- probe ---------------------------------------------------------------------------------------

def answer_names(text: str) -> set[str]:
    names = set()
    for line in text.splitlines():
        line = re.sub(r"^[\s*\-\d.)`]+|[`\s]+$", "", line).strip()
        if line and line.upper() != "NONE" and re.fullmatch(r"[\w:.-]+", line):
            names.add(line.split(":")[-1])
    return names


def probe_once(config: str, args: argparse.Namespace, label: str) -> dict:
    agent, _ = CONFIGS[config]
    run_dir = args.out / "probe" / label / config
    case = load_case(case_names("*")[0])
    prepare_run_dir(config, case, run_dir, args.out / "catalog")
    cmd, env = agent_command(config, case, run_dir, args, PROBE_PROMPT)
    code, timed_out, _ = run_process(cmd, env, run_dir / "workspace", 300,
                                     run_dir / "events.jsonl", run_dir / "stderr.txt")
    events = read_jsonl(run_dir / "events.jsonl")
    if agent == "claude":
        norm = normalize_claude(events)
        init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
        seen = {str(s).split(":")[-1] for s in init.get("skills", []) or []}
        extra = {
            "plugins": sorted(p.get("source", "?") for p in init.get("plugins", []) or []),
            "mcp_servers": init.get("mcp_servers") or [],
            "memory": sorted(k for k in (init.get("memory_paths") or {}) if k != "auto"),
        }
    else:
        final = run_dir / "final.txt"
        norm = normalize_codex(events, final.read_text() if final.is_file() else "")
        seen = answer_names(norm["final"])
        extra = {}
    return {"config": config, "ok_run": code == 0 and not timed_out and not norm["failed"]
            and bool(norm["final"].strip()), "seen": sorted(seen), **extra}


def judge_probe(results: dict[str, dict], names: set[str], user_names: set[str],
                codex_system: set[str]) -> list[str]:
    """Pure check of probe results. Returns the failures.

    Claude reports its skills in the init event, so its two arms must match exactly outside the
    catalog, and only built-in plugins (plus the catalog) may load. Codex reports them only in
    its answer, which varies, so outside the catalog it may name only its built-in .system set.
    """
    failures = []
    for agent in ("claude", "codex"):
        pair = {c: results[c] for c in results if c.startswith(agent)}
        if len(pair) != 2:
            continue
        with_s, without = pair[f"{agent}-skills"], pair[f"{agent}-none"]
        for result in pair.values():
            if not result["ok_run"]:
                failures.append(f"{result['config']}: the probe run failed")
        if len(set(with_s["seen"]) & names) < len(names) - 4:
            failures.append(f"{agent}-skills: sees {len(set(with_s['seen']) & names)}/{len(names)} catalog skills")
        if set(without["seen"]) & names:
            failures.append(f"{agent}-none: sees catalog skills {sorted(set(without['seen']) & names)}")
        background = (set(with_s["seen"]) - names, set(without["seen"]) - names)
        if agent == "codex":
            stray = sorted((background[0] | background[1]) - codex_system)
            if stray:
                leaked = sorted(set(stray) & user_names)
                failures.append(f"codex: skills outside the catalog and the built-in set: {stray}"
                                + (f" (user skills: {leaked})" if leaked else ""))
        elif background[0] != background[1]:
            failures.append(f"claude: the arms differ outside the catalog: "
                            f"only with skills {sorted(background[0] - background[1])}, "
                            f"only without {sorted(background[1] - background[0])}")
        if agent == "claude":
            for result in pair.values():
                allowed = {"rust-skills@inline"} if result is with_s else set()
                plugins = [p for p in result["plugins"] if not p.endswith("@builtin") and p not in allowed]
                if plugins:
                    failures.append(f"{result['config']}: unexpected plugins {plugins}")
                if result["mcp_servers"] or result["memory"]:
                    failures.append(f"{result['config']}: MCP servers or memory files loaded")
    return failures


def probe(args: argparse.Namespace) -> int:
    """Finds account-synced Claude plugins, turns them off for every Claude run, then asks each
    configuration what it can load, twice, and requires the arms to differ only in the catalog."""
    args.out.mkdir(parents=True, exist_ok=True)
    snapshot(args.out)
    names = set(catalog_names())
    user_names = {p.name for d in (Path.home() / ".claude/skills", Path.home() / ".agents/skills",
                                   Path.home() / ".codex/skills") if d.is_dir() for p in d.iterdir()}
    codex_system = {p.name for p in (args.codex_home / "skills/.system").glob("*") if p.is_dir()}
    agents = args.agents.split(",")
    if "claude" in agents:
        found = probe_once("claude-none", args, "discover")
        init_plugins = [p for p in found.get("plugins", []) if p.endswith("@synced")]
        settings = {"enabledPlugins": {p: False for p in init_plugins}}
        (args.out / "claude-settings.json").write_text(json.dumps(settings, indent=1))
        say(f"  account-synced Claude plugins turned off for every run: {init_plugins or 'none'}")
    failures: list[str] = []
    for attempt in ("first", "second"):
        results = {c: probe_once(c, args, attempt) for c in CONFIGS if CONFIGS[c][0] in agents}
        for result in results.values():
            say(f"  {attempt} {result['config']}: {len(set(result['seen']) & names)} catalog, "
                f"{len(set(result['seen']) - names)} other, run ok: {result['ok_run']}")
        failures += [f"{attempt}: {f}" for f in judge_probe(results, names, user_names - names, codex_system)]
        (args.out / f"probe-{attempt}.json").write_text(json.dumps(results, indent=1))
    ok = not failures
    (args.out / "probe.json").write_text(json.dumps({"ok": ok, "failures": failures, "agents": agents}, indent=1))
    for failure in failures:
        say(f"  FAIL {failure}")
    say("probe: OK" if ok else "probe: FAIL; no live run starts until it passes")
    return 0 if ok else 1


# --- run -----------------------------------------------------------------------------------------

def tasks(args: argparse.Namespace) -> list[tuple[str, str, int]]:
    wanted = set(filter(None, args.configs.split(","))) or set(CONFIGS)
    unknown = wanted - set(CONFIGS)
    if unknown:
        raise SystemExit(f"unknown configuration(s): {sorted(unknown)}")
    configs = [c for c in CONFIGS if CONFIGS[c][0] in args.agents.split(",") and c in wanted]
    return [(case, config, k) for case in case_names(args.case) for k in range(1, args.runs + 1)
            for config in configs]


def run_status(code: int | None, timed_out: bool, norm: dict, stderr: str) -> str:
    if timed_out:
        tail = stderr[-4000:] + json.dumps(norm["actions"][-3:])
        return "error" if LIMIT_HINT.search(tail) and not norm["actions"] else "timeout"
    if code != 0 or norm["failed"] or not norm["final"].strip():
        return "error"
    return "done"


def run_one(case_name: str, config: str, k: int, args: argparse.Namespace,
            gates: dict[str, threading.Semaphore]) -> str:
    run_dir = args.out / "runs" / case_name / config / str(k)
    meta_path = run_dir / "meta.json"
    if meta_path.is_file() and json.loads(meta_path.read_text()).get("status") in ("done", "timeout"):
        return "skipped"
    agent = CONFIGS[config][0]
    with gates[agent]:
        case = load_case(case_name)
        prepare_run_dir(config, case, run_dir, args.out / "catalog")
        prompt = PREAMBLE + case["execution"]["prompt"].strip()
        cmd, env = agent_command(config, case, run_dir, args, prompt)
        timeout = int(case["execution"].get("timeout_seconds", 900))
        say(f"  start   {case_name} {config} #{k}")
        code, timed_out, seconds = run_process(cmd, env, run_dir / "workspace", timeout,
                                               run_dir / "events.jsonl", run_dir / "stderr.txt")
    events = read_jsonl(run_dir / "events.jsonl")
    if agent == "claude":
        norm = normalize_claude(events)
    else:
        final_file = run_dir / "final.txt"
        norm = normalize_codex(events, final_file.read_text() if final_file.is_file() else "")
    stderr = (run_dir / "stderr.txt").read_text(errors="replace")
    status = run_status(code, timed_out, norm, stderr)
    (run_dir / "normalized.json").write_text(json.dumps(norm, indent=1))
    (run_dir / "final.diff").write_text(tree_diff(run_dir / "pristine", run_dir / "workspace"))
    meta = {
        "case": case_name, "config": config, "run": k, "status": status, "exit_code": code,
        "seconds": round(seconds, 1), "usage": norm["usage"],
        "skills_loaded": skills_loaded(norm["actions"], set(catalog_names())),
        "claude_model": args.claude_model, "codex_model": args.codex_model or "default",
    }
    meta_path.write_text(json.dumps(meta, indent=1))
    say(f"  {status:7} {case_name} {config} #{k} ({seconds:.0f}s)")
    return status


def environment(args: argparse.Namespace) -> dict:
    def version(cmd: list[str]) -> str:
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        text = (done.stdout or done.stderr).strip()
        return text.splitlines()[0] if text else "?"
    return {
        "catalog_commit": (args.out / "catalog" / "COMMIT").read_text().strip(),
        "claude_cli": version(["claude", "--version"]),
        "codex_cli": version(["codex", "--version"]),
        "claude_model": args.claude_model,
        "codex_model": args.codex_model or "default",
        "toolchain": toolchain(),
        "seed": args.seed,
    }


def run(args: argparse.Namespace) -> int:
    work = tasks(args)
    if args.dry_run:
        return dry_run(args, work)
    probe_file = args.out / "probe.json"
    probed = json.loads(probe_file.read_text()) if probe_file.is_file() else {}
    if not probed.get("ok") or not set(args.agents.split(",")) <= set(probed.get("agents", [])):
        say(f"run: no passing probe for {args.agents} in {args.out}; run `probe` first")
        return 1
    info = environment(args)
    env_file = args.out / "environment.json"
    if env_file.is_file():
        before = json.loads(env_file.read_text())
        changed = {k for k in info if before.get(k) != info[k]}
        if changed:
            say(f"run: {sorted(changed)} changed since this output directory started; use a new --out")
            return 1
    else:
        env_file.write_text(json.dumps({**info, "started_utc": dt.datetime.now(dt.timezone.utc)
                                        .isoformat(timespec="seconds")}, indent=1))
    install_interrupt_handler()
    gates = {"claude": threading.Semaphore(args.jobs_per_agent), "codex": threading.Semaphore(args.jobs_per_agent)}
    say(f"{len(work)} agent run(s) into {args.out}, {args.jobs_per_agent} per agent at a time")
    statuses: dict[str, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2 * args.jobs_per_agent) as pool:
        futures = [pool.submit(run_one, case, config, k, args, gates) for case, config, k in work]
        for future in concurrent.futures.as_completed(futures):
            try:
                status = future.result()
            except Exception as error:  # one broken run must not stop the others
                say(f"  error: {error}")
                status = "error"
            statuses[status] = statuses.get(status, 0) + 1
    say(f"run: {statuses}")
    return 0 if not statuses.get("error") else 2


def dry_run(args: argparse.Namespace, work: list[tuple[str, str, int]]) -> int:
    """Builds one workspace per configuration in a temporary directory and prints each command."""
    say(f"{len(work)} agent run(s) planned; showing one per configuration (no agent starts)")
    with tempfile.TemporaryDirectory(prefix="cross-agent-dry-") as tmp:
        args.out = Path(tmp).resolve()
        catalog = snapshot(args.out)
        for config in CONFIGS:
            if CONFIGS[config][0] not in args.agents.split(","):
                continue
            case = load_case(case_names(args.case)[0])
            run_dir = args.out / config
            prepare_run_dir(config, case, run_dir, catalog)
            cmd, env = agent_command(config, case, run_dir, args, "<prompt>")
            skills = sorted(p.name for p in (run_dir / "home/.agents/skills").iterdir())
            say(f"\n{config}: {' '.join(cmd)}")
            say(f"  env keys: {', '.join(sorted(env))}")
            say(f"  workspace: {sorted(p.name for p in (run_dir / 'workspace').iterdir())}")
            say(f"  $HOME/.agents/skills: {len(skills)} skill(s)")
    return 0


# --- grade ---------------------------------------------------------------------------------------

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "pass": {"type": "boolean"}, "evidence": {"type": "string"}},
        "required": ["name", "pass", "evidence"],
    }}},
    "required": ["verdicts"],
}

JUDGE_PROMPT = """You grade one run of a coding agent on a Rust task. You see the task, the agent's
recorded actions, its final answer, the final diff of its workspace, and the final content of
some files. Judge each criterion on the evidence only. A criterion passes only if its PASS
condition holds and no FAIL condition holds. The record was anonymized: paths read <workspace>
or <run>, and some names read "a guideline" or [agent]. Do not guess who or what produced the run.

Task given to the agent:
{task}

Criteria (judge every one, by name):
{criteria}

Evidence:
{evidence}

Answer with one verdict per criterion: its name, pass true or false, and one or two sentences of
evidence that cite what you saw."""


def evidence_for(focus, view: dict, workspace: Path, run_dir: Path, names: list[str]) -> str:
    if isinstance(focus, dict) and focus.get("source") == "file":
        path = workspace / focus["path"]
        body = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "(the file does not exist)"
        return f"--- final content of {focus['path']} ---\n{clip(redact(body, run_dir, names), FILE_LIMIT)}"
    if focus == "trace":
        return (f"--- recorded actions ---\n{view['trace']}\n\n--- final diff of the workspace ---\n"
                f"{view['diff']}\n\n--- final answer ---\n{view['final']}")
    return f"--- final answer ---\n{view['final']}"


def label_for(seed: str, case_name: str, config: str, k: int) -> str:
    """A stable blind label: it does not change when other runs are added or retried."""
    digest = hashlib.sha256(f"{seed}|{case_name}|{config}|{k}".encode()).hexdigest()
    return f"run-{digest[:8]}"


def final_diff(run_dir: Path) -> str:
    """Recomputes the diff (bounded) and stores it next to the run."""
    diff = tree_diff(run_dir / "pristine", run_dir / "workspace")
    (run_dir / "final.diff").write_text(diff)
    return diff


def grade_one(case: dict, run_dir: Path, args: argparse.Namespace, names: list[str],
              only: set[str] | None = None) -> dict:
    """Grades one run: every scored grader, or only the graders named in `only`."""
    meta = json.loads((run_dir / "meta.json").read_text())
    norm = json.loads((run_dir / "normalized.json").read_text())
    workspace = run_dir / "workspace"
    verdicts: dict[str, dict] = {}
    judged = []
    for grader in scored_graders(case):
        if only is not None and grader["name"] not in only:
            continue
        revision = grader_revision(grader)
        if grader["type"] == "regex":
            verdicts[grader["name"]] = {"pass": grade_regex(grader, norm, workspace), "by": "regex",
                                        "revision": revision}
        elif grader["type"] == "tool_used":
            verdicts[grader["name"]] = {"pass": grade_tool_used(grader, norm), "by": "tool_used",
                                        "revision": revision}
        else:
            judged.append(grader)
    if judged:
        view = {
            "trace": clip(redact(render_trace(norm["actions"]), run_dir, names), TRACE_LIMIT),
            "final": redact(norm["final"], run_dir, names),
            "diff": clip(redact(final_diff(run_dir), run_dir, names), DIFF_LIMIT),
        }
        criteria = "\n\n".join(f"[{g['name']}]\n{g['criteria']}" for g in judged)
        evidence = "\n\n".join(
            f"=== evidence for [{g['name']}] ===\n"
            f"{evidence_for(g.get('focus', 'last_message'), view, workspace, run_dir, names)}"
            for g in judged
        )
        prompt = JUDGE_PROMPT.format(task=case["execution"]["prompt"].strip(), criteria=criteria, evidence=evidence)
        answer = ask_judge(prompt, args) or []
        wanted = {g["name"]: grader_revision(g) for g in judged}
        for verdict in answer:
            if verdict.get("name") in wanted:
                verdicts[verdict["name"]] = {"pass": bool(verdict["pass"]), "by": "judge",
                                             "evidence": verdict.get("evidence", ""),
                                             "revision": wanted[verdict["name"]],
                                             "judge_model": args.judge_model}
        missing = wanted - verdicts.keys()
        if missing:
            raise RuntimeError(f"the judge gave no verdict for {sorted(missing)}")
    return {"case": meta["case"], "config": meta["config"], "run": meta["run"],
            "status": meta["status"], "verdicts": verdicts}


def grader_revision(grader: dict) -> str:
    """A short hash of the grader definition. It changes when the criteria, pattern, or focus change."""
    text = json.dumps(grader, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def stale_graders(stored: dict, subset: set[str], revisions: dict[str, str]) -> set[str]:
    """The graders of `subset` whose stored verdict is missing or came from another revision. A
    verdict recorded before revisions existed has none, so it is stale."""
    return {name for name in subset
            if stored["verdicts"].get(name, {}).get("revision") != revisions[name]}


def with_judge_model(verdict: dict, model: str | None) -> dict:
    """A judge verdict from an older grade file names its model only at the top of the file."""
    if model and verdict.get("by") == "judge" and "judge_model" not in verdict:
        return {**verdict, "judge_model": model}
    return verdict


def merge_regrade(stored: dict, fresh: dict, case: dict) -> dict:
    """Replaces the re-graded verdicts, appends each replaced verdict to its history under
    `superseded` (oldest first), and drops verdicts of graders the case no longer has. Each judge
    verdict names its own judge model, so a regrade with another model keeps the provenance."""
    current = {g["name"] for g in scored_graders(case)}
    stored = dict(stored)
    model = stored.pop("judge_model", None)
    # An older grade file holds one superseded verdict per name, not a list.
    superseded = {name: [with_judge_model(v, model) for v in (old if isinstance(old, list) else [old])]
                  for name, old in stored.get("superseded", {}).items()}
    verdicts = {}
    for name, verdict in stored["verdicts"].items():
        verdict = with_judge_model(verdict, model)
        if name in fresh["verdicts"] or name not in current:
            superseded.setdefault(name, []).append(verdict)
        else:
            verdicts[name] = verdict
    verdicts.update(fresh["verdicts"])
    return {**stored, "verdicts": verdicts, "superseded": superseded,
            "regraded": sorted(set(stored.get("regraded", [])) | set(fresh["verdicts"]))}


def grade(args: argparse.Namespace) -> int:
    names = catalog_names()
    problems = 0
    regrade = set(filter(None, args.regrade.split(",")))
    for case_name in case_names(args.case):
        case = load_case(case_name)
        revisions = {g["name"]: grader_revision(g) for g in scored_graders(case)}
        subset = regrade & revisions.keys()
        for meta_path in sorted((args.out / "runs" / case_name).glob("*/*/meta.json")):
            meta = json.loads(meta_path.read_text())
            if meta["status"] not in ("done", "timeout"):
                continue
            label = label_for(args.seed, case_name, meta["config"], meta["run"])
            out = args.out / "grades" / case_name / f"{label}.json"
            stored, only = None, None
            if out.is_file():
                stored = json.loads(out.read_text())
                if (stored.get("config"), stored.get("run")) != (meta["config"], meta["run"]):
                    stored = None
                else:
                    only = stale_graders(stored, subset, revisions)
                    if not only:
                        continue
            try:
                result = grade_one(case, meta_path.parent, args, names, only=only)
                if stored:
                    result = merge_regrade(stored, result, case)
            except Exception as error:  # one bad run must not stop the others
                say(f"  not graded: {case_name} {label}: {error}")
                problems += 1
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"label": label, **result}, indent=1))
            say(f"  graded {case_name} {label}")
    say("grade: OK" if not problems else f"grade: {problems} run(s) not graded; rerun to retry")
    return 0 if not problems else 2


def ask_judge(prompt: str, args: argparse.Namespace) -> list[dict] | None:
    with tempfile.TemporaryDirectory(prefix="judge-") as tmp:
        env = {k: os.environ[k] for k in PASSED_ENV if k in os.environ}
        env.update({"HOME": str(Path.home()), "CLAUDE_CONFIG_DIR": str(args.claude_home), "TERM": "dumb",
                    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})
        # The prompt goes on stdin: a trace can be long, and argv has a size limit.
        cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence",
               "--model", args.judge_model, "--tools", "", "--strict-mcp-config",
               "--json-schema", json.dumps(JUDGE_SCHEMA)]
        settings = args.out / "claude-settings.json"
        if settings.is_file():
            cmd += ["--settings", str(settings)]
        for _ in range(2):
            try:
                done = subprocess.run(cmd, cwd=tmp, env=env, input=prompt, capture_output=True,
                                      text=True, timeout=600, check=False)
                result = json.loads(done.stdout)
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                continue
            if result.get("is_error"):
                continue
            data = result.get("structured_output")
            if data is None:
                match = re.search(r"\{.*\}", result.get("result", ""), re.S)
                try:
                    data = json.loads(match.group(0)) if match else None
                except json.JSONDecodeError:
                    data = None
            if isinstance(data, dict) and isinstance(data.get("verdicts"), list):
                return data["verdicts"]
    return None


# --- report --------------------------------------------------------------------------------------

def report(args: argparse.Namespace) -> int:
    configs = list(CONFIGS)
    selected = case_names(args.case)
    grades = [json.loads(p.read_text()) for p in (args.out / "grades").glob("*/run-*.json")]
    grades = [g for g in grades if g["case"] in selected]
    lines = ["| Case | " + " | ".join(configs) + " |", "| --- |" + " ---: |" * len(configs)]
    totals = {c: [0, 0] for c in configs}
    per_grader: dict[str, dict[str, list[int]]] = {}
    for case_name in selected:
        cells = {c: [0, 0] for c in configs}
        for g in (g for g in grades if g["case"] == case_name):
            for name, verdict in g["verdicts"].items():
                cells[g["config"]][0] += int(verdict["pass"])
                cells[g["config"]][1] += 1
                row = per_grader.setdefault(f"{case_name} / {name}", {c: [0, 0] for c in configs})
                row[g["config"]][0] += int(verdict["pass"])
                row[g["config"]][1] += 1
        for c in configs:
            totals[c][0] += cells[c][0]
            totals[c][1] += cells[c][1]
        lines.append(f"| {case_name} | " + " | ".join(fmt(cells[c]) for c in configs) + " |")
    lines.append("| **Total** | " + " | ".join(f"**{fmt(totals[c])}**" for c in configs) + " |")

    detail = ["| Grader | " + " | ".join(configs) + " |", "| --- |" + " ---: |" * len(configs)]
    for name, row in per_grader.items():
        detail.append(f"| {name} | " + " | ".join(fmt(row[c]) for c in configs) + " |")

    runs = [json.loads(p.read_text()) for p in (args.out / "runs").glob("*/*/*/meta.json")]
    runs = [m for m in runs if m["case"] in selected]
    owner = {n: load_toml(CASES)["cases"][n]["skill"] for n in selected}
    expected = len(selected) * args.runs
    ops = ["| Configuration | Graded / expected | Timeouts | Errors | Owning skill loaded | Median seconds |",
           "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for c in configs:
        mine = [m for m in runs if m["config"] == c]
        if not mine:
            continue
        graded = sum(1 for g in grades if g["config"] == c)
        loaded = sum(1 for m in mine if owner[m["case"]] in m["skills_loaded"])
        median = statistics.median(m["seconds"] for m in mine)
        ops.append(f"| {c} | {graded}/{expected} | {sum(m['status'] == 'timeout' for m in mine)} | "
                   f"{sum(m['status'] == 'error' for m in mine)} | {loaded}/{len(mine)} | {median:.0f} |")

    text = "\n".join(["## Scored graders passed", "", *lines, "", "## Per grader", "", *detail,
                      "", "## Runs", "", *ops, ""])
    (args.out / "report.md").write_text(text)
    say(text)
    return 0


def fmt(cell: list[int]) -> str:
    return f"{cell[0]}/{cell[1]}" if cell[1] else "-"


def default_out() -> Path:
    """Outside $HOME: Claude reads memory files in every parent of the working directory."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path("/Users/Shared") if Path("/Users/Shared").is_dir() else Path(tempfile.gettempdir())
    return base / "rust-skills-evals" / f"outcome-{stamp}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["preflight", "probe", "run", "grade", "report"])
    parser.add_argument("--out", type=Path, default=None, help="one directory for every step")
    parser.add_argument("--case", default="*", help="glob over case names")
    parser.add_argument("--agents", default="claude,codex")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--configs", default="", help="comma-separated configurations; default: all four")
    parser.add_argument("--jobs-per-agent", type=int, default=2)
    parser.add_argument("--claude-home", type=Path, default=DEFAULT_CLAUDE_HOME)
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL)
    parser.add_argument("--codex-model", default="", help="default: the Codex login's default model")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--seed", default="outcome-v1", help="seed of the blind labels")
    parser.add_argument("--dry-run", action="store_true", help="with run: build workspaces, start nothing")
    parser.add_argument("--regrade", default="",
                        help="with grade: comma-separated graders to judge again where their definition changed")
    args = parser.parse_args()
    args.out = (args.out or default_out()).expanduser().resolve()
    args.claude_home = args.claude_home.expanduser().resolve()
    args.codex_home = args.codex_home.expanduser().resolve()
    return {"preflight": preflight, "probe": probe, "run": run, "grade": grade, "report": report}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
