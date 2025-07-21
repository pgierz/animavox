from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

import aiohttp
from aiohttp import web
from loguru import logger


@dataclass
class Message:
    """A message to be sent between peers"""

    message_id: str = field(default_factory=lambda: str(uuid4()))
    sender_id: str = ""
    message_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ttl: int = 10  # Time to live (number of hops)

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, json_str: str) -> Message:
        data = json.loads(json_str)
        return cls(**data)


class Peer:
    """A peer in a peer-to-peer network"""

    def __init__(
        self, peer_id: str | None = None, host: str = "0.0.0.0", port: int = 0
    ) -> None:
        self.peer_id = peer_id or str(uuid4())
        self.host = host
        self.port = port if port != 0 else self._find_free_port()
        self.known_peers: dict[str, tuple[str, int]] = {}  # peer_id -> (host, port)
        self.message_handlers: dict[str, Callable[[Message], None]] = {}
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.session: aiohttp.ClientSession | None = None

        # Initialize HTTP server
        self._setup_routes()

    def _find_free_port(self) -> int:
        """Find a free port to use"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", 0))
            return s.getsockname()[1]

    def _setup_routes(self) -> None:
        """Set up HTTP routes for peer communication"""
        self.app.router.add_route("GET", "/ping", self.handle_ping)
        self.app.router.add_route("POST", "/register", self.handle_register)
        self.app.router.add_route("POST", "/message", self.handle_message)
        self.app.router.add_route("GET", "/peers", self.handle_get_peers)

    async def start(self) -> None:
        """Start the peer server"""
        self.session = aiohttp.ClientSession()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"Peer {self.peer_id} running at http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the peer server and clean up"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        if self.session:
            await self.session.close()
        logger.info(f"Peer {self.peer_id} stopped")

    def register_message_handler(
        self, message_type: str, handler: Callable[[Message], None]
    ) -> None:
        """Register a handler for a specific message type"""
        self.message_handlers[message_type] = handler

    async def send_message(self, peer_id: str, message: Message) -> bool:
        """Send a message to a specific peer"""
        if peer_id not in self.known_peers:
            logger.warning(f"Unknown peer: {peer_id}")
            return False

        host, port = self.known_peers[peer_id]
        url = f"http://{host}:{port}/message"

        # Ensure the sender ID is set to our ID
        message.sender_id = self.peer_id

        # Add our port to the payload so the receiver knows how to reach us
        if not hasattr(message, "payload"):
            message.payload = {}
        message.payload["port"] = self.port

        try:
            logger.debug(
                f"Sending message to {peer_id} at {url}: {message.message_type}"
            )
            async with self.session.post(
                url, json=message.__dict__, timeout=5
            ) as response:
                if response.status == 200:
                    logger.debug(f"Message sent successfully to {peer_id}")
                    return True
                error_text = await response.text()
                logger.error(
                    f"Failed to send message to {peer_id}: HTTP {response.status} - {error_text}"
                )
                return False
        except TimeoutError:
            logger.error(f"Timeout sending message to {peer_id} at {url}")
            return False
        except Exception as e:
            logger.error(f"Error sending message to {peer_id} at {url}: {str(e)}")
            return False

    async def broadcast(
        self, message: Message, exclude: set[str] | None = None
    ) -> None:
        """Broadcast a message to all known peers"""
        if exclude is None:
            exclude = set()

        for peer_id in set(self.known_peers.keys()) - exclude:
            await self.send_message(peer_id, message)

    def add_peer(self, peer_id: str, host: str, port: int) -> None:
        """Add a peer to the known peers list"""
        if peer_id != self.peer_id:  # Don't add self
            self.known_peers[peer_id] = (host, port)
            logger.info(f"Added peer {peer_id} at {host}:{port}")

    # HTTP Handlers
    async def handle_ping(self, request: web.Request) -> web.Response:
        """Handle ping requests"""
        return web.Response(text="pong")

    async def handle_message(self, request: web.Request) -> web.Response:
        """Handle incoming messages"""
        try:
            data = await request.json()
            logger.debug(f"Received message data: {data}")
            message = Message(**data)

            # Update sender's address
            if message.sender_id and message.sender_id != self.peer_id:
                # Get the IP from the request's remote
                sender_host = request.remote
                # Try to get the port from the message payload first, then from URL
                sender_port = message.payload.get("port") or (request.url.port or 80)
                logger.info(
                    f"Adding/updating peer {message.sender_id} at {sender_host}:{sender_port}"
                )
                self.add_peer(message.sender_id, sender_host, sender_port)

            # Handle the message if there's a registered handler
            if message.message_type in self.message_handlers:
                try:
                    logger.debug(
                        f"Dispatching message of type '{message.message_type}' to handler"
                    )
                    # Run the handler in the event loop to avoid blocking
                    asyncio.create_task(self._run_message_handler(message))
                except Exception as e:
                    logger.error(
                        f"Error in message handler for {message.message_type}: {e}"
                    )
            else:
                logger.warning(
                    f"No handler registered for message type: {message.message_type}"
                )

            return web.Response(text="Message received")
        except Exception as e:
            logger.error(
                f"Error handling message: {str(e)}\n{getattr(e, '__traceback__', '')}"
            )
            return web.Response(status=400, text=str(e))

    async def _run_message_handler(self, message: Message) -> None:
        """Run a message handler in the event loop"""
        try:
            handler = self.message_handlers.get(message.message_type)
            if asyncio.iscoroutinefunction(handler):
                await handler(message)
            else:
                handler(message)
        except Exception as e:
            logger.error(f"Error in message handler: {e}")

    async def handle_register(self, request: web.Request) -> web.Response:
        """Handle peer registration"""
        try:
            data = await request.json()
            peer_id = data.get("peer_id")
            host = data.get("host")
            port = data.get("port")

            if not all([peer_id, host, port]):
                return web.json_response(
                    {"status": "error", "message": "Missing required fields"},
                    status=400,
                )

            # Don't register ourselves
            if peer_id != self.peer_id:
                self.add_peer(peer_id, host, port)
                logger.debug(f"Registered new peer: {peer_id} at {host}:{port}")

            return web.json_response({"status": "success"})

        except Exception as e:
            logger.error(f"Error in registration handler: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def handle_get_peers(self, request: web.Request) -> web.Response:
        """Return list of known peers including self"""
        peers = [
            {"peer_id": peer_id, "host": host, "port": port}
            for peer_id, (host, port) in self.known_peers.items()
            if peer_id != self.peer_id  # Don't include self in the peer list
        ]
        # Include self in the peer list so others can connect back
        peers.append({"peer_id": self.peer_id, "host": self.host, "port": self.port})
        return web.json_response({"peers": peers})


class Network:
    """Manages a peer-to-peer network"""

    def __init__(self, bootstrap_nodes: list[tuple[str, int]] | None = None) -> None:
        self.peers: dict[str, Peer] = {}
        self.bootstrap_nodes = bootstrap_nodes or []

    async def create_peer(
        self,
        peer_id: str | None = None,
        host: str = "0.0.0.0",
        port: int = 0,
        connect_to_bootstrap: bool = True,
    ) -> Peer:
        """Create and start a new peer

        Args:
            peer_id: Optional peer ID. If not provided, a random UUID will be generated
            host: Host address to bind to (default: 0.0.0.0)
            port: Port to bind to (0 = auto-select)
            connect_to_bootstrap: Whether to automatically connect to bootstrap nodes

        Returns:
            The created and started Peer instance
        """
        peer = Peer(peer_id=peer_id, host=host, port=port)
        await peer.start()
        self.peers[peer.peer_id] = peer

        # Connect to bootstrap nodes if requested
        if connect_to_bootstrap and self.bootstrap_nodes:
            logger.info(f"Connecting to {len(self.bootstrap_nodes)} bootstrap nodes...")
            await asyncio.gather(
                *[
                    self._connect_to_bootstrap(peer, host, port)
                    for host, port in self.bootstrap_nodes
                ],
                return_exceptions=True,  # Don't let one failed connection stop others
            )

        return peer

    async def _connect_to_bootstrap(
        self,
        peer: Peer,
        host: str,
        port: int,
        max_retries: int = 5,
        initial_delay: float = 1.0,
    ) -> bool:
        """Connect a peer to a bootstrap node with exponential backoff retry

        Args:
            peer: The peer to connect
            host: Bootstrap node host
            port: Bootstrap node port
            max_retries: Maximum number of connection attempts
            initial_delay: Initial delay between retries in seconds (will double each retry)

        Returns:
            bool: True if connection was successful, False otherwise
        """
        delay = initial_delay
        last_exception = None

        # Convert host to IP if it's localhost
        if host in ("localhost", "127.0.0.1"):
            host = "127.0.0.1"  # Always use IPv4 for localhost

        logger.debug(f"Attempting to connect to bootstrap node at {host}:{port}")

        for attempt in range(max_retries):
            try:
                # First, register with the bootstrap node
                register_url = f"http://{host}:{port}/register"
                logger.debug(f"Registering with bootstrap node at {register_url}")

                async with aiohttp.ClientSession() as session:
                    # Register our peer with the bootstrap node
                    register_data = {
                        "peer_id": peer.peer_id,
                        "host": peer.host if peer.host != "0.0.0.0" else "127.0.0.1",
                        "port": peer.port,
                    }

                    async with session.post(
                        register_url, json=register_data, timeout=5
                    ) as reg_response:
                        if reg_response.status != 200:
                            error_text = await reg_response.text()
                            last_exception = f"Failed to register with bootstrap: {reg_response.status} - {error_text}"
                            continue

                    # Now get the list of peers
                    url = f"http://{host}:{port}/peers"
                    logger.debug(
                        f"Fetching peers from {url} (attempt {attempt + 1}/{max_retries})"
                    )

                    async with session.get(url, timeout=5) as response:
                        if response.status == 200:
                            data = await response.json()
                            peers = data.get("peers", [])
                            logger.debug(f"Received peer list: {peers}")

                            added_peers = 0
                            for p in peers:
                                peer_id = p.get("peer_id")
                                peer_host = p.get("host")
                                peer_port = p.get("port")

                                # Skip invalid peer entries
                                if not all([peer_id, peer_host, peer_port]):
                                    logger.warning(f"Invalid peer entry: {p}")
                                    continue

                                # Skip ourselves
                                if peer_id == peer.peer_id:
                                    continue

                                # Add the peer
                                peer.add_peer(peer_id, peer_host, peer_port)
                                added_peers += 1

                            logger.info(
                                f"Connected to bootstrap node {host}:{port}, "
                                f"added {added_peers} new peers"
                            )

                            # If we're the first peer, we won't have any peers yet, which is fine
                            if added_peers == 0:
                                logger.info("No other peers found in the network yet")

                            return True
                        else:
                            error_text = await response.text()
                            last_exception = (
                                f"Unexpected status {response.status}: {error_text}"
                            )
            except TimeoutError:
                last_exception = (
                    f"Connection to {host}:{port} timed out after 5 seconds"
                )
            except aiohttp.ClientConnectorError as e:
                last_exception = f"Failed to connect to {host}:{port}: {str(e)}"
            except aiohttp.ClientError as e:
                last_exception = f"HTTP client error: {str(e)}"
            except Exception as e:
                last_exception = f"Unexpected error: {str(e)}"
                import traceback

                logger.error(f"Error traceback: {traceback.format_exc()}")

            if attempt < max_retries - 1:  # Don't sleep on the last attempt
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {last_exception}"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)  # Exponential backoff, max 30 seconds

        logger.error(
            f"Failed to connect to bootstrap node {host}:{port} after "
            f"{max_retries} attempts: {last_exception}"
        )
        return False

    async def stop(self) -> None:
        """Stop all peers in the network"""
        for peer in list(self.peers.values()):
            await peer.stop()
        self.peers.clear()
