#!/bin/bash
a=1; b=1
for i in $(seq 1 8); do
  c=$((a + b)); a=$b; b=$c
done
echo "result=$b"
