#!/usr/bin/env python3
"""Deploy Habitat disk images to Ultimate 64 USB flash drive via FTP.

Copies Dist/Habitat-A.d64 and Habitat-B.d64 to /USB1/HABITAT/ on the U64,
then optionally mounts them on drives A and B.

Usage:
    python3 u64_deploy.py                    # Deploy to U64_HOST or default
    python3 u64_deploy.py 192.168.1.158      # Deploy to specific IP
    python3 u64_deploy.py --mount            # Deploy and mount on drives
    python3 u64_deploy.py --mount --run      # Deploy, mount, and run habitat.prg
"""

import ftplib
import os
import sys
import argparse

PROJECT = os.path.dirname(os.path.abspath(__file__))
DISK_A = os.path.join(PROJECT, "Dist", "Habitat-A.d64")
DISK_B = os.path.join(PROJECT, "Dist", "Habitat-B.d64")
HABITAT_PRG = os.path.join(PROJECT, "Launcher", "habitat.prg")
REMOTE_DIR = "/USB1/HABITAT"


def deploy(host, mount=False, run=False):
    files = []
    for path in [DISK_A, DISK_B]:
        if os.path.exists(path):
            files.append(path)
        else:
            print(f"WARNING: {path} not found, skipping")

    if not files:
        print("ERROR: No disk images found. Run ./dockerbuild first.")
        sys.exit(1)

    # Upload via FTP
    print(f"Connecting to {host}:21 ...")
    ftp = ftplib.FTP(host, timeout=10)
    ftp.login()  # anonymous
    ftp.cwd(REMOTE_DIR)
    print(f"Remote directory: {REMOTE_DIR}")

    for path in files:
        name = os.path.basename(path)
        size = os.path.getsize(path)
        print(f"  Uploading {name} ({size:,} bytes) ... ", end="", flush=True)
        with open(path, "rb") as f:
            ftp.storbinary(f"STOR {name}", f)
        print("OK")

    ftp.quit()
    print("FTP upload complete.")

    if mount or run:
        from u64_tool import U64Session
        u = U64Session(host)

        if mount:
            print("Mounting disks on U64 ...")
            u.mount_disk("a", DISK_A)
            u.mount_disk("b", DISK_B)

        if run:
            print("Running habitat.prg ...")
            u.run_prg(HABITAT_PRG)


def main():
    parser = argparse.ArgumentParser(description="Deploy Habitat disks to U64 USB")
    parser.add_argument("host", nargs="?",
                        default=os.environ.get("U64_HOST", "192.168.1.158"),
                        help="U64 IP address")
    parser.add_argument("--mount", action="store_true",
                        help="Also mount disks on drives A and B")
    parser.add_argument("--run", action="store_true",
                        help="Also run habitat.prg (implies --mount)")
    args = parser.parse_args()

    if args.run:
        args.mount = True

    deploy(args.host, mount=args.mount, run=args.run)


if __name__ == "__main__":
    main()
