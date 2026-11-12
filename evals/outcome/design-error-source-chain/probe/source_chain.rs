// Probe: proves the planted defect. evals/outcome/check.py copies this file into the fixture's
// tests/ and requires it to fail there. The scaffold never copies it into an agent's workspace.
use std::error::Error;
use std::io;
use std::path::Path;

use config_loader::load;

#[test]
fn a_read_error_keeps_its_io_cause_in_the_source_chain() {
    let err = load(Path::new("/nonexistent/config.conf")).unwrap_err();
    let cause = err.source().expect("the io::Error must be reachable through Error::source");
    let io = cause.downcast_ref::<io::Error>().expect("the source must be the io::Error");
    assert_eq!(io.kind(), io::ErrorKind::NotFound);
}

#[test]
fn the_message_does_not_repeat_its_source() {
    let err = load(Path::new("/nonexistent/config.conf")).unwrap_err();
    let cause = err.source().map(ToString::to_string).unwrap_or_default();
    assert!(
        cause.is_empty() || !err.to_string().contains(&cause),
        "a chain printer would show the cause twice: {err}"
    );
}
