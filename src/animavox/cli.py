import json
import os

import rich_click as click
from rich import print
from rich.pretty import Pretty
from rich.json import JSON

from . import __version__
from ._utils import _get_info
from .telepathic_objects import TelepathicObject


def print_transaction_log(txn_log):
    for txn in txn_log:
        print(
            f"[{txn['timestamp']} - {txn['transaction_id']}] [cyan]{txn['action']}[/cyan] {txn['path']}"
        )
        if txn["action"] == "init":
            print(f"  [green]Initialized data structure...")
        else:  # 'set' action
            print(
                f"  [green]Changed: {json.dumps(txn['value']['old'])} -> {json.dumps(txn['value']['new'])}"
            )
            if txn["message"]:
                print(f"  Note: {txn['message']}")


@click.group()
@click.version_option(version=__version__)
def cli():
    pass


@cli.command()
@click.option(
    "--ofile",
    type=click.Path(
        exists=False,
        writable=True,
    ),
    default="my-state.yjs",
    show_default=True,
    help="Path to save (and later reload) the TelepathicObject CRDT state.",
)
def example(ofile: str):
    """A simple CLI tool for animavox."""
    print("[bold cyan]Welcome to animavox![/bold cyan]")
    print("Let's make an example object:")
    obj = TelepathicObject(
        {
            "root": {
                "collection": {
                    "friends": [
                        {
                            "name": "hugin",
                            "age": 999,
                            "tags": [
                                "raven",
                                "thought",
                            ],
                        }
                    ],
                }
            }
        }
    )
    print(obj)
    assert "data" in obj.doc

    print("Let's get some information about the object:")
    print(Pretty(_get_info(obj)))
    print(JSON(obj.to_json()))

    print("We can save it to disk to get a reproducible state:")
    print("We use save_from_scratch, since this object does not exist at all yet...")
    obj.save_from_scratch(ofile)

    # Update a value:
    print("Now we update something. Let's set the age to 1000:")
    obj.set_field("root/collection/friends/0/age", 1000)
    print("Let's also do a more complex update")
    print("...adding 'new-tag' to the tags list:")
    obj.set_field("root/collection/friends/0/tags", ["raven", "thought", "new-tag"])
    print("...adding a new attribute 'birthday':")
    obj.set_field("root/collection/friends/0/birthday", "2025-07-17")
    print("...adding a new attribute 'hobbies' (test of lists)")
    obj.set_field("root/collection/friends/0/hobbies", ["reading", "gaming", "hiking"])
    print(obj)
    print(Pretty(_get_info(obj)))
    print(JSON(obj.to_json()))

    print("We can get a clean record of all the transactions to our object:")
    print_transaction_log(obj.get_transaction_log())

    print(
        "That's pretty cool. We can do something even cooler though, you can save the transactions individually:"
    )
    obj.save_transaction_history("transactions")

    print("Now let's load the saved state:")
    print("First check if the file exists and is sensible:")
    try:
        with open(ofile, "rb") as f:
            data = f.read()
        print(f"[green]File check:[/] {len(data)} bytes; first 16 bytes: {data[:16]!r}")
    except FileNotFoundError:
        print(f"[red]File not found:[/] {ofile}")
        sys.exit(1)

    print(
        "Looks good. Now remember, we saved *before* the update, so we should get back the original state before the age change:"
    )
    print("Now re-create the object:")
    print("\n=== Loading saved state ===")
    loaded_obj = TelepathicObject.load(ofile)
    print(loaded_obj)
    print(Pretty(_get_info(loaded_obj)))
    print(JSON(loaded_obj.to_json()))
    print(
        "Note that this transaction log is different from what we had before in the new object:"
    )
    print_transaction_log(loaded_obj.get_transaction_log())

    # Now let's apply the saved transactions
    print("\n=== Applying saved transactions ===")
    transaction_dir = "transactions"
    if os.path.exists(transaction_dir) and os.path.isdir(transaction_dir):
        # Get all transaction files sorted by name (which should be in chronological order)
        txn_files = sorted(
            [f for f in os.listdir(transaction_dir) if f.endswith(".json")]
        )

        if not txn_files:
            print("No transaction files found in the transactions directory.")
            return

        print(f"Found {len(txn_files)} transaction files to apply...")

        for txn_file in txn_files:
            txn_path = os.path.join(transaction_dir, txn_file)
            try:
                with open(txn_path, "r") as f:
                    txn_data = json.load(f)

                print(f"\nApplying transaction from {txn_file}:")
                print(f"  Action: {txn_data['action']} {txn_data['path']}")
                if txn_data["action"] == "set":
                    print(
                        f"  Change: {json.dumps(txn_data['value']['old'])} -> {json.dumps(txn_data['value']['new'])}"
                    )

                # Apply the transaction
                loaded_obj.apply_transaction(txn_data)
                print(
                    f"  [green]✓ Successfully applied transaction {txn_data['transaction_id'][:8]}..."
                )

            except Exception as e:
                print(f"  [red]✗ Failed to apply transaction {txn_file}: {str(e)}")

        print("After applying transactions, log now is:")
        print_transaction_log(loaded_obj.get_transaction_log())

        print("\nFinal state after applying all transactions:")
        print(loaded_obj)
        print(loaded_obj.data)
        print(loaded_obj.to_json())
    else:
        print(f"No transaction directory found at '{transaction_dir}'")


def main():
    cli()


if __name__ == "__main__":
    main()
