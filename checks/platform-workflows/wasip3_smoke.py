#!/usr/bin/env python3
"""Build and run a WASIp3 async clock/file fixture with and without its file capability."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(args):
    return subprocess.run([str(x) for x in args], text=True, capture_output=True, timeout=120)


def checked(args):
    result = run(args)
    if result.returncode:
        raise RuntimeError(f"{args!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    wasmtime, wasm_tools = args.tools.resolve() / "wasmtime", args.tools.resolve() / "wasm-tools"
    runtime = checked([wasmtime, "--version"]).strip()
    tooling = checked([wasm_tools, "--version"]).strip()
    require(runtime.startswith("wasmtime 50.0.1 "), runtime)
    require(tooling.split()[:2] == ["wasm-tools", "1.263.0"], tooling)
    with tempfile.TemporaryDirectory(prefix="wasip3-smoke-") as directory:
        work = Path(directory)
        component = work / "guest.wasm"
        checked(["rustc", "+1.100.0", "--edition=2024", "--target", "wasm32-wasip3",
                 ROOT / "wasip3_guest.rs", "-o", component])
        checked([wasm_tools, "validate", component])
        wit = checked([wasm_tools, "component", "wit", component])
        for required in ["wasi:clocks/monotonic-clock@0.3.0", "wasi:filesystem/preopens@0.3.0",
                         "run: async func()", "wait-for: async func", "wait-until: async func"]:
            require(required in wit, f"missing WIT interface: {required}")
        fixture = work / "fixture"
        fixture.mkdir()
        (fixture / "input.txt").write_text("capability granted\n")
        command = [wasmtime, "run", "-S", "p3", "-W", "component-model-async"]
        allowed = checked(command + ["--dir", f"{fixture}::/fixture", component])
        require(allowed == "async clock wait completed\nfile capability granted\n", allowed)
        denied = run(command + [component])
        require(denied.returncode != 0, "missing capability unexpectedly succeeded")
        require(denied.stdout == "async clock wait completed\n", denied.stdout)
        require("NotFound" in denied.stderr, denied.stderr)
        disabled = run([wasmtime, "run", "-S", "p3=n", "-W", "component-model-async", component])
        require(disabled.returncode != 0 and not disabled.stdout, "WASIp3 disabled unexpectedly ran")
        require("wasi:cli/environment@0.3.0" in disabled.stderr
                and "matching implementation was not found in the linker" in disabled.stderr,
                f"expected missing WASIp3 interface, got: {disabled.stderr}")
        report = {"rust": "1.100.0", "wasmtime": runtime, "wasm_tools": tooling,
                  "async_clock_and_file": "pass", "no_directory_capability": "denied after clock wait",
                  "wasip3_disabled": "rejected", "allowed_stdout": allowed,
                  "denied_stderr": denied.stderr.strip()}
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "imports.wit").write_text(wit)
            (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
