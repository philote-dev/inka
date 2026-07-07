# pgrep hosting roadmap

Date: 2026-07-06. Status: reference. Written for L6 (WI4 of the structural de-Anki design). This
documents how pgrep syncs today and how to grow it. No servers are built by this doc.

pgrep is offline-first. Study and AI-off scoring never need a server. Sync is what carries a
learner's progress between their desktop and phone, so the "server" here is only the sync endpoint.

## Part 1: self-host on your own Mac (where we are now)

### What runs today

`just sync-server` runs `tools/sync-server.py`, which is Anki's own built-in sync server (the same
engine the app syncs against, no third-party code). Its defaults:

- User and password: `SYNC_USER1=pgrep:pgrep`.
- Port: `SYNC_PORT` or `8090`.
- Binds to `0.0.0.0:8090`, so it is reachable from other devices on your network, not just
  localhost.
- Plain HTTP (no TLS).

The desktop and phone point at it from pgrep Settings to Sync, with the URL
`http://<your-mac-ip>:8090/` and the account above. This is the setup the two devices in the current
logs are already using.

### Keep it running across reboots

Today the server lives only as long as the `just sync-server` terminal. To make it durable, run it
as a launchd LaunchAgent so macOS starts it at login and restarts it if it exits. A minimal
`~/Library/LaunchAgents/com.pgrep.syncserver.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>com.pgrep.syncserver</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/philote/projects/inka/out/pyenv/bin/python</string>
    <string>/Users/philote/projects/inka/tools/sync-server.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SYNC_USER1</key> <string>pgrep:CHANGE-ME</string>
    <key>SYNC_PORT</key>  <string>8090</string>
    <key>SYNC_BASE</key>  <string>/Users/philote/pgrep-sync-data</string>
  </dict>
  <key>RunAtLoad</key>        <true/>
  <key>KeepAlive</key>        <true/>
  <key>StandardOutPath</key>  <string>/Users/philote/Library/Logs/pgrep-sync.log</string>
  <key>StandardErrorPath</key><string>/Users/philote/Library/Logs/pgrep-sync.err.log</string>
</dict>
</plist>
```

Load it with `launchctl load ~/Library/LaunchAgents/com.pgrep.syncserver.plist`. Because the Mac can
sleep, keep it awake while it should serve (System Settings energy options, or run under
`caffeinate`), otherwise the phone cannot reach it while the Mac naps.

### Where the data lives and how to back it up

The server stores each user's collection under its base folder. Set `SYNC_BASE` (as above) so you
know exactly where it is, then back that folder up: Time Machine covers it, or a scheduled copy to
an external disk or a cloud folder. The collections are small (text and SVG), so backups are cheap.

### Reaching it from the phone

- On the same Wi-Fi (LAN): point the phone at `http://<your-mac-ip>:8090/`. Find the IP in System
  Settings to Network. This is the simplest path and needs nothing extra.
- Away from home (over the internet): do not port-forward `8090` directly, it is plain HTTP. Use a
  tunnel instead. Tailscale is the easiest: install it on the Mac and the phone, join the same
  tailnet, and point the phone at the Mac's Tailscale IP on `8090`. For a public HTTPS URL, a
  Cloudflare Tunnel terminates TLS and forwards to `8090`.

### Security and limits (be honest about this setup)

- The default `pgrep:pgrep` credential is a placeholder. Change it to a strong password via
  `SYNC_USER1`.
- Plain HTTP is unencrypted. It is acceptable on a trusted home LAN or over Tailscale (which
  encrypts), not on the open internet.
- The server is only up when the Mac is on and awake.
- It is single-user and has no dashboard, metrics, or automated backups.

This is enough for you plus a few testers. It is not a multi-user production service.

## Part 2: cloud hosting (later, delegated)

Move here when you want an always-on, HTTPS, managed, multi-user service with self-serve signup.
The client code does not change: pgrep still points at a sync URL with a credential, so this choice
can be made later without touching the app.

### The recommended shape (pick the flavor at decision time)

- Host: a small VPS. Hetzner CPX22 is about $8/month (self-managed, more control). Fly.io is about
  $5/month usage-based (less server maintenance).
- Sync server: the `anki-sync-server-enhanced` Docker image, built from official Anki source. It
  adds a multi-user `user-manager` CLI, hashed passwords, nightly backups with S3 upload, a
  dashboard, metrics, and fail2ban.
- TLS and proxy: Caddy (automatic HTTPS), or the image's built-in TLS.
- Backups: Cloudflare R2 (no egress fees), pennies a month for text and SVG collections.
- Auth, in two steps: (a) closed beta uses the server's built-in `user-manager` CLI, no extra cost;
  (b) production adds Firebase Auth plus a small provisioning function that creates the matching
  sync account on first login. Heavy study data still syncs over Anki's protocol; auth only owns
  identity.

### Rough costs

About $10/month to launch (tens of users), scaling to about $10 to $25/month into the low thousands
because local-first sync is small and intermittent and pgrep content is mostly text and SVG. One
time or yearly: Apple Developer $99/year, Google Play $25 once, a domain about $12/year.

### Decision: delegated

The final host, TLS, and auth choices are delegated. Because the client is identical across all of
these, the decision does not block any app work and can be made when the beta is ready to grow.

### Deferred: a browser (web) app

A true web app needs the engine compiled to WASM or run server-side, plus browser storage. It is its
own project. Desktop plus phone plus sync is the native, cheap path, so web stays parked here.
