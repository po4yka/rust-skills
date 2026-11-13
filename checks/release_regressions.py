#!/usr/bin/env python3
"""Run Rust transition, Cargo policy, and isolated loom regression fixtures.

Default: every suite, with no skips. --suite selects a diagnostic subset, not CI
acceptance. Requires the pinned toolchain, Rust 1.99.1, and cached harness crates
for loom. All builds use temporary directories. The registry listens on loopback
and serves only generated fixture crates; it never contacts a public registry.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import tomllib
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "release-fixtures"
BEFORE = "1.99.1"
AFTER = tomllib.loads((HERE / "rust-toolchain.toml").read_text())["toolchain"]["channel"]


class Failure(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def environment(root: Path, *, registry_cache: bool = False) -> dict[str, str]:
    # Pass only host/toolchain settings, not registry tokens or service secrets.
    allowed = {"PATH", "HOME", "RUSTUP_HOME", "SYSTEMROOT", "WINDIR", "USERPROFILE",
               "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SDKROOT", "DEVELOPER_DIR"}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    cargo_home = root / "cargo-home"
    env.update(CARGO_TARGET_DIR=str(root / "target"), CARGO_TERM_COLOR="never",
               CARGO_HOME=str(cargo_home))
    if registry_cache:
        # Share cached packages, not global Cargo config or credentials. Run
        # offline and compare the resolved graph with the harness lock below.
        cache = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo"))) / "registry"
        (cargo_home / "registry").mkdir(parents=True, exist_ok=True)
        for name in ("index", "cache", "src"):
            source = cache / name
            dest = cargo_home / "registry" / name
            if source.exists() and not dest.exists():
                dest.symlink_to(source.resolve(), target_is_directory=True)
    return env


def run(command: list[str], root: Path, *, env: dict[str, str] | None = None,
        error: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=root, env=env or environment(root),
                            capture_output=True, text=True, timeout=timeout, check=False)
    text = result.stdout + result.stderr
    expected = result.returncode == 0 if error is None else result.returncode != 0 and error in text
    if not expected:
        raise Failure(f"{' '.join(command)}\nexpected: {error or 'exit 0'}; exit: {result.returncode}\n{text[-6000:]}")
    return result


def write(root: Path, path: str, text: str) -> None:
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)


def compiler(root: Path) -> None:
    root.mkdir()
    count = 0

    def probe(name: str, version: str, *, edition: int = 2024,
              error: str | None = None, flags: tuple[str, ...] = ()) -> None:
        nonlocal count
        binary = root / "probe"
        run(["rustc", f"+{version}", "--edition", str(edition),
             str(FIXTURES / "compiler" / f"{name}.rs"), "-o", str(binary), *flags],
            root, error=error)
        if error is None:
            run([str(binary)], root)
        count += 1

    for name, error in (("if-let-field", "E0382"), ("if-let-send", "E0277")):
        probe(name, BEFORE, error=error)
        probe(name, AFTER)
    probe("if-let-drop", BEFORE)
    probe("if-let-drop", AFTER, flags=("--cfg", "modern"))
    probe("infallible-alias", BEFORE, error="E0658")
    probe("infallible-alias", AFTER)
    probe("infallible-coherence", BEFORE)
    probe("infallible-coherence", AFTER, error="E0119")
    for edition in (2015, 2018, 2021, 2024):
        # The old diagnostic is already deny-by-default. An explicit allow is
        # a separate language-behavior probe, not a proposed application fix.
        probe("never-fallback", BEFORE, edition=edition,
              error="E0277" if edition == 2024 else "dependency_on_unit_never_type_fallback")
        probe("never-fallback", BEFORE, edition=edition,
              error="E0277" if edition == 2024 else None,
              flags=("-Adependency_on_unit_never_type_fallback",))
        probe("never-fallback", AFTER, edition=edition, error="E0277",
              flags=("-Adependency_on_unit_never_type_fallback",))
        for version in (BEFORE, AFTER):
            probe("never-fallback", version, edition=edition, flags=("--cfg", "explicit"))
    print(f"  compiler: {count} compile/execute expectations pass ({BEFORE} -> {AFTER})", flush=True)


def package(root: Path, name: str, source: str = "pub fn value() -> u8 { 7 }\n") -> None:
    write(root, "Cargo.toml", f'[package]\nname = "{name}"\nversion = "0.0.0"\nedition = "2024"\npublish = false\n')
    write(root, "src/lib.rs", source)


def cargo(root: Path, args: list[str], *, env: dict[str, str] | None = None,
          error: str | None = None) -> subprocess.CompletedProcess[str]:
    return run(["cargo", f"+{AFTER}", *args], root, env=env, error=error, timeout=600)


def cargo_lints(root: Path) -> None:
    package(root, "policy-fixture", "")
    for name in ("used", "conditional", "platform", "inactive", "dev_only"):
        package(root / name, name)
    manifest = '''[package]
name = "policy-fixture"
version = "0.0.0"
edition = "2024"
publish = false
[features]
uses-conditional = []
[dependencies]
used = { path = "used" }
conditional = { path = "conditional" }
[target.'cfg(unix)'.dependencies]
platform = { path = "platform" }
[target.'cfg(windows)'.dependencies]
inactive = { path = "inactive" }
[dev-dependencies]
dev_only = { path = "dev_only" }
[lints.cargo]
unused_dependencies = "deny"
'''
    write(root, "Cargo.toml", manifest)
    write(root, "src/bin/one.rs", "fn main() { assert_eq!(used::value(), 7); }\n")
    write(root, "src/bin/two.rs", '''fn main() {
    #[cfg(feature = "uses-conditional")]
    assert_eq!(conditional::value(), 7);
    #[cfg(unix)]
    assert_eq!(platform::value(), 7);
}
''')
    cargo(root, ["generate-lockfile", "--offline"])
    cargo(root, ["check", "--locked", "--offline", "--bin", "one"])
    cargo(root, ["check", "--locked", "--offline", "--all-targets"], error="unused dependency `conditional`")
    cargo(root, ["check", "--locked", "--offline", "--all-targets", "--features", "uses-conditional"])
    # Every applicable dependency is used, except the dev-dependency: no lint.
    source = (root / "src/bin/two.rs").read_text()
    write(root, "src/bin/two.rs", source.replace('assert_eq!(platform::value(), 7);', 'let _ = 7;'))
    if sys.platform != "win32":
        cargo(root, ["check", "--locked", "--offline", "--all-targets", "--features", "uses-conditional"],
              error="unused dependency `platform`")
    else:
        raise Failure("Cargo target-cfg fixture requires a Unix host; use Linux CI or macOS")
    print("  Cargo lints: selected binary, feature sets, active/inactive target dependencies, dev-dependency boundary pass", flush=True)


def cargo_artifacts(root: Path) -> None:
    package(root, "artifact-fixture", "")
    with (root / "Cargo.toml").open("a") as stream:
        stream.write('[features]\nextra = []\n')
    write(root, "build.rs", '''fn main() {
    println!("cargo::rerun-if-env-changed=CARGO_FEATURE_EXTRA");
    let value = if std::env::var_os("CARGO_FEATURE_EXTRA").is_some() { "extra" } else { "base" };
    let out = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    std::fs::write(out.join("selected.rs"), format!("pub const VALUE: &str = {value:?};")).unwrap();
}
''')
    write(root, "src/main.rs", 'include!(concat!(env!("OUT_DIR"), "/selected.rs"));\nfn main() { println!("{VALUE}"); }\n')
    cargo(root, ["generate-lockfile", "--offline"])
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    # Revisit the first configuration to test cached messages and stale output.
    for profile, feature in (("dev", "base"), ("dev", "extra"), ("release", "base"), ("release", "extra"), ("dev", "base")):
        args = ["build", "--locked", "--offline", "--message-format=json", "--profile", profile]
        if feature == "extra":
            args += ["--features", "extra"]
        result = cargo(root, args)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        artifacts = [e for e in events if e.get("reason") == "compiler-artifact" and e.get("executable")
                     and e["target"]["name"] == "artifact-fixture"]
        scripts = [e for e in events if e.get("reason") == "build-script-executed"]
        require(len(artifacts) == len(scripts) == 1, "expected one binary artifact and one build-script message")
        artifact, script = artifacts[0], scripts[0]
        executable = Path(artifact["executable"])
        require(str(executable) in artifact["filenames"], "executable absent from compiler-artifact filenames")
        require(executable.is_file(), "compiler-artifact executable does not exist")
        require(run([str(executable)], root).stdout.strip() == feature, "JSON selected a stale executable")
        generated = Path(script["out_dir"]) / "selected.rs"
        require(generated.read_text() == f'pub const VALUE: &str = "{feature}";', "JSON selected stale build-script output")
        key = (profile, feature)
        paths = (str(executable), script["out_dir"])
        if key in seen:
            require(paths == seen[key], "cached build changed its selected paths")
        seen[key] = paths
    require(len({out for _, out in seen.values()}) == 4, "build-script outputs collide across build configurations")
    print("  Cargo JSON: feature/profile matrix and cached revisit select the correct executable and generated output", flush=True)


def rustdoc_tables(root: Path) -> None:
    root.mkdir()
    path = root / "table.rs"
    bad = '//! | Column |\n//! | ------ |\n//! | `f(|x| x)` |\n'
    good = bad.replace('f(|x| x)', r'f(\|x\| x)')
    for source, expected in ((bad, "rustdoc::invalid_markdown_table"), (good, None)):
        path.write_text(source)
        run(["rustdoc", f"+{AFTER}", "--edition=2024", "--crate-type=lib", "--error-format=json",
             "-D", "rustdoc::invalid_markdown_table", str(path), "-o", str(root / "html")], root, error=expected)
    print("  rustdoc: unescaped table pipes fail and escaped pipes pass", flush=True)


class RegistryHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass


def registry_crate(root: Path, name: str, version: str, pubtime: str | None) -> dict:
    """Create a real crate archive and its sparse-index record."""
    buffer = io.BytesIO()
    files = {
        "Cargo.toml": f'[package]\nname="{name}"\nversion="{version}"\nedition="2024"\n',
        "src/lib.rs": 'pub fn value() -> u8 { 7 }\n',
    }
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{name}-{version}/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    data = buffer.getvalue()
    target = root / "crates" / name / version / "download"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    record = {"name": name, "vers": version, "deps": [], "cksum": hashlib.sha256(data).hexdigest(),
              "features": {}, "yanked": False}
    if pubtime is not None:
        record["pubtime"] = pubtime
    return record


def locked_version(root: Path, name: str) -> str:
    packages = tomllib.loads((root / "Cargo.lock").read_text())["package"]
    return next(p["version"] for p in packages if p["name"] == name)


def cargo_cooldown(root: Path) -> None:
    root.mkdir()
    registry = root / "registry"
    registry.mkdir()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for name in ("cooldown-probe", "unknown-age-probe"):
        records = [registry_crate(registry, name, "1.0.0", "2000-01-01T00:00:00Z"),
                   registry_crate(registry, name, "1.0.1", now if name == "cooldown-probe" else None)]
        write(registry, f"index/{name[:2]}/{name[2:4]}/{name}", "\n".join(json.dumps(r) for r in records) + "\n")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RegistryHandler, directory=str(registry)))
    server.daemon_threads = True
    base = f"http://127.0.0.1:{server.server_port}"
    write(registry, "index/config.json", json.dumps({"dl": base + "/crates/{crate}/{version}/download"}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        project = root / "project"
        package(project, "cooldown-consumer", 'pub fn value() -> u8 { cooldown_probe::value() + unknown_age_probe::value() }\n')
        with (project / "Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\ncooldown-probe="1"\nunknown-age-probe="1"\n')
        write(project, ".cargo/config.toml", f'''[source.crates-io]
replace-with = "fixture"
[source.fixture]
registry = "sparse+{base}/index/"
[registry]
global-min-publish-age = "3 days"
''')
        env = environment(project)
        env.update(NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        cargo(project, ["generate-lockfile"], env=env)
        require(locked_version(project, "cooldown-probe") == "1.0.0", "cooldown selected a fresh release")
        require(locked_version(project, "unknown-age-probe") == "1.0.1", "missing pubtime was unexpectedly delayed")
        # Build actual registry packages: checksums, archive paths and Rust source
        # must be valid, rather than only exercising a synthetic lock parser.
        cargo(project, ["check", "--locked"], env=env)
        cargo(project, ["update", "-p", "cooldown-probe", "--precise", "1.0.1"],
              env={**env, "CARGO_RESOLVER_INCOMPATIBLE_PUBLISH_AGE": "allow"})
        require(locked_version(project, "cooldown-probe") == "1.0.1", "one-command exception did not select the fresh release")
        cargo(project, ["check", "--locked"], env=env)
        require(locked_version(project, "cooldown-probe") == "1.0.1", "locked build discarded the selected release")
        cargo(project, ["update"], env=env)
        require(locked_version(project, "cooldown-probe") == "1.0.0", "full update did not apply cooldown on re-resolution")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print("  Cargo cooldown: real sparse registry, old/fresh/missing age, one-command exception, and locked version pass", flush=True)


def loom(root: Path) -> None:
    shutil.copytree(FIXTURES / "loom", root)
    shutil.copy2(HERE / "Cargo.lock", root / "Cargo.lock")
    env = environment(root, registry_cache=True)
    env["RUSTFLAGS"] = "--cfg loom --check-cfg=cfg(loom) --check-cfg=cfg(broken)"
    # Prune the copied workspace lock without downloading packages for inactive
    # targets or optional features. metadata resolves their full package data;
    # metadata --no-deps does not update the lock at all.
    cargo(root, ["update", "--offline", "--workspace"], env=env)
    reference = {(p["name"], p["version"]) for p in tomllib.loads((HERE / "Cargo.lock").read_text())["package"]}
    selected = {(p["name"], p["version"]) for p in tomllib.loads((root / "Cargo.lock").read_text())["package"]}
    require(selected <= reference, f"loom resolved versions outside the harness lock: {selected - reference}")
    cargo(root, ["test", "--offline", "--locked"], env=env)
    result = cargo(root, ["test", "--offline", "--locked"], env={**env, "RUSTFLAGS": env["RUSTFLAGS"] + " --cfg broken"},
                   error="assertion `left == right` failed")
    require("left: 0" in result.stdout and "right: 42" in result.stdout, "loom failure is not the planted publication defect")
    print("  loom: cfg(loom) Release passes; Relaxed fails with the planted 0 != 42 defect", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "compiler", "cargo", "loom"), default="all")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="rust-release-regressions-") as temp:
            root = Path(temp)
            # Fail on absent tools/toolchains before reporting any coverage.
            for version in ((BEFORE, AFTER) if args.suite in ("all", "compiler") else (AFTER,)):
                run(["rustc", f"+{version}", "--version"], root)
            if args.suite in ("all", "compiler"):
                compiler(root / "compiler")
            if args.suite in ("all", "cargo"):
                cargo_lints(root / "lints")
                cargo_artifacts(root / "artifacts")
                cargo_cooldown(root / "cooldown")
                rustdoc_tables(root / "rustdoc")
            if args.suite in ("all", "loom"):
                loom(root / "loom")
    except (Failure, OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"FAIL: release regressions: {error}", file=sys.stderr)
        return 1
    print("OK: all release regression suites pass" if args.suite == "all"
          else f"OK: {args.suite} diagnostic subset passes; run without --suite for all gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
