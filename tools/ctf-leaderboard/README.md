# CTF leaderboard display

A static page that loops between the team and individual leaderboards of one CTF event.
Use it on an unattended screen.

## Files

| File | Purpose |
|---|---|
| `index.html` | The display page. It reads `data.json` from its own directory. |
| `refresh.sh` | Writes `data.json` from the live event. It runs a read-only scoring query in a portal pod. |

## Why the page does not call the portal

The portal's public scoreboard API returns only team rankings in team mode.
The API also sends no CORS headers, so a page on another host cannot read it.
`refresh.sh` reads both leaderboards on the operator host and writes them beside the page.

## Run it

1. Put `index.html` in a directory that a static web server serves.
2. Start the refresher on a host with `kubectl` access to the tenant cluster:

   ```bash
   KUBE_CONTEXT=<tenant cluster context> \
   EVENT_ID=<CTF event UUID> \
   OUT=<served directory>/data.json \
   tools/ctf-leaderboard/refresh.sh
   ```

3. Open the page in a browser. Press F for full screen.

## Page options

| Parameter | Default | Effect |
|---|---|---|
| `rows` | 14 | Rows on each screen. |
| `secs` | 12 | Seconds on each screen. |
| `all` | off | `all=1` also shows entries with no points. |
| `title` | `CTF` | Event name in the heading. |

## Data

`data.json` holds rank, name, team, solves, score, and team member count.
It holds no email addresses, internal IDs, or flags.
The refresher needs a valid cloud login for `kubectl`.
If the login expires, the page keeps the last data.
