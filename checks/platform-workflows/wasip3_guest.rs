//! The WASI 0.3 host services the async clock wait and filesystem operation.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let start = std::time::Instant::now();
    std::thread::sleep(std::time::Duration::from_millis(25));
    assert!(start.elapsed() >= std::time::Duration::from_millis(25));
    println!("async clock wait completed");
    let data = std::fs::read_to_string("/fixture/input.txt")?;
    assert_eq!(data, "capability granted\n");
    println!("file capability granted");
    Ok(())
}
