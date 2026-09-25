# Termination and signals

Read this when you implement or change Ctrl-C, `SIGTERM`, or `SIGHUP` handling.

## Signals per platform

On Unix, consider `SIGINT` and `SIGTERM`. Review `SIGHUP` separately because a
daemon and an interactive CLI can assign it different meaning. On Windows,
handle the console Ctrl-C event through the selected cross-platform facility.
Do not assume that every Unix signal exists on Windows.

## Shutdown sequence

Use this sequence:

1. The first termination request stops admission of new work.
2. Notify owned tasks through the existing cancellation mechanism.
3. Stop progress rendering and keep stderr available for the final diagnostic.
4. Let the current atomic output either complete or discard its temporary file.
5. Drain owned work for one finite grace period.
6. Return the documented cancellation status if shutdown completes.
7. On a second interrupt or grace expiry, use the product's forced-exit policy.

## Durability after a crash

State which file and directory sync operations the supported filesystem needs,
and test the failure states that the platform can reproduce. The sync steps of
the commit transaction are in [`atomic-output.md`](atomic-output.md).
