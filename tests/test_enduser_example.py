"""
The end-user example

This is how I imagine interacting with this library as an end-user, and serves
as a reference for how I eventually want to design inner parts.

This test demonstrates how two peers can share simulation data using the NetworkPeer API.
"""

import pytest
import json
from typing import Any

from tellus import Simulation
import trio

from animavox.network import Message, NetworkPeer


def create_experiment_update_message(
    sender: str, experiment: Simulation
) -> dict[str, Any]:
    """Helper to create an experiment update message."""
    return {
        "type": "experiment_update",
        "sender": sender,
        "experiment": experiment.to_dict(),
    }


@pytest.mark.trio  # [NOTE] Used to be:  @pytest.mark.asyncio
async def test_simulation_sharing_user_adds_new_location(
    sample_simulation_awi_locations_with_laptop,
):
    """Test that when one peer updates an experiment, other peers receive the update."""
    # Create two peers with unique ports
    andreas = NetworkPeer(handle="little_a", host="127.0.0.1", port=9001)
    bernd = NetworkPeer(handle="major_b", host="127.0.0.1", port=9002)

    try:
        # Start both peers
        await andreas.start()
        await bernd.start()
        # Connect the peers (in a real scenario, this would be done via discovery)
        # Create a proper multiaddress for the peer
        peer_addr = f"/ip4/127.0.0.1/tcp/9002/p2p/{bernd.peer_id}"
        await andreas.connect_to_peer(peer_addr)

        # Initialize experiments
        andreas.experiments = [
            Simulation.from_dict(sample_simulation_awi_locations_with_laptop.to_dict())
        ]
        bernd.experiments = [
            Simulation.from_dict(sample_simulation_awi_locations_with_laptop.to_dict())
        ]

        # Set up message handler for bernd
        message_received = trio.Event()

        async def handle_experiment_update(sender_id: str, message: Message):
            if message.type == "experiment_update":
                data = message.content
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get("type") == "experiment_update":
                    bernd.experiments = [Simulation.from_dict(data["experiment"])]
                    message_received.set()

        bernd.on_message("experiment_update")(handle_experiment_update)

        # Andreas adds a new location
        new_location = {
            "name": "uni_server",
            "type": "server",
            "config": {
                "protocol": "file",
                "storage_options": {"host": "uni-server.example.com"},
            },
            "optional": False,
        }
        andreas.experiments[0].add_location(new_location)

        # Broadcast the update
        update_msg = create_experiment_update_message("andreas", andreas.experiments[0])
        message = Message(
            type="experiment_update", content=update_msg, sender=andreas.peer_id
        )
        await andreas.broadcast(message)

        # Wait for message with timeout
        with trio.fail_after(5):  # 5 second timeout
            await message_received.wait()

        # Verify the update was received
        assert "uni_server" in bernd.experiments[0].locations

    finally:
        # Clean up
        await andreas.stop()
        await bernd.stop()
