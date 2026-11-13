#!/usr/bin/env python3
"""Install pinned public WASI test tools into --output, with release-asset SHA-256 checks."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import shutil
import tarfile
import urllib.request

PINS = {
    ("Linux", "aarch64"): [
        ("wasmtime", "v50.0.1", "wasmtime-v50.0.1-aarch64-linux.tar.xz", "d737e077416d78fbfb0a008229ec27d6a0fd5a4924874b8c38b293c850cf4094"),
        ("wasm-tools", "v1.263.0", "wasm-tools-1.263.0-aarch64-linux.tar.gz", "773b5e6bf957f0d93a9a337c9c5fc4c35509706301a80799f57a76fa367fd1ca"),
    ],
    ("Darwin", "arm64"): [
        ("wasmtime", "v50.0.1", "wasmtime-v50.0.1-aarch64-macos.tar.xz", "960e5216c7ebd7e9b45e6561d15821b8b801b7d54aee28c7b91921aeb30c65c8"),
        ("wasm-tools", "v1.263.0", "wasm-tools-1.263.0-aarch64-macos.tar.gz", "b568f04746a699c4068b8d751779b60b501cf2cab6d259a3bc973eb5eeb1f62b"),
    ],
    ("Linux", "x86_64"): [
        ("wasmtime", "v50.0.1", "wasmtime-v50.0.1-x86_64-linux.tar.xz", "685466455dd42a14774a86c36c8f2e45cbb9bd6d92a850139315df60a75498a5"),
        ("wasm-tools", "v1.263.0", "wasm-tools-1.263.0-x86_64-linux.tar.gz", "21c036c1740a0552124c79c6e2170cb61c5b016005671a6d5bc06cf642165431"),
    ],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = (platform.system(), platform.machine())
    if key not in PINS:
        parser.error(f"no reviewed asset for {key}")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, version, asset, checksum in PINS[key]:
        url = f"https://github.com/bytecodealliance/{name}/releases/download/{version}/{asset}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != checksum:
            raise RuntimeError(f"SHA-256 mismatch: {asset}")
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            members = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name == name]
            if len(members) != 1:
                raise RuntimeError(f"expected one {name} executable")
            with archive.extractfile(members[0]) as source, (args.output / name).open("wb") as dest:
                shutil.copyfileobj(source, dest)
        (args.output / name).chmod(0o755)
        print(f"verified {asset}: {checksum}")


if __name__ == "__main__":
    main()
