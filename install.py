#!/usr/bin/env python3
"""Install a reviewed local plugin copy; preserve an existing copy as a backup."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def copy_package(source, staging):
    """Copy only reviewed package files, never local data or linked inputs."""
    files = [
        "manifest.json", "Service.qml", "BarWidget.qml", "Panel.qml",
        "Chart.qml", "MetricCard.qml", "WatchFace.qml", "WatchIcon.qml", "ActivityIcon.qml", "StressChart.qml", "Model.js", "Grafana.js", "backend.py",
        "README.md", "LICENSE", "install.py",
    ]
    if source.is_symlink() or (source / "docs").is_symlink():
        raise ValueError("Refusing to copy a symlinked package directory.")
    for name in ("docs/SETUP.md", "docs/PUBLISHING.md", "docs/REFERENCE.md"):
        path = source / name
        if path.is_symlink():
            raise ValueError(f"Refusing to copy a symlinked package file: {name}")
        if path.exists():
            files.append(name)
    for name in files:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Package file must be a regular, non-symlink file: {name}")
    staging.mkdir()
    for name in files:
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)


def main():
    source = Path(__file__).resolve().parent
    plugin_id = json.loads((source / "manifest.json").read_text())["id"]
    config = Path.home() / ".config/omarchy"
    plugins = config / "plugins"
    destination = plugins / plugin_id
    if source == destination.resolve():
        raise SystemExit("Refusing to install over the source directory; run install.py from a separate checkout.")
    if destination.is_symlink():
        raise SystemExit("Refusing to replace a symlinked plugin.")
    subprocess.run(["omarchy", "plugin", "validate", str(source)], check=True)
    plugins.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        manifest = destination / "manifest.json"
        if not manifest.is_file() or json.loads(manifest.read_text()).get("id") != plugin_id:
            raise SystemExit("Existing directory is not this plugin; left untouched.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with tempfile.TemporaryDirectory(prefix=".garmin-install-", dir=config) as temporary:
        staging = Path(temporary) / plugin_id
        copy_package(source, staging)
        subprocess.run(["omarchy", "plugin", "validate", str(staging)], check=True)
        if destination.exists():
            backups = config / "plugin-backups"
            backups.mkdir(exist_ok=True)
            os.rename(destination, backups / (plugin_id + "-" + stamp))
        os.rename(staging, destination)
    shell_config = config / "shell.json"
    if shell_config.exists():
        shutil.copy2(shell_config, config / ("shell.json.before-garmin-" + stamp))
    subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
    deadline = time.monotonic() + 10
    while True:
        listing = subprocess.run(["omarchy-shell", "shell", "listPlugins"], capture_output=True, text=True, check=True, timeout=3)
        if any(entry.get("id") == plugin_id for entry in json.loads(listing.stdout)):
            break
        if time.monotonic() >= deadline:
            raise SystemExit("Plugin copied, but discovery timed out. Rescan and enable it manually.")
        time.sleep(0.2)
    subprocess.run(["omarchy", "plugin", "enable", plugin_id], check=True)
    print("Installed Garmin Glance 1.0.0. Click the Garmin metric in the bar.")
    print("When updating an already loaded version, run: omarchy restart shell")


if __name__ == "__main__":
    main()
