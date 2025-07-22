"""Abstract base classes for P2P network components."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar, runtime_checkable

from .message import Message, PeerInfo

# Type aliases
MessageHandler = Callable[[str, Message], Awaitable[None]]
StatusHandler = Callable[[str, str], Awaitable[None]]

# Type variable for covariant return types
T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class IPeer(Protocol):
    """Protocol defining the interface for a P2P peer.

    This protocol can be used for runtime type checking and to document
    the expected interface for peer implementations.
    """

    # Properties
    @property
    def is_running(self) -> bool:
        """Whether the peer's server is currently running."""
        ...

    @property
    def handle(self) -> str:
        """Get the peer's human-readable handle."""
        ...

    @property
    def host(self) -> str:
        """Get the host the peer is bound to."""
        ...

    @property
    def port(self) -> int:
        """Get the port the peer is bound to."""
        ...

    @property
    def peer_id(self) -> str:
        """Get the peer's unique identifier."""
        ...

    @property
    def known_peers(self) -> dict[str, PeerInfo]:
        """Get a dictionary of known peers."""
        ...

    # Core methods
    async def start(self) -> None:
        """Start the peer's server and initialize resources."""
        ...

    async def stop(self) -> None:
        """Stop the peer and clean up resources."""
        ...

    # Message handling
    def on_message(
        self, message_type: str | MessageHandler, handler: MessageHandler | None = None
    ) -> MessageHandler:
        """Register a message handler for a specific message type.

        Can be used as a decorator or a regular function.
        """
        ...

    def on_peer_status_change(self, handler: StatusHandler) -> StatusHandler:
        """Register a handler for peer status changes."""
        ...

    # Network operations
    async def connect_to_peer(self, peer_addr: str, *args, **kwargs) -> bool:
        """Connect to a peer using its address."""
        ...

    async def send_message(self, recipient_id: str, message: Message | dict) -> bool:
        """Send a direct message to a specific peer."""
        ...

    async def broadcast(self, message: Message | dict) -> int:
        """Broadcast a message to all connected peers."""
        ...

    def get_info(self) -> PeerInfo:
        """Get information about this peer."""
        ...


class AbstractPeer(ABC):
    """Abstract base class for P2P peer implementations.

    This class provides a base implementation that can be extended by
    concrete peer implementations. It enforces the IPeer protocol.
    """

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the peer's server is currently running."""
        ...

    @property
    @abstractmethod
    def handle(self) -> str:
        """Get the peer's human-readable handle."""
        ...

    @property
    @abstractmethod
    def host(self) -> str:
        """Get the host the peer is bound to."""
        ...

    @property
    @abstractmethod
    def port(self) -> int:
        """Get the port the peer is bound to."""
        ...

    @property
    @abstractmethod
    def peer_id(self) -> str:
        """Get the peer's unique identifier."""
        ...

    @property
    @abstractmethod
    def known_peers(self) -> dict[str, PeerInfo]:
        """Get a dictionary of known peers."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the peer's server and initialize resources."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the peer and clean up resources."""
        ...

    @abstractmethod
    def on_message(
        self, message_type: str | MessageHandler, handler: MessageHandler | None = None
    ) -> MessageHandler:
        """Register a message handler for a specific message type."""
        ...

    @abstractmethod
    def on_peer_status_change(self, handler: StatusHandler) -> StatusHandler:
        """Register a handler for peer status changes."""
        ...

    @abstractmethod
    async def connect_to_peer(self, peer_addr: str, *args, **kwargs) -> bool:
        """Connect to a peer using its address."""
        ...

    @abstractmethod
    async def send_message(self, recipient_id: str, message: Message | dict) -> bool:
        """Send a direct message to a specific peer."""
        ...

    @abstractmethod
    async def broadcast(self, message: Message | dict) -> int:
        """Broadcast a message to all connected peers."""
        ...

    @abstractmethod
    def get_info(self) -> PeerInfo:
        """Get information about this peer."""
        ...

    # Make the class callable as a context manager
    async def __aenter__(self) -> AbstractPeer:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
