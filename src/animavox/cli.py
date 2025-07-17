import json
import os
import time

import rich_click as click
from rich import print
from rich.console import Console
from rich.json import JSON
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.box import ROUNDED

from . import __version__
from .telepathic_objects import TelepathicObject


def print_transaction_log(txn_log):
    for txn in txn_log:
        print(
            f"[{txn['timestamp']} - {txn['transaction_id']}] [cyan]{txn['action']}[/cyan] {txn['path']}"
        )
        if txn["action"] == "init":
            print("  [green]Initialized data structure...")
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


class LiveDisplay:
    def __init__(self):
        self.console = Console()
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )
        self.live = None

    def __enter__(self):
        self.live = Live(self.layout, refresh_per_second=4, screen=True)
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.live:
            self.live.__exit__(exc_type, exc_val, exc_tb)

    def make_step(self, step_name: str, content: str = "", is_error: bool = False):
        """Helper to update the layout with a new step

        Args:
            step_name: The title of the step to display
            content: The content to display (string or Rich renderable)
            is_error: If True, display as an error
        """
        # Update header with appropriate color
        if is_error:
            self.layout["header"].update(
                Panel(
                    f"[bold red]Error: {step_name}[/bold red]",
                    border_style="red",
                    box=ROUNDED,
                )
            )
            border_style = "red"
        else:
            self.layout["header"].update(
                Panel(
                    f"[bold blue]Step: {step_name}[/bold blue]",
                    border_style="blue",
                    box=ROUNDED,
                )
            )
            border_style = "blue"

        # Update main content if provided
        if content:
            if isinstance(content, str):
                self.layout["main"].update(
                    Panel(
                        content,
                        border_style=border_style,
                        box=ROUNDED,
                    )
                )
            else:
                self.layout["main"].update(content)

        # Update the display
        self.live.update(self.layout)
        time.sleep(0.5)

    def make_error(self, title: str, message: str):
        """Show an error message.

        Args:
            title: The error title/heading
            message: The error message content
        """
        self.make_step(
            title,
            Panel(
                message,
                title="Error",
                border_style="red",
                box=ROUNDED,
            ),
            is_error=True,
        )


@cli.command()
@click.argument(
    "ofile",
    type=click.Path(
        exists=False,
        writable=True,
    ),
    default="my-state.yjs",
    required=False,
)
def example(ofile: str = "my-state.yjs"):
    """Run a simple example that shows off the basic functionality with rich output.

    OFILE: Path to save (and later reload) the TelepathicObject CRDT state.
    """
    """Run a simple example that shows off the basic functionality with rich output."""
    with LiveDisplay() as display:
        try:
            # Create a new object
            display.make_step("Creating a new TelepathicObject...")
            obj = TelepathicObject()
            time.sleep(0.5)

            # Make some changes
            display.make_step("Setting some fields...")
            obj.set_field("name", "Test Object", "Initial setup")
            obj.set_field("status", "active", "Initial setup")
            obj.set_field("config/theme", "dark", "User preference")
            obj.set_field("config/notifications/enabled", True, "User preference")
            obj.set_field("config/notifications/sound", "ding", "User preference")
            time.sleep(1)

            # Show the current state
            display.make_step(
                "Current State",
                Panel(
                    f"{JSON(json.dumps(obj.to_dict()))}",
                    title="Current Object State",
                    border_style="green",
                    box=ROUNDED,
                ),
            )
            time.sleep(1)

            # Show transaction log
            log_entries = "\n".join(
                f"[dim]{entry['timestamp']}[/dim] - [bold]{entry['action']} {entry.get('path', '')}[/bold]\n"
                f"  {entry.get('message', '')}"
                for entry in obj.get_transaction_log()
            )

            display.make_step(
                "Transaction Log",
                Panel(
                    log_entries,
                    title="Transaction History",
                    border_style="yellow",
                    box=ROUNDED,
                ),
            )

            # Save the state
            display.make_step("Saving state...")
            obj.save(ofile)
            time.sleep(1)

            # Show saved state info
            file_size = os.path.getsize(ofile)
            display.make_step(
                "State Saved",
                f"[green]✓ State saved to {ofile} ({file_size} bytes)[/green]\n"
                f"[dim]File path: {os.path.abspath(ofile)}[/dim]",
            )
            time.sleep(1)

            # Save transaction log
            obj.save_transaction_history("transactions")

            display.make_step(
                "Transaction Log Saved",
                Panel(
                    "[green]✓ Transaction log saved to transactions directory.[/green]",
                    border_style="green",
                    box=ROUNDED,
                ),
            )

            # Final completion message
            display.layout["footer"].update(
                "[green]✓ Main demo completed successfully![/green]"
            )
            time.sleep(2)

            # Initialize the main live display
            with LiveDisplay() as loaded_display:
                try:
                    # Update the layout with loading message
                    loaded_display.make_step("Loading saved state...")
                    time.sleep(0.5)

                    # Read the saved file
                    with open(ofile, "rb") as f:
                        data = f.read()

                    # Update with file check status
                    loaded_display.make_step(
                        "File Check",
                        f"[green]✓ File check passed:[/green] {len(data)} bytes; "
                        f"first 16 bytes: {data[:16]!r}",
                    )
                    time.sleep(1)

                    # Create and load the object
                    loaded_display.make_step("Creating object from saved state...")
                    obj2 = TelepathicObject()
                    obj2.load(ofile)

                    # Show loaded object
                    loaded_display.make_step(
                        "Loaded Object",
                        Panel(
                            f"[bold]Loaded Object:[/bold] {obj2}\n"
                            f"[bold]Type:[/bold] {type(obj2).__name__}\n"
                            f"[bold]Content:[/bold]\n{JSON(json.dumps(obj2.to_dict()))}",
                            title="Loaded Object",
                            border_style="green",
                            box=ROUNDED,
                        ),
                    )
                    time.sleep(1)

                except Exception as e:
                    loaded_display.make_error(
                        "Error Loading State", f"Failed to load saved state: {str(e)}"
                    )
                    time.sleep(2)
                    return

                # Show transaction log comparison
                loaded_display.make_step(
                    "Transaction Log Comparison",
                    "Note that this transaction log is different from what we had before in the new object",
                )
                time.sleep(1)

                # Apply saved transactions if any
                transaction_dir = "transactions"
                if os.path.exists(transaction_dir) and os.path.isdir(transaction_dir):
                    txn_files = sorted(
                        [f for f in os.listdir(transaction_dir) if f.endswith(".json")]
                    )

                    if txn_files:
                        loaded_display.make_step(
                            f"Found {len(txn_files)} transaction files to apply..."
                        )

                        with Progress(
                            SpinnerColumn(),
                            TextColumn("[progress.description]{task.description}"),
                            console=loaded_display.console,
                            transient=True,
                        ) as progress:
                            task = progress.add_task(
                                "Applying transactions...", total=len(txn_files)
                            )
                            results = []

                            for idx, txn_file in enumerate(txn_files, 1):
                                txn_path = os.path.join(transaction_dir, txn_file)
                                try:
                                    with open(txn_path, "r") as f:
                                        txn_data = json.load(f)

                                    progress.update(
                                        task, description=f"Applying {txn_file}"
                                    )
                                    obj2.apply_transaction(txn_data)

                                    results.append(
                                        f"[green]✓[/green] {txn_file}: {txn_data.get('action')} {txn_data.get('path', '')}"
                                    )

                                except Exception as e:
                                    results.append(f"[red]✗[/red] {txn_file}: {str(e)}")

                                progress.update(task, completed=idx + 1)
                                time.sleep(0.1)

                        # Show transaction results
                        loaded_display.make_step(
                            "Transaction Results",
                            Panel(
                                "\n".join(results),
                                title="Transaction Application Results",
                                border_style="blue",
                                box=ROUNDED,
                            ),
                        )

                        # Show final state after transactions
                        loaded_display.make_step(
                            "Final State After Transactions",
                            Panel(
                                f"{JSON(json.dumps(obj2.to_dict()))}",
                                title="Final State After Transactions",
                                border_style="green",
                                box=ROUNDED,
                            ),
                        )

                        # Show transaction log
                        with Progress(
                            SpinnerColumn(),
                            TextColumn("[progress.description]{task.description}"),
                            transient=True,
                        ) as progress:
                            task = progress.add_task(
                                "Processing transaction log...", total=1
                            )
                            log_entries = "\n".join(
                                f"{entry['timestamp']} - {entry['operation']}: {entry.get('path', '')} = {entry.get('value', '')}"
                                for entry in obj2.get_transaction_log()
                            )
                            progress.update(task, completed=1)

                        loaded_display.make_step(
                            "Transaction Log from Loaded Object",
                            Panel(
                                log_entries,
                                title="Transaction Log",
                                border_style="green",
                            ),
                        )

                    else:
                        loaded_display.make_error(
                            "No Transactions",
                            "[yellow]No transaction files found in the transactions directory.[/yellow]",
                        )
                else:
                    loaded_display.make_error(
                        "No Transaction Directory",
                        f"[yellow]No transaction directory found at '{transaction_dir}'[/yellow]",
                    )

                # Save the modified state
                loaded_display.make_step("Saving modified state...")
                obj2.save("modified-state.yjs")

                # Final message
                loaded_display.make_step(
                    "Demo Complete!",
                    "[green]✓ Successfully completed the demo![/green]\n"
                    "The modified state has been saved to 'modified-state.yjs'.",
                )

                # Final completion message
                loaded_display.layout["footer"].update(
                    "[green]✓ Demo completed successfully![/green]"
                )
                time.sleep(2)

        except Exception as e:
            display.make_error(
                "An Error Occurred", f"An unexpected error occurred: {str(e)}"
            )
            time.sleep(2)


def main():
    cli()


if __name__ == "__main__":
    main()
