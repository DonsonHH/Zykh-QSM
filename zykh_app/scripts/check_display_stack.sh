#!/bin/sh

echo "== DRM connectors =="
for s in /sys/class/drm/*/status; do
  [ -e "$s" ] || continue
  printf "%s: " "$s"
  cat "$s"
done

echo
echo "== HDMI modes =="
cat /sys/class/drm/card0-HDMI-A-1/modes 2>/dev/null || true

echo
echo "== Input devices =="
for n in /sys/class/input/event*/device/name; do
  [ -e "$n" ] || continue
  printf "%s: " "$n"
  cat "$n"
done

echo
echo "== Display processes =="
ps | grep -E 'weston|cog|chrom|qt|wpe' | grep -v grep || true

echo
echo "== Browser candidates =="
for bin in cog chromium chromium-browser qt5 qmlscene wpe; do
  printf "%s: " "$bin"
  which "$bin" 2>/dev/null || echo "not found"
done
