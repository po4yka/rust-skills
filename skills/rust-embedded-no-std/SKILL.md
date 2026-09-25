---
name: rust-embedded-no-std
description: Use when writing, porting, or debugging bare-metal Rust firmware or no_std libraries, such as embedded-hal drivers, Embassy or RTIC tasks, flashing and logging with probe-rs and defmt, memory.x and linker scripts, panic and allocator policy, interrupt-shared state, and atomics on cores without compare-and-swap. Triggers on embedded Rust, cortex-m-rt, thumbv6m, critical-section, portable-atomic, panic_handler, or HardFault.
license: BSD-3-Clause
---

# Rust Embedded and no_std

Keep the firmware bootable, bounded, observable, and testable on a host. Do not
add an executor, allocator, or hardware abstraction until the product needs it.
A synchronous static program is the smallest reliable firmware.

Use these skills, when they are installed, for adjacent work:

- `cargo-workflows` for workspace features, profiles, and CI gates;
- `rust-native-linking` when firmware links a C library or vendor SDK;
- `rust-unsafe` for raw pointers, SAFETY comments, and soundness review;
- `memory-model` for atomic orderings and general `static mut` rules;
- `rust-wasm` for `wasm32v1-none` and other WebAssembly targets.

## Failure triage

| Symptom | Likely cause | Check and fix |
|---|---|---|
| `` custom targets are unstable and require `-Zunstable-options` ``, or `` `.json` target specs require -Zjson-target-spec to be added to the cargo invocation `` | JSON target spec on stable (Rust 1.95+) | Use a built-in target, or pin nightly with `-Z json-target-spec` and `-Z build-std=core` |
| E0599 ``no method named `fetch_add` found``, or the same for `compare_exchange` or `swap` | Target has no compare-and-swap | Use `portable-atomic`; the final binary selects its backend |
| E0432 `` unresolved import `core::sync::atomic::AtomicU32` `` | Target has no atomic types | Use `portable-atomic`; the final binary selects its backend |
| ``invalid definition of the runtime `memset` symbol used by the standard library`` | Hand-written `memset`, `memcpy`, `memmove`, `memcmp`, `bcmp`, or `strlen` with a wrong signature (`invalid_runtime_symbol_definitions`, deny-by-default since 1.98) | Match the C signature, or remove `#[unsafe(no_mangle)]` or `export_name` |
| `` `-C soft-float`: this option has been removed (use a corresponding *eabi target instead) ``, or ``target feature `<name>` must be enabled to ensure that the ABI of the current target can be implemented correctly`` | Float ABI changed by a flag | Select the `eabi` or `eabihf` target that matches the linked C objects; do not toggle ABI features |
| `creating a shared reference to mutable static` (or `mutable reference`) | `static mut` under edition 2024 | Use an atomic, `critical_section::Mutex`, or framework resources |
| Duplicate panic implementation | Two panic provider crates | Inspect `cargo tree`; select one in the binary |
| `#[global_allocator]` missing | `alloc` is used with no allocator | Remove allocation or initialize one bounded heap |
| Link errors that name defmt symbols or sections | No `-Tdefmt.x`, or zero or two global loggers | Add the link argument; link exactly one logger in the binary |
| Linker reports region overflow | Code, statics, heap, or stack exceed layout | Inspect sections; reduce use or change only a verified memory budget |
| Firmware flashes but does not start | Wrong vector address, entry point, or reset setup | Check boot offset, vector contents, and runtime feature |
| Hard fault after enabling DMA | Buffer lifetime, alignment, cache, or region error | Stop DMA; inspect ownership and chip memory rules |
| Interrupt fires once | Pending flag is not cleared correctly | Read the peripheral sequence; clear only documented flags |
| Interrupt storm | Level source remains asserted or priority is wrong | Inspect source state and acknowledgement order |
| Async task stops progressing | Blocking call, lost wake, or exhausted task slot | Inspect executor trace and all bounded slots |
| Logs missing below `ERROR` | `DEFMT_LOG` not set for this build | Set `DEFMT_LOG` and rebuild; record it with the ELF |
| Logs corrupt or disappear | Wrong ELF, transport overflow, or reset during output | Match build identity and reduce bounded log volume |
| Host tests try to run firmware | Global embedded target or runner leaked into tests | Pass the host target explicitly or scope target config |
| Debug build works, release fails | Timing race, overflow, layout, or logging side effect | Test the release ELF and inspect optimization-sensitive sharing |

Do not weaken optimization, increase memory, or add delays as the final fix until
inspection identifies the violated invariant.

Apply these rules to every change. Each one prevents a silent, unsound, or
irreversible defect:

- Access memory-mapped registers only through the PAC or HAL, or with
  `core::ptr::read_volatile` and `write_volatile`. The compiler can elide or
  reorder a plain dereference.
- Run no Rust code before RAM initialization; static access there is undefined
  behavior. Write `__pre_init` in assembly (`global_asm!`), not `#[pre_init]`.
- Use `critical-section-single-core` (`cortex-m`) or `unsafe-assume-single-core`
  (`portable-atomic`) only on a single-core chip in privileged mode.
- Keep a DMA buffer alive, at a stable address, and untouched until the driver
  confirms the stop. A timeout, `select`, or dropped future does not stop DMA.
- Keep one memory-layout owner; two owners can silently select the wrong memory
  map. Do not add a `memory.x` copy in `build.rs` when the runtime or HAL has one.
- Do not treat a successful flash as proof that the image fits. The programmer
  can erase adjacent data before it notices an invalid layout.

## Verify with the check that proves the claim

Keep protocol parsing, state machines, unit conversion, filters, and retry
decisions independent of registers and global peripherals. Test that library on
the host. Replace a peripheral with a small trait fake only at the existing HAL
boundary; do not emulate the whole chip.

```bash
host_target="$(rustc -vV | sed -n 's/^host: //p')"
cargo test --locked -p <logic-crate> --lib --target "$host_target"
cargo check --locked --target <target> --no-default-features --features <chip-feature>
cargo build --locked --release --target <target> --bin <firmware>
```

Host tests prove logic only. They prove nothing about startup, registers,
timing, or interrupts. A clean target build proves that the image links inside
the declared regions; it does not prove stack or heap limits at run time. Do not
put a global `build.target` in a reusable workspace without a host-test command
like the one above: it can make `cargo test` try to execute firmware on the host.

Use `--all-features` only when the features are additive. When features select
a chip or runtime, check each supported feature set explicitly, and reject
invalid combinations with `compile_error!`.

When a library claims support for cores without compare-and-swap (CAS), add this
check to its gate even if the product ships on a CAS-capable core. Run
`rustup target add thumbv6m-none-eabi` first.

```bash
cargo check --locked -p <lib> --target thumbv6m-none-eabi --features portable-atomic/critical-section
```

The backend feature belongs to this command only, never to the library's
manifest. `cargo check` does not link, so it needs no `critical-section`
implementation. Without the flag, a library that needs CAS fails this check as
expected; do not fix that by adding a backend to its `Cargo.toml`.

Inspect the final ELF. These `cargo-binutils` wrappers need
`rustup component add llvm-tools`. If the workspace does not install them, use
the matching LLVM tools from the pinned toolchain; do not add tools only to make
command spelling uniform.

```bash
cargo size --release --target <target> --bin <firmware> -- -A
cargo objdump --release --target <target> --bin <firmware> -- -h
cargo nm --release --target <target> --bin <firmware> -- --size-sort
```

Install the probe tools with `cargo install probe-rs-tools --locked`. It provides
`probe-rs`, `cargo-flash`, and `cargo-embed`. Give `probe-rs` an explicit chip.
Do not rely on automatic chip detection in CI or production instructions.

```bash
probe-rs run --chip <chip> target/<target>/release/<firmware>
probe-rs attach --chip <chip> target/<target>/release/<firmware>
```

`probe-rs attach` does not reset or flash, so it preserves a running fault.

Add hardware-in-the-loop checks only for behavior that a host cannot prove:
startup, interrupt routing, clock accuracy, DMA, reset cause, watchdog action,
sleep and wake, flash update, and real peripheral timing. Give each check a
timeout and a recovery action so a failed board does not occupy CI forever.

## Completion checklist

For every change:

- Reusable logic compiles as `no_std`; host tests run on the host triple.
- The final binary owns one panic policy, one allocator if needed, one
  critical-section implementation, and one defmt logger if it logs.
- Interrupt, DMA, and task ownership are explicit and bounded.

For a firmware release, or a change to boot, memory layout, interrupts, DMA, or
panic policy, also complete the hardware items below. For a no_std library
change, host tests and a target build are the evidence. When no board or probe
is available, report each hardware item as not run.

- The exact chip, target, runtime, boot offset, and memory regions are recorded.
- Flash, RAM, stack, heap, queue, latency, and timing budgets have evidence.
- The release ELF is inspected, flashed, and run without a debugger attached.
  Its `DEFMT_LOG` value, if any, is recorded with it.
- Panic, watchdog, reset, queue-full, and transport-failure paths are exercised.
- Calibration values remain bounded knobs and have real-hardware measurements.

## Keep concurrency bounded

Use interrupt handlers only to acknowledge hardware and move bounded state.
Move parsing, formatting, allocation, and blocking I/O to task context.

For every interrupt-shared value, write down:

1. Which contexts read and write it.
2. Which operation makes access exclusive.
3. The maximum time that interrupts stay masked.
4. Which memory ordering or critical-section rule publishes the data.

Do not share state through `static mut`. Edition 2024 denies every reference to
it (`static_mut_refs`). `&raw mut` and by-value access still compile, but they
keep the data race with the interrupt handler. Use an atomic, a
`critical_section::Mutex<RefCell<T>>`, or the framework's resource model.

Read atomic support from `rustc --target <target> --print cfg | rg 'target_has_atomic='`.
`target_has_atomic="32"` means that 32-bit CAS exists. A target that prints no
`target_has_atomic="N"` line has no CAS. `target_has_atomic_primitive_alignment`
lines describe alignment, not atomic support. Stable `--print cfg` does not show
load and store support. On `thumbv6m-none-eabi` and
`riscv32imc-unknown-none-elf`, `AtomicU32::load` compiles and `fetch_add` fails
with E0599. On `armv4t-none-eabi`, `armv5te-none-eabi`, and `msp430-none-elf`,
the import of `core::sync::atomic::AtomicU32` fails with E0432. Do not assume
native atomic loads; compile a one-line probe on the target.

Use native atomics only when `--print cfg` lists the required width. On a
target without CAS, use `portable-atomic`, which also supplies the missing
atomic types. A library depends on it without a backend feature, and enables
`require-cas` when it cannot work without CAS. The final binary selects the
backend: `critical-section`, or `unsafe-assume-single-core`.

Let the final binary select exactly one `critical-section` implementation. On a
multi-core chip such as the RP2040, use the HAL's implementation. Do not create
a second interrupt-mask implementation in a driver.

Never hold a critical section across these operations:

- An `.await` point.
- A peripheral transaction that waits for hardware.
- Logging or formatting.
- A callback into unknown code.
- A loop with an input-dependent bound.

Model interrupt priority and preemption. Masking same-priority work is not proof
against a higher-priority interrupt. On a multi-core target, disabling local
interrupts is not a cross-core lock.

Treat DMA as concurrent access by hardware. Read
[references/dma.md](references/dma.md) when firmware starts, completes, or
cancels a DMA transfer; it holds the fence, cache, and cancellation rules.

## Put no_std at the correct boundary

Make reusable logic a library with `#![no_std]`. Keep the runtime, startup,
panic policy, and hardware singleton in the final binary. The block below is a
complete `lib.rs`:

```rust,ignore
#![no_std]
#![forbid(unsafe_code)]

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

Stay in `core` by default. Do not enable `alloc` because a dependency exposes
an allocation feature. First select a bounded container or pass caller-owned
storage. If allocation is required, define all of these facts:

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
debug = 2 # debug info stays in the ELF; it does not use flash
```

Provide exactly one panic implementation in the final dependency graph. Let a
debug crate provide it when it reports through the selected transport. Let a
production crate provide reset, safe shutdown, or a bounded fault record.
Libraries must not select the application panic policy.

Do not claim that a panic message is delivered until the same release artifact
reports it on the real transport. The logging path can fail after clocks,
interrupts, or memory become corrupt.

## Select the target and own startup

Inspect the current workspace:

```bash
rg -n '#!\[(no_std|no_main)\]|entry|interrupt|exception|global_allocator|panic_handler' --type rust
rg -n 'memory\.x|link\.x|runner|rustflags|build-std|panic\s*=' -g '*.toml' -g '*.json' -g '*.x'
cargo tree --edges normal,build
rustc --print target-list | rg '<architecture>|thumb|riscv'
```

Use a built-in target when it matches the CPU, ABI, floating-point mode, and
atomic support. Install it with `rustup target add <target>`. Then read
`rustc --target <target> --print cfg`: it is the source of truth for CAS
support, pointer width, endianness, and target features. Since Rust 1.95 a
custom JSON target spec needs a pinned nightly; add one only when no built-in
target fits.

Do not infer the memory map from a similar board. Account for a bootloader,
configuration pages, secure regions, and retained RAM explicitly.

Prefer the architecture runtime crate and its linker template. Supply the chip
memory regions in `memory.x` or the runtime's documented input. Do not copy the
runtime's full linker script into the application unless the shipped image has
a requirement that its extension points cannot express. Add linker `ASSERT`
expressions for stack, heap, and image boundaries when the runtime template
permits them.

Keep linker arguments and the runner on the final binary's exact target. A
library cannot reliably inject final-artifact layout for every consumer.

Read [references/board-bring-up.md](references/board-bring-up.md) when you bring
up a board, port to a new chip, need a custom target spec, make `memory.x`
visible to the linker, own a linker script, or configure the runner and link
arguments.

## Select the hardware and task model

Use `embedded-hal` 1.0 traits at reusable driver boundaries. Keep board pin
choices, clock setup, interrupts, and concrete HAL types in the application.
Apply these 1.0 rules
([migration guide](https://github.com/rust-embedded/embedded-hal/blob/master/docs/migrating-from-0.2-to-1.0.md)):

- A driver for a device with its own chip select takes `SpiDevice`. Do not take
  `SpiBus` plus a chip-select `OutputPin`: that driver breaks on a shared bus.
- Serial I/O uses the `embedded-io` traits.
- Async traits live in `embedded-hal-async`, and `nb` traits in
  `embedded-hal-nb`. Use async traits only when the caller already has a runtime.
- 0.2 paths such as `digital::v2` and `blocking::spi` do not exist in 1.0.

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

Read [references/task-frameworks.md](references/task-frameworks.md) when you
write, port, or review Embassy or RTIC code. It holds the static-slot,
time-driver, dispatcher, and interrupt-ownership rules, and the Embassy 0.10
API changes that break code copied from older examples.

## Budget every finite resource

Give each release an explicit budget, with evidence, for flash, static RAM,
stack, heap, queues, interrupt latency, CPU time, and energy. Read
[references/resource-budgets.md](references/resource-budgets.md) when you set or
review that budget; it lists the evidence for each resource and the Cortex-M
stack measurement.

Make a stack overflow fault instead of corrupting statics: link with
`flip-link` (LLD only), or enable the `cortex-m-rt` `set-msplim` feature on
Armv8-M Mainline.

Reject unbounded queues, recursive retry, and growth from input-controlled
lengths. Treat a queue full condition as a normal state. Choose drop-oldest,
drop-newest, backpressure, coalescing, or fail-safe behavior deliberately.

Keep physical calibration, such as clock tolerance, watchdog window, debounce
time, and sensor thresholds, as bounded configuration with safe defaults.
Record the real-hardware measurements that justify the values.

## Log from the device

Use `defmt` for bounded device logs when the target integration supports it.
Decode with the exact ELF from the same build: a log decoded with a different
ELF is invalid evidence. Do not log secrets, credentials, private identifiers,
or unbounded input. defmt emits only `ERROR` messages unless the compile-time
`DEFMT_LOG` value enables more; record that value with the ELF. A debug probe
that drains logs can hide a deadlock or timing failure that appears when the
device runs alone.

Read [references/defmt.md](references/defmt.md) when you add or change a defmt
logger, its transport, or the shipped log level.
