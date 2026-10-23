# Security policy

## Reporting a vulnerability

Report security issues privately through GitHub's
[security advisories](https://github.com/Flexy01/frugalroute/security/advisories/new)
rather than a public issue. Please include the version, a minimal reproduction and
the impact you believe it has.

Expect an initial reply within a week.

## Key handling

`frugalroute` reads the API key from the environment variable named by
`api_key_env` in the config. The key is never written to disk, never included in
the JSONL call log, and never echoed in error messages.

The HTTP client refuses redirects instead of following them, because `urllib`
copies the `Authorization` header to the redirect target — following one could
send the key to a different host.

If you configure `log_path` inside a repository, keep it out of version control
(`*.jsonl` is already in `.gitignore`).
