"""Write new live data over the old file only if it is valid and newer. Exit 0 = file changed."""
import json, sys
KEYS = {"status", "actualDepUtc", "estArriveUtc", "lat", "lon", "altitudeFt", "updatedAt", "source"}
new = json.load(open(sys.argv[1]))
if not isinstance(new, dict) or set(new) != KEYS: sys.exit(2)
try: old = json.load(open(sys.argv[2]))
except Exception: old = None
if old and (old.get("updatedAt") or "") > new["updatedAt"]: sys.exit(1)
if old and {k: v for k, v in old.items() if k != "updatedAt"} == {k: v for k, v in new.items() if k != "updatedAt"} \
        and new["lat"] is None: sys.exit(1)  # nothing new to say while still at the gate
json.dump(new, open(sys.argv[2], "w"), indent=1)
