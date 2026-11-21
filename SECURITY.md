# Security policy

saleVault is a local, single-user application. Its server binds to `127.0.0.1` and has no authentication by design, so do not expose it to a network. It answers only to the host names `localhost` and `127.0.0.1` and refuses writes sent from other websites. The UI is served with a strict Content-Security-Policy for scripts.

## Supported versions

Only the latest `main` is supported.

## Reporting a vulnerability

Please report security issues privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for them. You will get an answer as soon as possible.
