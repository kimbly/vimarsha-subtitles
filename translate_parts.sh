#!/bin/bash
set -euo pipefail

{
dir=`dirname $0`
lang=$1
shift
parts_to_redo=$@

mkdir -p $lang

# todo: run each part in parallel (using background tasks, [xargs -P] or GNU parallel)
for i in $parts_to_redo; do 
	echo Translating part$i to $lang...
	time ../query_openai.py ../prompt_translate_to_$lang.txt part$i.txt $lang/part$i.txt
	grep NOTE $lang/part$i.txt
done

$dir/concatenate_parts.sh $lang > $lang/$lang.txt

exit 0
}
