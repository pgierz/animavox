"""Message class for network communication."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Local imports
from .sentinels import NetworkState


@dataclass
class Message:
    """A message that can be sent between peers.

    Attributes:
        type: The type of the message (e.g., 'chat', 'discovery')
        content: The message payload
        sender: The ID of the sender peer
        recipient: The ID of the recipient peer (empty for broadcast)
        timestamp: When the message was created
    """

    type: str
    content: dict[str, Any] | str | None = None
    sender: str | None = None
    recipient: str | None = None
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        # Ensure content is serializable
        if not isinstance(
            self.content, str | int | float | bool | type(None) | dict | list
        ):
            self.content = str(self.content)

    def to_dict(self) -> dict[str, Any]:
        """Convert the message to a dictionary for serialization."""
        return {
            "type": self.type,
            "content": self.content,
            "sender": self.sender,
            "recipient": self.recipient,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Create a message from a dictionary."""
        return cls(
            type=data["type"],
            content=data["content"],
            sender=data.get("sender", ""),
            recipient=data.get("recipient", ""),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class PeerInfo:
    """Information about a peer in the network."""

    handle: str
    host: str
    port: int
    last_seen: datetime | NetworkState = NetworkState.NEVER_BEEN_IN_A_NETWORK
    status: NetworkState = NetworkState.DISCONNECTED

    def __repr__(self) -> str:
        """Return a nicely formatted representation string."""
        last_seen_str = (
            self.last_seen.isoformat(sep=" ", timespec="seconds")
            if isinstance(self.last_seen, datetime)
            else str(self.last_seen)
        )
        return (
            f"PeerInfo(handle='{self.handle}', host='{self.host}', port={self.port}, "
            f"last_seen={last_seen_str}, status={self.status!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert peer info to a dictionary."""
        return {
            "handle": self.handle,
            "host": self.host,
            "port": self.port,
            "last_seen": (
                self.last_seen.isoformat()
                if isinstance(self.last_seen, datetime)
                else None
            ),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeerInfo:
        """Create a PeerInfo from a dictionary."""
        return cls(
            handle=data["handle"],
            host=data["host"],
            port=data["port"],
            last_seen=(
                datetime.fromisoformat(data["last_seen"])
                if data.get("last_seen") is not None
                else NetworkState.NEVER_BEEN_IN_A_NETWORK
            ),
            status=NetworkState(data.get("status", NetworkState.DISCONNECTED))
            if isinstance(data.get("status"), str)
            else data.get("status", NetworkState.DISCONNECTED),
        )
