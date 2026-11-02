// Probe: proves the planted defect. evals/outcome/check.py copies this file into the fixture's
// tests/ and requires it to fail there. The scaffold never copies it into an agent's workspace.
use ledger::{parse_amount, parse_rate_bps};

#[test]
fn amount_with_one_decimal() {
    assert_eq!(parse_amount("12.5"), Ok(1250));
}

#[test]
fn rate_with_one_decimal() {
    assert_eq!(parse_rate_bps("7.5"), Ok(750));
}
