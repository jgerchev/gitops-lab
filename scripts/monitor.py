#!/usr/bin/env python3
"""Bounded host swap monitor; gracefully stop ONLY gitops-lab on pressure.

Five consecutive current vmstat samples with swap I/O count as sustained
activity. Historical swap occupancy and vmstat's since-boot row are ignored.
Run on the virtualization host. Keep raw output outside the public checkout.
"""
import argparse
import datetime
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 1800:
        parser.error("seconds must be 10..1800")
    process = subprocess.Popen(["vmstat", "-w", "1", str(args.seconds + 1)],
                               stdout=subprocess.PIPE, text=True)
    first = True
    consecutive = 0
    try:
        for line in process.stdout:
            fields = line.split()
            print(datetime.datetime.now(datetime.timezone.utc).isoformat(), line.rstrip(), flush=True)
            if len(fields) < 10 or not fields[0].isdigit():
                continue
            if first:
                first = False
                continue
            si, so = int(fields[6]), int(fields[7])
            consecutive = consecutive + 1 if si or so else 0
            if consecutive >= 5:
                print("SAFETY STOP: sustained swap I/O; requesting graceful lab shutdown", flush=True)
                result = subprocess.run(["virsh", "-c", "qemu:///system", "shutdown", "gitops-lab"], check=False)
                return 2 if result.returncode == 0 else 3
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait()


if __name__ == "__main__":
    sys.exit(main())
