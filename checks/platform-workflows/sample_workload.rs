//! A sampling fixture, not a product benchmark.
use std::hint::black_box;

#[unsafe(no_mangle)]
#[inline(never)]
pub fn sampled_hot(mut value: u64) -> u64 {
    for index in 0..20_000_u64 {
        value = value.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(index);
        if value & 255 == 0 {
            value = value.rotate_left(19);
        }
    }
    value
}

fn main() {
    let iterations: u64 = std::env::args().nth(1).expect("iteration count").parse().unwrap();
    let mut result = 1;
    for _ in 0..iterations {
        result = sampled_hot(black_box(result));
    }
    println!("{result}");
}
