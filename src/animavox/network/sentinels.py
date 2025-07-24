"""Sentinel values used throughout the network module."""

from enum import Enum, auto


class NetworkState(Enum):
    """
    Represents the state of a peer in the network.

    This enum serves two purposes:
    1. As a sentinel value (NEVER_BEEN_IN_A_NETWORK)
    2. As a state machine for peer connection status
    """

    # Sentinel value
    NEVER_BEEN_IN_A_NETWORK = auto()

    # Connection states
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"

    def __repr__(self) -> str:
        if self is NetworkState.NEVER_BEEN_IN_A_NETWORK:
            return "<NEVER_BEEN_IN_A_NETWORK>"
        return f"<NetworkState.{self.name}>"

    def __bool__(self) -> bool:
        return self is not NetworkState.NEVER_BEEN_IN_A_NETWORK

    @property
    def is_connected(self) -> bool:
        """Return True if the peer is connected."""
        return self is NetworkState.CONNECTED

    @property
    def is_connecting(self) -> bool:
        """Return True if the peer is in the process of connecting."""
        return self is NetworkState.CONNECTING

    @property
    def is_disconnected(self) -> bool:
        """Return True if the peer is disconnected."""
        return self in (NetworkState.DISCONNECTED, NetworkState.NEVER_BEEN_IN_A_NETWORK)

    @classmethod
    def is_never_been_in_network(cls, value):
        """Check if a value is the NEVER_BEEN_IN_A_NETWORK sentinel."""
        return value is cls.NEVER_BEEN_IN_A_NETWORK
