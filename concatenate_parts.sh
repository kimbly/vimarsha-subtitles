#!/bin/bash
{

set -euo pipefail

lang=$1

for f in $lang/part*.txt; do cat $f; echo; echo; done

}