# Handle ownership: header and Swift owner

Deep material for `rust-swift-ffi`, "Use one opaque type per handle kind". SKILL.md holds the
rules; this file holds the declarations.

## One incomplete C type per handle kind

```c
typedef struct rs_engine rs_engine_t;
typedef struct rs_job rs_job_t;
typedef struct rs_error rs_error_t; /* not a handle: complete struct below */

rs_engine_t * _Nullable rs_engine_create(rs_error_t * _Nonnull error_out);
void rs_engine_release(rs_engine_t * _Nullable engine);
```

## The Swift owner releases once

```swift
nonisolated final class Engine {
    private let raw: OpaquePointer

    init() throws {
        var error = rs_error_t()
        guard let raw = rs_engine_create(&error) else {
            throw EngineError(taking: &error)
        }
        self.raw = raw
    }

    deinit {
        rs_engine_release(raw)
    }
}
```
