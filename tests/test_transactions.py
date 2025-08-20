import json
from datetime import datetime

import pytest

from animavox.telepathic_objects import (DateTimeEncoder, TelepathicObject,
                                         TelepathicObjectTransaction)


@pytest.fixture()
def simple_object():
    obj = TelepathicObject()
    obj.set_field("name", "Test Object")
    obj.set_field("count", 10)
    obj.set_field("tags", ["tag1", "tag2"])
    return obj


@pytest.fixture()
def sample_transaction():
    return TelepathicObjectTransaction(
        action="set", path="test/path", value="test value", message="Test transaction"
    )


def test_transaction_initialization():
    """Test that a transaction is properly initialized with all attributes."""
    txn = TelepathicObjectTransaction(
        action="set", path="test/path", value="test value", message="Test transaction"
    )

    assert txn.action == "set"
    assert txn.path == "test/path"
    assert txn.value == "test value"
    assert txn.message == "Test transaction"
    assert isinstance(txn.timestamp, datetime)
    assert len(txn.transaction_id) == 64  # SHA-256 hex digest length


def test_transaction_to_dict(sample_transaction):
    """Test conversion of transaction to dictionary."""
    txn_dict = sample_transaction.to_dict()

    assert isinstance(txn_dict, dict)
    assert txn_dict["action"] == "set"
    assert txn_dict["path"] == "test/path"
    assert txn_dict["value"] == "test value"
    assert txn_dict["message"] == "Test transaction"
    assert "transaction_id" in txn_dict
    assert "timestamp" in txn_dict


def test_transaction_from_dict():
    """Test creating a transaction from a dictionary."""
    txn_data = {
        "action": "set",
        "path": "test/path",
        "value": "test value",
        "message": "Test transaction",
        "timestamp": "2023-01-01T00:00:00",
        "transaction_id": "test_id_123",
    }

    txn = TelepathicObjectTransaction.from_dict(txn_data)

    assert txn.action == "set"
    assert txn.path == "test/path"
    assert txn.value == "test value"
    assert txn.message == "Test transaction"
    assert txn.transaction_id == "test_id_123"
    assert isinstance(txn.timestamp, datetime)


def test_transaction_serialization_roundtrip(sample_transaction):
    """Test that a transaction can be serialized and deserialized."""
    # Convert to dict and back
    txn_dict = sample_transaction.to_dict()
    txn_json = json.dumps(txn_dict, cls=DateTimeEncoder)
    txn_dict_loaded = json.loads(txn_json)
    new_txn = TelepathicObjectTransaction.from_dict(txn_dict_loaded)

    # Check that all attributes match
    assert new_txn.action == sample_transaction.action
    assert new_txn.path == sample_transaction.path
    assert new_txn.value == sample_transaction.value
    assert new_txn.message == sample_transaction.message
    assert new_txn.transaction_id == sample_transaction.transaction_id
    assert new_txn.timestamp == sample_transaction.timestamp


def test_transaction_id_consistency():
    """Test that the transaction ID is consistent for the same data."""
    # Create a fixed time for consistent testing
    fixed_time = datetime(2023, 1, 1, 12, 0, 0)

    # Create transactions with the same data and timestamp
    txn1 = TelepathicObjectTransaction("set", "path", "value")
    txn1.timestamp = fixed_time

    txn2 = TelepathicObjectTransaction("set", "path", "value")
    txn2.timestamp = fixed_time

    # The IDs should match since all data is the same
    assert txn1.transaction_id == txn2.transaction_id

    # Create a transaction with different data
    txn3 = TelepathicObjectTransaction("set", "different_path", "value")
    txn3.timestamp = fixed_time

    # Different data should result in different IDs
    assert txn1.transaction_id != txn3.transaction_id


def test_transaction_repr(sample_transaction):
    """Test the string representation of a transaction."""
    repr_str = repr(sample_transaction)
    assert "TelepathicObjectTransaction" in repr_str
    assert sample_transaction.action in repr_str
    assert sample_transaction.path in repr_str
    assert sample_transaction.transaction_id[:8] in repr_str


def test_simple_object_save_transaction_history(simple_object, tmp_path):
    """Test saving transaction history to disk."""
    save_dir = tmp_path / "transaction_history"
    simple_object.save_transaction_history(save_dir)

    # Directory should exist
    assert save_dir.exists()

    # Should have created transaction files
    txn_files = list(save_dir.glob("*.json"))
    assert len(txn_files) > 0


def test_simple_object_serialize_transaction(simple_object):
    """Test that transactions from an object can be serialized."""
    transactions = simple_object.get_transaction_log()
    assert len(transactions) > 0

    for txn in transactions:
        txn_dict = txn.to_dict()
        assert "timestamp" in txn_dict
        assert "action" in txn_dict
        assert "path" in txn_dict
        assert "value" in txn_dict
        assert "message" in txn_dict
        assert "transaction_id" in txn_dict

        # Should be able to create a new transaction from the dict
        new_txn = TelepathicObjectTransaction.from_dict(txn_dict)
        assert new_txn.transaction_id == txn.transaction_id


# Note: test_apply_transaction_history removed - old transaction loading functionality
# is deprecated in favor of the new distributed CRDT synchronization system
