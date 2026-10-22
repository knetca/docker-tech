#!/usr/bin/env python3
# starlink-feed-build.py — Starlink geofeed -> IPv4 CIDR list, verbatim (no aggregation)
import csv, io, ipaddress, os, sys, urllib.request

URL = "https://geoip.starlinkisp.net/feed.csv"
OUT = os.environ.get("OUT", "/data")
ALLOW = {a.strip() for a in os.environ.get("ALLOW", "*").split(",")}
MIN_V4 = int(os.environ.get("MIN_V4", "50"))
MAX_DROP = 0.5

raw = urllib.request.urlopen(URL, timeout=30).read().decode()
nets = set()
for row in csv.reader(io.StringIO(raw)):
    if len(row) < 3 or row[0].startswith("#"):
        continue
    if "*" not in ALLOW and row[1].strip() not in ALLOW and row[2].strip() not in ALLOW:
        continue
    try:
        n = ipaddress.ip_network(row[0].strip(), strict=False)
    except ValueError:
        continue
    if n.version == 4:
        nets.add(n)

nets = sorted(nets)
path = f"{OUT}/starlink-v4.txt"
try:
    prev = sum(1 for _ in open(path))
except FileNotFoundError:
    prev = 0

if len(nets) < MIN_V4 or (prev and len(nets) < prev * (1 - MAX_DROP)):
    sys.exit(f"REFUSING: {len(nets)} entries (prev {prev})")

tmp = path + ".tmp"
with open(tmp, "w") as f:
    f.write("\n".join(str(n) for n in nets) + "\n")
os.replace(tmp, path)
print(f"v4={len(nets)} allow={sorted(ALLOW)}")
