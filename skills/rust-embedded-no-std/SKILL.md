---
name: rust-embedded-no-std
description: Use when a Rust firmware or library targets bare metal with no_std, core or alloc, a panic handler, a linker script, interrupts, critical sections, embedded-hal, Embassy, RTIC, probe-rs, or defmt. Triggers on no_std, bare metal, embedded Rust, memory.x, linker script, panic handler, embedded-hal, Embassy, RTIC, probe-rs, or defmt.
license: BSD-3-Clause
---

# Rust Embedded and no_std

Use this skill to build or review Rust that runs without an operating system.
Keep the firmware bootable, bounded, observable, and testable on a host.

Use these boundaries:

- Use `cargo-workflows` for general workspace features and profiles.
- Use `rust-native-linking` when a firmware build links a C library or vendor SDK.
- Use `rust-unsafe` for volatile access, raw pointers, inline assembly, and DMA
  soundness.
- Use this skill for the `no_std` boundary, runtime selection, memory layout,
  interrupts, embedded framework selection, and device validation.

Do not add an executor, allocator, or hardware abstraction until the product
needs it. A synchronous static program is the smallest reliable firmware.

## Establish the target contract

Record these facts before you edit code:

| Fact | Evidence |
|---|---|
| Exact chip and revision | Schematic, board manifest, or chip marking |
| Rust target triple | Workspace config and `rustc --print target-list` |
| Runtime crate | Dependency graph and the binary entry attribute |
| Flash and RAM regions | Vendor memory map and bootloader reservation |
| Clock source and frequency | Clock tree configuration and measurement |
| Debug transport | SWD, JTAG, USB, serial, or semihosting |
| Reset and update path | Boot ROM, bootloader, watchdog, or debugger |

Do not infer the memory map from a similar board. Account for a bootloader,
configuration pages, secure regions, and retained RAM explicitly.

Inspect the current workspace:

```bash
rg -n '#!\[(no_std|no_main)\]|entry|interrupt|exception|global_allocator|panic_handler' --type rust
rg -n 'memory\.x|link\.x|runner|rustflags|build-std|panic\s*=' -g '*.toml' -g '*.json' -g '*.x'
cargo tree --edges normal,build
rustc --print target-list | rg '<architecture>|thumb|riscv'
```

Use a built-in target when it matches the CPU, ABI, floating-point mode, and
atomic support. Add a custom target JSON only when one of those properties is
not represented. Compare a custom file with `rustc --print target-spec-json`
on the pinned nightly toolchain. Pin that nightly because the JSON schema is
unstable.

Install a target only with authorization when it is missing:

```bash
rustup target add <target>
rustc --target <target> --print cfg
```

The second command is the source of truth for `target_has_atomic`, pointer
width, endianness, and target features. Do not assume that every microcontroller
has compare-and-swap or even native atomic loads.

## Put no_std at the correct boundary

Make reusable logic a library with `#![no_std]`. Keep the runtime, startup,
panic policy, and hardware singleton in the final binary. The complete example
below is a library crate root, so a binary-example compiler cannot judge it.

```rust,ignore
#![no_std]

pub fn saturating_scale(sample: u16, gain: u16) -> u16 {
    sample.saturating_mul(gain)
}

#[cfg(test)]
extern crate std;

#[cfg(test)]
mod tests {
    use super::saturating_scale;

    #[test]
    fn scale_saturates() {
        assert_eq!(saturating_scale(u16::MAX, 2), u16::MAX);
    }
}
```

Use the smallest available library layer:

| Need | Layer | Constraint |
|---|---|---|
| Arithmetic, slices, iterators, atomics | `core` | No heap |
| `Vec`, `String`, `Box`, reference counting | `alloc` | One valid global allocator |
| Files, sockets, threads, process environment | `std` | Requires an OS integration |

Do not enable `alloc` because a dependency exposes an allocation feature.
First select a bounded container or pass caller-owned storage. If allocation is
required, define all of these facts:

- The heap address and size in the linker layout.
- The allocator implementation and initialization point.
- The earliest time that allocation is permitted.
- The out-of-memory behavior.
- The measured high-water mark under worst-case load.

Install exactly one `#[global_allocator]` in the final program. Do not install
one in a reusable library. An allocation failure is normally terminal on bare
metal. Do not retry it in an unbounded loop.

Use `panic = "abort"` for firmware unless the selected target and runtime have
a tested unwind implementation. Set it for each shipped profile:

```toml
[profile.dev]
panic = "abort"

[profile.release]
panic = "abort"
overflow-checks = true
debug = 1
```

Provide exactly one panic implementation in the final dependency graph. Let a
debug crate provide it when it reports through the selected transport. Let a
production crate provide reset, safe shutdown, or a bounded fault record.
Libraries must not select the application panic policy.

Never claim that a panic message is delivered until the same release artifact
reports it on the real transport. The logging path can fail after clocks,
interrupts, or memory become corrupt.

## Own startup and memory layout

Prefer the architecture runtime crate and its linker template. Supply the chip
memory regions in `memory.x` or the runtime's documented input. Do not copy the
runtime's full linker script into the application unless the shipped image has
a requirement that its extension points cannot express.

Follow the runtime or HAL layout-generation path when it has one. Otherwise,
make `memory.x` visible to the linker from every workspace directory. Copy it
to `OUT_DIR` in the firmware crate's `build.rs` and add that directory to the
linker search path:

```rust
use std::{env, fs, path::PathBuf};

fn main() {
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR is set by Cargo"));
    fs::copy("memory.x", output.join("memory.x")).expect("copy memory.x to OUT_DIR");
    println!("cargo::rustc-link-search={}", output.display());
    println!("cargo::rerun-if-changed=memory.x");
}
```

Do not add this build script when the selected runtime or HAL already emits the
layout and linker search path. Two layout owners can select the wrong memory
map without an obvious compile error.

A memory file must use values from the selected chip and boot layout:

```text
MEMORY
{
  FLASH : ORIGIN = <application-flash-origin>, LENGTH = <application-flash-length>
  RAM   : ORIGIN = <usable-ram-origin>,         LENGTH = <usable-ram-length>
}
```

Keep these linker invariants:

- Place the vector table at the address expected by the boot path.
- Retain vectors and required startup sections with `KEEP`.
- Copy initialized data from flash to RAM before Rust code reads it.
- Zero BSS before Rust code reads it.
- Align the stack, heap, DMA buffers, and vector table as the architecture needs.
- Reserve bootloader mailboxes, retained crash data, and peripheral DMA memory.
- Fail the link when sections overlap or exceed a region.
- Export only symbols that startup code or a verified diagnostic reads.

Add linker `ASSERT` expressions for stack, heap, and image boundaries when the
runtime template permits them. Do not use a successful flash operation as proof
that the image fits. A programmer can erase adjacent data before it notices an
invalid layout.

Keep application-specific linker arguments on the final binary. A library or a
runtime dependency cannot reliably inject final-artifact layout for every
consumer.

Use a runner only for the exact target:

```toml
[target.<target>]
runner = "probe-rs run --chip <chip>"
rustflags = ["-C", "link-arg=-Tlink.x"]
```

Do not put a global `build.target` in a reusable workspace without preserving a
host-test command. It can make `cargo test` try to execute firmware on the host.

## Keep concurrency bounded

Use interrupt handlers only to acknowledge hardware and move bounded state.
Move parsing, formatting, allocation, and blocking I/O to task context.

For every interrupt-shared value, write down:

1. Which contexts read and write it.
2. Which operation makes access exclusive.
3. The maximum time that interrupts stay masked.
4. Which memory ordering or critical-section rule publishes the data.

Use native atomics only when `rustc --target <target> --print cfg` lists the
required width and operation. Otherwise use the `critical-section` abstraction
with exactly one implementation selected by the final binary. Do not create a
second interrupt-mask implementation in a driver.

Never hold a critical section across these operations:

- An `.await` point.
- A peripheral transaction that waits for hardware.
- Logging or formatting.
- A callback into unknown code.
- A loop with an input-dependent bound.

Model interrupt priority and preemption. Masking same-priority work is not proof
against a higher-priority interrupt. On a multi-core target, disabling local
interrupts is not a cross-core lock.

Treat DMA as concurrent access by hardware. Keep its buffer alive and at a
stable address until completion. Transfer ownership to the driver when its API
supports that model. Apply the chip's cache clean and invalidate rules. See
`rust-unsafe` before adding a raw DMA buffer API.

Treat DMA cancellation as a separate state transition. A timeout, a `select`
branch, or a dropped future does not prove that the transfer stopped. Do not
reuse or drop the buffer until the driver confirms that DMA stopped, clears the
pending interrupt, and completes the required cache maintenance. If the driver
cannot prove that state, keep ownership quarantined and reset the peripheral
through its documented recovery path.

## Select the hardware and task model

Use `embedded-hal` traits at reusable driver boundaries. Keep board pin choices,
clock setup, interrupts, and concrete HAL types in the application. Use the
async traits only when the caller already has an async runtime and the device
operation benefits from sleeping instead of polling.

Select one task model:

| Requirement | Select |
|---|---|
| Short sequential control loop | Synchronous functions and interrupts |
| Many I/O waits with static async tasks | Embassy |
| Priority-driven tasks with static resources | RTIC |
| Vendor certification or existing scheduler contract | The required RTOS integration |

Do not mix Embassy and RTIC in one binary unless an existing platform contract
requires it and documents interrupt ownership. Both frameworks need control of
execution and interrupt resources.

With Embassy, prove that every spawned task has a static slot and that no task
waits synchronously inside the executor. With RTIC, prove resource ceilings,
priority ordering, and maximum lock duration. For both, bound channel capacity
and define overflow policy at the sender.

When Embassy uses time, select exactly one compatible time driver in the final
binary. Use its fixed tick rate, or select a rate only when the driver supports
that choice. Verify that the clock and interrupt-latency budget support the
rate. Bind each interrupt that an asynchronous driver requires through the
documented HAL or runtime mechanism. With RTIC, reserve each declared
dispatcher for software tasks. Bind and start each selected monotonic. Reject
an interrupt vector that a HAL, executor, dispatcher, or monotonic owns twice.
Verify timer progress and every asynchronous interrupt wake-up on the real
device.

## Budget every finite resource

Create an explicit release budget for these resources:

| Resource | Required evidence |
|---|---|
| Flash | Linked section sizes plus update or bootloader reserve |
| Static RAM | Data, BSS, retained memory, and static task storage |
| Stack | Per-context estimate plus measured high-water mark |
| Heap | Configured size and measured high-water mark, or zero |
| Queues | Fixed capacity and full-queue behavior |
| Interrupt latency | Longest masked interval under release optimization |
| CPU time | Worst observed task and interrupt time with margin |
| Energy | Duty cycle under the real clock and peripheral configuration |

Reject unbounded queues, recursive retry, and growth from input-controlled
lengths. Treat a queue full condition as a normal state. Choose drop-oldest,
drop-newest, backpressure, coalescing, or fail-safe behavior deliberately.

Keep physical calibration as configuration. Clock tolerance, oscillator startup,
watchdog window, debounce time, ADC offset, sensor threshold, and radio timing
vary by board and environment. Set safe defaults, limit accepted values, and
record the real-hardware measurements that justify them.

## Debug the shipped shape

Use `probe-rs` with an explicit chip. Do not rely on automatic chip detection in
CI or production instructions.

```bash
cargo build --locked --release --target <target> --bin <firmware>
probe-rs run --chip <chip> target/<target>/release/<firmware>
probe-rs attach --chip <chip> target/<target>/release/<firmware>
```

Use `defmt` for bounded device logs when the target integration supports it.
Keep the decoder metadata and the exact ELF from the same build. A log decoded
with a different ELF is invalid evidence. Do not log secrets, credentials,
private identifiers, or unbounded input.

Select exactly one global `defmt` logger and transport implementation in the
final binary. For RTT, link the workspace's compatible `defmt-rtt` crate or its
equivalent explicitly; `probe-rs run` decodes the stream but does not add the
transport to the firmware. Keep the logger-retention import in the binary, not
in a reusable library. Select exactly one panic provider separately. Inspect
the final dependency graph and link output for duplicate or missing logger and
panic symbols, then run the release ELF through the real transport.

Set the release log level deliberately. Measure flash, timing, and transport
backpressure with that level. A debug probe that drains logs can hide a deadlock
or timing failure that appears when the device runs alone.

Inspect the final ELF:

```bash
cargo size --release --target <target> --bin <firmware> -- -A
cargo objdump --release --target <target> --bin <firmware> -- -h
cargo nm --release --target <target> --bin <firmware> -- --size-sort
```

If the workspace does not install the Cargo wrappers, use the matching LLVM
tools from the pinned Rust toolchain. Do not add tools only to make command
spelling uniform.

## Preserve host tests

Keep protocol parsing, state machines, unit conversion, filters, and retry
decisions independent of registers and global peripherals. Test that library on
the host. Replace a peripheral with a small trait fake only at the existing HAL
boundary; do not emulate the whole chip.

```bash
host_target="$(rustc -vV | sed -n 's/^host: //p')"
cargo test --locked --lib --target "$host_target"
cargo check --locked --target <target> --all-features
cargo build --locked --release --target <target> --bin <firmware>
```

Do not enable mutually exclusive chip or runtime features together only because
`--all-features` is convenient. When features select hardware, test an explicit
feature matrix and reject invalid combinations with `compile_error!`.

Add hardware-in-the-loop checks only for behavior that a host cannot prove:
startup, interrupt routing, clock accuracy, DMA, reset cause, watchdog action,
sleep and wake, flash update, and real peripheral timing. Give each check a
timeout and a recovery action so a failed board does not occupy CI forever.

## Failure triage

| Symptom | Likely cause | Check and fix |
|---|---|---|
| Duplicate panic implementation | Two panic provider crates | Inspect `cargo tree`; select one in the binary |
| `#[global_allocator]` missing | `alloc` is used with no allocator | Remove allocation or initialize one bounded heap |
| Linker reports region overflow | Code, statics, heap, or stack exceed layout | Inspect sections; reduce use or change only a verified memory budget |
| Firmware flashes but does not start | Wrong vector address, entry point, or reset setup | Check boot offset, vector contents, and runtime feature |
| Hard fault after enabling DMA | Buffer lifetime, alignment, cache, or region error | Stop DMA; inspect ownership and chip memory rules |
| Interrupt fires once | Pending flag is not cleared correctly | Read the peripheral sequence; clear only documented flags |
| Interrupt storm | Level source remains asserted or priority is wrong | Inspect source state and acknowledgement order |
| Async task stops progressing | Blocking call, lost wake, or exhausted task slot | Inspect executor trace and all bounded slots |
| Logs corrupt or disappear | Wrong ELF, transport overflow, or reset during output | Match build identity and reduce bounded log volume |
| Host tests try to run firmware | Global embedded target or runner leaked into tests | Pass the host target explicitly or scope target config |
| Debug build works, release fails | Timing race, overflow, layout, or logging side effect | Test the release ELF and inspect optimization-sensitive sharing |

Do not weaken optimization, increase memory, or add delays as the final fix until
inspection identifies the violated invariant.

## Completion checklist

- The exact chip, target, runtime, boot offset, and memory regions are recorded.
- Reusable logic compiles as `no_std`; host tests run on the host triple.
- The final binary owns one panic policy, one allocator if needed, and one
  critical-section implementation.
- Interrupt, DMA, and task ownership are explicit and bounded.
- Flash, RAM, stack, heap, queue, latency, and timing budgets have evidence.
- The release ELF is inspected, flashed, and run without a debugger attached.
- Panic, watchdog, reset, queue-full, and transport-failure paths are exercised.
- Calibration values remain bounded knobs and have real-hardware measurements.
