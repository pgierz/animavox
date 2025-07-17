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
def example(ofile: str = "my-state.yjs"):
    """Run a simple example that shows off the basic functionality with rich output."""
    console = Console()
    
    # Create a live display for dynamic updates
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3),
    )
    
    def make_step(step_name: str, content: str = ""):
        """Helper to update the layout with a new step"""
        layout["header"].update(f"[bold blue]Step:[/] {step_name}")
        if content:
            if isinstance(content, str):
                layout["main"].update(Panel(content, border_style="blue"))
            else:
                layout["main"].update(content)
        console.print(layout, end="")
        time.sleep(0.5)
    
    # Wrap the entire demo in a Live display
    with Live(console=console, refresh_per_second=4):
        # Initial setup
        make_step("Initializing...", "Starting the demo...")
        
        # Create and show initial object
        make_step("Creating initial object...")
        obj = TelepathicObject()
        
        # Set initial data
        make_step("Setting initial data...")
        obj.set_field("root/collection/friends/0/name", "Alice")
        obj.set_field("root/collection/friends/0/age", 30)
        obj.set_field("root/collection/friends/0/tags", ["happy", "friendly"])
        
        # Show initial state
        make_step("Initial State",
                 Panel(
                     f"{JSON(json.dumps(obj.to_dict()))}",
                     title="Initial Object State",
                     border_style="green",
                     box=ROUNDED
                 ))
        
        # Save state
        make_step("Saving state...")
        obj.save(ofile)
        make_step("State Saved", 
                 f"[green]✓ Saved state to {ofile}[/green]\n"
                 f"[dim]File size: {os.path.getsize(ofile)} bytes")
        
        # Make updates
        updates = [
            ("Update age to 1000", "root/collection/friends/0/age", 1000),
            ("Add 'new-tag' to tags", "root/collection/friends/0/tags", ["happy", "friendly", "new-tag"]),
            ("Add birthday", "root/collection/friends/0/birthday", "1993-04-15"),
            ("Add hobbies", "root/collection/friends/0/hobbies", ["reading", "hiking"])
        ]
        
        for desc, path, value in updates:
            # Instead of using console.status, just show the step
            make_step(f"Applying update: {desc}...")
            time.sleep(0.5)
            obj.set_field(path, value, message=desc)
            make_step(f"Applied: {desc}",
                     Panel(
                         f"[bold]Field:[/bold] {path}\n"
                         f"[bold]New Value:[/bold] {JSON(json.dumps(value))}",
                             border_style="blue",
                             box=ROUNDED
                         ))
        
        # Show final state
        make_step("Final State",
                 Panel(
                     f"{JSON(json.dumps(obj.to_dict()))}",
                     title="Final Object State",
                     border_style="green",
                     box=ROUNDED
                 ))
        
        # Show transaction log
        log_entries = "\n".join(
            f"[dim]{entry['timestamp']}[/dim] - [bold]{entry['action']} {entry.get('path', '')}[/bold]\n"
            f"  {entry.get('message', '')}"
            for entry in obj.get_transaction_log()
        )
        
        make_step("Transaction Log",
                 Panel(
                     log_entries,
                     title="Transaction History",
                     border_style="yellow",
                     box=ROUNDED
                 ))
        
        # Final completion message
        layout["footer"].update("[green]✓ Main demo completed successfully![/green]")
        time.sleep(2)
        
        # Load saved state section
        make_step("Loading saved state...")
        time.sleep(0.5)
        
        try:
            with open(ofile, "rb") as f:
                data = f.read()
            make_step("File Check", 
                     f"[green]✓ File check passed:[/green] {len(data)} bytes; "
                     f"first 16 bytes: {data[:16]!r}")
            time.sleep(1)
            
            # Create new object from saved state
            make_step("Creating object from saved state...")
            obj2 = TelepathicObject()
            obj2.load(ofile)
            
            make_step("Loaded Object", 
                     Panel(
                         f"[bold]Loaded Object:[/bold] {obj2}\n"
                         f"[bold]Type:[/bold] {type(obj2).__name__}\n"
                         f"[bold]Content:[/bold]\n{JSON(json.dumps(obj2.to_dict()))}",
                         title="Loaded Object",
                         border_style="green",
                         box=ROUNDED
                     ))
            time.sleep(1)
            
            # Show transaction log comparison
            make_step("Transaction Log Comparison", 
                     "Note that this transaction log is different from what we had before in the new object")
            time.sleep(1)
            
            # Apply saved transactions if any
            transaction_dir = "transactions"
            if os.path.exists(transaction_dir) and os.path.isdir(transaction_dir):
                txn_files = sorted([f for f in os.listdir(transaction_dir) if f.endswith(".json")])
                
                if txn_files:
                    make_step(f"Found {len(txn_files)} transaction files to apply...")
                    
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        console=console,
                        transient=True,
                    ) as progress:
                        task = progress.add_task("Applying transactions...", total=len(txn_files))
                        results = []
                        
                        for idx, txn_file in enumerate(txn_files, 1):
                            txn_path = os.path.join(transaction_dir, txn_file)
                            try:
                                with open(txn_path, "r") as f:
                                    txn_data = json.load(f)
                                
                                progress.update(task, description=f"Applying {txn_file}")
                                obj2.apply_transaction(txn_data)
                                
                                results.append(
                                    f"[green]✓[/green] {txn_file}: {txn_data.get('action')} {txn_data.get('path', '')}"
                                )
                                
                            except Exception as e:
                                results.append(
                                    f"[red]✗[/red] {txn_file}: {str(e)}"
                                )
                            
                            progress.update(task, completed=idx)
                            time.sleep(0.1)
                    
                    # Show transaction results
                    make_step("Transaction Results", 
                             Panel(
                                 "\n".join(results),
                                 title="Transaction Application Results",
                                 border_style="blue",
                                 box=ROUNDED
                             ))
                    
                    # Show final state after transactions
                    make_step("Final State After Transactions",
                             Panel(
                                 f"{JSON(json.dumps(obj2.to_dict()))}",
                                 title="Final State After Transactions",
                                 border_style="green",
                                 box=ROUNDED
                             ))
                    
                    # Show final transaction log
                    log_entries = "\n".join(
                        f"[dim]{entry['timestamp']}[/dim] - [bold]{entry['action']} {entry.get('path', '')}[/bold]\n"
                        f"  {entry.get('message', '')}"
                        for entry in obj2.get_transaction_log()
                    )
                    
                    make_step("Final Transaction Log",
                             Panel(
                                 log_entries,
                                 title="Final Transaction Log",
                                 border_style="yellow",
                                 box=ROUNDED
                             ))
                    
                else:
                    make_step("No Transactions", 
                             "[yellow]No transaction files found in the transactions directory.[/yellow]")
            else:
                make_step("No Transaction Directory",
                         f"[yellow]No transaction directory found at '{transaction_dir}'[/yellow]")
            
            # Final completion message
            layout["footer"].update("[green]✓ Demo completed successfully![/green]")
            time.sleep(2)
            
        except Exception as e:
            make_step("Error Loading State", 
                     Panel(
                         f"[red]Error loading saved state:[/red] {str(e)}",
                         border_style="red",
                         box=ROUNDED
                     ))
            time.sleep(2)

    # The demo is now fully interactive with the Live display
    # All output is handled within the Live context
    pass


def main():
    cli()


if __name__ == "__main__":
    main()
