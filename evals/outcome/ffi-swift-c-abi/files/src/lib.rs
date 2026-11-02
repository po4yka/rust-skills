//! The C ABI that the iOS app calls through `include/tally.h`.
//!
//! A tally is a named counter. Swift creates one, adds to it, reads its name, and frees it.

use std::ffi::{CStr, CString, c_char};

/// A named counter. Swift sees only an opaque pointer to it.
#[derive(Debug)]
pub struct Tally {
    name: String,
    count: u64,
}

/// Creates a tally. `name` is a NUL-terminated UTF-8 string.
#[unsafe(no_mangle)]
pub extern "C" fn tally_new(name: *const c_char) -> *mut Tally {
    let name = unsafe { CStr::from_ptr(name) }.to_str().unwrap().to_owned();
    Box::into_raw(Box::new(Tally { name, count: 0 }))
}

/// Adds `n` and returns the new count.
#[unsafe(no_mangle)]
pub extern "C" fn tally_add(tally: *mut Tally, n: u64) -> u64 {
    let tally = unsafe { &mut *tally };
    tally.count = tally.count.checked_add(n).expect("tally overflow");
    tally.count
}

/// Returns the name of the tally.
#[unsafe(no_mangle)]
pub extern "C" fn tally_name(tally: *const Tally) -> *const c_char {
    let tally = unsafe { &*tally };
    CString::new(tally.name.clone()).unwrap().as_ptr()
}

/// Frees a tally.
#[unsafe(no_mangle)]
pub extern "C" fn tally_free(tally: *mut Tally) {
    unsafe { drop(Box::from_raw(tally)) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counts_up() {
        let tally = tally_new(c"visits".as_ptr());
        assert_eq!(tally_add(tally, 2), 2);
        assert_eq!(tally_add(tally, 3), 5);
        tally_free(tally);
    }
}
