# Safe network diagnostics

The field vocabulary behind "Emit safe network diagnostics" in `SKILL.md`.

## Emit safe network diagnostics

Record bounded, low-cardinality fields: route template or operation name (not
the full URL), method, attempt number, retry reason class, timeout phase,
elapsed bucket, status class, bytes sent and received, TLS version, certificate
error class, pool reuse, DNS result count, and a proxy-used boolean.

Do not record URL queries, raw paths with identifiers, headers, cookies,
tokens, certificate contents, body fragments, proxy credentials, or peer error
text that can echo those values. Do not put the remote address into a metric
label. Use `rust-observability`, when it is installed, to implement redaction and
cardinality gates.
