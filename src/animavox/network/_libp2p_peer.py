"""LibP2P implementation of the P2P peer interface."""

from __future__ import annotations

import json
import logging

from libp2p import new_host
from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.floodsub import FloodSub

from ._abc import AbstractPeer, MessageHandler, StatusHandler
from .message import Message, PeerInfo

logger = logging.getLogger(__name__)


class LibP2PPeer(AbstractPeer):
    """A peer in the P2P network using libp2p for communication."""

    def __init__(
        self,
        handle: str,
        host: str = "0.0.0.0",
        port: int = 0,
        peer_id: str | None = None,
    ) -> None:
        """Initialize a new NetworkPeer using libp2p.

        Args:
            handle: A human-readable identifier for this peer.
            host: The host address to bind to.
            port: The port to bind to (0 for auto-select).
            peer_id: Optional unique identifier for this peer.
        """
        self.handle = handle
        self.host = host
        self.port = port
        self.peer_id = peer_id or handle

        # Libp2p components
        self._host: BasicHost | None = None
        self._pubsub: FloodSub | None = None

        # Message handling
        self._message_handlers: dict[str, MessageHandler] = {}
        self._status_handlers: list[StatusHandler] = []

        # Peer management
        self.known_peers: dict[str, PeerInfo] = {}
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Whether the peer's server is currently running."""
        return self._is_running

    def get_info(self) -> PeerInfo:
        """Get information about this peer."""
        if not self._host:
            return PeerInfo(
                handle=self.handle,
                host=self.host,
                port=self.port,
                status="disconnected",
            )

        _ = [
            str(addr) for addr in self._host.get_addrs()
        ]  # Store in _ to indicate it's intentionally unused
        return PeerInfo(
            handle=self.handle,
            host=self.host,
            port=self.port,
            status="connected" if self._is_running else "disconnected",
        )

    async def start(self) -> None:
        """Start the libp2p node and initialize resources."""
        if self._is_running:
            return

        try:
            # Initialize libp2p host
            self._host = await new_host(
                transport_opt=["/ip4/0.0.0.0/tcp/0"],  # Let OS choose port
            )

            # Initialize pubsub for message broadcasting
            self._pubsub = FloodSub()

            # Set up protocol handlers
            await self._host.set_stream_handler(
                "/animavox/1.0.0",
                self._handle_stream,
            )

            # Start the host
            await self._host.get_network().listen()
            self._is_running = True

            # Notify status change
            await self._notify_status_change(self.peer_id, "connected")
            logger.info(f"LibP2P peer started with ID: {self._host.get_id().pretty()}")

        except Exception as e:
            logger.error(f"Failed to start LibP2P peer: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop the peer and clean up resources."""
        if not self._is_running or not self._host:
            return

        try:
            # Close all connections
            await self._host.close()
            self._is_running = False

            # Notify status change
            await self._notify_status_change(self.peer_id, "disconnected")
            logger.info("LibP2P peer stopped")

        except Exception as e:
            logger.error(f"Error stopping LibP2P peer: {e}")
        finally:
            self._host = None
            self._pubsub = None

    # Message handling
    def on_message(
        self, message_type: str | MessageHandler, handler: MessageHandler | None = None
    ):
        """Register a message handler for a specific message type.

        Can be used as a decorator or a regular function.
        """
        if isinstance(message_type, str) and handler is not None:
            self._message_handlers[message_type] = handler
            return handler
        elif callable(message_type):
            # Used as a decorator without arguments
            self._message_handlers[message_type.__name__] = message_type
            return message_type

        raise ValueError("Invalid arguments to on_message")

    def on_peer_status_change(self, handler: StatusHandler):
        """Register a handler for peer status changes.

        The handler will be called with (peer_id: str, status: str) whenever
        a peer's connection status changes.
        """
        self._status_handlers.append(handler)
        return handler

    # Peer management
    async def connect_to_peer(self, peer_addr: str) -> bool:
        """Connect to a peer using its multiaddress.

        Args:
            peer_addr: Multiaddress of the peer to connect to (e.g., "/ip4/127.0.0.1/tcp/12345/p2p/QmPeerId")

        Returns:
            bool: True if connection was successful, False otherwise
        """
        if not self._host:
            logger.error("Cannot connect to peer: Host not initialized")
            return False

        try:
            peer_info = info_from_p2p_addr(peer_addr)
            await self._host.connect(peer_info)
            logger.info(f"Connected to peer: {peer_info.peer_id.pretty()}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to peer {peer_addr}: {e}")
            return False

    async def send_message(self, recipient_id: str, message: Message | dict) -> bool:
        """Send a direct message to a specific peer.

        Args:
            recipient_id: The ID of the recipient peer
            message: The message to send (can be a Message object or a dict)

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        if not self._host:
            logger.error("Cannot send message: Host not initialized")
            return False

        try:
            # Convert message to dict if it's a Message object
            if isinstance(message, Message):
                message_dict = message.to_dict()
            else:
                message_dict = message

            # Set sender if not already set
            if "sender" not in message_dict:
                message_dict["sender"] = self.peer_id

            # Serialize the message
            message_bytes = json.dumps(message_dict).encode()

            # Find the peer and open a stream
            peer_id = PeerID.from_base58(recipient_id)
            stream = await self._host.new_stream(
                peer_id, ["/animavox/1.0.0"]
            )

            # Send the message
            await stream.write(message_bytes)
            await stream.close()
            return True

        except Exception as e:
            logger.error(f"Failed to send message to {recipient_id}: {e}")
            return False

    async def broadcast(self, message: Message | dict) -> int:
        """Broadcast a message to all connected peers via pubsub.

        Args:
            message: The message to broadcast (can be a Message object or a dict)

        Returns:
            int: Number of peers the message was sent to
        """
        if not self._pubsub or not self._host:
            logger.error("Cannot broadcast: PubSub or Host not initialized")
            return 0

        try:
            # Convert message to dict if it's a Message object
            if isinstance(message, Message):
                message_dict = message.to_dict()
            else:
                message_dict = message

            # Set sender if not already set
            if "sender" not in message_dict:
                message_dict["sender"] = self.peer_id

            # Publish to the network
            topic = "animavox-messages"
            await self._pubsub.publish(topic, json.dumps(message_dict).encode())

            # Return the number of peers we're connected to
            return len(self._host.get_network().connections)

        except Exception as e:
            logger.error(f"Failed to broadcast message: {e}")
            return 0

    # Internal handlers
    async def _handle_stream(self, stream):
        """Handle incoming stream connections."""
        try:
            # Read the message
            data = await stream.read()
            message_dict = json.loads(data.decode())

            # Convert to Message object
            message = Message.from_dict(message_dict)

            # Find appropriate handler
            handler = self._message_handlers.get(message.type)
            if handler:
                await handler(message.sender, message)
            else:
                logger.warning(f"No handler for message type: {message.type}")

        except Exception as e:
            logger.error(f"Error handling incoming message: {e}", exc_info=True)
        finally:
            await stream.close()

    async def _notify_status_change(self, peer_id: str, status: str) -> None:
        """Notify all status handlers about a peer status change."""
        for handler in self._status_handlers:
            try:
                await handler(peer_id, status)
            except Exception as e:
                logger.error(f"Error in status handler: {e}", exc_info=True)
