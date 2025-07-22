"""Message class for network communication."""

import time
from dataclasses import dataclass, field
from typing import Any


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
    content: Any
    sender: str = ""
    recipient: str = ""
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
    def from_dict(cls, data: dict[str, Any]) -> "Message":
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
    last_seen: float = 0.0
    status: str = "disconnected"  # 'connected', 'disconnected', 'connecting'

    def to_dict(self) -> dict[str, Any]:
        """Convert peer info to a dictionary."""
        return {
            "handle": self.handle,
            "host": self.host,
            "port": self.port,
            "last_seen": self.last_seen,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerInfo":
        """Create a PeerInfo from a dictionary."""
        return cls(
            handle=data["handle"],
            host=data["host"],
            port=data["port"],
            last_seen=data.get("last_seen", 0.0),
            status=data.get("status", "disconnected"),
        )
