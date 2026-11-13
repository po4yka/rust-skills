#!/usr/bin/env python3
"""Capture real samply samples on Apple Silicon, apply SPGO, and compare timed runs.

The converter supports only sample_workload.rs: one noinline, unmangled hot
function, leaf-PC samples, no inferred call counts or inline/discriminator data.
All raw profiles stay in the caller's --output directory.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parent
RUST = ["rustc", "+1.100.0"]
FLAGS = ["--edition=2024", "-Copt-level=3", "-Cdebuginfo=2", "-Cforce-frame-pointers=yes"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command):
    result = subprocess.run([str(x) for x in command], text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{command!r}\n{result.stdout}\n{result.stderr}")
    return result


def leaf_counts(profile, binary):
    libraries = [i for i, lib in enumerate(profile["libs"]) if Path(lib["path"]) == binary]
    if len(libraries) != 1:
        raise ValueError("profile must name exactly the recorded binary")
    counts, total = Counter(), 0
    for thread in profile["threads"]:
        samples = thread["samples"]
        weights = samples["weight"] or [1] * samples["length"]
        for stack, weight in zip(samples["stack"], weights, strict=True):
            if stack is None:
                continue
            if not isinstance(weight, int) or weight <= 0:
                raise ValueError("expected positive integer sample weights")
            total += weight
            frame = thread["stackTable"]["frame"][stack]
            function = thread["frameTable"]["func"][frame]
            resource = thread["funcTable"]["resource"][function]
            if resource >= 0 and thread["resourceTable"]["lib"][resource] == libraries[0]:
                counts[thread["frameTable"]["address"][frame]] += weight
    return counts, total


def tools():
    version = run(RUST + ["-vV"]).stdout
    require("release: 1.100.0\n" in version, version)
    sysroot = Path(run(RUST + ["--print", "sysroot"]).stdout.strip())
    host = run(RUST + ["--print", "host-tuple"]).stdout.strip()
    directory = sysroot / "lib/rustlib" / host / "bin"
    llvm_version = run([directory / "llvm-profdata", "--version"]).stdout
    llvm_major = re.search(r"LLVM version: (\d+)", version)[1]
    require(re.search(rf"LLVM version {llvm_major}\.", llvm_version), llvm_version)
    return directory, version, llvm_version


def validate_capture(capture, source_hash, profile):
    require(capture["source_sha256"] == source_hash, "record a new profile after a source edit")
    require(capture["profile_sha256"] == hashlib.sha256(profile.encode()).hexdigest(), "recorded profile changed")
    require(capture["mapped_leaf_samples"] >= 100, "recorded profile has too few samples")
    require(profile.startswith(f"sampled_hot:{capture['mapped_leaf_samples']}:"), "sample count does not match capture")


def apply_profile(out, profile, llvm_tools):
    profdata = llvm_tools / "llvm-profdata"
    run([profdata, "merge", "--sample", "--extbinary", profile, "-o", out / "samples.prof"])
    shown = run([profdata, "show", "--sample", "--all-functions", out / "samples.prof"]).stdout
    (out / "profile-show.txt").write_text(shown)
    compiled = run(RUST + FLAGS + [f"-Cprofile-sample-use={out / 'samples.prof'}",
                   f"--emit=link={out / 'optimized'},llvm-ir={out / 'optimized.ll'}", ROOT / "sample_workload.rs"])
    (out / "apply.log").write_text(compiled.stdout + compiled.stderr)
    if "warning:" in compiled.stderr:
        raise RuntimeError("profile build warned; inspect apply.log")
    ir = (out / "optimized.ll").read_text()
    definition = re.search(r"^define .*@sampled_hot\(.*$", ir, re.MULTILINE)[0]
    metadata = re.search(r"!prof !(\d+)", definition)
    if not metadata or not re.search(rf'^!{metadata[1]} = !\{{!"function_entry_count", i64 \d+\}}', ir, re.MULTILINE):
        raise RuntimeError("sample profile was not attached to sampled_hot")
    return shown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samply", default="samply")
    parser.add_argument("--rounds", type=int, default=9)
    parser.add_argument("--replay", action="store_true", help="check the recorded fixture; do not sample or benchmark")
    args = parser.parse_args()
    if args.rounds < 5:
        parser.error("use at least five alternating benchmark rounds")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    llvm_tools, rust_version, llvm_version = tools()
    source = ROOT / "sample_workload.rs"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if args.replay:
        capture = json.loads((ROOT / "sample_capture.json").read_text())
        validate_capture(capture, source_hash, (ROOT / "sample_capture.txt").read_text())
        apply_profile(out, ROOT / "sample_capture.txt", llvm_tools)
        result = run([out / "optimized", "30000"]).stdout.strip()
        require(result == capture["workload_output"], result)
        print("PASS: recorded sample profile loads, attaches to sampled_hot, and preserves output")
        return
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("capture requires Apple Silicon macOS, Xcode atos, and samply 0.13.1")
    samply_version = run([args.samply, "--version"]).stdout.strip()
    require(samply_version == "samply 0.13.1", samply_version)
    baseline, optimized = out / "baseline", out / "optimized"
    run(RUST + FLAGS + [source, "-o", baseline])
    recorded = run([args.samply, "record", "--save-only", "--main-thread-only", "--rate", "1000",
                    "--output", out / "samples.json.gz", baseline, "100000"])
    (out / "record.log").write_text(recorded.stdout + recorded.stderr)
    with gzip.open(out / "samples.json.gz") as file:
        counts, total = leaf_counts(json.load(file), baseline)
    headers = run([llvm_tools / "llvm-objdump", "--macho", "--private-headers", baseline]).stdout
    base = int(re.search(r"segname __TEXT\s+vmaddr (0x[0-9a-fA-F]+)", headers)[1], 16)
    addresses = sorted(counts)
    symbols = run(["xcrun", "atos", "-arch", "arm64", "-o", str(baseline) + ".dSYM/Contents/Resources/DWARF/baseline",
                   *[hex(base + address) for address in addresses]]).stdout.splitlines()
    first_line = next(i for i, line in enumerate(source.read_text().splitlines(), 1)
                      if line.startswith("pub fn sampled_hot("))
    lines = Counter()
    for address, symbol in zip(addresses, symbols, strict=True):
        match = re.fullmatch(r"sampled_hot \(in baseline\) \(sample_workload.rs:(\d+)\)", symbol)
        if match:
            lines[max(0, int(match[1]) - first_line)] += counts[address]
    mapped = sum(lines.values())
    if mapped < 100 or mapped < total / 2:
        raise RuntimeError(f"insufficient resolved workload samples: {mapped}/{total}")
    profile = f"sampled_hot:{mapped}:{lines.get(0, 0)}\n" + "".join(
        f" {offset}: {count}\n" for offset, count in sorted(lines.items()))
    (out / "samples.txt").write_text(profile)
    shown = apply_profile(out, out / "samples.txt", llvm_tools)
    require(f"sampled_hot: {mapped}," in shown, shown)
    times, outputs = {"baseline": [], "optimized": []}, set()
    for binary in (baseline, optimized):
        outputs.add(run([binary, "30000"]).stdout)  # unmeasured warmup
    for index in range(args.rounds):
        for binary in ((baseline, optimized) if index % 2 == 0 else (optimized, baseline)):
            start = time.perf_counter()
            outputs.add(run([binary, "30000"]).stdout)
            times[binary.name].append(time.perf_counter() - start)
    require(len(outputs) == 1, f"workload outputs differ: {outputs}")
    result = {"rustc": rust_version.strip(), "llvm_profdata": llvm_version.strip(), "samply": samply_version,
              "host": platform.platform(), "source_sha256": source_hash,
              "profile_sha256": hashlib.sha256(profile.encode()).hexdigest(),
              "sample_count": total, "mapped_leaf_samples": mapped, "line_samples": dict(lines),
              "workload_output": next(iter(outputs)).strip(), "profile_attached": True,
              "rounds": args.rounds, "iterations_per_run": 30000, "seconds": times,
              "median_seconds": {name: statistics.median(values) for name, values in times.items()},
              "binary_bytes": {path.name: path.stat().st_size for path in (baseline, optimized)}}
    result["median_ratio_optimized_over_baseline"] = result["median_seconds"]["optimized"] / result["median_seconds"]["baseline"]
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
