# Tooling Policy

## Go

Use the repository's declared Go version and standard module conventions.
Format source with gofmt, analyze it with go vet, and test packages with `go
test`. Do not install or update the host Go toolchain.

Keep generated binaries, coverage output, caches, and vendored dependencies out
of Git unless the project explicitly requires them.
