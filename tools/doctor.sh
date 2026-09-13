#!/bin/sh
# Prove the containerised toolchain is real and report exact versions.
set -e
echo "arch:        $(uname -m)"
echo "python3:     $(python3 --version 2>&1)"

printf 'sjasmplus:   '; sjasmplus --version 2>&1 | head -1
[ -f /usr/local/share/sjasmplus.commit ] && echo "             commit $(cat /usr/local/share/sjasmplus.commit)"

printf 'hdfmonkey:   '; hdfmonkey 2>&1 | head -1
[ -f /usr/local/share/hdfmonkey.commit ] && echo "             commit $(cat /usr/local/share/hdfmonkey.commit)"

printf 'zesarux:     '; zesarux --version 2>&1 | head -1
[ -f /usr/local/share/zesarux.commit ] && sed 's/^/             /' /usr/local/share/zesarux.commit

echo 'z88dk:       not in this image, by design - see the Dockerfile note.'
echo '             `make doctor` reports it separately from its own pinned image.'

echo
echo "Z80N smoke test (assemble a Next-only instruction):"
tmp=$(mktemp -d)
cat > "$tmp/z80n.asm" <<'EOF'
        DEVICE ZXSPECTRUMNEXT
        ORG $8000
start:  MUL D,E
        LDIX
        NEXTREG $12, 9
        RET
        SAVENEX OPEN "z80n.nex", start
        SAVENEX AUTO
        SAVENEX CLOSE
EOF
(cd "$tmp" && sjasmplus --zxnext=cspect z80n.asm >/dev/null && \
    echo "             OK - $(wc -c < z80n.nex) byte .nex produced")
rm -rf "$tmp"

