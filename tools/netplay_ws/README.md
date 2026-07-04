# Official Taiko Web Netplay WebSocket Node

This directory contains the MVP standalone WebSocket node for official netplay.
The Taiko Web main server stores and publishes official node metadata, while
browsers connect directly to one of these WebSocket nodes.

## Flow

1. Add an official node in `/admin/netplay` on the main server and copy the token
   shown once.
2. Deploy this node with the same `server_id`, `server_token`, and public
   `wss://` endpoint.
3. The node posts heartbeats to `POST /api/netplay/heartbeat`.
4. The public client calls `GET /api/netplay/servers`, receives only online
   official nodes, and opens a WebSocket directly to the chosen node.

## Invite Lifecycle

- Host sends `create_invite`.
- Node returns `invite_created` with an `invite_id` and a 5 minute expiry.
- Guest opens the main-site hash link and sends `join_invite`.
- The invite is consumed after the first successful join.
- Once either player sends `leave` or disconnects, the room is destroyed and the
  invite/session cannot be reused.

## Messages

Client to server:

- `ping`
- `create_invite`
- `join_invite`
- `join` with `invite_id`, kept as a compatibility alias
- `ready`
- `start`
- `input`
- `state`
- `finish`
- `leave`

Server to client:

- `hello`
- `pong`
- `invite_created`
- `invite_joined`
- `player_joined`
- `room_closed`
- `error`

Gameplay messages in the set `ready`, `start`, `input`, `state`, and `finish`
are forwarded to the other player in the same two-player room.

## Run Manually

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
$EDITOR config.json
python server.py --config config.json
```

Environment variables override JSON config. Common variables:

- `TAIKO_MAIN_SERVER`
- `TAIKO_SERVER_ID`
- `TAIKO_SERVER_TOKEN`
- `TAIKO_PUBLIC_ENDPOINT`
- `TAIKO_REGION`
- `TAIKO_LISTEN_HOST`
- `TAIKO_LISTEN_PORT`
- `TAIKO_MAX_PLAYERS`
- `TAIKO_MAX_ROOMS`
- `TAIKO_ALLOWED_ORIGINS`

Use `./setup.sh deploy-netplay-ws` from the repository root for the guided
systemd install.
