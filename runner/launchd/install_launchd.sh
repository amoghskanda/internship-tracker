#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
python_bin=${PYTHON_BIN:-"$(command -v python3)"}
config_path=${INTERNSHIP_RUNNER_CONFIG:-"$repo_dir/config.json"}
label=com.internship-runner.scheduler
user_home=${HOME:?HOME must be set}
launch_agents_dir="$user_home/Library/LaunchAgents"
plist_path="$launch_agents_dir/$label.plist"
log_dir="$repo_dir/data/logs"

usage() {
    printf '%s\n' "Usage: $0 install|uninstall|print"
    printf '%s\n' "Set PYTHON_BIN or INTERNSHIP_RUNNER_CONFIG to override defaults."
}

case "${1:-}" in
    install)
        mkdir -p "$launch_agents_dir" "$log_dir"
        python3 - "$script_dir/com.internship-runner.scheduler.plist.template" "$plist_path" "$repo_dir" "$python_bin" "$config_path" "$log_dir" <<'PY'
import plistlib
import sys
from pathlib import Path

template_path, output_path, repo_dir, python_bin, config_path, log_dir = sys.argv[1:]
with Path(template_path).open("rb") as handle:
    plist = plistlib.loads(handle.read())
arguments = plist["ProgramArguments"]
plist["ProgramArguments"] = [
    python_bin if item == "__PYTHON_BIN__" else
    config_path if item == "__CONFIG_PATH__" else item
    for item in arguments
]
plist["WorkingDirectory"] = repo_dir
plist["StandardOutPath"] = str(Path(log_dir) / "scheduler.stdout.log")
plist["StandardErrorPath"] = str(Path(log_dir) / "scheduler.stderr.log")
with Path(output_path).open("wb") as handle:
    plistlib.dump(plist, handle, sort_keys=False)
PY
        launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
        launchctl bootstrap "gui/$(id -u)" "$plist_path"
        printf '%s\n' "Installed $label. It runs one tick every 60 seconds."
        printf '%s\n' "Logs: $log_dir"
        ;;
    uninstall)
        if [ -f "$plist_path" ]; then
            launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
            rm -f "$plist_path"
            printf '%s\n' "Removed $label."
        else
            printf '%s\n' "$label is not installed."
        fi
        ;;
    print)
        printf '%s\n' "repo: $repo_dir"
        printf '%s\n' "python: $python_bin"
        printf '%s\n' "config: $config_path"
        printf '%s\n' "plist: $plist_path"
        ;;
    *)
        usage
        exit 2
        ;;
esac
