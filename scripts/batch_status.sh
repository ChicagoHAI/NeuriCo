#!/bin/bash
# One-screen health check for scripts/run_methods.py batches (all under logs/batch/).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BATCHES="$ROOT/logs/batch"
STALL=${STALL_SECONDS:-1200}
echo "== $(date '+%F %T')"
if pgrep -f "[r]un_methods.py" >/dev/null; then echo "loop: RUNNING"; else echo "loop: NOT RUNNING"; fi
python3 - "$BATCHES" <<'P'
import json,sys,collections,glob,os
jobs=[j for f in sorted(glob.glob(sys.argv[1]+"/*/status.json")) for j in json.load(open(f))["jobs"]]
print("jobs:", dict(collections.Counter(j["state"] for j in jobs)))
for j in jobs:
    if j["state"] in ("failed","stopped","cancelled"):
        print(f"  {j['state'].upper()} {os.path.basename(j['log_file'])} rc={j['return_code']}")
    elif j.get("attempts"):
        print(f"  retried x{j['attempts']}: {os.path.basename(j['log_file'])} ({j['state']})")
P
now=$(date +%s)
for c in $(docker ps --format '{{.Names}}' | grep -E "^neurico-[0-9]{8}_[0-9]{6}-"); do
    batch=$(echo "$c" | sed -E 's/^neurico-([0-9]{8}_[0-9]{6})-.*/\1/'); name="${c#neurico-$batch-}"
    f="$BATCHES/$batch/$name.log"
    age=$(( now - $(stat -c %Y "$f") ))
    stage=$(grep -a -E "STAGE|Paper Writing|ZERO-SHOT AGENT" "$f" | tail -1 | tr -s ' ' | cut -c1-34)
    flag="ok"; [ "$age" -gt "$STALL" ] && flag="STALLED?"
    # a child process (training, API loop) can keep a quiet agent legitimately busy
    busy=$(docker exec "$c" sh -c "ps -eo pcpu,comm --no-headers | sort -rn | head -1" 2>/dev/null | tr -s ' ')
    echo "  $flag | $name | $(docker ps --filter name="$c" --format '{{.RunningFor}}' | sed 's/ ago//') | log idle ${age}s | $stage | top proc:$busy"
    grep -a -i -E "authentication_error|Please run /login|OAuth token has expired|Invalid API key|usage limit reached|\"status\":\"rejected\"|insufficient_quota|No space left|model is at capacity" "$f" | tail -2 | cut -c1-220 | sed 's/^/      ! /'
done
latest=$(ls -t "$BATCHES"/*/*claude*.log 2>/dev/null | head -1)
[ -n "$latest" ] && grep -a -o -E '"rateLimitType":"[a-z_]+","utilization":[0-9.]+' "$latest" | tail -1 | sed -E 's/"rateLimitType":"([a-z_]+)","utilization":([0-9.]+)/claude \1 limit utilization: \2/'
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader | tr '\n' ';'; echo
df -h /data | tail -1 | awk '{print "disk /data free: "$4}'
# NeuriCo runs cache models in the container's home, which lives on the root disk.
df -h / | tail -1 | awk '{print "root disk free: "$4}'
docker ps -s --format '{{.Names}} {{.Size}}' | grep -E "^neurico-[0-9]{8}_" | sed -E 's/^neurico-[0-9_]+-/  container layer: /; s/ \(virtual.*//'
