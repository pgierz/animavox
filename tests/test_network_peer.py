"""Tests for the NetworkPeer class.

These tests define the desired API for the NetworkPeer implementation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from animavox.network import Message, NetworkPeer


@pytest_asyncio.fixture
async def peer_factory() -> AsyncGenerator[Callable[..., Any], None]:
    """Fixture to create and clean up test peers."""
    peers = []
    port = 9000  # Start port for test peers

    async def _create_peer(handle: str, auto_start: bool = True) -> NetworkPeer:
        nonlocal port
        port += 1
        peer = NetworkPeer(handle=handle, host="127.0.0.1", port=port)
        if auto_start:
            await peer.start()
        peers.append(peer)
        return peer

    yield _create_peer

    # Cleanup
    for peer in peers:
        if hasattr(peer, "is_running") and peer.is_running:
            await peer.stop()


class TestNetworkPeerBasic:
    """Basic functionality tests for NetworkPeer."""

    @pytest.mark.asyncio
    async def test_peer_creation(self, peer_factory):
        """Test basic peer creation and properties."""
        peer = await peer_factory("test_peer")

        assert peer.handle == "test_peer"
        assert peer.host == "127.0.0.1"
        assert peer.port > 0
        assert peer.is_running is True

        # Test peer info
        info = peer.get_info()
        assert info.handle == "test_peer"
        assert info.host == "127.0.0.1"
        assert info.port == peer.port


class TestPeerMessaging:
    """Tests for peer-to-peer messaging functionality."""

    @pytest.mark.asyncio
    async def test_direct_messaging(self, peer_factory):
        """Test direct messaging between peers."""
        # Create two peers
        alice = await peer_factory("alice")
        bob = await peer_factory("bob")

        # Make peers aware of each other
        await alice.connect_to_peer("bob", "127.0.0.1", bob.port)
        await bob.connect_to_peer("alice", "127.0.0.1", alice.port)

        # Set up a message handler on Bob
        mock_handler = AsyncMock()
        bob.on_message("greeting", mock_handler)

        # Alice sends a message to Bob
        message = Message(type="greeting", content={"text": "Hello Bob!"})
        await alice.send_message("bob", message)

        # Give some time for message delivery
        for _ in range(5):  # Retry a few times
            if mock_handler.called:
                break
            await asyncio.sleep(0.1)

        # Verify Bob received the message
        mock_handler.assert_called_once()
        args, _ = mock_handler.call_args
        assert args[0] == "alice"  # sender_id
        assert args[1].content["text"] == "Hello Bob!"
        assert args[1].sender == "alice"

    @pytest.mark.asyncio
    async def test_broadcast_messaging(self, peer_factory):
        """Test broadcasting messages to multiple peers."""
        # Create multiple peers
        broadcaster = await peer_factory("broadcaster")
        peer1 = await peer_factory("peer1")
        peer2 = await peer_factory("peer2")

        # Make all peers aware of each other
        for peer in [broadcaster, peer1, peer2]:
            for other in [p for p in [broadcaster, peer1, peer2] if p != peer]:
                await peer.connect_to_peer(other.handle, "127.0.0.1", other.port)

        # Set up message handlers
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        peer1.on_message("announcement", handler1)
        peer2.on_message("announcement", handler2)

        # Broadcast a message
        message = Message(type="announcement", content={"text": "Important update!"})
        await broadcaster.broadcast(message)

        # Give some time for message delivery with retries
        for _ in range(5):
            if handler1.called and handler2.called:
                break
            await asyncio.sleep(0.1)

        # Verify all peers received the message
        handler1.assert_called_once()
        handler2.assert_called_once()

        # Verify message content
        args1, _ = handler1.call_args
        args2, _ = handler2.call_args
        assert args1[0] == "broadcaster"
        assert args1[1].content["text"] == "Important update!"
        assert args2[0] == "broadcaster"
        assert args2[1].content["text"] == "Important update!"


class TestPeerDiscovery:
    """Tests for peer discovery functionality."""

    @pytest.mark.asyncio
    async def test_bootstrap_discovery(self, peer_factory):
        """Test peer discovery through a bootstrap node."""
        # Create a bootstrap node
        bootstrap = await peer_factory("bootstrap")

        # Create two regular peers that will use the bootstrap node
        peer1 = await peer_factory("peer1")
        peer2 = await peer_factory("peer2")

        # Connect peers to bootstrap
        await peer1.connect_to_bootstrap("127.0.0.1", bootstrap.port)
        await peer2.connect_to_bootstrap("127.0.0.1", bootstrap.port)

        # Give some time for discovery with retries
        for _ in range(5):
            if (
                "peer2" in peer1.known_peers
                and "peer1" in peer2.known_peers
                and "peer1" in bootstrap.known_peers
                and "peer2" in bootstrap.known_peers
            ):
                break
            await asyncio.sleep(0.1)

        # Both peers should know about each other through the bootstrap
        assert "peer2" in peer1.known_peers, f"peer1's known_peers: {peer1.known_peers}"
        assert "peer1" in peer2.known_peers, f"peer2's known_peers: {peer2.known_peers}"

        # The bootstrap node should know about both peers
        assert "peer1" in bootstrap.known_peers, (
            f"bootstrap's known_peers: {bootstrap.known_peers}"
        )
        assert "peer2" in bootstrap.known_peers, (
            f"bootstrap's known_peers: {bootstrap.known_peers}"
        )


class TestCustomMessageHandling:
    """Tests for custom message handling."""

    @pytest.mark.asyncio
    async def test_custom_message_types(self, peer_factory):
        """Test handling of custom message types with complex data."""

        @dataclass
        class CustomData:
            value: int
            timestamp: float

        # Create peers
        sender = await peer_factory("sender")
        receiver = await peer_factory("receiver")

        # Set up custom message handler
        received_data = []

        @receiver.on_message("custom_data")
        async def handle_custom_data(sender_id: str, message: Message):
            data = CustomData(**message.content)
            received_data.append((sender_id, data))

        # Send custom data
        custom_data = CustomData(value=42, timestamp=1234567890.0)
        message = Message(type="custom_data", content=custom_data.__dict__)
        await sender.send_message("receiver", message)

        # Give some time for message delivery
        await asyncio.sleep(0.1)

        # Verify data was received and processed
        assert len(received_data) == 1
        assert received_data[0][0] == "sender"
        assert received_data[0][1].value == 42


class TestPeerStatusMonitoring:
    """Tests for peer status monitoring."""

    @pytest.mark.asyncio
    async def test_peer_status_updates(self, peer_factory):
        """Test monitoring peer connection status changes."""
        # Create peers
        monitor = await peer_factory("monitor")
        target = await peer_factory("target")

        # Track status changes
        status_updates = []

        @monitor.on_peer_status_change
        async def handle_status_change(peer_id: str, status: str):
            status_updates.append((peer_id, status))

        # Connect to target
        await monitor.connect_to_peer(target.handle, "127.0.0.1", target.port)

        # Give some time for connection
        await asyncio.sleep(0.1)

        # Stop target
        await target.stop()

        # Give some time for disconnection detection
        await asyncio.sleep(0.2)

        # Verify status updates
        assert len(status_updates) >= 2
        assert status_updates[0] == (target.handle, "connected")
        assert status_updates[-1] == (target.handle, "disconnected")
