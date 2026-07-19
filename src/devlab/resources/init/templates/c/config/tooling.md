# Tooling Policy

## C

Use C11 or the version required by the specification. This starter uses checked-in
CMake presets as the stable workspace-root build interface; replace the profile
before planning dependent tasks when the repository uses Make, Meson, or another
build system. Enable useful compiler warnings and add focused tests. Do not
install compilers or build tools.

Ignore configured build directories, object files, binaries, and test output.
