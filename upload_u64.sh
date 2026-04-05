#!/bin/bash
# Upload and run Habitat.crt on Ultimate 64 via REST API.
#
# Usage: ./upload_u64.sh [ip_address] [crt_file]
#   ip_address  — U64 IP (default: from U64_IP env var, or 192.168.1.64)
#   crt_file    — CRT to upload (default: Dist/Habitat.crt)
#
# Prerequisites:
#   - U64 firmware 3.11+ with REST API enabled
#   - U64 Modem Settings: DF80/NMI
#
# The CRT is POSTed directly to the U64 which resets and boots from it.

set -e

IP="${1:-${U64_IP:-192.168.1.64}}"
CRT="${2:-Dist/Habitat.crt}"

if [ ! -f "$CRT" ]; then
    echo "Error: $CRT not found"
    echo "Run ./dockerbuild && python3 build_crt.py Launcher/habitat.prg Dist/Habitat-B.d64 Dist/Habitat.crt"
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
