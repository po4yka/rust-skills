fn unwrap(result: Result<u32, !>) -> u32 {
    let Ok(value) = result;
    value
}
fn main() {
    let result: Result<u32, std::convert::Infallible> = Ok(42);
    assert_eq!(unwrap(result), 42);
}
