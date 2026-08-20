# On-Device Sanitizers: Android and iOS

Platform-specific runtime validation for a Rust library that you
cross-compile into a mobile app. Read `SKILL.md` first for the host-side
ASan, TSan and MSan flow and for Miri.

Check the current [Android HWASan guide](https://developer.android.com/ndk/guides/hwasan),
[Android MTE guide](https://developer.android.com/ndk/guides/arm-mte), and
[Xcode sanitizer guide](https://developer.apple.com/documentation/xcode/diagnosing-memory-thread-and-crash-issues-early)
before you change the platform matrix.

## 1. Android: HWASan and ASan

Use these to validate a cdylib or staticlib that you cross-compile to an
Android target.

```bash
# HWASan: ARM64 only. See the device requirements below.
RUSTFLAGS="-Z sanitizer=hwaddress" \
    cargo +nightly build --locked -Zbuild-std \
    --target aarch64-linux-android

```

Put the flags in `.cargo/config.toml` under the target section if you do not
want to repeat them on every command.

HWASan is the supported Android sanitizer for new memory-error tests. Android
ASan is unsupported as of 2023. HWASan needs a 64-bit Arm device. On Android
14 and later, a debuggable app can start HWASan through `wrap.sh`. Android 10
through 13 need a HWASan build of Android, such as a supported Pixel system
image.

To run on the device:

1. Build every native target with HWASan and frame pointers.
2. Use `c++_shared` when the app also links libc++.
3. For Android 14 or later, package this `wrap.sh` for `arm64-v8a`:

   ```bash
   #!/system/bin/sh
   LD_HWASAN=1 exec "$@"
   ```

4. For Android 10 through 13, install a compatible HWASan system image.
5. Run the debuggable app and read the report from logcat or the tombstone.

## 2. Android MTE (Memory Tagging Extension)

MTE is available on select arm64 devices starting with Android 13. Check the
device before you configure the app:

```bash
adb shell grep mte /proc/cpuinfo
```

Continue only when the feature list contains `mte`. MTE tags heap allocations
and checks the tag on each access.

### Activation

MTE needs no Rust code change. Set the mode in `AndroidManifest.xml`:

```xml
<application
    android:memtagMode="async"
    ... >
```

| Mode | Effect |
|---|---|
| `async` | Lower overhead. The CPU reports a tag mismatch at a later kernel entry. |
| `sync` | Debug only. The CPU reports the mismatch at the exact access. |
| `off` | Explicit disable. |

Manifest activation works through the bionic allocator and checks the native
heap. It does not need a Rust rebuild. Stack checks are different. They need
Android 14 QPR3 or later and code built with MTE instrumentation. A mismatch
raises `SIGSEGV` with `si_code = SEGV_MTEAERR` in async mode or
`SEGV_MTESERR` in sync mode.

### Cost and detection trade-off

| Setting | Detection | Cost | Use for |
|---|---|---|---|
| `memtagMode="async"` | Delayed report without the faulting access | Lower overhead | A well-tested release candidate |
| `memtagMode="sync"` | Exact report at the access | Higher overhead | Development and soak tests |
| HWASan | Exact report at the access | About 2x CPU, 10% to 35% RAM | A device without MTE, or full stack and heap instrumentation |

Do not use Android ASan as the fallback. It is unsupported. Use HWASan on a
compatible device or run ASan against a host build.

### Read an MTE crash

```bash
adb pull /data/tombstones/<latest>
grep -E 'MTEAERR|MTESERR' <tombstone>
```

The tombstone gives the tagged address and the access kind (read or write).
Resolve the Rust frames with `addr2line` against the build that still carries
symbols. See the `rust-debugging` skill.

### What MTE catches

Heap MTE catches use-after-free, double free, and overflows that cross a tagged
heap allocation boundary.

Heap MTE does not catch:

- Stack use-after-free. Stack-MTE is a separate and less deployed extension.
- Reads of uninitialized memory. Use MSan or Miri.
- Data races. Use TSan, Miri with a seed, or `loom`.

### Rollout

1. Confirm that `/proc/cpuinfo` reports the `mte` feature.
2. Add `android:memtagMode="sync"` to the debug manifest.
3. Run the full test suite on MTE hardware and fix each report.
4. Test `android:memtagMode="async"` on the release candidate.
5. Confirm that no compatibility failure appears.
6. Ship only after the compatible-device test passes.

## 3. iOS app sanitizers through Xcode

Xcode instruments the Swift, Objective-C, and C or C++ code that it compiles. A
prebuilt Rust static library or XCFramework is not instrumented by the scheme
setting. ASan can still report some heap errors because it intercepts allocator
calls. TSan does not validate ordinary memory accesses inside an uninstrumented
Rust library. Run ASan and TSan against a supported host Rust target for that
coverage.

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

Run TSan as a separate Simulator job:

```bash
xcodebuild \
    -scheme <YourScheme> \
    -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
    -enableThreadSanitizer YES \
    test
```

Notes:

- ASan on the Simulator catches use-after-free, buffer overflow and
  stack-use-after-return in the Swift code. In an uninstrumented Rust library it
  catches the heap classes only, because those go through the intercepted
  allocator.
- Thread Sanitizer is in the same Diagnostics panel. Run it on the Simulator.
  Do not enable ASan and TSan at the same time.
- MTE is not available on iOS. Do not treat an Xcode sanitizer pass as proof
  that a prebuilt Rust library was instrumented.
