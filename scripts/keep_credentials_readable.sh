#!/bin/bash
# Containers run as a different uid and read ~/.claude/.credentials.json through
# a bind mount. Claude Code rewrites that file owner-only whenever a token is
# refreshed or the user logs in, which makes running agents fail with
# "Please run /login". Keep it readable while batches are running.
F="$HOME/.claude/.credentials.json"
# Host mode runs agents as this user, so the file must keep its owner-only mode.
if [ "${NEURICO_MODE:-docker}" = "host" ]; then
    echo "NEURICO_MODE=host: credentials are read directly by this user; nothing to do." >&2
    exit 0
fi
while pgrep -f "[r]un_methods.py" >/dev/null; do
    [ -f "$F" ] && [ "$(stat -c %a "$F")" != "666" ] && chmod a+rw "$F"
    sleep 5
done
