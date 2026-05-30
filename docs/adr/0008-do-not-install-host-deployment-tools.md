# Do not install host deployment tools

DevLab may invoke target-owned deployment verification commands, including commands that use tools such as Podman, Docker, kind, kubectl, rpmbuild, or systemd-analyze. If required tools are missing, DevLab reports actionable diagnostics and leaves the related deployment claim unverified.

DevLab must not install host deployment tools automatically. Host tool installation is outside the target workspace, platform-specific, often privileged, and can change daemon, network, credential, or security state.

A future explicit, user-approved setup mode may model host provisioning, but it must not be inferred from deployment specs or profile validation commands.
