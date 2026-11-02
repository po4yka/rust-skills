// Probe: proves the planted defect. evals/outcome/check.py copies this file into the fixture's
// tests/ and requires it to fail there. The scaffold never copies it into an agent's workspace.
// The counter is per thread, so allocations of the test harness on other threads do not count.
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

struct Counting;

thread_local! {
    static ALLOCS: Cell<usize> = const { Cell::new(0) };
}

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCS.with(|n| n.set(n.get() + 1));
        // SAFETY: the caller upholds the GlobalAlloc contract for `layout`.
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        // SAFETY: `ptr` came from `System.alloc` with the same `layout`.
        unsafe { System.dealloc(ptr, layout) }
    }
}

#[global_allocator]
static GLOBAL: Counting = Counting;

#[test]
fn a_normalized_header_set_costs_no_allocation() {
    let headers: &[(&str, &str)] = &[("host", "example.org"), ("content-length", "42")];
    let before = ALLOCS.with(Cell::get);
    let found = headers::has_header(headers, "content-length");
    let length = headers::content_length(headers);
    let after = ALLOCS.with(Cell::get);
    assert!(found);
    assert_eq!(length, Some(42));
    assert_eq!(after - before, 0, "allocations on already-normalized names");
}
