#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 /absolute/path/to/disposable-target" >&2
    exit 2
fi

target=${1%/}
case "$target" in
    /tmp/* | /private/tmp/*) ;;
    *)
        echo "refusing to remove a target outside /tmp: $target" >&2
        exit 1
        ;;
esac

target=$(CDPATH= cd -- "$target" 2>/dev/null && pwd -P) || {
    echo "target is not an accessible directory: $target" >&2
    exit 1
}
case "$target" in
    /tmp/* | /private/tmp/*) ;;
    *)
        echo "refusing to remove a target resolving outside /tmp: $target" >&2
        exit 1
        ;;
esac

marker=$target/.devlab-first-workflow-demo
expected='Created by DevLab demos/first-workflow/prepare.sh'
if [ ! -f "$marker" ] || [ "$(sed -n '1p' "$marker")" != "$expected" ]; then
    echo "refusing to remove an unmarked target: $target" >&2
    exit 1
fi

repo_root=$(git -C "$target" rev-parse --show-toplevel 2>/dev/null || true)
if [ "$repo_root" != "$target" ]; then
    echo "refusing to remove target with unexpected Git root: $target" >&2
    exit 1
fi

rm -rf -- "$target"
echo "Removed disposable first-workflow demo at $target"
