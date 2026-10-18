#!/bin/sh
# Container entry: fix volume ownership for PUID/PGID, then run the command as that user (never as root).
# Started with `user:` (not root), it does nothing but run the command; volumes must then be writable for that user.
set -eu

if [ "$(id -u)" = 0 ]; then
  PUID="${PUID:-1000}"; PGID="${PGID:-1000}"
  case "$PUID$PGID" in *[!0-9]*) echo "PUID and PGID must be numbers" >&2; exit 1 ;; esac
  if [ "$PUID" = 0 ]; then
    echo "folivox: PUID=0 would write files as root; set PUID/PGID to your user (id -u, id -g)." >&2; exit 1
  fi
  groupmod -o -g "$PGID" folivox 2>/dev/null || true
  usermod -o -u "$PUID" -g "$PGID" folivox >/dev/null 2>&1 || true
  for d in /data /audiobooks /work; do
    # only the top folder of a big library: a recursive chown of a mounted audiobook shelf would be slow and rude
    [ "$(stat -c %u "$d")" = "$PUID" ] || chown "$PUID:$PGID" "$d" 2>/dev/null || echo "folivox: cannot chown $d" >&2
  done
  # state created by an earlier run under another PUID
  [ -d /data/share ] && [ "$(stat -c %u /data/share)" != "$PUID" ] && chown -R "$PUID:$PGID" /data 2>/dev/null || true
  export HOME=/home/folivox
  set -- setpriv --reuid "$PUID" --regid "$PGID" --init-groups "$@"
else
  export HOME="${HOME:-/tmp}"
fi

# Optional: fetch the models before the first start instead of at the first render (progress goes to the log).
if [ "${FOLIVOX_PRELOAD_MODELS:-0}" = 1 ] && [ "${1:-}" != "setup" ]; then
  echo "folivox: downloading models (FOLIVOX_PRELOAD_MODELS=1)…"
  if [ "$(id -u)" = 0 ]; then setpriv --reuid "$PUID" --regid "$PGID" --init-groups folivox setup </dev/null || echo "folivox: model download failed; the studio will retry on the first render" >&2
  else folivox setup </dev/null || echo "folivox: model download failed; the studio will retry on the first render" >&2; fi
fi
exec "$@"
