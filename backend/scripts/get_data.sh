#!/usr/bin/env bash
# Downloads the public RCRV General Arrangement drawing (Oregon State University).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw
curl -fL --max-time 300 -A "Mozilla/5.0" \
  "https://oregonstate.box.com/index.php?rm=box_download_shared_file&shared_name=xbxepay8qgd31pmvisxtwtemvpb4637q&file_id=f_836309805515" \
  -o data/raw/rcrv_ga.pdf
echo "Saved data/raw/rcrv_ga.pdf"
