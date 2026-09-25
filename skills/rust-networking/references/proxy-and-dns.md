# Proxy and DNS

## Proxy

Resolve proxy policy once per request destination. Parse `NO_PROXY` with a maintained
implementation, not a home-grown suffix matcher.

Never log proxy credentials. Keep origin credentials and proxy credentials in separate
configuration. Send `Proxy-Authorization` only to the proxy. Do not reuse origin `Authorization` or
cookies as proxy authentication. For HTTPS through `CONNECT`, send origin headers and client
certificates only inside the verified end-to-end TLS tunnel. A plaintext forward proxy can inspect
origin requests, so do not send secrets through it unless the product policy accepts that trust
boundary.

## DNS

Apply DNS changes to new connections. Do not assume that an existing pooled connection follows a
changed DNS record. Bound the DNS cache by the resolver TTL or by a shorter product cap. Do not
cache a failure forever. Keep all returned addresses and use the IPv6 and IPv4 fallback strategy
of the stack. Do not select the first address permanently.

## Sources

- [RFC 8305](https://www.rfc-editor.org/rfc/rfc8305.html): Happy Eyeballs, IPv6 and IPv4 racing.
