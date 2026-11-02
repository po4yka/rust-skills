//! Header-name helpers on the request path of the proxy.

/// Normalizes an HTTP header name: trims ASCII whitespace and lowercases ASCII letters.
pub fn normalize_name(name: &str) -> String {
    name.trim_ascii().to_ascii_lowercase()
}

/// Returns true if `headers` has a header whose normalized name equals the normalized `wanted`.
pub fn has_header(headers: &[(&str, &str)], wanted: &str) -> bool {
    let wanted = normalize_name(wanted);
    headers.iter().any(|(name, _)| normalize_name(name) == wanted)
}

/// Returns the value of the first `content-length` header, if it parses as a number.
pub fn content_length(headers: &[(&str, &str)]) -> Option<u64> {
    headers
        .iter()
        .find(|(name, _)| normalize_name(name) == "content-length")
        .and_then(|(_, value)| value.trim_ascii().parse().ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    const HEADERS: &[(&str, &str)] =
        &[("host", "example.org"), (" Content-Length ", "42"), ("accept", "*/*")];

    #[test]
    fn normalizes_case_and_whitespace() {
        assert_eq!(normalize_name(" Content-Type\t"), "content-type");
        assert_eq!(normalize_name("accept"), "accept");
        assert_eq!(normalize_name(""), "");
    }

    #[test]
    fn finds_a_header_in_any_case() {
        assert!(has_header(HEADERS, "HOST"));
        assert!(has_header(HEADERS, "content-length"));
        assert!(!has_header(HEADERS, "cookie"));
    }

    #[test]
    fn reads_content_length() {
        assert_eq!(content_length(HEADERS), Some(42));
        assert_eq!(content_length(&[("content-length", "x")]), None);
    }
}
