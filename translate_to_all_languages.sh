#!/bin/bash
set -euo pipefail

{
dir="$(dirname "$0")"

if [ $# -lt 1 ]; then
  echo "Usage: translate_to_all_languages.sh <num-parts>"
  echo "Example: translate_to_all_languages.sh 6"
  exit 1
fi

num_parts=$1

# skip bhojpuri because educated speakers likely prefer hindi
# skip javanese because educated speakers likely prefer indonesian
for lang in arabic bengali chinese french german greek gujarati hausa hindi indonesian italian japanese kannada kashmiri korean marathi nepali persian polish portuguese russian spanish swahili tamil telugu tibetan thai turkish urdu vietnamese yoruba; do 
  echo
  if [ -d $lang ]; then
    echo "Skipping $lang because $(pwd)/$lang already exists"
  else
    echo "====== Translating to $lang ======="
    $dir/translate_parts.sh $lang $(eval echo {1..$num_parts})
  fi
done

exit 0
}
