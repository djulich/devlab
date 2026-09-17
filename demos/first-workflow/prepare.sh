#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 /absolute/path/to/new-target" >&2
    exit 2
fi

target=$1
case "$target" in
    /*) ;;
    *)
        echo "target must be an absolute path: $target" >&2
        exit 2
        ;;
esac

if [ -e "$target" ]; then
    echo "refusing to replace existing target: $target" >&2
    exit 1
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p -- "$target"
cd -- "$target"

devlab init --template python
cp -- "$script_dir/system-spec.md" .devlab/specs/system/README.md
cp -- "$script_dir/agents.codex.toml" .devlab/config/agents.toml

marker=.devlab-first-workflow-demo
printf '%s\n' 'Created by DevLab demos/first-workflow/prepare.sh' > "$marker"
git add .devlab/specs/system/README.md .devlab/config/agents.toml "$marker"
git commit -m "Configure the DevLab first-workflow demo"

echo "Prepared first-workflow demo at $target"
