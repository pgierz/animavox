"""Network module for P2P communication.

This module provides the NetworkPeer class for establishing peer-to-peer
connections and message passing.
"""

from .peer import Message, NetworkPeer, PeerInfo
from .sentinels import NetworkState

__all__ = [
    "NetworkPeer",
    "Message",
    "PeerInfo",
    "NetworkState",  # Expose the NetworkState enum
]
