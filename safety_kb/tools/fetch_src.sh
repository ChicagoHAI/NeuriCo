#!/bin/bash
# usage: fetch_src.sh URL OUTPATH(.md or .txt)   -- fetches, converts HTML->md or PDF->txt, prepends header
url="$1"; out="$2"; tmp=$(mktemp -d /tmp/fetchsrc.XXXXXX)
code=$(curl -sL -A "Mozilla/5.0 (X11; Linux x86_64) research-kb" --max-time 90 -o "$tmp/raw" -w "%{http_code}" "$url")
if [ "$code" != "200" ]; then echo "FAIL $code $url"; rm -rf "$tmp"; exit 1; fi
sz=$(stat -c %s "$tmp/raw"); if [ "$sz" -gt 20000000 ]; then echo "TOO LARGE $sz $url"; rm -rf "$tmp"; exit 1; fi
ft=$(file -b --mime-type "$tmp/raw")
{ echo "Source URL: $url | Fetched: 2026-10-19"; echo; } > "$out"
if [ "$ft" = "application/pdf" ]; then
  cp "$tmp/raw" "${out%.*}.pdf"; pdftotext -layout "$tmp/raw" - >> "$out"
elif echo "$ft" | grep -q html; then
  python3 -I /data/haokun_test/neurico/scripts_kb/html2md.py "$tmp/raw" >> "$out"
else
  cat "$tmp/raw" >> "$out"
fi
rm -rf "$tmp"; echo "OK $(wc -c < "$out") bytes $ft -> $out"
