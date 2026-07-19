# Tooling Policy

## Rust

Use stable Rust and Cargo workspace conventions. Format with rustfmt, lint with
Clippy, and test through Cargo. Prefer explicit feature coverage and keep unsafe
code isolated and justified. Do not install or update the host toolchain.

Ignore `target/` and other generated artifacts. Keep `Cargo.lock` for binaries
and applications; follow the repository's documented policy for libraries.
