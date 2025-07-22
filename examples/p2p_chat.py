#!/usr/bin/env python3
"""
A simple P2P chat application using the NetworkPeer implementation.

This example creates a simple chat application where each peer can:
1. Start a P2P node on a given port
2. Connect to other peers using their multiaddress
3. Send and receive chat messages in real-time
4. See when peers join/leave

Usage:
    # Start the first peer
    python examples/p2p_chat.py --port 0 --name Alice

    # Start additional peers (in new terminals)
    python examples/p2p_chat.py --port 0 --name Bob --connect /ip4/127.0.0.1/tcp/12345/p2p/Qm...
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from loguru import logger

# Configure logging
logging.basicConfig(level=logging.INFO)
logger.remove()
logger.add(sys.stderr, level="INFO")

# Add the parent directory to path so we can import animavox
sys.path.append(str(Path(__file__).parent.parent))

from animavox.network import Message, NetworkPeer


class ChatApp:
    def __init__(self, name: str, port: int = 0, peer_addr: str | None = None):
        self.name = name
        self.peer_addr = peer_addr
        self.peer = NetworkPeer(handle=name, host="0.0.0.0", port=port)
        self.connected = False

    async def start(self):
        """Start the chat application."""
        # Register message handlers
        self.peer.on_message("chat", self.handle_chat_message)
        self.peer.on_peer_status_change(self.handle_peer_status)

        # Start the peer
        await self.peer.start()
        self.connected = True

        # Get our address to share with others
        info = self.peer.get_info()
        our_addr = f"/ip4/127.0.0.1/tcp/{info.port}/p2p/{self.peer.peer_id}"

        print(f"\n🚀 Chat started! You are: {self.name} ({self.peer.peer_id[:8]}...)")
        print(f"📡 Your address: {our_addr}")
        print("\nType a message and press Enter to send. Type '/quit' to exit.")

        # Connect to the provided peer if specified
        if self.peer_addr:
            try:
                print(f"\n🔗 Connecting to {self.peer_addr}...")
                if await self.peer.connect_to_peer(self.peer_addr):
                    print("✅ Connected to peer!")
                else:
                    print("❌ Failed to connect to peer")
            except Exception as e:
                print(f"❌ Error connecting to peer: {e}")

        # Start the input loop
        await self.input_loop()

    async def stop(self):
        """Stop the chat application."""
        if self.connected:
            await self.peer.stop()
            self.connected = False

    async def handle_chat_message(self, sender: str, message: Message):
        """Handle incoming chat messages."""
        if sender != self.peer.peer_id:  # Don't echo our own messages
            print(
                f"\n💬 {message.content.get('sender_name', 'Unknown')}: {message.content.get('text', '')}"
            )
            print("> ", end="", flush=True)

    async def handle_peer_status(self, peer_id: str, status: str):
        """Handle peer status changes."""
        status_emoji = "🟢" if status == "connected" else "🔴"
        print(f"\n{status_emoji} Peer {peer_id[:8]}... {status}")
        print("> ", end="", flush=True)

    async def send_message(self, text: str):
        """Send a chat message to all connected peers."""
        message = {
            "type": "chat",
            "content": {
                "text": text,
                "sender_name": self.name,
                "timestamp": str(asyncio.get_event_loop().time()),
            },
        }

        # Broadcast to all connected peers
        count = await self.peer.broadcast(message)
        if count > 0:
            print(f"📤 Sent to {count} peer{'s' if count != 1 else ''}")
        else:
            print("⚠️  No peers connected to receive message")

    async def input_loop(self):
        """Handle user input in a loop."""
        try:
            while self.connected:
                try:
                    text = await asyncio.get_event_loop().run_in_executor(
                        None, input, "> "
                    )

                    if text.lower() == "/quit":
                        break
                    elif text.startswith("/connect "):
                        addr = text.split(" ", 1)[1]
                        print(f"🔗 Connecting to {addr}...")
                        if await self.peer.connect_to_peer(addr):
                            print("✅ Connected!")
                        else:
                            print("❌ Connection failed")
                    elif text == "/peers":
                        peers = self.peer.known_peers
                        if peers:
                            print("\nConnected peers:")
                            for peer_id, info in peers.items():
                                print(f"- {info.handle} ({peer_id[:8]}...)")
                        else:
                            print("No peers connected")
                        print()
                    elif text.strip():
                        await self.send_message(text)

                except (EOFError, KeyboardInterrupt):
                    break
                except Exception as e:
                    print(f"\n⚠️  Error: {e}")
                    print("> ", end="", flush=True)

        finally:
            await self.stop()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="P2P Chat Application")
    parser.add_argument(
        "--port", type=int, default=0, help="Port to listen on (0 for random)"
    )
    parser.add_argument("--name", required=True, help="Your display name in the chat")
    parser.add_argument(
        "--connect", metavar="ADDRESS", help="Multiaddress of a peer to connect to"
    )
    return parser.parse_args()


async def main():
    """Run the chat application."""
    args = parse_args()

    app = ChatApp(name=args.name, port=args.port, peer_addr=args.connect)

    try:
        await app.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await app.stop()
        print("Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
