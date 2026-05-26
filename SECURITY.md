# Security Policy

## Supported Versions

Security fixes are handled for the latest tagged release and the
`main` branch.

| Version | Supported |
|---|---|
| 1.x | Yes |
| < 1.0 | No |

## Reporting a Vulnerability

Please do not open a public issue for a suspected vulnerability.
Use GitHub's private vulnerability reporting flow for this repository
when available, or contact the maintainer through the repository owner
profile with enough detail to reproduce the issue.

Useful reports include:

- affected version or commit;
- a minimal reproducer;
- expected impact;
- whether credentials, private maps, robot logs, or network services
  are involved.

The project has no hosted service component. Most security issues are
therefore expected to be dependency, file parsing, CLI, or optional
HTTP scheduler transport issues.
