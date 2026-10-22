#!/bin/bash
# Live event stream for scripts/run_methods.py batches: one line per job
# start/finish/fail/retry, container exit, stalled log, or error signal.
# Ends when the loop exits and no batch container is left.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
OUT=logs/batch_main.out
E='DONE|FAILED|NO_PAPER|STOPPED|RETRY|START '
P='authentication_error|Please run /login|OAuth token has expired|usage limit reached|insufficient_quota|No space left|model is at capacity'
n=$(grep -c -E "$E" $OUT); declare -A warned seen
for f in logs/batch/*/*.log; do warned[e$f]=$(grep -a -c -E "$P" "$f"); done
for c in $(docker ps --format '{{.Names}}' | grep -E "^neurico-[0-9]{8}_[0-9]{6}-"); do seen[$c]=1; done
while true; do
  m=$(grep -c -E "$E" $OUT)
  if [ "$m" -gt "$n" ]; then grep -E "$E" $OUT | tail -n $((m-n)) | cut -c1-230; n=$m; fi
  now=$(date +%s); live=$(docker ps --format '{{.Names}}' | grep -E "^neurico-[0-9]{8}_[0-9]{6}-")
  for f in logs/batch/*/*.log; do
    e=$(grep -a -c -E "$P" "$f")
    if [ "$e" -gt "${warned[e$f]:-0}" ]; then warned[e$f]=$e; echo "PROBLEM $(basename $f .log): $(grep -a -o -E "$P" "$f" | tail -1)"; fi
  done
  for c in $live; do
    seen[$c]=1; batch=$(echo "$c" | sed -E 's/^neurico-([0-9]{8}_[0-9]{6})-.*/\1/'); f="logs/batch/$batch/${c#neurico-$batch-}.log"
    age=$(( now - $(stat -c %Y "$f") ))
    if [ $age -gt 1800 ] && [ -z "${warned[$c]}" ]; then warned[$c]=1; echo "STALL? ${c#neurico-$batch-} log idle ${age}s"; fi
  done
  for c in "${!seen[@]}"; do
    if ! grep -q -x "$c" <<<"$live"; then
      unset "seen[$c]"; batch=$(echo "$c" | sed -E 's/^neurico-([0-9]{8}_[0-9]{6})-.*/\1/'); f="logs/batch/$batch/${c#neurico-$batch-}.log"
      echo "EXITED ${c#neurico-$batch-}: $(grep -a -E 'Paper: |SUCCESS!|did not complete' "$f" | tail -1 | cut -c1-150)"
    fi
  done
  if ! pgrep -f "[r]un_methods.py" >/dev/null && [ -z "$live" ]; then echo "BATCH LOOP NOT RUNNING"; tail -3 $OUT | cut -c1-200; break; fi
  sleep 30
done
