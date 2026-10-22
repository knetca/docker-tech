# docker-tech

A small Docker Compose stack: a few web utilities behind Caddy, plus a builder that converts the Starlink IP geofeed into a plain CIDR list that a FortiGate external connector can ingest.

## Contents

- [Services](#services)
- [Layout](#layout)
- [Usage](#usage)
- [Starlink feed for FortiGate](#starlink-feed-for-fortigate)
- [Operations](#operations)
- [Troubleshooting](#troubleshooting)

## Services

| Service | Image / build | Purpose |
|---|---|---|
| caddy | `caddy:2-alpine` | TLS termination (automatic certificates), reverse proxy, static file hosting |
| wifiqr | `bndw/wifi-card` | WiFi QR code generator |
| pwgen | `jocxfin/pwgen` | Password generator |
| visualsubnetcalc | `ckabalan/visualsubnetcalc` | Visual subnet calculator |
| starlink-feed | `./starlink-feed` (local build) | Builds the Starlink IPv4 CIDR list |

Only Caddy publishes ports (80, 443/tcp, 443/udp). Everything else is reachable only on the compose network.

Image tags are pinned in `docker-compose.yml`. Review them occasionally.

## Layout

```
.
├── docker-compose.yml
├── config/caddy/Caddyfile
├── starlink-feed/
│   ├── Dockerfile
│   └── starlink-feed-build.py
└── volumes/                  # runtime state, do not commit
    ├── caddy/data/           # certificates and ACME state
    ├── caddy/config/
    └── starlink-feed/        # builder output, served read-only by Caddy
```

Add `volumes/` to `.gitignore`.

## Usage

Requirements: Docker with the Compose plugin, DNS records pointing at the host, and inbound TCP 80 and 443 reachable (needed for ACME certificate issuance).

1. Edit `config/caddy/Caddyfile` and replace the site hostnames with your own.
2. Create the output directory:

   ```
   mkdir -p volumes/starlink-feed
   ```

3. Start the stack:

   ```
   docker compose up -d --build
   docker compose ps
   docker logs starlink-feed
   ```

4. Validate and reload Caddy after config changes:

   ```
   docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile
   docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```

Notes:

- Compose reads the `docker-compose.yml` in the current directory. `docker compose ls` shows which file a project uses.
- Adding a volume mount to an existing service requires `docker compose up -d <service>`. A Caddy reload does not add mounts.

## Starlink feed for FortiGate

### What it does

`starlink-feed-build.py` downloads Starlink's public geofeed (`https://geoip.starlinkisp.net/feed.csv`), keeps the IPv4 rows, and writes one CIDR per line to `starlink-v4.txt`. The container runs the script at start and then every 6 hours. Caddy serves the result as plain text at:

```
https://<your-host>/feeds/starlink-v4.txt
```

The FortiGate external connector expects one IP, range, or CIDR per line. The upstream feed is CSV with extra columns, which it does not accept, so this builder does the conversion.

The output is a verbatim list of the feed's IPv4 prefixes. There is no aggregation and no static additions.

### Configuration

Set these as environment variables on the `starlink-feed` service.

| Variable | Default | Meaning |
|---|---|---|
| `OUT` | `/data` | Output directory inside the container |
| `ALLOW` | `*` | `*` means no location filter. Otherwise a comma-separated list of country or region codes from the feed (for example `CA,CA-ON`) |
| `MIN_V4` | `50` | Refuse to publish if the list has fewer entries than this |

Location labels in the geofeed describe where Starlink places an address range, and they may not match where a subscriber actually is. Check them against known subscriber addresses before relying on `ALLOW` to filter.

### Safety guards

- If the new list has fewer than `MIN_V4` entries, or is more than 50% smaller than the previous list, the script exits without writing and the last good file stays in place.
- Writes are atomic (temp file, then rename).
- The previous list is read from the bind mount, so `volumes/starlink-feed/` must persist across container recreation.
- After a failed run the container waits 6 hours before retrying. To retry immediately:

  ```
  docker compose restart starlink-feed
  ```

Set `MIN_V4` to about half the real entry count after the first run.

### FortiGate configuration

Create the external connector (verify option names against your FortiOS version):

```
config system external-resource
    edit "TF-STARLINK-V4"
        set type address
        set resource "https://<your-host>/feeds/starlink-v4.txt"
        set refresh-rate 360
    next
end
```

Then use `TF-STARLINK-V4` as a source address in a policy. Multiple source entries in a policy are ORed, so it can sit alongside other address objects (for example a country GeoIP object or a static address group).

Points to check:

- The FortiGate must trust the certificate on the feed host and be able to reach it from its local-out interface.
- FortiOS limits entries per external resource. The limit depends on model and version, so compare the connector's entry count with `wc -l` on the feed.
- The list is IPv4 only. If the protected service is reachable over IPv6, those clients are not matched.
- Treat this as a coarse pre-filter. Ranges that are not in the geofeed will not match, so cover them with a static address object if needed.

### Check it

```
docker logs starlink-feed                              # expect: v4=<n> allow=['*']
wc -l volumes/starlink-feed/starlink-v4.txt
curl -sI https://<your-host>/feeds/starlink-v4.txt     # expect 200, content-type: text/plain
```

### Optional hardening

In the Caddyfile `/feeds/*` handler, uncomment the `remote_ip` block and set it to the FortiGate's fetch source addresses. Check the real source address in the Caddy access log before enforcing it. The feed contents are public data, so this is optional.

## Operations

| Task | Command |
|---|---|
| Rebuild and restart the builder | `docker compose up -d --build starlink-feed` |
| Rebuild with no cache | `docker compose build --no-cache starlink-feed` |
| Retry the builder now | `docker compose restart starlink-feed` |
| Recreate Caddy after a compose change | `docker compose up -d caddy` |
| Builder logs | `docker logs starlink-feed` |
| Caddy logs | `docker logs caddy` |

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `404` on `/feeds/...` | Wrong filename (it is `starlink-v4.txt`), or the first build has not completed. Check `ls -l volumes/starlink-feed/` |
| `REFUSING: n entries` in builder logs | Below `MIN_V4`, or more than 50% shrink against the previous list. Check the upstream feed, then adjust `MIN_V4` |
| Builder ignores script edits | Rebuild with `docker compose up -d --build starlink-feed` (add `--no-cache` if needed) |
| File exists on the host but Caddy returns 404 | Caddy started before the `/srv/feeds` mount existed. Run `docker compose up -d caddy` |
| Compose ignores your edits | A different compose file is being used. Run `docker compose ls` |
| Feed served with the wrong content type | Keep the `/feeds/*` handler in its own `handle_path` block, separate from any site-wide `templates` or `header` directives |

