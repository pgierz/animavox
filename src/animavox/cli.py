import sys

import rich_click as click
from rich import print
from rich.json import JSON
from rich.pretty import Pretty

from . import __version__
from ._utils import _get_info
from .telepathic_objects import TelepathicObject


@click.command()
@click.version_option(version=__version__)
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
def main(ofile: str):
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
    print(obj)
    print(Pretty(_get_info(obj)))
    print(JSON(obj.to_json()))

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
    obj2 = TelepathicObject.load(ofile)

    print(obj2)
    print(Pretty(_get_info(obj2)))
    print(JSON(obj2.to_json()))


if __name__ == "__main__":
    main()
