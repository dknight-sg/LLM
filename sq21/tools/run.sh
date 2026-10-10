#!/usr/bin/env bash
# Runs inside the GitHub Action: fetch SQ 21 about every 90 s for ~7 min, saving real data only.
set -u
TOOLS="$GITHUB_WORKSPACE/site/sq21/tools"
cd "$GITHUB_WORKSPACE/live"
git config user.name "github-actions[bot]"
git config user.email "41898283+github-actions[bot]@users.noreply.github.com"
start=$(date +%s)
while :; do
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if [ "$DRY_RUN" != "true" ] && { [[ "$now" < "2026-10-10T10:20:00Z" ]] || [[ ! "$now" < "2026-10-11T13:00:00Z" ]]; }; then
    echo "$now is outside the tracking window; nothing to do."; exit 0
  fi
  if python3 -I "$TOOLS/sq21.py" "$DEP_DATE" > /tmp/out.json 2> /tmp/err.txt; then
    cat /tmp/err.txt /tmp/out.json
    [ "$DRY_RUN" = "true" ] && exit 0
    if python3 -I "$TOOLS/merge.py" /tmp/out.json live.json; then
      git add live.json && git commit -qm "SQ 21 live data $now" && { git pull -q --rebase -X theirs || true; git push -q || echo "push failed"; }
    else echo "no newer data to save"; fi
  else
    cat /tmp/err.txt; echo "fetch failed; live.json left unchanged"
    [ "$DRY_RUN" = "true" ] && exit 1
  fi
  [ $(( $(date +%s) - start )) -gt 400 ] && break
  sleep 90
done
