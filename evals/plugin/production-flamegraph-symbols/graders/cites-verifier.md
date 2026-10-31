---
type: llm
---

PASS if the answer tells the user to profile a dedicated profiling profile that keeps debug symbols (for example `--profile profiling` with `debug = true` or line-table debug info and no stripping) and to check the binary with `readelf -S` or an equivalent section listing.
FAIL if the answer only says to use a debug build, or gives no way to confirm the binary carries symbols.
