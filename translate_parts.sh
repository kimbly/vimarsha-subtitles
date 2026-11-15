#!/bin/bash
set -euo pipefail

{
dir="$(dirname "$0")"
lang=$1
shift
parts_to_redo=$@

if [ $# -lt 1 ]; then
  echo "Usage: translate_parts.sh <language> <part-number> <part-number> ..."
  echo "Example: translate_parts.sh hindi {1..6}"
  exit 1
fi

echo "I will read english files named part<n>.txt from $(pwd)"
echo "And I will write the translated output here:     $(pwd)/$lang/"
echo
mkdir -p "$lang"

for i in $parts_to_redo; do 
	echo Translating part$i to $lang...
	time ($dir/query_openai.py $dir/prompts/translate_to_$lang.txt part$i.txt $lang/part$i.txt; grep NOTE $lang/part$i.txt || true) &
done

wait

$dir/concatenate_parts.sh $lang > $lang/$lang.vtt

exit 0
}
