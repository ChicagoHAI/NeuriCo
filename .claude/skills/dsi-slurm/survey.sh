#!/bin/bash
# Free-GPU survey of the DSI cluster: one line per GPU type with free/total counts and the nodes that have free GPUs.
# Usage: .claude/skills/dsi-slurm/survey.sh [partition list, default general,complementary-ai]
P="${1:-general,complementary-ai}"
sinfo -h -N -p "$P" -O "NodeList:14,StateCompact:8,Gres:44,GresUsed:60,FreeMem:10,Features:40" \
| awk '
  $3 ~ /gpu:/ {
    node=$1; state=$2; split($3,a,":"); type=a[2]; total=a[3]; sub(/\(.*/,"",total)
    used=0; if (match($0,/gpu:[a-z0-9]+:[0-9]+\(IDX/)) { u=substr($0,RSTART,RLENGTH); split(u,b,":"); used=b[3]; sub(/\(IDX/,"",used) }
    if (state ~ /drain|down|drng|maint/) { bad[type]+=total; next }
    free=total-used; tot[type]+=total; fr[type]+=free
    if (free>0) nodes[type]=nodes[type] sprintf("%s(%d) ", node, free)
  }
  END {
    printf "%-6s %5s %5s %5s  %s\n","type","free","total","off","nodes with free GPUs"
    for (t in tot) printf "%-6s %5d %5d %5d  %s\n", t, fr[t], tot[t], bad[t]+0, nodes[t]
  }' | sort -k1,1
echo
echo "our jobs:"; squeue -u "$USER" -h -o "  %i %j %T %M %N %b %r" 
echo "pending 4-GPU requests ahead of us (reason counts):"; squeue -h -p general -t PD -o "%b %r" | grep -c "gpu:4" | sed 's/^/  /'
