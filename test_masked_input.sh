#!/bin/bash
# Quick test for read_masked — run via:
#   bash test_masked_input.sh
#   OR
#   curl -fsSL <url> | bash  (to simulate the installer)

RED='\033[0;31m'
GREEN='\033[0;32m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

read_masked() {
    local __resultvar="$1"
    local _input="" _char=""

    local old_stty
    old_stty=$(stty -g < /dev/tty 2>/dev/null)
    stty -echo < /dev/tty 2>/dev/null
    trap 'stty '"$old_stty"' < /dev/tty 2>/dev/null; trap - INT TERM' INT TERM

    while true; do
        IFS= read -r -n 1 _char < /dev/tty
        if [[ -z "$_char" ]]; then
            break
        fi
        if [[ "$_char" == $'\x7f' ]] || [[ "$_char" == $'\x08' ]]; then
            if [ ${#_input} -gt 0 ]; then
                _input="${_input%?}"
                echo -ne '\b \b' >&2
            fi
        else
            _input+="$_char"
            echo -ne '*' >&2
        fi
    done

    echo "" >&2
    stty "$old_stty" < /dev/tty 2>/dev/null
    trap - INT TERM

    printf -v "$__resultvar" '%s' "$_input"
}

tmpfile=$(mktemp /tmp/test_masked_XXXXXX)

echo -e "${BOLD}Test 1: Masked input (secret)${NC}"
echo -ne "  Enter a secret: "
local_value=""
read_masked local_value

if [ -n "$local_value" ]; then
    echo -e "  ${GREEN}[OK]${NC} Got ${#local_value} chars: ${local_value:0:4}...${local_value: -4}"
    echo "SECRET=$local_value" > "$tmpfile"
else
    echo -e "  ${RED}[FAIL]${NC} Value is empty!"
    echo "SECRET=" > "$tmpfile"
fi

echo ""
echo -e "${BOLD}Test 2: Plain input (non-secret)${NC}"
echo -ne "  Enter visible text: "
read plain_value < /dev/tty

if [ -n "$plain_value" ]; then
    echo -e "  ${GREEN}[OK]${NC} Got: $plain_value"
    echo "PLAIN=$plain_value" >> "$tmpfile"
else
    echo -e "  ${RED}[FAIL]${NC} Value is empty!"
    echo "PLAIN=" >> "$tmpfile"
fi

echo ""
echo -e "${BOLD}Results saved to:${NC} $tmpfile"
echo -e "${DIM}$(cat "$tmpfile")${NC}"
