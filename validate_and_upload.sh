#!/bin/bash
set -euo pipefail

{
dir="$(dirname "$0")"

if [ $# -lt 2 ]; then
  echo "Usage: validate_and_upload.sh <video_id> <language>"
  echo "Example: validate_and_upload.sh 1244820661 hindi"
  exit 1
fi

video_id=$1
lang=$2

echo -n "Validating $lang ..."
if python $dir/validate_vtt.py $lang/$lang.vtt; then
  echo -n "Uploading $lang ..."
  if python $dir/upload_to_vimeo.py $video_id $lang/$lang.vtt $lang; then
    echo "✅ $lang uploaded successfully!"
  else
    echo "❌ $lang upload failed."
  fi
else
  echo "❌ $lang validation failed."
fi

exit 0
}
