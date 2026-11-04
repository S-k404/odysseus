#!/bin/bash
# Raise (or restore) how much unified memory the GPU may wire: macOS's iogpu.wired_limit_mb.
#
# Local models (llama.cpp through Docker Model Runner, MLX) must fit in this budget. 0 means "macOS
# default" (about 78% of RAM: 38,339 MB on the 48 GB M5 Max, as Metal reports it). It does not create RAM:
# a higher limit lets the GPU take memory from macOS and your apps, so keep headroom. It only matters
# for a model bigger than the default budget; a 35B at 128k context needs about 19 GB.
#
#   scripts/dev/gpu_wired_limit.sh status               the limit now, the default, the safe maximum
#   sudo scripts/dev/gpu_wired_limit.sh set [MB]        change it now (lost at reboot)
#   sudo scripts/dev/gpu_wired_limit.sh install [MB]    change it now and at every boot (LaunchDaemon)
#   sudo scripts/dev/gpu_wired_limit.sh uninstall       remove the LaunchDaemon and restore the default
#   add --dry-run first to print what would happen and change nothing
#
# MB defaults to the safe maximum: RAM minus 6 GB (43,008 on a 48 GB Mac). Values below 60% of RAM or
# above the maximum are refused. If memory pressure turns yellow or red, or it starts swapping, lower it
# or run `uninstall`.
set -eu

LABEL=com.local.iogpu-wired-limit
PLIST="/Library/LaunchDaemons/$LABEL.plist"
HERE="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$HERE/$LABEL.plist.template"
RAM_MB=$(( $(sysctl -n hw.memsize) / 1048576 ))
HEADROOM_MB=6144
MAX_MB=$(( RAM_MB - HEADROOM_MB ))
MIN_MB=$(( RAM_MB * 6 / 10 ))

DRY=0
[ "${1:-}" = "--dry-run" ] && { DRY=1; shift; }
cmd="${1:-status}"; shift || true
mb="${1:-$MAX_MB}"

say() { printf '%s\n' "$*"; }
act() { if [ "$DRY" = 1 ]; then say "  would run: $*"; else "$@"; fi; }
need_root() { [ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { say "This needs sudo: sudo $0 $cmd ${mb:-}"; exit 1; }; }

check_value() {
  case "$mb" in ''|*[!0-9]*) say "MB must be a whole number, got '$mb'."; exit 2;; esac
  if [ "$mb" -gt "$MAX_MB" ]; then
    say "$mb MB leaves less than 6 GB for macOS and your apps (the maximum here is $MAX_MB MB). Refusing."; exit 2
  fi
  if [ "$mb" -lt "$MIN_MB" ]; then
    say "$mb MB is below 60% of RAM ($MIN_MB MB), which would shrink the GPU's budget. Refusing."; exit 2
  fi
}

render_plist() { sed "s/__MB__/$mb/" "$TEMPLATE"; }

metal_default() {
  command -v swift >/dev/null 2>&1 || return 0
  local f; f="$(mktemp -t gpulimit).swift"
  printf 'import Metal\nif let d = MTLCreateSystemDefaultDevice() { print(Int(d.recommendedMaxWorkingSetSize / 1048576)) }\n' > "$f"
  swift "$f" 2>/dev/null | tail -1; rm -f "$f"
}

case "$cmd" in
  status)
    cur="$(sysctl -n iogpu.wired_limit_mb 2>/dev/null || echo unknown)"
    say "RAM:                         $RAM_MB MB"
    say "iogpu.wired_limit_mb now:    $cur$([ "$cur" = 0 ] && echo '  (0 = the macOS default)')"
    d="$(metal_default || true)"; [ -n "$d" ] && say "Metal says the GPU may wire:  $d MB right now"
    say "Safe maximum to set:         $MAX_MB MB  (RAM minus 6 GB)"
    say "LaunchDaemon installed:      $([ -f "$PLIST" ] && echo "yes ($PLIST)" || echo no)"
    ;;
  set)
    check_value; need_root
    act sysctl "iogpu.wired_limit_mb=$mb"
    [ "$DRY" = 1 ] || say "now: $(sysctl -n iogpu.wired_limit_mb) MB (lost at reboot; use install to keep it)"
    ;;
  install)
    check_value; need_root
    [ -f "$TEMPLATE" ] || { say "Missing $TEMPLATE"; exit 1; }
    say "LaunchDaemon $PLIST would contain:"; render_plist | sed 's/^/    /'
    if [ "$DRY" = 0 ]; then
      tmp="$(mktemp)"; render_plist > "$tmp"
      plutil -lint "$tmp" >/dev/null || { say "The generated plist is not valid."; rm -f "$tmp"; exit 1; }
      install -m 644 -o root -g wheel "$tmp" "$PLIST"; rm -f "$tmp"
      launchctl bootout "system/$LABEL" 2>/dev/null || true
      launchctl bootstrap system "$PLIST"
    else
      say "  would run: install -m 644 -o root -g wheel <plist> $PLIST"
      say "  would run: launchctl bootout system/$LABEL (if loaded); launchctl bootstrap system $PLIST"
    fi
    act sysctl "iogpu.wired_limit_mb=$mb"
    [ "$DRY" = 1 ] || say "now: $(sysctl -n iogpu.wired_limit_mb) MB, and it is re-applied at every boot"
    ;;
  uninstall)
    need_root
    [ -f "$PLIST" ] && { act launchctl bootout "system/$LABEL" || true; act rm -f "$PLIST"; } || say "No LaunchDaemon installed."
    act sysctl iogpu.wired_limit_mb=0
    [ "$DRY" = 1 ] || say "now: $(sysctl -n iogpu.wired_limit_mb) MB (0 = the macOS default)"
    ;;
  *)
    sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
