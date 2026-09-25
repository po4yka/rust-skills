# Release resource budget

Use this table when you set or review the release budget. Each resource needs
the evidence in the second column.

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

## Stack on Cortex-M

With `cortex-m-rt`, enable its `paint-stack` feature, run the worst-case load,
and read the stack high-water mark. Make a stack overflow fault instead of
corrupting statics: link with `flip-link` (LLD only), or enable the `set-msplim`
feature on Armv8-M Mainline (`thumbv8m.main-none-eabi*`).

## Calibration

Clock tolerance, oscillator startup, watchdog window, debounce time, ADC offset,
sensor threshold, and radio timing vary by board and environment. Keep each one
as configuration. Set a safe default, limit the accepted values, and record the
real-hardware measurements that justify them.
