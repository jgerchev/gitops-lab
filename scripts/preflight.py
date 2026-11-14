#!/usr/bin/env python3
"""Read-only, bounded host evidence collector. Run on the virtualization host.

Output can contain local addresses and service names: keep raw evidence private.
"""
import argparse
import datetime
import json
import subprocess
from pathlib import Path


def collect(argv, timeout=30):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {"command": argv, "exit": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": argv, "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    if not 2 <= args.samples <= 300:
        parser.error("samples must be between 2 and 300")
    commands = [
        ["free", "-h"], ["vmstat", "1", str(args.samples)], ["df", "-h", "/"],
        ["docker", "stats", "--no-stream"],
        ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
        ["ip", "-4", "route", "show", "table", "all"],
        ["virsh", "-c", "qemu:///system", "list", "--all"],
        ["virsh", "-c", "qemu:///system", "net-list", "--all"],
        ["virsh", "-c", "qemu:///system", "pool-list", "--all"],
        ["ollama", "ps"],
    ]
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            meminfo[key + "_KiB"] = int(value.split()[0])
    print(json.dumps({
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "memory": meminfo,
        "results": [collect(command, args.samples + 30) for command in commands],
        "interpretation": "Ignore first vmstat row for current rates. Historical swap occupancy alone does not establish thrashing. Peak-load capacity is not proven by an idle sample.",
    }, indent=2))


if __name__ == "__main__":
    main()
