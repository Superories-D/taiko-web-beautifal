#!/usr/bin/env python3
import argparse
import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import secrets
import signal
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

try:
    from websockets.asyncio.server import serve
except ImportError:  # pragma: no cover - compatibility for older websockets
    from websockets import serve

from websockets.exceptions import ConnectionClosed


VERSION = "taiko-netplay-ws-mvp/1"
FORWARDED_TYPES = {"ready", "start", "input", "state", "finish"}
DEFAULT_ALLOWED_ORIGINS = [
    "https://taiko.asia",
    "https://www.taiko.asia",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]


def env_value(name: str, default: Any = None) -> Any:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def to_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def normalize_origin(origin: str) -> str:
    parsed = urlparse(origin.strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return origin.strip().rstrip("/")


def load_config(path: Optional[str]) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "main_server": "https://taiko.asia",
        "listen_host": "0.0.0.0",
        "listen_port": 8765,
        "region": "",
        "max_players": 100,
        "max_rooms": 50,
        "max_players_per_ip": 3,
        "heartbeat_interval": 20,
        "invite_ttl_seconds": 300,
        "room_idle_seconds": 900,
        "message_rate_limit_per_second": 25,
        "max_message_bytes": 32768,
        "allowed_origins": DEFAULT_ALLOWED_ORIGINS,
        "allow_missing_origin": False,
    }
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise SystemExit("Config file must contain a JSON object.")
        config.update(data)

    env_map = {
        "main_server": "TAIKO_MAIN_SERVER",
        "server_id": "TAIKO_SERVER_ID",
        "server_token": "TAIKO_SERVER_TOKEN",
        "public_endpoint": "TAIKO_PUBLIC_ENDPOINT",
        "region": "TAIKO_REGION",
        "listen_host": "TAIKO_LISTEN_HOST",
        "listen_port": "TAIKO_LISTEN_PORT",
        "max_players": "TAIKO_MAX_PLAYERS",
        "max_rooms": "TAIKO_MAX_ROOMS",
        "max_players_per_ip": "TAIKO_MAX_PLAYERS_PER_IP",
        "heartbeat_interval": "TAIKO_HEARTBEAT_INTERVAL",
        "invite_ttl_seconds": "TAIKO_INVITE_TTL_SECONDS",
        "room_idle_seconds": "TAIKO_ROOM_IDLE_SECONDS",
        "message_rate_limit_per_second": "TAIKO_MESSAGE_RATE_LIMIT_PER_SECOND",
        "max_message_bytes": "TAIKO_MAX_MESSAGE_BYTES",
        "allowed_origins": "TAIKO_ALLOWED_ORIGINS",
        "allow_missing_origin": "TAIKO_ALLOW_MISSING_ORIGIN",
    }
    for key, env_name in env_map.items():
        value = env_value(env_name)
        if value is not None:
            config[key] = value

    config["listen_port"] = to_int(config.get("listen_port"), 8765, 1, 65535)
    config["max_players"] = to_int(config.get("max_players"), 100, 2, 10000)
    config["max_rooms"] = to_int(config.get("max_rooms"), 50, 1, 5000)
    config["max_players_per_ip"] = to_int(config.get("max_players_per_ip"), 3, 1, 1000)
    config["heartbeat_interval"] = to_int(config.get("heartbeat_interval"), 20, 5, 120)
    config["invite_ttl_seconds"] = to_int(config.get("invite_ttl_seconds"), 300, 60, 300)
    config["room_idle_seconds"] = to_int(config.get("room_idle_seconds"), 900, 60, 7200)
    config["message_rate_limit_per_second"] = to_int(config.get("message_rate_limit_per_second"), 25, 5, 200)
    config["max_message_bytes"] = to_int(config.get("max_message_bytes"), 32768, 1024, 262144)
    config["allowed_origins"] = [normalize_origin(origin) for origin in parse_list(config.get("allowed_origins"))]
    config["allow_missing_origin"] = to_bool(config.get("allow_missing_origin"), False)
    config["main_server"] = str(config.get("main_server") or "").rstrip("/")

    missing = [
        key for key in ("main_server", "server_id", "server_token", "public_endpoint")
        if not str(config.get(key) or "").strip()
    ]
    if missing:
        raise SystemExit("Missing required config keys: " + ", ".join(missing))
    return config


def utc_iso_from_monotonic_delay(seconds: int) -> str:
    timestamp = time.time() + seconds
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def safe_name(value: Any) -> str:
    name = str(value or "").strip()[:25]
    return name or "Player"


@dataclass
class Client:
    client_id: str
    websocket: Any
    ip: str
    name: str = "Player"
    room_id: Optional[str] = None
    last_seen: float = field(default_factory=time.monotonic)
    rate_window_started: float = field(default_factory=time.monotonic)
    rate_count: int = 0


@dataclass
class Room:
    room_id: str
    invite_id: str
    host_id: str
    clients: List[str]
    created_at: float
    expires_at: float
    last_activity: float
    invite_used: bool = False


class OfficialNetplayServer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.clients: Dict[str, Client] = {}
        self.rooms: Dict[str, Room] = {}
        self.invites: Dict[str, str] = {}
        self.ip_counts: Dict[str, int] = {}
        self.stop_event = asyncio.Event()
        self.log = logging.getLogger("taiko.netplay_ws")

    @property
    def heartbeat_url(self) -> str:
        return self.config["main_server"] + "/api/netplay/heartbeat"

    def get_headers(self, websocket: Any) -> Any:
        headers = getattr(websocket, "request_headers", None)
        if headers is not None:
            return headers
        request = getattr(websocket, "request", None)
        return getattr(request, "headers", {}) or {}

    def get_origin(self, websocket: Any) -> Optional[str]:
        headers = self.get_headers(websocket)
        try:
            origin = headers.get("Origin")
        except AttributeError:
            origin = None
        return normalize_origin(origin) if origin else None

    def origin_allowed(self, origin: Optional[str]) -> bool:
        allowed = self.config.get("allowed_origins") or []
        if "*" in allowed:
            return True
        if not origin:
            return bool(self.config.get("allow_missing_origin"))
        return origin in allowed

    def remote_ip(self, websocket: Any) -> str:
        remote = getattr(websocket, "remote_address", None)
        if isinstance(remote, tuple) and remote:
            return str(remote[0])
        return "unknown"

    def player_count(self) -> int:
        return len(self.clients)

    def room_count(self) -> int:
        return len(self.rooms)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, self.stop_event.set)

        cleanup_task = asyncio.create_task(self.cleanup_loop())
        heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        host = self.config["listen_host"]
        port = self.config["listen_port"]
        self.log.info("Starting official netplay node %s on %s:%s", self.config["server_id"], host, port)
        async with serve(
            self.handler,
            host,
            port,
            max_size=self.config["max_message_bytes"],
            ping_interval=20,
            ping_timeout=20,
        ):
            await self.stop_event.wait()

        cleanup_task.cancel()
        heartbeat_task.cancel()
        await asyncio.gather(cleanup_task, heartbeat_task, return_exceptions=True)
        await self.send_heartbeat("offline")

    async def handler(self, websocket: Any, path: Optional[str] = None) -> None:
        origin = self.get_origin(websocket)
        if not self.origin_allowed(origin):
            await websocket.close(code=1008, reason="origin_not_allowed")
            return

        ip = self.remote_ip(websocket)
        if self.player_count() >= self.config["max_players"]:
            await websocket.close(code=1013, reason="server_full")
            return
        if self.ip_counts.get(ip, 0) >= self.config["max_players_per_ip"]:
            await websocket.close(code=1013, reason="too_many_connections")
            return

        client = Client(client_id=secrets.token_urlsafe(9), websocket=websocket, ip=ip)
        self.clients[client.client_id] = client
        self.ip_counts[ip] = self.ip_counts.get(ip, 0) + 1
        await self.send(client, {
            "type": "hello",
            "server_id": self.config["server_id"],
            "client_id": client.client_id,
            "invite_ttl_seconds": self.config["invite_ttl_seconds"],
            "max_room_size": 2,
        })

        try:
            async for raw in websocket:
                if isinstance(raw, bytes):
                    if len(raw) > self.config["max_message_bytes"]:
                        await websocket.close(code=1009, reason="message_too_large")
                        break
                    raw = raw.decode("utf-8", errors="replace")
                elif len(raw.encode("utf-8")) > self.config["max_message_bytes"]:
                    await websocket.close(code=1009, reason="message_too_large")
                    break

                if not self.rate_allowed(client):
                    await self.send_error(client, "rate_limited", "Too many messages.")
                    await websocket.close(code=1008, reason="rate_limited")
                    break

                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await self.send_error(client, "invalid_json", "Invalid JSON.")
                    continue
                if not isinstance(message, dict):
                    await self.send_error(client, "invalid_message", "Message must be an object.")
                    continue
                await self.handle_message(client, message)
        except ConnectionClosed:
            pass
        except Exception:
            self.log.exception("Unhandled client error")
        finally:
            await self.cleanup_client(client)

    def rate_allowed(self, client: Client) -> bool:
        now = time.monotonic()
        if now - client.rate_window_started >= 1:
            client.rate_window_started = now
            client.rate_count = 0
        client.rate_count += 1
        return client.rate_count <= self.config["message_rate_limit_per_second"]

    async def handle_message(self, client: Client, message: Dict[str, Any]) -> None:
        client.last_seen = time.monotonic()
        msg_type = str(message.get("type") or "").strip()
        if msg_type == "ping":
            await self.send(client, {"type": "pong", "server_time": int(time.time() * 1000)})
            return
        if msg_type == "create_invite":
            await self.create_invite(client, message)
            return
        if msg_type in {"join_invite", "join"}:
            await self.join_invite(client, message)
            return
        if msg_type == "leave":
            await self.leave_room(client, "player_left")
            return
        if msg_type in FORWARDED_TYPES:
            await self.forward_to_room(client, message)
            return
        await self.send_error(client, "unknown_type", "Unknown message type.")

    async def create_invite(self, client: Client, message: Dict[str, Any]) -> None:
        self.cleanup_expired_rooms()
        if client.room_id:
            await self.send_error(client, "already_in_room", "Already in a room.")
            return
        if self.room_count() >= self.config["max_rooms"]:
            await self.send_error(client, "rooms_full", "Server room limit reached.")
            return

        client.name = safe_name(message.get("player_name"))
        room_id = self.unique_token("room", self.rooms)
        invite_id = self.unique_token("invite", self.invites)
        now = time.monotonic()
        ttl = self.config["invite_ttl_seconds"]
        room = Room(
            room_id=room_id,
            invite_id=invite_id,
            host_id=client.client_id,
            clients=[client.client_id],
            created_at=now,
            expires_at=now + ttl,
            last_activity=now,
        )
        self.rooms[room_id] = room
        self.invites[invite_id] = room_id
        client.room_id = room_id
        await self.send(client, {
            "type": "invite_created",
            "room_id": room_id,
            "invite_id": invite_id,
            "expires_at": utc_iso_from_monotonic_delay(ttl),
            "ttl_seconds": ttl,
            "server_id": self.config["server_id"],
        })

    async def join_invite(self, client: Client, message: Dict[str, Any]) -> None:
        self.cleanup_expired_rooms()
        if client.room_id:
            await self.send_error(client, "already_in_room", "Already in a room.")
            return

        invite_id = str(message.get("invite_id") or message.get("room_id") or "").strip()
        room_id = self.invites.get(invite_id)
        room = self.rooms.get(room_id or "")
        if not invite_id or not room or room.invite_used or time.monotonic() > room.expires_at:
            await self.send_error(client, "invite_expired", "This invite is no longer available.")
            return
        if len(room.clients) >= 2:
            await self.send_error(client, "room_full", "Room is full.")
            return

        client.name = safe_name(message.get("player_name"))
        room.clients.append(client.client_id)
        room.invite_used = True
        room.last_activity = time.monotonic()
        client.room_id = room.room_id
        self.invites.pop(invite_id, None)

        await self.send(client, {
            "type": "invite_joined",
            "room_id": room.room_id,
            "players": self.room_players(room),
        })
        await self.broadcast(room, {
            "type": "player_joined",
            "room_id": room.room_id,
            "player": self.public_player(client, host=False),
            "players": self.room_players(room),
        }, exclude=client.client_id)

    async def leave_room(self, client: Client, reason: str) -> None:
        if not client.room_id:
            await self.send(client, {"type": "left"})
            return
        room = self.rooms.get(client.room_id)
        if room:
            await self.close_room(room, reason)
        client.room_id = None

    async def cleanup_client(self, client: Client) -> None:
        if client.client_id not in self.clients:
            return
        await self.leave_room(client, "player_left")
        self.clients.pop(client.client_id, None)
        if self.ip_counts.get(client.ip, 0) <= 1:
            self.ip_counts.pop(client.ip, None)
        else:
            self.ip_counts[client.ip] -= 1

    async def close_room(self, room: Room, reason: str) -> None:
        self.invites.pop(room.invite_id, None)
        self.rooms.pop(room.room_id, None)
        payload = {"type": "room_closed", "room_id": room.room_id, "reason": reason}
        for client_id in list(room.clients):
            client = self.clients.get(client_id)
            if client:
                client.room_id = None
                await self.send(client, payload)

    async def forward_to_room(self, client: Client, message: Dict[str, Any]) -> None:
        room = self.rooms.get(client.room_id or "")
        if not room or client.client_id not in room.clients:
            await self.send_error(client, "not_in_room", "Not in a room.")
            return
        room.last_activity = time.monotonic()
        forwarded = dict(message)
        forwarded["from"] = client.client_id
        forwarded["player_name"] = client.name
        await self.broadcast(room, forwarded, exclude=client.client_id)

    async def broadcast(self, room: Room, message: Dict[str, Any], exclude: Optional[str] = None) -> None:
        for client_id in list(room.clients):
            if client_id == exclude:
                continue
            client = self.clients.get(client_id)
            if client:
                await self.send(client, message)

    async def send(self, client: Client, message: Dict[str, Any]) -> None:
        try:
            await client.websocket.send(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        except ConnectionClosed:
            pass

    async def send_error(self, client: Client, code: str, message: str) -> None:
        await self.send(client, {"type": "error", "code": code, "message": message})

    def unique_token(self, prefix: str, existing: Dict[str, Any]) -> str:
        for _ in range(20):
            value = f"{prefix}_{secrets.token_urlsafe(7).replace('-', '').replace('_', '')[:10]}"
            if value not in existing:
                return value
        raise RuntimeError("Could not allocate token")

    def public_player(self, client: Client, host: bool) -> Dict[str, Any]:
        return {"client_id": client.client_id, "name": client.name, "host": host}

    def room_players(self, room: Room) -> List[Dict[str, Any]]:
        players = []
        for client_id in room.clients:
            client = self.clients.get(client_id)
            if client:
                players.append(self.public_player(client, host=client_id == room.host_id))
        return players

    def cleanup_expired_rooms(self) -> None:
        now = time.monotonic()
        expired: List[Room] = []
        for room in list(self.rooms.values()):
            if not room.invite_used and now > room.expires_at:
                expired.append(room)
            elif now - room.last_activity > self.config["room_idle_seconds"]:
                expired.append(room)
        for room in expired:
            self.invites.pop(room.invite_id, None)
            self.rooms.pop(room.room_id, None)
            for client_id in list(room.clients):
                client = self.clients.get(client_id)
                if client:
                    client.room_id = None
                    asyncio.create_task(self.send(client, {
                        "type": "room_closed",
                        "room_id": room.room_id,
                        "reason": "invite_expired" if not room.invite_used else "inactive",
                    }))

    async def cleanup_loop(self) -> None:
        while not self.stop_event.is_set():
            self.cleanup_expired_rooms()
            await asyncio.sleep(10)

    async def heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            await self.send_heartbeat("online")
            await asyncio.sleep(self.config["heartbeat_interval"])

    async def send_heartbeat(self, status: str) -> None:
        payload = {
            "server_id": self.config["server_id"],
            "endpoint": self.config["public_endpoint"],
            "region": self.config.get("region") or "",
            "current_players": self.player_count(),
            "current_rooms": self.room_count(),
            "max_players": self.config["max_players"],
            "max_rooms": self.config["max_rooms"],
            "version": VERSION,
            "status": status,
        }
        headers = {
            "Authorization": "Bearer " + self.config["server_token"],
            "Content-Type": "application/json",
            "User-Agent": VERSION,
        }

        def post() -> requests.Response:
            return requests.post(self.heartbeat_url, json=payload, headers=headers, timeout=(3.05, 8))

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, post)
            if response.status_code >= 400:
                self.log.warning("Heartbeat failed with HTTP %s", response.status_code)
        except Exception as exc:
            self.log.warning("Heartbeat failed: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Taiko Web official netplay WebSocket node")
    parser.add_argument("--config", help="Path to JSON config file")
    parser.add_argument("--log-level", default=env_value("TAIKO_LOG_LEVEL", "INFO"))
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = load_config(args.config)
    asyncio.run(OfficialNetplayServer(config).run())


if __name__ == "__main__":
    main()
