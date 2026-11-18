# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

Please do not open a public issue for security problems. Email **frankoduro1912@gmail.com** with a description, reproduction steps and the affected version.

Expected response: acknowledgement within 5 business days, and a status update within 14 days. Please allow time for a coordinated fix before publishing exploit details.

## Scope

In scope: path policy bypass, staging of unowned files, secret leakage into commits, logs or reports, command injection, lock bypass, ledger corruption that hides history.

Out of scope: vulnerabilities in code of repositories that Pulse is pointed at, or in third party tools that a user configures as task commands.

## Hardening defaults

Commit and push are disabled, network access is denied, deletion is disabled, subprocesses use argument arrays with `shell=False`, and credentials in remote URLs are redacted from all output.
