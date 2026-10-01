#!/usr/bin/env bash
# Install a Stockfish binary and print its resolved path.
#
# The path it prints is what Config.stockfish_path resolves to, in the order
# frozen by the design record:
#   1. $CHESSLEAK_STOCKFISH_PATH
#   2. the shared binary installed here ($CHESSLEAK_STOCKFISH_ROOT/stockfish)
#   3. "stockfish" on PATH
#
# The shared location is read-only by convention: one engine binary is safe to
# share between workers, a writable cache is not.
#
# Usage:
#   scripts/get_stockfish.sh                 # install (idempotent) and print the path
#   scripts/get_stockfish.sh --force         # reinstall even if a working binary is there
#   scripts/get_stockfish.sh --from-source   # build from the Stockfish repo instead
#   CHESSLEAK_STOCKFISH_VERSION=sf_17 scripts/get_stockfish.sh   # pin a release tag
set -euo pipefail

ROOT="${CHESSLEAK_STOCKFISH_ROOT:-$HOME/.local/share/chessleak/stockfish}"
VERSION="${CHESSLEAK_STOCKFISH_VERSION:-latest}"
REPO="official-stockfish/Stockfish"
BIN="$ROOT/stockfish"
FORCE=0
FROM_SOURCE=0

for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --from-source) FROM_SOURCE=1 ;;
    -h | --help)
      sed -n '2,20p' "$0" | cut -c3-
      exit 0
      ;;
    *)
      echo "get_stockfish: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

log() { echo "get_stockfish: $*" >&2; }
die() {
  log "ERROR: $*"
  cat >&2 <<'FALLBACK'
FALLBACK — install a Stockfish binary by one of these, then re-run
scripts/get_stockfish.sh (or point $CHESSLEAK_STOCKFISH_PATH at it):

  * Distribution package:   sudo apt-get install -y stockfish
  * Official release binary: scripts/get_stockfish.sh            (this script)
  * Build from source:
        git clone https://github.com/official-stockfish/Stockfish.git
        cd Stockfish/src && make -j"$(nproc)" build ARCH=x86-64
        install -m 0755 stockfish "$CHESSLEAK_STOCKFISH_ROOT/stockfish"
FALLBACK
  exit 1
}

# Does the installed binary answer UCI? Proving the handshake here keeps a
# truncated download or a wrong-architecture file from becoming a test failure
# in another unit's suite. The engine's own name comes back on the "id name"
# line, so this doubles as the version check.
engine_name() {
  printf 'uci\nquit\n' | "$1" 2>/dev/null | sed -n 's/^id name //p' | head -1
}

usable() {
  [ -x "$1" ] || return 1
  [ -n "$(engine_name "$1")" ]
}

# Pick the engine out of an unpacked archive. Release archives name the binary
# after the platform ("stockfish-linux-x86-64-universal"), a source build calls
# it plain "stockfish", so take the exact name when it is there and otherwise
# the largest stockfish* file. The UCI handshake above is the real check.
pick_binary() {
  local root="$1" f exact
  exact="$(find "$root" -type f -name stockfish -print -quit)"
  if [ -n "$exact" ]; then
    echo "$exact"
    return 0
  fi
  for f in $(find "$root" -type f -name 'stockfish*'); do
    echo "$(wc -c <"$f") $f"
  done | sort -rn | head -1 | cut -d' ' -f2-
}

mkdir -p "$ROOT"

if [ "$FORCE" -eq 0 ] && usable "$BIN"; then
  log "already installed: $(engine_name "$BIN")"
  echo "$BIN"
  exit 0
fi

if [ "$FROM_SOURCE" -eq 1 ]; then
  command -v git >/dev/null || die "git is required for --from-source"
  command -v make >/dev/null || die "make is required for --from-source"
  case "$(uname -m)" in
    x86_64 | amd64) ARCH=x86-64 ;;
    aarch64 | arm64) ARCH=armv8 ;;
    *) die "--from-source does not know ARCH for $(uname -m); set it manually" ;;
  esac
  log "building Stockfish from source (ARCH=$ARCH), this takes a few minutes"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  git clone --depth 1 https://github.com/official-stockfish/Stockfish.git "$tmp/Stockfish" >&2
  make -C "$tmp/Stockfish/src" -j"$(nproc)" build ARCH="$ARCH" >&2
  install -m 0755 "$tmp/Stockfish/src/stockfish" "$BIN"
else
  command -v curl >/dev/null || die "curl is required to download a release binary"
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64 | Linux-amd64) ASSET=stockfish-linux-x86-64-universal.tar.gz ;;
    Linux-aarch64 | Linux-arm64) ASSET=stockfish-linux-arm64-universal.tar.gz ;;
    Darwin-*) ASSET=stockfish-macos-universal.tar.gz ;;
    *) die "no official release binary for $(uname -s)-$(uname -m)" ;;
  esac

  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT

  log "resolving $REPO release ($VERSION)"
  if [ "$VERSION" = latest ]; then
    api="https://api.github.com/repos/$REPO/releases/latest"
  else
    api="https://api.github.com/repos/$REPO/releases/tags/$VERSION"
  fi
  # Fetch to a file before parsing: grep -m1 closing the pipe early would make
  # curl fail with error 23 under `set -o pipefail`.
  curl -fsSL --retry 3 -H 'Accept: application/vnd.github+json' -o "$tmp/release.json" "$api" ||
    die "could not read $api"
  tag="$(sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$tmp/release.json" | head -1)"
  [ -n "$tag" ] || die "no release tag in $api (offline, or the tag does not exist?)"
  url="https://github.com/$REPO/releases/download/$tag/$ASSET"
  log "downloading $tag / $ASSET"

  curl -fL --retry 3 --progress-bar -o "$tmp/sf.tar.gz" "$url" || die "download failed: $url"
  tar -xzf "$tmp/sf.tar.gz" -C "$tmp" || die "could not unpack $ASSET"
  found="$(pick_binary "$tmp")"
  [ -n "$found" ] || die "$ASSET did not contain a 'stockfish' binary"
  install -m 0755 "$found" "$BIN"
  # Keep the licence and copying notice next to a redistributed binary.
  find "$tmp" -maxdepth 2 -type f \( -iname 'copying.txt' -o -iname 'license*' \) \
    -exec install -m 0644 {} "$ROOT/" \; || true
fi

usable "$BIN" || die "installed $BIN but it did not answer a UCI handshake"
log "installed: $(engine_name "$BIN") at $BIN"
echo "$BIN"
