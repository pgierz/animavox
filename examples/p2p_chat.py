#!/usr/bin/env python3
"""
A simple P2P chat application demonstrating the P2P network functionality.

This example creates a simple chat application where each peer can:
1. Join the network using a bootstrap node
2. Discover other peers
3. Send and receive chat messages
4. See when peers join/leave

Usage:
    # Start the first peer (bootstrap node)
    python examples/p2p_chat.py --port 8000

    # Start additional peers (in new terminals)
    python examples/p2p_chat.py --port 8001 --bootstrap localhost:8000
    python examples/p2p_chat.py --port 8002 --bootstrap localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
import uuid
from pathlib import Path
import os

from loguru import logger

# Add the parent directory to path so we can import animavox
sys.path.append(str(Path(__file__).parent.parent))

from animavox.network import Message, Network

logger.remove()
logger.add(sys.stdout, level=os.environ.get("LOG_LEVEL", "INFO"))


class ChatApp:
    def __init__(
        self, port: int, bootstrap_nodes: list[tuple[str, int]] | None = None
    ) -> None:
        self.port = port
        # Convert bootstrap nodes to use 127.0.0.1 for localhost to avoid IPv6 issues
        self.bootstrap_nodes = [
            (host if host != "localhost" else "127.0.0.1", port)
            for host, port in (bootstrap_nodes or [])
        ]
        # Initialize network with bootstrap nodes but don't connect yet
        self.network = Network(bootstrap_nodes=self.bootstrap_nodes)
        self.ping_responses = {}  # Track ping responses
        self.peer = None
        self.running = False
        self.user_input_task = None

    async def start(self):
        """Start the chat application"""
        self.running = True

        logger.debug(f"Starting peer with bootstrap nodes: {self.bootstrap_nodes}")

        # Create and start a new peer with automatic bootstrap connection
        # Use '127.0.0.1' as the host to ensure consistent binding
        self.peer = await self.network.create_peer(
            host="127.0.0.1",
            port=self.port,
            connect_to_bootstrap=bool(self.bootstrap_nodes),
        )

        # Register message handlers
        self.peer.register_message_handler("chat", self.handle_chat_message)
        self.peer.register_message_handler("peer_joined", self.handle_peer_joined)
        self.peer.register_message_handler("peer_left", self.handle_peer_left)
        self.peer.register_message_handler("ping", self.handle_ping)
        self.peer.register_message_handler("pong", self.handle_pong)

        logger.info(f"Chat peer started with ID: {self.peer.peer_id}")
        logger.info(f"Listening on port {self.port}")
        logger.debug(f"Known peers after startup: {self.peer.known_peers}")

        # Start user input loop in the background
        self.user_input_task = asyncio.create_task(self.user_input_loop())

        # Notify others that we've joined
        await self.broadcast_peer_joined()
        logger.debug(
            f"After broadcast_peer_joined, known peers: {self.peer.known_peers}"
        )

        try:
            # Keep the application running
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self):
        """Stop the chat application"""
        if not self.running:
            return

        self.running = False

        # Cancel the user input task
        if self.user_input_task and not self.user_input_task.done():
            self.user_input_task.cancel()
            try:
                await self.user_input_task
            except asyncio.CancelledError:
                pass

        # Notify others that we're leaving
        if self.peer:
            await self.broadcast_peer_left()
            await self.network.stop()

        logger.info("Chat application stopped")

    async def user_input_loop(self):
        """Handle user input in a loop"""
        try:
            while self.running:
                try:
                    # Use asyncio.to_thread to handle input without blocking
                    message = await asyncio.to_thread(input, "\nYou: ")
                    if message.lower() in ("exit", "quit", "q"):
                        await self.stop()
                        break
                    elif message.lower() == "ping":
                        await self.broadcast_ping()
                    # Send the message to all peers
                    elif message.strip():
                        await self.send_chat_message(message)

                except (EOFError, KeyboardInterrupt):
                    await self.stop()
                    break
                except Exception as e:
                    logger.error(f"Error handling input: {e}")
        except asyncio.CancelledError:
            pass

    async def send_chat_message(self, text: str) -> None:
        """Send a chat message to all peers"""
        if not self.peer:
            return

        message = Message(
            sender_id=self.peer.peer_id, message_type="chat", payload={"text": text}
        )
        await self.peer.broadcast(message)
        logger.info(f"You: {text}")

    async def broadcast_peer_joined(self) -> None:
        """Notify all peers that we've joined"""
        if not self.peer:
            return

        message = Message(
            sender_id=self.peer.peer_id,
            message_type="peer_joined",
            payload={
                "peer_id": self.peer.peer_id,
                "host": self.peer.host if self.peer.host != "0.0.0.0" else "127.0.0.1",
                "port": self.peer.port,
            },
        )
        logger.info("Broadcasting peer_joined message to all known peers")
        await self.peer.broadcast(message)

    async def broadcast_peer_left(self) -> None:
        """Notify all peers that we're leaving"""
        if not self.peer:
            return

        message = Message(
            sender_id=self.peer.peer_id,
            message_type="peer_left",
            payload={"peer_id": self.peer.peer_id},
        )
        await self.peer.broadcast(message)

    async def broadcast_ping(self) -> None:
        """Broadcast a ping to all peers and wait for responses"""
        if not self.peer:
            logger.warning("Cannot ping: peer not initialized")
            return

        ping_id = str(uuid.uuid4())
        known_peers = self.peer.known_peers

        if not known_peers:
            logger.warning(f"No known peers to ping. Known peers: {known_peers}")
            return

        message = Message(
            sender_id=self.peer.peer_id,
            message_type="ping",
            payload={"ping_id": ping_id, "timestamp": time.time()},
        )

        logger.info(f"Sending ping {ping_id} to {len(known_peers)} peers...")
        logger.debug(f"Recipients: {known_peers}")

        await self.peer.broadcast(message)

        # Schedule a task to check for responses after a delay
        asyncio.create_task(self._check_ping_responses(ping_id, time.time()))

    async def _check_ping_responses(self, ping_id: str, start_time: float) -> None:
        """Check which peers responded to our ping"""
        await asyncio.sleep(2)  # Wait 2 seconds for responses

        total_peers = len(self.peer.known_peers)
        if total_peers == 0:
            logger.warning("No known peers to check for ping responses")
            return

        responded = self.ping_responses.get(ping_id, set())
        response_time = (time.time() - start_time) * 1000  # Convert to milliseconds

        logger.info(f"Ping results (took {response_time:.2f}ms):")
        logger.info(f"  - {len(responded)}/{total_peers} peers responded")

        if responded:
            logger.debug(f"Responded peers: {responded}")
        if total_peers > len(responded):
            missing = set(self.peer.known_peers.keys()) - responded
            logger.debug(f"Missing responses from: {missing}")

        # Clean up
        if ping_id in self.ping_responses:
            del self.ping_responses[ping_id]

    async def handle_ping(self, message: Message) -> None:
        """Handle incoming ping requests"""
        if message.sender_id == self.peer.peer_id:
            return  # Ignore our own pings

        ping_id = message.payload.get("ping_id")
        if not ping_id:
            return

        # Respond with a pong
        response = Message(
            sender_id=self.peer.peer_id,
            message_type="pong",
            payload={
                "ping_id": ping_id,
                "in_response_to": message.sender_id,
                "timestamp": time.time(),
            },
        )
        await self.peer.send_message(message.sender_id, response)

    async def handle_pong(self, message: Message) -> None:
        """Handle pong responses to our pings"""
        ping_id = message.payload.get("ping_id")
        if not ping_id or message.sender_id == self.peer.peer_id:
            return

        # Track this response
        if ping_id not in self.ping_responses:
            self.ping_responses[ping_id] = set()
        self.ping_responses[ping_id].add(message.sender_id)

    # Message handlers
    async def handle_chat_message(self, message: Message) -> None:
        """Handle incoming chat messages"""
        if message.sender_id == self.peer.peer_id:
            return  # Ignore our own messages

        # Make sure we have the latest peer information
        if message.sender_id in self.peer.known_peers:
            host, port = self.peer.known_peers[message.sender_id]
            logger.info(
                f"Peer {message.sender_id[:8]}@{port}: {message.payload.get('text', '(no text)')}"
            )
        else:
            logger.info(
                f"Peer {message.sender_id[:8]}: {message.payload.get('text', '(no text)')}"
            )

        # Log the full message for debugging
        logger.debug(f"Full message from {message.sender_id}: {message.__dict__}")

    async def handle_peer_joined(self, message: Message) -> None:
        """Handle peer joined notifications"""
        peer_id = message.payload["peer_id"]
        if peer_id == self.peer.peer_id:
            logger.debug(
                f"Ignoring peer_joined message from ourselves. Message Peer ID: {peer_id=} == {self.peer.peer_id=}"
            )
            return  # Ignore our own messages

        # Extract peer details
        peer_host = message.payload.get("host", "127.0.0.1")
        peer_port = message.payload.get("port")

        if not peer_port:
            logger.warning(f"Received peer_joined without port: {message.payload}")
            return

        logger.info(f"Peer {peer_id[:8]} joined the chat (port: {peer_port})")

        # Add the peer to our known peers if not already present
        if peer_id not in self.peer.known_peers:
            self.peer.add_peer(peer_id, peer_host, peer_port)
            logger.debug(
                f"Added peer {peer_id} at {peer_host}:{peer_port} to known peers"
            )

    async def handle_peer_left(self, message: Message) -> None:
        """Handle peer left notifications"""
        peer_id = message.payload["peer_id"]
        if peer_id != self.peer.peer_id:  # Don't notify about ourselves
            logger.info(f"Peer {peer_id[:8]} left the chat")


def parse_bootstrap_nodes(nodes_str: str) -> list[tuple[str, int]]:
    """Parse bootstrap nodes from string format 'host:port,host2:port2'"""
    if not nodes_str:
        return []

    nodes = []
    for node in nodes_str.split(","):
        host, port = node.strip().rsplit(":", 1)
        nodes.append((host, int(port)))
    return nodes


async def main():
    logger.debug("Starting P2P Chat Application...")
    parser = argparse.ArgumentParser(description="P2P Chat Application")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--bootstrap", type=str, help="Bootstrap node (host:port)")
    args = parser.parse_args()

    # Parse bootstrap nodes
    bootstrap_nodes = []
    if args.bootstrap:
        bootstrap_nodes = parse_bootstrap_nodes(args.bootstrap)

    # Set up signal handlers
    app = ChatApp(port=args.port, bootstrap_nodes=bootstrap_nodes)

    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        asyncio.create_task(app.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await app.start()
    except Exception as e:
        logger.error(f"Error in chat application: {e}")
    finally:
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
