//! Detects configuration file formats from file names.

use std::path::Path;

/// A configuration file format.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Format {
    /// JSON, `.json`.
    Json,
    /// TOML, `.toml`.
    Toml,
    /// YAML, `.yaml` or `.yml`.
    Yaml,
}

impl Format {
    /// Every supported format, in a stable order.
    pub const ALL: [Format; 3] = [Format::Json, Format::Toml, Format::Yaml];

    /// Returns the usual file extension, without the dot.
    pub fn extension(self) -> &'static str {
        match self {
            Self::Json => "json",
            Self::Toml => "toml",
            Self::Yaml => "yaml",
        }
    }

    /// Returns the format for a file extension, without the dot. The match ignores ASCII case.
    pub fn from_extension(ext: &str) -> Option<Self> {
        match ext.to_ascii_lowercase().as_str() {
            "json" => Some(Self::Json),
            "toml" => Some(Self::Toml),
            "yaml" | "yml" => Some(Self::Yaml),
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
        assert_eq!(detect(Path::new("deploy.yml")), Some(Format::Yaml));
        assert_eq!(detect(Path::new("README")), None);
    }

    #[test]
    fn detection_ignores_ascii_case() {
        assert_eq!(detect(Path::new("CONFIG.TOML")), Some(Format::Toml));
    }

    #[test]
    fn extension_round_trips() {
        for format in Format::ALL {
            assert_eq!(Format::from_extension(format.extension()), Some(format));
        }
    }
}
