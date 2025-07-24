from animavox.network import NetworkPeer, Message
from loguru import logger
import trio
from tellus import Simulation


async def main():
    logger.info("Creating NetworkPeer objects...")
    # Create two peers with different ports for local testing
    peer1 = NetworkPeer(handle="scientist1", host="127.0.0.1", port=9001)
    peer2 = NetworkPeer(handle="scientist2", host="127.0.0.1", port=9002)
    logger.info(f"{peer1=}")
    logger.info(f"{peer2=}")
    logger.info(f"{peer1.get_info()=}")
    logger.info(f"{peer2.get_info()=}")
    try:
        # Start both peers
        logger.info("Starting peers...")
        await peer1.start()
        await peer2.start()
        logger.info(f"Peer 1 ID: {peer1.peer_id}")
        logger.info(f"Peer 2 ID: {peer2.peer_id}")

        # Connect the peers
        peer2_addr = f"/ip4/127.0.0.1/tcp/9002/p2p/{peer2.peer_id}"
        await peer1.connect_to_peer(peer2_addr)
        logger.info("Connected peer1 to peer2")

        # Set up message handler for peer2
        message_received = trio.Event()
        received_message = None

        @peer2.on_message("test_message")
        async def handle_message(sender_id: str, message: Message):
            nonlocal received_message, message_received
            logger.info(f"Peer2 received message from {sender_id}: {message.content}")
            received_message = message.content
            message_received.set()

        # Send a test message from peer1 to peer2
        test_content = {"type": "greeting", "message": "Hello from peer1!"}
        logger.info(f"Sending message from peer1 to peer2: {test_content}")
        await peer1.send_message(
            peer2.peer_id,
            Message(type="test_message", content=test_content, sender=peer1.peer_id),
        )

        # Wait for message to be received with a timeout
        with trio.fail_after(5):  # 5 second timeout
            await message_received.wait()
            logger.info(f"Peer2 received: {received_message}")

        # Interactive loop
        logger.info("Starting interactive mode. Press Ctrl+C to exit.")
        while True:
            await trio.sleep(1)
            # Add more interactive code here if needed

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        # Clean up
        logger.info("Stopping peers...")
        await peer1.stop()
        await peer2.stop()
        logger.info("Peers stopped. Goodbye!")


if __name__ == "__main__":
    logger.info("Starting manual test of NetworkPeer communication...")
    trio.run(main)
