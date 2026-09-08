#!/bin/sh
# build_pdf.sh HTML PDF [SECONDS]
#
# Print an HTML file to PDF with a headless Chromium/Chrome, defensively:
#
#   * a hard timeout, so a browser that hangs cannot hang the build. Chrome
#     headless does hang rather than erroring, and macOS has no timeout(1);
#     this uses a watchdog subshell instead.
#   * a private --user-data-dir, so an already-running Chrome does not refuse
#     the job or block on the shared profile.
#   * --virtual-time-budget, so it stops waiting for the renderer to settle.
#   * output built in a temp directory and moved into place only on success,
#     so a failed run leaves the previous PDF intact.
#   * exit 0 whatever happens. A missing PDF is a skip: the HTML is built and
#     is the real deliverable. Only a usage error is fatal.
#
# The browser is taken from $BROWSER if set, else the first one found.

HTML=$1
PDF=$2
LIMIT=${3:-45}
[ -n "$HTML" ] && [ -n "$PDF" ] || { echo "usage: build_pdf.sh HTML PDF [SECONDS]" >&2; exit 2; }

if [ -z "$BROWSER" ]; then
  for b in \
    /Applications/Chromium.app/Contents/MacOS/Chromium \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    /opt/pw-browsers/chromium \
    "$(command -v chromium 2>/dev/null)" \
    "$(command -v chromium-browser 2>/dev/null)" \
    "$(command -v google-chrome 2>/dev/null)"
  do
    [ -n "$b" ] && [ -x "$b" ] && BROWSER=$b && break
  done
fi
[ -n "$BROWSER" ] || { echo "SKIP $(basename "$PDF"): no chromium/chrome found; $(basename "$HTML") is built"; exit 0; }

T=$(mktemp -d) || exit 0
trap 'rm -rf "$T"' EXIT

# --no-sandbox is a Linux container workaround; passing it on macOS is at best
# useless. Only add it when running as root, where Chrome refuses without it.
SANDBOX=
[ "$(id -u)" = "0" ] && SANDBOX=--no-sandbox

run() {   # run() HEADLESS_FLAG ; leaves the pdf at $T/out.pdf if it worked
  "$BROWSER" "$1" --disable-gpu $SANDBOX \
    --no-first-run --no-default-browser-check --disable-extensions \
    --disable-background-networking --disable-sync --disable-default-apps \
    --disable-component-update --mute-audio \
    --virtual-time-budget=10000 --run-all-compositor-stages-before-draw \
    --user-data-dir="$T/profile" --no-pdf-header-footer \
    --print-to-pdf="$T/out.pdf" "$HTML" >>"$T/log" 2>&1 &
  bpid=$!
  ( sleep "$LIMIT"; kill -9 "$bpid" 2>/dev/null; echo "TIMEOUT after ${LIMIT}s" >>"$T/log" ) &
  wpid=$!
  wait "$bpid" 2>/dev/null
  kill "$wpid" 2>/dev/null
  wait "$wpid" 2>/dev/null
}

run --headless=new
[ -s "$T/out.pdf" ] || run --headless

if [ -s "$T/out.pdf" ]; then
  mv "$T/out.pdf" "$PDF"
  echo "wrote $(basename "$PDF")"
else
  echo "SKIP $(basename "$PDF"): the browser produced nothing; $(basename "$HTML") is built"
  echo "     tried: $BROWSER"
  sed 's/^/     /' "$T/log" 2>/dev/null | tail -8
fi
exit 0
