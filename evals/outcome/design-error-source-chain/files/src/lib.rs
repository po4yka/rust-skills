//! Loads `key = value` configuration files.

use std::error::Error;
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// Why a configuration file could not be loaded.
#[derive(Debug)]
pub enum ConfigError {
    /// The file could not be read.
    Read { path: PathBuf, cause: io::Error },
    /// A line is not `key = value`.
    Parse { line: usize, reason: String },
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConfigError::Read { path, cause } => {
                write!(f, "cannot read {}: {cause}", path.display())
            }
            ConfigError::Parse { line, reason } => write!(f, "line {line}: {reason}"),
        }
    }
}

impl Error for ConfigError {}

/// Parses `key = value` lines. Blank lines and lines that start with `#` are skipped.
pub fn parse(text: &str) -> Result<Vec<(String, String)>, ConfigError> {
    let mut pairs = Vec::new();
    for (index, raw) in text.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            return Err(ConfigError::Parse { line: index + 1, reason: "expected `key = value`".into() });
        };
        pairs.push((key.trim().to_owned(), value.trim().to_owned()));
    }
    Ok(pairs)
}

/// Reads and parses the file at `path`.
pub fn load(path: &Path) -> Result<Vec<(String, String)>, ConfigError> {
    let text = fs::read_to_string(path)
        .map_err(|cause| ConfigError::Read { path: path.to_owned(), cause })?;
    parse(&text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_pairs_and_skips_comments() {
        let pairs = parse("# comment\nport = 8080\n\nhost = example.org\n").unwrap();
        assert_eq!(pairs, vec![("port".into(), "8080".into()), ("host".into(), "example.org".into())]);
    }

    #[test]
    fn reports_the_line_of_a_bad_entry() {
        let err = parse("port = 8080\nnonsense\n").unwrap_err();
        assert!(matches!(err, ConfigError::Parse { line: 2, .. }));
    }

    #[test]
    fn a_missing_file_is_a_read_error() {
        let err = load(Path::new("/nonexistent/config.conf")).unwrap_err();
        assert!(matches!(err, ConfigError::Read { .. }));
    }
}
