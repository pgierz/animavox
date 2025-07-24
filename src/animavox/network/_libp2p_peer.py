"""LibP2P implementation of the P2P peer interface."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import multiaddr
import trio
from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex

from ._abc import AbstractPeer, MessageHandler, StatusHandler
from .message import Message, PeerInfo
from .sentinels import NetworkState

logger = logging.getLogger(__name__)

_GOSSIPSUB_PROTOCOL_ID = TProtocol("/gossipsub/1.1.0")


class LibP2PPeer(AbstractPeer):
    """A peer in the P2P network using libp2p for communication."""

    def __init__(
        self,
        handle: str,
        host: str = "0.0.0.0",
        port: int = 0,
        peer_id: str | None = None,
    ) -> None:
        """Initialize a new NetworkPeer using libp2p.

        Args:
            handle: A human-readable identifier for this peer.
            host: The host address to bind to.
            port: The port to bind to (0 for auto-select).
            peer_id: Optional unique identifier for this peer.
        """
        self.handle = handle
        self.host = host
        self.port = port
        self.peer_id = peer_id or handle

        # Libp2p components
        self._libp2p_host: BasicHost | None = None
        self._libp2p_gossipsub: GossipSub | None = None
        self._libp2p_pubsub: Pubsub | None = None
        self._libp2p_listen_addr: multiaddr.Multiaddr | None = None
        self._libp2p_key_pair: Any | None = None

        # Message handling
        self._message_handlers: dict[str, MessageHandler] = {}
        self._status_handlers: list[StatusHandler] = []

        # Peer management
        self._known_peers: dict[str, PeerInfo] = {}
        self._is_running = False
        self._nursery: trio.Nursery | None = None
        self._cancel_scope: trio.CancelScope | None = None

        # Initialize instance attributes
        self._handle = handle
        self._host_str = host  # String representation of the host
        self._port = port
        self._peer_id = peer_id or handle

    def get_info(self) -> PeerInfo:
        """Get information about this peer."""
        if not self._libp2p_host:
            return PeerInfo(
                handle=self.handle,
                host=self.host,
                port=self.port,
                status=NetworkState.DISCONNECTED,
            )

        _ = [
            str(addr) for addr in self._libp2p_host.get_addrs()
        ]  # Store in _ to indicate it's intentionally unused
        return PeerInfo(
            handle=self.handle,
            host=self.host,
            port=self.port,
            status=NetworkState.CONNECTED if self._is_running else NetworkState.DISCONNECTED,
        )

    def on_message(
        self, message_type: str | MessageHandler, handler: MessageHandler | None = None
    ) -> MessageHandler | Callable[[MessageHandler], MessageHandler]:
        """Register a message handler for a specific message type.

        Can be used as a decorator or a regular function.

        Examples:
            # As a decorator with message type
            @peer.on_message("my_message_type")
            async def handle_my_message(sender_id: str, message: Message) -> None:
                pass

            # As a decorator without arguments (uses function name as message type)
            @peer.on_message
            async def another_message(sender_id: str, message: Message) -> None:
                pass

            # As a regular function
            async def handle_my_message(sender_id: str, message: Message) -> None:
                pass
            peer.on_message("my_message_type", handle_my_message)
        """
        # Case 1: Called with message_type as string and handler as function
        # @peer.on_message("msg_type")
        # def handler(): ...
        if isinstance(message_type, str) and handler is not None:
            self._message_handlers[message_type] = handler
            return handler

        # Case 2: Called with just a function (no message_type)
        # @peer.on_message
        # def my_message_type(): ...
        if callable(message_type) and handler is None:
            # The actual handler is the message_type parameter
            actual_handler = message_type
            # Use the function name as the message type
            msg_type = actual_handler.__name__
            self._message_handlers[msg_type] = actual_handler
            return actual_handler

        # Case 3: Called with just a message_type string (returns a decorator)
        # @peer.on_message("msg_type")
        # def handler(): ...
        if isinstance(message_type, str) and handler is None:

            def decorator(func: MessageHandler) -> MessageHandler:
                self._message_handlers[message_type] = func
                return func

            return decorator

        # Invalid usage
        raise ValueError(
            "Invalid arguments to on_message. "
            "Use @peer.on_message, @peer.on_message('msg_type'), or peer.on_message('msg_type', handler)"
        )

    def on_peer_status_change(self, handler: StatusHandler) -> StatusHandler:
        """Register a handler for peer status changes.

        The handler will be called with (peer_id: str, status: NetworkState) whenever
        a peer's connection status changes.
        """
        self._status_handlers.append(handler)
        return handler

    @property
    def is_running(self) -> bool:
        """Whether the peer's server is currently running."""
        return self._is_running

    @is_running.setter
    def is_running(self, value: bool) -> None:
        """Set whether the peer's server is running."""
        self._is_running = value

    @property
    def handle(self) -> str:
        """Get the peer's human-readable handle."""
        return self._handle

    @handle.setter
    def handle(self, value: str) -> None:
        """Set the peer's human-readable handle."""
        self._handle = value

    @property
    def host(self) -> str:
        """Get the host the peer is bound to."""
        return self._host_str

    @host.setter
    def host(self, value: str) -> None:
        """Set the host the peer is bound to."""
        self._host_str = value

    @property
    def port(self) -> int:
        """Get the port the peer is bound to."""
        return self._port

    @port.setter
    def port(self, value: int) -> None:
        """Set the port the peer is bound to."""
        self._port = value

    @property
    def peer_id(self) -> str:
        """Get the peer's unique identifier."""
        return self._peer_id

    @peer_id.setter
    def peer_id(self, value: str) -> None:
        """Set the peer's unique identifier."""
        self._peer_id = value

    @property
    def known_peers(self) -> dict[str, PeerInfo]:
        """Get a dictionary of known peers."""
        return self._known_peers

    @known_peers.setter
    def known_peers(self, value: dict[str, PeerInfo]) -> None:
        """Set the dictionary of known peers."""
        self._known_peers = value

    async def _handle_pubsub_message(self, topic: str, message: bytes) -> None:
        """Handle incoming PubSub messages."""
        try:
            logger.debug(f"Received message on topic {topic}")
            # Process the message data
            await self._process_message(message)
        except Exception as e:
            logger.error(f"Error handling PubSub message: {e}", exc_info=True)

    async def _receive_loop(self, subscription) -> None:
        """Continuously receive messages from the subscription."""
        while self._is_running:
            try:
                message = await subscription.get()
                if message:
                    await self._handle_pubsub_message(message.topic, message.data)
            except trio.Cancelled:
                logger.debug("Receive loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                await trio.sleep(1)  # Prevent tight loop on errors

    async def start(self) -> None:
        """Start the libp2p node and initialize resources."""
        if self._is_running:
            return

        try:
            # 1. Create key pair and host
            self._libp2p_key_pair = create_new_key_pair()
            self._libp2p_listen_addr = multiaddr.Multiaddr(
                f"/ip4/{self.host}/tcp/{self.port}"
            )

            # 2. Initialize host
            self._libp2p_host = new_host(
                key_pair=self._libp2p_key_pair,
                muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
            )

            # 3. Initialize GossipSub
            self._libp2p_gossipsub = GossipSub(
                protocols=[_GOSSIPSUB_PROTOCOL_ID],
                degree=3,
                degree_low=2,
                degree_high=4,
                time_to_live=120,
            )

            # 4. Create PubSub instance
            self._libp2p_pubsub = Pubsub(self._libp2p_host, self._libp2p_gossipsub)

            # 5. Start the host
            async with self._libp2p_host.run(
                listen_addrs=[self._libp2p_listen_addr]
            ) as network:  # why not host?
                # 6. Start the pubsub service
                await self._libp2p_pubsub.wait_until_ready()

                # 7. Subscribe to topics
                self._broadcast_topic = "animavox-broadcast"
                subscription = await self._libp2p_pubsub.subscribe(
                    self._broadcast_topic
                )

                # 8. Set up a message handler
                self._libp2p_pubsub.set_pubsub_handler(self._handle_pubsub_message)

                # 9. Start the receive loop in a separate task
                self._receive_task = asyncio.create_task(
                    self._receive_loop(subscription)
                )

                # 10. Update port if auto-assigned
                for addr in self._libp2p_host.get_addrs():
                    if "/tcp/" in str(addr):
                        self._port = int(str(addr).split("/tcp/")[1].split("/")[0])
                        break

                self._is_running = True
                logger.info(
                    f"LibP2P peer started with ID: {self._libp2p_host.get_id().pretty()} "
                    f"on {self.host}:{self.port}"
                )

                # Keep the peer running
                while self._is_running:
                    await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Failed to start LibP2P peer: {e}", exc_info=True)
            await self.stop()
            raise

    async def _run_host(self) -> None:
        """Run the libp2p host in a separate task."""
        try:
            # Start the host
            network = self._libp2p_host.get_network()

            # 5. Create a nursery for background tasks
            async with trio.open_nursery() as nursery:
                # 6. Start the host and pubsub services
                async with self._libp2p_host.run(
                    listen_addrs=[self._libp2p_listen_addr]
                ):
                    await self._libp2p_pubsub.wait_until_ready()

                    # 7. Subscribe to topics
                    self._broadcast_topic = "animavox-broadcast"
                    subscription = await self._libp2p_pubsub.subscribe(
                        self._broadcast_topic
                    )

                    # 8. Set up message handler
                    self._libp2p_pubsub.set_pubsub_handler(self._handle_pubsub_message)

                    # 9. Start the receive loop in the nursery
                    self._receive_task = nursery.start_soon(
                        self._receive_loop, subscription
                    )

                    # 10. Update port if auto-assigned
                    for addr in self._libp2p_host.get_addrs():
                        if "/tcp/" in str(addr):
                            self._port = int(str(addr).split("/tcp/")[1].split("/")[0])
                            break

                    self._is_running = True
                    logger.info(
                        f"LibP2P peer started with ID: {self._libp2p_host.get_id().pretty()} "
                        f"on {self.host}:{self.port}"
                    )

                    # Keep the peer running
                    while self._is_running:
                        await trio.sleep(1)

        except Exception as e:
            logger.error(f"Failed to start LibP2P peer: {e}", exc_info=True)
            await self.stop()
            raise

    async def _run_host(self) -> None:
        """Run the libp2p host in a separate task."""
        try:
            # Start the host
            network = self._libp2p_host.get_network()
            await network.listen(f"/ip4/{self.host}/tcp/{self.port}")

            # Keep the host running until explicitly stopped
            while self._is_running:
                await trio.sleep(0.1)

        except trio.Cancelled:
            logger.info("LibP2P peer received cancellation signal")
            raise
        except Exception as e:
            logger.error(f"Error in LibP2P host loop: {e}")
            await self.stop()

    async def stop(self) -> None:
        """Stop the peer and clean up resources."""
        if not self._is_running:
            return

        self._is_running = False

        try:
            # Cancel the receive task if it exists
            if hasattr(self, "_receive_task"):
                self._receive_task.cancel()
                try:
                    await self._receive_task
                except trio.Cancelled:
                    logger.debug("Receive task cancelled during stop")
                except Exception as e:
                    logger.error(
                        f"Error while cancelling receive task: {e}", exc_info=True
                    )

            # Close the libp2p host if it exists
            if self._libp2p_host is not None:
                try:
                    await self._libp2p_host.close()
                except Exception as e:
                    logger.error(f"Error while closing libp2p host: {e}", exc_info=True)
                finally:
                    self._libp2p_host = None

            # Clean up other resources
            self._libp2p_pubsub = None
            self._libp2p_gossipsub = None
            self._libp2p_key_pair = None
            self._libp2p_listen_addr = None

            logger.info("LibP2P peer stopped")

        except Exception as e:
            logger.error(f"Error during peer shutdown: {e}", exc_info=True)
        finally:
            self._is_running = False

    # Peer management
    async def connect_to_peer(self, peer_addr: str, *args, **kwargs) -> bool:
        """Connect to a peer using its multiaddress.

        Args:
            peer_addr: Multiaddress of the peer to connect to (e.g., "/ip4/127.0.0.1/tcp/12345/p2p/QmPeerId")
            *args: For backward compatibility (host, port)
            **kwargs: For backward compatibility

        Returns:
            bool: True if connection was successful, False otherwise
        """
        if not self._libp2p_host:
            logger.warning("Cannot connect to peer: host not initialized")
            return False

        try:
            # For backward compatibility with tests that pass host and port separately/co
            if args and len(args) >= 2 and "/" not in peer_addr:
                # Old style: connect_to_peer(peer_handle, host, port)
                peer_handle = peer_addr
                host = args[0]
                port = args[1]
                addr = f"/ip4/{host}/tcp/{port}/p2p/{peer_handle}"
            else:
                # New style: connect_to_peer("/ip4/1.2.3.4/tcp/1234/p2p/QmPeerId")
                addr = peer_addr
                # Extract peer_handle from the multiaddr
                parts = addr.split("/")
                if "p2p" in parts:
                    peer_handle = parts[parts.index("p2p") + 1]
                else:
                    peer_handle = "unknown"

            peer_info = info_from_p2p_addr(addr)

            # Connect to the peer
            await self._libp2p_host.connect(peer_info)

            # Add to known peers
            if peer_handle not in self._known_peers:
                self._known_peers[peer_handle] = PeerInfo(
                    handle=peer_handle,
                    host=peer_info.addrs[0].get("ip4") if peer_info.addrs else "",
                    port=peer_info.addrs[0].get("tcp") if peer_info.addrs else 0,
                    peer_id=peer_info.peer_id.to_string(),
                )

            logger.info(f"Connected to peer: {peer_handle}")

            # Notify status change
            await self._notify_status_change(peer_handle, NetworkState.CONNECTED)
            return True

        except Exception as e:
            logger.error(f"Failed to connect to peer {peer_addr}: {e}")
            return False

    async def send_message(self, recipient_id: str, message: Message | dict) -> bool:
        """Send a direct message to a specific peer.

        Args:
            recipient_id: The ID of the recipient peer
            message: The message to send (can be a Message object or a dict)

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        if not self._libp2p_host:
            logger.error("Cannot send message: Host not initialized")
            return False

        try:
            # Convert message to dict if it's a Message object
            if isinstance(message, Message):
                message_dict = message.to_dict()
            else:
                message_dict = message

            # Set sender if not already set
            if "sender" not in message_dict:
                message_dict["sender"] = self.peer_id

            # Serialize the message
            message_bytes = json.dumps(message_dict).encode()

            # Find the peer and open a stream
            peer_id = PeerID.from_base58(recipient_id)
            stream = await self._libp2p_host.new_stream(peer_id, ["/animavox/1.0.0"])

            # Send the message
            await stream.write(message_bytes)
            await stream.close()
            return True

        except Exception as e:
            logger.error(f"Failed to send message to {recipient_id}: {e}")
            return False

    # Internal handlers
    async def _handle_stream(self, stream):
        """Handle incoming stream connections."""
        try:
            # Read the message
            data = await stream.read()
            message_dict = json.loads(data.decode())

            # Convert to Message object
            message = Message.from_dict(message_dict)

            # Find appropriate handler
            handler = self._message_handlers.get(message.type)
            if handler:
                await handler(message.sender, message)
            else:
                logger.warning(f"No handler for message type: {message.type}")

        except Exception as e:
            logger.error(f"Error handling incoming message: {e}", exc_info=True)
        finally:
            await stream.close()

    async def _handle_pubsub_message(self, message_data: bytes) -> None:
        """Handle incoming pubsub messages.

        Args:
            message_data: The raw message data received via pubsub
        """
        if not message_data:
            logger.warning("Received empty message data")
            return

        try:
            # Log raw message data (first 100 chars to avoid huge logs)
            logger.debug(
                f"Raw message data received (truncated): {message_data[:100]}..."
            )

            # Parse the message
            try:
                message_dict = json.loads(message_data.decode())
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode message as JSON: {e}")
                return

            # Extract message type and sender
            message_type = message_dict.get("type")
            sender_id = message_dict.get("sender")

            if not message_type or not sender_id:
                logger.warning("Received message missing required fields")
                return

            # Don't process our own messages
            if sender_id == self.peer_id:
                return

            logger.debug(
                f"Received message from {sender_id} (type: {message_type}): {message_dict}"
            )

            # Create a Message object
            try:
                message = Message.from_dict(message_dict)
            except Exception as e:
                logger.error(f"Failed to create Message object: {e}")
                return

            # Call the appropriate handler if registered
            if message_type in self._message_handlers:
                try:
                    await self._message_handlers[message_type](sender_id, message)
                except Exception as e:
                    logger.error(
                        f"Error in message handler for type '{message.type}': {e}",
                        exc_info=True,
                    )
            else:
                logger.warning(
                    f"No handler registered for message type: {message.type}"
                )

        except Exception as e:
            logger.error(
                f"Unexpected error handling pubsub message: {e}", exc_info=True
            )

    async def _notify_status_change(self, peer_id: str, status: str | NetworkState) -> None:
        """Notify all status handlers about a peer status change.
        
        Args:
            peer_id: The ID of the peer whose status changed
            status: Either a status string or a NetworkState enum value
        """
        if isinstance(status, str):
            try:
                status = NetworkState(status)
            except ValueError:
                logger.warning(f"Unknown status string: {status}, defaulting to DISCONNECTED")
                status = NetworkState.DISCONNECTED
                
        for handler in self._status_handlers:
            try:
                await handler(peer_id, status)
            except Exception as e:
                logger.error(f"Error in status handler: {e}", exc_info=True)

    async def connect_to_bootstrap(self, host: str, port: int) -> bool:
        """Connect to a bootstrap node in the network.

        Args:
            host: The bootstrap node's host address
            port: The bootstrap node's port

        Returns:
            bool: True if connection was successful, False otherwise
        """
        if not self._libp2p_host:
            logger.warning("Cannot connect to bootstrap: host not initialized")
            return False

        try:
            # Construct the multiaddress from host and port
            peer_id = "bootstrap"  # This is just for logging, actual peer ID will come from the connection
            peer_addr = f"/ip4/{host}/tcp/{port}/p2p/{peer_id}"

            # Connect to the bootstrap node
            success = await self.connect_to_peer(peer_addr)
            if not success:
                return False

            logger.info(f"Connected to bootstrap node at {host}:{port}")

            # If we have pubsub, subscribe to the discovery topic
            if self._pubsub:
                await self._pubsub.subscribe("animavox-discovery")

            return True

        except Exception as e:
            logger.error(f"Failed to connect to bootstrap node {host}:{port}: {e}")
            return False

    async def _handle_pubsub_message(self, message_data: bytes) -> None:
        """Handle incoming pubsub messages.

        Args:
            message_data: The raw message data received via pubsub
        """
        if not message_data:
            logger.warning("Received empty message data")
            return

        try:
            # Log raw message data (first 100 chars to avoid huge logs)
            logger.debug(
                f"Raw message data received (truncated): {message_data[:100]}..."
            )

            # Parse the message
            try:
                message_dict = json.loads(message_data.decode())
                logger.debug(f"Decoded message dict: {message_dict}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode message as JSON: {e}")
                logger.debug(f"Raw message content: {message_data}")
                return
            except UnicodeDecodeError as e:
                logger.error(f"Failed to decode message as UTF-8: {e}")
                logger.debug(f"Raw message bytes: {message_data.hex()}")
                return

            # Skip messages from self
            sender = message_dict.get("sender")
            if sender == self.peer_id:
                logger.debug("Skipping message from self")
                return

            # Log the received message
            msg_type = message_dict.get("type", "unknown")
            logger.debug(f"Received pubsub message: {msg_type} from {sender}")

            # Create a Message object from the received data
            try:
                # Handle both direct content and nested content structure
                content = message_dict
                if "content" in message_dict:
                    content = message_dict["content"]
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except json.JSONDecodeError:
                            pass  # Keep as string if not JSON

                logger.debug(
                    f"Creating message with type={msg_type}, content={content}"
                )

                message = Message(
                    type=msg_type,
                    content=content,
                    sender=sender or "unknown",
                    recipient="",
                )
                logger.debug(f"Created message object: {message}")

            except Exception as e:
                logger.error(f"Failed to create message from data: {e}", exc_info=True)
                logger.debug(f"Message data that caused error: {message_dict}")
                return

            # Find and call the appropriate handler
            handler = self._message_handlers.get(message.type)
            logger.debug(f"Looking for handler for message type: {message.type}")
            logger.debug(f"Available handlers: {list(self._message_handlers.keys())}")

            if handler:
                try:
                    logger.debug(f"Calling handler for message type: {message.type}")
                    await handler(message.sender, message)
                    logger.debug(f"Handler for {message.type} completed successfully")
                except Exception as e:
                    logger.error(
                        f"Error in message handler for type '{message.type}': {e}",
                        exc_info=True,
                    )
            else:
                logger.warning(
                    f"No handler registered for message type: {message.type}"
                )

        except json.JSONDecodeError:
            logger.error(
                f"Failed to decode pubsub message (invalid JSON): {message_data}"
            )
        except Exception as e:
            logger.error(
                f"Unexpected error handling pubsub message: {e}", exc_info=True
            )

    async def broadcast(self, message: Message | dict) -> int:
        """Broadcast a message to all connected peers via pubsub.

        Args:
            message: The message to broadcast (can be a Message object or a dict)

        Returns:
            int: Number of peers the message was sent to (approximate)
        """
        if not self._is_running:
            logger.warning("Cannot broadcast: peer is not running")
            return 0

        if not self._pubsub:
            logger.error("Cannot broadcast: pubsub is not initialized")
            return 0

        if not self._libp2p_host:
            logger.error("Cannot broadcast: libp2p host is not initialized")
            return 0

        try:
            # Convert dict to Message if needed
            if isinstance(message, dict):
                if "type" not in message:
                    raise ValueError("Message must have a 'type' field")
                message = Message(
                    type=message["type"],
                    content=message.get("content", {}),
                    sender=self.peer_id,
                    recipient="",
                )

            # Ensure the message has required fields
            if not hasattr(message, "type") or not message.type:
                raise ValueError("Message must have a 'type' field")

            # Create a dictionary with the message data that matches what the handler expects
            message_dict = {
                "type": message.type,
                "content": message.content,
                "sender": self.peer_id,
                "timestamp": time.time(),
            }

            # Convert to JSON and encode
            try:
                message_data = json.dumps(message_dict).encode("utf-8")
                logger.debug(f"Serialized message data: {message_data}")
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to serialize message: {e}", exc_info=True)
                return 0

            # Publish the message to the pubsub topic
            try:
                topic = self._broadcast_topic
                logger.debug(f"Publishing message to topic '{topic}': {message_dict}")

                # Publish the message using the PubSub API
                logger.debug(
                    f"Publishing to topic={topic}, data_length={len(message_data)}"
                )

                # Publish the message
                await self._pubsub.publish(topic, message_data)

                # Log success
                network = self._libp2p_host.get_network()
                peer_count = len(network.connections) if network else 0
                logger.info(
                    f"Successfully published message '{message.type}' to ~{peer_count} peers"
                )

                # Return the approximate number of peers
                return max(1, peer_count)  # At least 1 peer (ourselves)

            except Exception as e:
                logger.error(f"Failed to publish message: {e}", exc_info=True)
                return 0

        except Exception as e:
            logger.error(f"Unexpected error in broadcast: {e}", exc_info=True)
            return 0
