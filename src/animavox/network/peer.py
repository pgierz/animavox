"""NetworkPeer implementation using libp2p for P2P communication.

This module provides a high-level interface for P2P networking using libp2p as the backend.
It maintains backward compatibility with the existing NetworkPeer interface while
leveraging the more robust libp2p implementation.
"""

from __future__ import annotations

import logging

from ._abc import AbstractPeer, MessageHandler, StatusHandler
from ._libp2p_peer import LibP2PPeer as _LibP2PPeer
from .message import Message, PeerInfo

logger = logging.getLogger(__name__)


class NetworkPeer(AbstractPeer):
    """A peer in the P2P network capable of sending and receiving messages.

    This class provides a high-level interface for peer-to-peer communication,
    including message passing, peer discovery, and connection management.
    It uses libp2p as the underlying networking implementation.
    """

    def __init__(
        self,
        handle: str,
        host: str = "0.0.0.0",
        port: int = 0,
        peer_id: str | None = None,
    ) -> None:
        """Initialize a new NetworkPeer.

        Args:
            handle: A human-readable identifier for this peer.
            host: The host address to bind to (default: "0.0.0.0").
            port: The port to bind to (0 for auto-select).
            peer_id: Optional unique identifier for this peer (defaults to handle if None).
        """
        self._libp2p_peer = _LibP2PPeer(
            handle=handle, host=host, port=port, peer_id=peer_id or handle
        )

    @property
    def known_peers(self) -> dict[str, PeerInfo]:
        """Get a dictionary of known peers."""
        return self._libp2p_peer.known_peers

    @property
    def is_running(self) -> bool:
        """Whether the peer's server is currently running."""
        return self._libp2p_peer.is_running

    @property
    def handle(self) -> str:
        """Get the peer's handle."""
        return self._libp2p_peer.handle

    @property
    def host(self) -> str:
        """Get the host the peer is bound to."""
        return self._libp2p_peer.host

    @property
    def port(self) -> int:
        """Get the port the peer is bound to."""
        return self._libp2p_peer.port

    @property
    def peer_id(self) -> str:
        """Get the peer's unique identifier."""
        return self._libp2p_peer.peer_id

    def get_info(self) -> PeerInfo:
        """Get information about this peer."""
        return self._libp2p_peer.get_info()

    async def start(self) -> None:
        """Start the peer's server and initialize resources."""
        logger.debug("Starting peer...")
        logger.debug(f"About to start inner {self._libp2p_peer=}")
        await self._libp2p_peer.start()

    async def stop(self) -> None:
        """Stop the peer and clean up resources."""
        await self._libp2p_peer.stop()

    def on_message(
        self, message_type: str | MessageHandler, handler: MessageHandler | None = None
    ) -> MessageHandler:
        """Register a message handler for a specific message type.

        Can be used as a decorator or a regular function.

        Args:
            message_type: The message type to handle or the handler function
            handler: The handler function (if message_type is a string)

        Returns:
            The handler function for decorator support
        """
        return self._libp2p_peer.on_message(message_type, handler)

    def on_peer_status_change(self, handler: StatusHandler):
        """Register a handler for peer status changes.

        The handler will be called with (peer_id: str, status: str) whenever
        a peer's connection status changes.

        Args:
            handler: The handler function

        Returns:
            The handler function for decorator support
        """
        return self._libp2p_peer.on_peer_status_change(handler)

    async def connect_to_peer(self, peer_addr: str, *args, **kwargs) -> bool:
        """Connect to a peer using its multiaddress.

        Args:
            peer_addr: Multiaddress of the peer to connect to
            *args: For backward compatibility (ignored)
            **kwargs: For backward compatibility (ignored)

        Returns:
            bool: True if connection was successful, False otherwise
        """
        return await self._libp2p_peer.connect_to_peer(peer_addr)

    async def send_message(self, recipient_id: str, message: Message | dict) -> bool:
        """Send a direct message to a specific peer.

        Args:
            recipient_id: The ID of the recipient peer
            message: The message to send (can be a Message object or a dict)

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        return await self._libp2p_peer.send_message(recipient_id, message)

    async def broadcast(self, message: Message | dict) -> int:
        """Broadcast a message to all connected peers.

        Args:
            message: The message to broadcast (can be a Message object or a dict)

        Returns:
            int: Number of peers the message was sent to
        """
        return await self._libp2p_peer.broadcast(message)

    def __getattr__(self, name):
        """Delegate any undefined attributes to the underlying libp2p peer."""
        return getattr(self._libp2p_peer, name)
