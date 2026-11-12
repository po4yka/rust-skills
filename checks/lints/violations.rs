//! One deliberate violation for each lint that the strict `[workspace.lints]` template of the
//! `rust-lints` skill names. `checks/lint_gate.py` builds this file with that template and the
//! skill's `clippy.toml`, and requires each lint to report on the line that carries its marker
//! comment. Nothing here is an example to copy.

use std::collections::HashMap; // expect: disallowed_types

mod inner {
    pub fn not_reexported() {} // expect: unreachable_pub
}

/// Gate item.
pub fn reach() { inner::not_reexported(); }

/// Gate item.
pub fn undocumented_neighbor() {}

pub fn no_docs() {} // expect: missing_docs

/// Gate item.
pub struct Holder<'a> { // expect: exhaustive_structs
    /// Gate item.
    pub text: &'a str,
}

/// Gate item.
pub enum Choice { // expect: exhaustive_enums
    /// Gate item.
    A,
    /// Gate item.
    B,
}

/// Gate item.
#[must_use]
pub fn unused_lifetime<'a, 'b>(x: &'a str) -> &'a str { x } // expect: unused_lifetimes

/// Gate item.
pub fn elided(f: &mut std::fmt::Formatter) -> std::fmt::Result { f.write_str("x") } // expect: elided_lifetimes_in_paths

struct Guard;
impl Drop for Guard {
    fn drop(&mut self) {}
}

/// Gate item.
pub fn drops() {
    let _ = Guard; // expect: let_underscore_drop
    let g = Guard;
    drop(&g); // expect: dropping_references
}

/// Gate item.
pub fn forever(n: u32) -> u32 { forever(n) } // expect: unconditional_recursion

/// Gate item.
pub fn naïve() {} // expect: non_ascii_idents

/// Gate item.
#[must_use]
pub fn trivial(x: u32) -> u32 { x as u32 } // expect: trivial_numeric_casts

#[must_use]
fn must() -> u32 { 1 }

/// Gate item.
pub fn ignores() { must(); } // expect: unused_must_use

/// # Safety
/// `p` points to a readable byte.
pub unsafe fn raw(p: *const u8) -> u8 { *p } // expect: unsafe_op_in_unsafe_fn

/// Gate item.
pub unsafe fn no_safety_doc() {} // expect: missing_safety_doc

/// Gate item.
pub fn unsafe_blocks(p: &u8) -> u8 {
    let q: *const u8 = p;
    let a = unsafe { *q }; // expect: undocumented_unsafe_blocks
    // SAFETY: q comes from a reference.
    let b = unsafe { *q.add(0) + *q }; // expect: multiple_unsafe_ops_per_block
    a + b
}

/// Gate item.
pub fn forget(v: Vec<u8>) { std::mem::forget(v) } // expect: disallowed_methods

/// Gate item.
pub fn may_panic(v: Option<u8>) -> u8 { v.unwrap() } // expect: unwrap_used, missing_panics_doc

/// Gate item.
pub fn may_fail(s: &str) -> Result<u8, std::num::ParseIntError> { s.parse() } // expect: missing_errors_doc

/// Gate item.
pub fn explicit_panic() { panic!("gate") } // expect: panic

/// Gate item.
pub fn later() { todo!() } // expect: todo

/// Gate item.
pub fn never() { unimplemented!() } // expect: unimplemented

/// Gate item.
pub fn debug(x: u8) -> u8 { dbg!(x) } // expect: dbg_macro

/// Gate item.
pub fn print() { println!("gate"); } // expect: print_stdout

/// Gate item.
pub fn quit() { std::process::exit(1) } // expect: exit

/// Gate item.
pub fn big_array() -> usize { let a = [0u8; 600_000]; a.len() } // expect: large_stack_arrays, large_stack_frames

/// Gate item.
pub async fn big_future() { let a = [0u8; 20_000]; ready().await; drop(a); }

async fn ready() {}

/// Gate item.
pub async fn awaits_big() { big_future().await; } // expect: large_futures

/// Gate item.
pub enum Uneven { // expect: exhaustive_enums, large_enum_variant
    /// Gate item.
    Small(u8),
    /// Gate item.
    Large([u8; 1000]),
}

/// Gate item.
/// # Errors
/// Always.
pub fn large_err() -> Result<(), [u8; 256]> { Err([0; 256]) } // expect: result_large_err

/// Gate item.
#[must_use]
pub fn to_owned_str(s: &str) -> String { s.to_string() } // expect: str_to_string

/// Gate item.
#[must_use]
pub fn implicit(a: &[u8]) -> Vec<u8> { let v = a.to_vec(); v.to_vec() } // expect: implicit_clone

/// Gate item.
pub fn assigns(a: &mut String, b: &String) { *a = b.clone(); } // expect: assigning_clones, ptr_arg

/// Gate item.
#[must_use]
pub fn redundant(s: String) -> usize { let t = s.clone(); t.len() } // expect: redundant_clone, needless_pass_by_value

/// Gate item.
#[must_use]
pub fn or_call(v: Option<String>) -> String { v.unwrap_or(String::from("x")) } // expect: or_fun_call

/// Gate item.
#[must_use]
pub fn lazy(v: Option<u8>) -> u8 { v.unwrap_or_else(|| 0) } // expect: unnecessary_lazy_evaluations

/// Gate item.
#[must_use]
pub fn collects(v: &[u8]) -> usize { v.iter().collect::<Vec<_>>().len() } // expect: needless_collect

/// Gate item.
#[must_use]
pub(crate) fn ref_opt(v: &Option<u8>) -> bool { v.is_some() } // expect: ref_option

/// Gate item.
#[must_use]
pub(crate) fn by_ref(x: &u8) -> u8 { *x } // expect: trivially_copy_pass_by_ref

/// Gate item.
#[must_use]
pub fn closures(v: &[u8]) -> Vec<String> { v.iter().map(|x| x.to_string()).collect() } // expect: redundant_closure_for_method_calls

/// Gate item.
#[must_use]
pub fn nested(a: bool, b: bool) -> u8 { if a { if b { return 1; } } 0 } // expect: collapsible_if

/// Gate item.
#[must_use]
pub fn format_arg(x: u8) -> String { format!("{}", x) } // expect: uninlined_format_args

/// Gate item.
#[allow(dead_code)] // expect: allow_attributes, allow_attributes_without_reason
pub fn allowed() {}

/// Gate item.
#[must_use]
pub fn index(v: &[u8]) -> u8 { v[3] } // expect: indexing_slicing

/// Gate item.
#[must_use]
pub fn divide(a: u32, b: u32) -> u32 { a / b } // expect: integer_division

/// Gate item.
#[must_use]
pub fn add(a: u32, b: u32) -> u32 { a + b } // expect: arithmetic_side_effects

/// Gate item.
#[must_use]
pub fn modulo(a: i32, b: i32) -> i32 { a % b } // expect: modulo_arithmetic

/// Gate item.
/// # Errors
/// Never.
pub fn in_result(s: &str) -> Result<u8, String> { Ok(s.parse::<u8>().expect("number")) } // expect: unwrap_in_result

/// Gate item.
#[must_use]
pub fn map_len(m: &HashMap<u8, u8>) -> usize { m.len() }
