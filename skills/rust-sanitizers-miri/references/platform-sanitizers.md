# On-Device Sanitizers: Android and iOS

Platform-specific runtime validation for a Rust library that you
cross-compile into a mobile app. Read `SKILL.md` first for the host-side
ASan, TSan and MSan flow and for Miri.

## 1. Android: HWASan and ASan

Use these to validate a cdylib or staticlib that you cross-compile to an
Android target.

```bash
# HWASan: ARM64 only, Android 10 and later. Preferred over ASan on ARM64.
RUSTFLAGS="-Z sanitizer=hwaddress" \
    cargo +nightly build --locked -Zbuild-std \
    --target aarch64-linux-android

# ASan: works on ARM devices and on x86 emulators.
RUSTFLAGS="-Z sanitizer=address" \
    cargo +nightly build --locked -Zbuild-std \
    --target aarch64-linux-android
```

Put the flags in `.cargo/config.toml` under the target section if you do not
want to repeat them on every command.

HWASan is preferred on ARM64. It has lower overhead than ASan, it catches the
same bugs, and the hardware accelerates it through top-byte-ignore (TBI). It
needs Android 10 or later and an ARM64 device or emulator image.

To run on the device:

1. Build the shared library with the flags above.
2. Push the library to the device and set `LD_PRELOAD` to the sanitizer
   runtime, or
3. Enable the sanitizer through the Android Gradle plugin
   `android.defaultConfig.externalNativeBuild` with
   `arguments "-DANDROID_STL=c++_shared"`, and enable HWASan in CMake.

## 2. Android MTE (Memory Tagging Extension)

MTE is the hardware successor to HWASan. It is available on arm64 Android 14
and later on a supporting SoC. HWASan tags in software through top-byte-ignore.
MTE tags heap allocations with dedicated CPU instructions and checks the tag on
each access. The production cost in async mode is near zero.

### Activation

MTE needs no Rust code change. Set the mode in `AndroidManifest.xml`:

```xml
<application
    android:memtagMode="async"
    ... >
```

| Mode | Effect |
|---|---|
| `async` | Production-safe. The CPU reports a tag mismatch after a delay, usually at the next syscall. |
| `sync` | Debug only. The CPU reports the mismatch at the exact access. |
| `off` | Explicit disable. |

MTE works through the bionic allocator. Do not set `RUSTFLAGS`, do not add a
`cfg_attr`, and do not rebuild the Rust code. The allocator writes the tags,
the CPU verifies them, and a mismatch raises `SIGSEGV` with
`si_code = SEGV_MTEAERR` in async mode or `SEGV_MTESERR` in sync mode.

### Cost and detection trade-off

| Setting | Detection | Cost | Use for |
|---|---|---|---|
| `memtagMode="async"` | Eventually consistent, delay of about 10-100 us | About 3% on benchmarked workloads | Release builds |
| `memtagMode="sync"` | Exact, at the access | About 15-25% | Internal dogfood, soak tests |
| HWASan | Exact, at the access | About 15% RAM plus about 5% CPU | When MTE hardware is not available |
| ASan | Exact | About 100% RAM plus about 50% CPU | When neither HWASan nor MTE is available |

Keep HWASan available for CI runs on emulators. Emulator images usually do not
expose MTE hardware.

### Read an MTE crash

```bash
adb pull /data/tombstones/<latest>
grep -E 'MTEAERR|MTESERR' <tombstone>
```

The tombstone gives the tagged address and the access kind (read or write).
Resolve the Rust frames with `addr2line` against the build that still carries
symbols. See the `rust-debugging` skill.

### What MTE catches

MTE catches the same UB class as HWASan: use-after-free on a heap allocation,
double free, an overflow into an adjacent tagged allocation, and type confusion
that crosses an allocation boundary.

MTE does not catch:

- Stack use-after-free. Stack-MTE is a separate and less deployed extension.
- Reads of uninitialized memory. Use MSan or Miri.
- Data races. Use TSan, Miri with a seed, or `loom`.

### Rollout

1. Set `targetSdkVersion` to 34 or later.
2. Add `android:memtagMode="async"` to `<application>` in the manifest.
3. Run the full soak suite on MTE hardware and confirm that no false positive
   appears.
4. Ship.

## 3. iOS: ASan and TSan through Xcode

Xcode instruments the Swift and Objective-C code that it compiles. A prebuilt
Rust static library or XCFramework is not instrumented by the scheme setting.
ASan still intercepts the allocator, so it reports heap errors that the Rust
code causes. To instrument the Rust code itself, build the Rust library for the
iOS target with `-Z sanitizer=address` as well.

Enable it in the scheme editor:

```text
Product -> Scheme -> Edit Scheme -> Run -> Diagnostics -> Address Sanitizer
```

Or from the command line:

```bash
xcodebuild \
    -scheme <YourScheme> \
    -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
    -enableAddressSanitizer YES \
    test
```

Notes:

- ASan on the Simulator catches use-after-free, buffer overflow and
  stack-use-after-return in the Swift code. In an uninstrumented Rust library it
  catches the heap classes only, because those go through the intercepted
  allocator.
- Thread Sanitizer is in the same Diagnostics panel. Do not enable ASan and
  TSan at the same time.
- MTE is not available on iOS. Use ASan and TSan for device-side validation on
  Apple silicon.

