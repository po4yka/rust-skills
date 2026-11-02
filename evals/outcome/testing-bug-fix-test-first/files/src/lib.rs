//! Parses money amounts, tax rates, and invoice lines from the billing CSV export.
//!
//! Amounts and rates are non-negative decimal strings such as `12.34`.

use std::fmt;
use std::str::FromStr;

/// Why a field could not be parsed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParseError {
    /// The field is empty or holds a character that is not a digit or one `.`.
    NotANumber(String),
    /// The field has more fraction digits than the unit allows.
    TooManyDecimals(String),
    /// An invoice line does not have exactly three comma-separated fields.
    WrongFieldCount(usize),
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotANumber(s) => write!(f, "not a number: {s:?}"),
            Self::TooManyDecimals(s) => write!(f, "too many decimals: {s:?}"),
            Self::WrongFieldCount(n) => write!(f, "expected 3 fields, found {n}"),
        }
    }
}

impl std::error::Error for ParseError {}

/// Parses a decimal string with at most `scale` fraction digits into minor units.
fn parse_fixed(s: &str, scale: u32) -> Result<u64, ParseError> {
    let (whole, frac) = s.split_once('.').unwrap_or((s, ""));
    if frac.len() > scale as usize {
        return Err(ParseError::TooManyDecimals(s.to_owned()));
    }
    let whole: u64 = whole.parse().map_err(|_| ParseError::NotANumber(s.to_owned()))?;
    let frac: u64 = if frac.is_empty() {
        0
    } else {
        frac.parse().map_err(|_| ParseError::NotANumber(s.to_owned()))?
    };
    Ok(whole * 10_u64.pow(scale) + frac)
}

/// Parses an amount in currency units into cents: `"12.34"` is 1234.
pub fn parse_amount(s: &str) -> Result<u64, ParseError> {
    parse_fixed(s, 2)
}

/// Parses a tax rate in percent into basis points: `"7.25"` is 725.
pub fn parse_rate_bps(s: &str) -> Result<u64, ParseError> {
    let (whole, frac) = s.split_once('.').unwrap_or((s, ""));
    if frac.len() > 2 {
        return Err(ParseError::TooManyDecimals(s.to_owned()));
    }
    let whole: u64 = whole.parse().map_err(|_| ParseError::NotANumber(s.to_owned()))?;
    let frac: u64 = if frac.is_empty() {
        0
    } else {
        frac.parse().map_err(|_| ParseError::NotANumber(s.to_owned()))?
    };
    Ok(whole * 100 + frac)
}

/// One line of the invoice export: `SKU,QUANTITY,UNIT_PRICE`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvoiceLine {
    pub sku: String,
    pub quantity: u32,
    pub unit_price_cents: u64,
}

impl InvoiceLine {
    /// Returns the line total in cents.
    pub fn total_cents(&self) -> u64 {
        u64::from(self.quantity) * self.unit_price_cents
    }
}

impl FromStr for InvoiceLine {
    type Err = ParseError;

    fn from_str(line: &str) -> Result<Self, Self::Err> {
        let fields: Vec<&str> = line.split(',').map(str::trim).collect();
        let [sku, quantity, price] = fields[..] else {
            return Err(ParseError::WrongFieldCount(fields.len()));
        };
        let quantity = quantity.parse().map_err(|_| ParseError::NotANumber(quantity.to_owned()))?;
        Ok(Self { sku: sku.to_owned(), quantity, unit_price_cents: parse_amount(price)? })
    }
}
