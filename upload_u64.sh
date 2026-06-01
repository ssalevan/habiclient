#!/bin/bash
# Upload and run Habitat.crt on Ultimate 64 via REST API.
#
# Usage: ./upload_u64.sh [ip_address] [crt_file]
#   ip_address  — U64 IP (default: from U64_IP env var, or 192.168.1.64)
#   crt_file    — CRT to upload.  If omitted, downloads the latest rolling
#                 build (tag "rolling") from the habiclient GitHub releases
#                 via the `gh` CLI — i.e. the most recent CI build of main.
#
# Prerequisites:
#   - U64 firmware 3.11+ with REST API enabled
#   - U64 Modem Settings: DF80/NMI
#   - `gh` CLI (authenticated) — only when no crt_file is given
#
# The CRT is POSTed directly to the U64 which resets and boots from it.

set -e

IP="${1:-${U64_IP:-192.168.1.64}}"
CRT="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$CRT" ]; then
    # No CRT given — fetch the latest rolling build CI publishes to the
    # habiclient GitHub releases (tag "rolling", refreshed on every push to
    # main).  Needs the authenticated `gh` CLI.
    if ! command -v gh >/dev/null 2>&1; then
        echo "Error: no CRT given and the 'gh' CLI isn't installed to fetch the latest build."
        echo "Install gh (https://cli.github.com) or pass one: ./upload_u64.sh <ip> path/to.crt"
        exit 1
    fi
    CRT="$(mktemp -t habitat-rolling)"
    trap 'rm -f "$CRT"' EXIT
    echo "No CRT given — downloading the latest rolling build from GitHub releases..."
    # Run gh from the repo dir so it auto-detects the repository.
    ( cd "$SCRIPT_DIR" && gh release download rolling --pattern 'Habitat.crt' --output "$CRT" --clobber )
fi

if [ ! -f "$CRT" ]; then
    echo "Error: $CRT not found"
    echo "Build locally (./dockerbuild && python3 build_crt.py ...) or omit the arg to fetch the latest CI build."
    exit 1
fi

SIZE=$(stat -f%z "$CRT" 2>/dev/null || stat -c%s "$CRT" 2>/dev/null)
echo "Uploading $CRT (${SIZE} bytes) to U64 at $IP..."

# POST the CRT file — U64 resets and boots with cartridge active
HTTP_CODE=$(curl -s -o /tmp/u64_response.json -w "%{http_code}" \
    -X POST \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@${CRT}" \
    "http://${IP}/v1/runners:run_crt")

if [ "$HTTP_CODE" = "200" ]; then
    echo "Success! U64 is booting Habitat from cartridge."
    echo "Remember: U64 Modem Settings must be set to DF80/NMI"
else
    echo "HTTP $HTTP_CODE — upload may have failed:"
    cat /tmp/u64_response.json 2>/dev/null
    echo
    echo "Check: is the U64 at $IP? Is the REST API enabled?"
    exit 1
fi
