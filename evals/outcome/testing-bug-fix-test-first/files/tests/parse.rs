use ledger::{InvoiceLine, ParseError, parse_amount, parse_rate_bps};

#[test]
fn amount_with_two_decimals() {
    assert_eq!(parse_amount("12.34"), Ok(1234));
}

#[test]
fn amount_without_decimals() {
    assert_eq!(parse_amount("12"), Ok(1200));
}

#[test]
fn amount_with_three_decimals_is_rejected() {
    assert_eq!(parse_amount("1.005"), Err(ParseError::TooManyDecimals("1.005".to_owned())));
}

#[test]
fn rate_with_two_decimals() {
    assert_eq!(parse_rate_bps("7.25"), Ok(725));
}

#[test]
fn invoice_line_total() {
    let line: InvoiceLine = "WIDGET, 3, 2.50".parse().expect("valid line");
    assert_eq!(line.total_cents(), 750);
}

#[test]
fn invoice_line_with_missing_field() {
    assert_eq!("WIDGET,3".parse::<InvoiceLine>(), Err(ParseError::WrongFieldCount(2)));
}
