fn value<T: Default>() -> Result<T, ()> { Ok(T::default()) }
fn exercise() -> Result<(), ()> {
    #[cfg(not(explicit))]
    value()?;
    #[cfg(explicit)]
    value::<()>()?;
    Ok(())
}
fn main() { assert_eq!(exercise(), Ok(())); }
