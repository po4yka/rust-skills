//! Detects configuration file formats from file names.

use std::path::Path;

/// A configuration file format.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Format {
    /// JSON, `.json`.
    Json,
    /// TOML, `.toml`.
    Toml,
}

impl Format {
    /// Returns the usual file extension, without the dot.
    pub fn extension(self) -> &'static str {
        match self {
            Self::Json => "json",
            Self::Toml => "toml",
        }
    }

    /// Returns the format for a file extension, without the dot.
    pub fn from_extension(ext: &str) -> Option<Self> {
        match ext {
            "json" => Some(Self::Json),
            "toml" => Some(Self::Toml),
            _ => None,
        }
    }
}

/// Returns the format of the file at `path`, from its extension.
pub fn detect(path: &Path) -> Option<Format> {
    Format::from_extension(path.extension()?.to_str()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_by_extension() {
        assert_eq!(detect(Path::new("app/config.toml")), Some(Format::Toml));
        assert_eq!(detect(Path::new("package.json")), Some(Format::Json));
        assert_eq!(detect(Path::new("README")), None);
    }

    #[test]
    fn extension_round_trips() {
        for format in [Format::Json, Format::Toml] {
            assert_eq!(Format::from_extension(format.extension()), Some(format));
        }
    }
}
