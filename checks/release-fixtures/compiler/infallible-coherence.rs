trait Marker {}
impl Marker for fn() -> ! {}
impl Marker for fn() -> std::convert::Infallible {}
fn main() {}
