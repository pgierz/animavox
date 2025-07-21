import json
import os
import sys
import time

import rich_click as click
from rich import print
from rich.box import ROUNDED
from rich.console import Console, Group
from rich.json import JSON
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import __version__
from .telepathic_objects import TelepathicObject


def wait_for_key_press():
    input("Press Enter to continue...")


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

    def make_step(
        self,
        step_name: str,
        content: str = "",
        is_error: bool = False,
    ):
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
        self.layout["footer"].update(
            Panel(
                "Press Enter to continue...",
                border_style=border_style,
                box=ROUNDED,
            )
        )
        self.live.update(self.layout)
        wait_for_key_press()

    def _get_current_content(self):
        """Helper to safely get current content from the main panel."""
        panel = self.layout["main"].renderable
        if not hasattr(panel, "renderable"):
            return panel
        return panel.renderable if panel.renderable != panel else None

    def _update_panel(self, content):
        """Helper to update the main panel with new content."""
        self.layout["main"].update(
            Panel(content, border_style="yellow", box=ROUNDED, expand=True)
        )
        self.live.update(self.layout)
        wait_for_key_press()

    def push(self, text: str) -> None:
        """Append plain text content to the main panel.

        Args:
            text: The text content to append. Will be added with proper spacing.
        """
        current = self._get_current_content()
        if current is None:
            new_content = text
        elif isinstance(current, str):
            new_content = f"{current}\n\n{text}" if current.strip() else text
        else:
            new_content = Group(current, "", text) if str(current).strip() else text
        self._update_panel(new_content)

    def push_raw(self, renderable) -> None:
        """Append a Rich renderable object to the main panel.

        Args:
            renderable: Any Rich renderable object (Panel, Table, etc.)
        """
        current = self._get_current_content()
        if current is None:
            new_content = renderable
        elif isinstance(current, Group):
            new_content = Group(*current.renderables, "", renderable)
        else:
            new_content = Group(current, "", renderable)
        self._update_panel(new_content)

    def push_code(self, code: str, language: str = "python") -> None:
        """Display a code block with syntax highlighting.

        Args:
            code: The source code to display
            language: Language for syntax highlighting (default: "python")
        """
        from rich.syntax import Syntax

        self.push_raw(
            Panel(
                Syntax(
                    code,
                    language,
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                    background_color="default",
                ),
                border_style="blue",
                box=ROUNDED,
                expand=False,
            )
        )

    def push_python(
        self,
        code: str,
        globals_dict=None,
        locals_dict=None,
        title: str = "Python",
        capture_globally: bool = False,  # Changed default to False for safety
        hide_code: bool = False,
    ) -> any:
        """Execute Python code and display the code and its result.

        This method will:
        1. Display the code with syntax highlighting
        2. Execute the code in the specified context
        3. Update the global namespace if capture_globally is True
        4. Display the result or any errors

        Args:
            code: The Python code to execute
            globals_dict: Optional dictionary for globals. If None, uses an empty dict.
            locals_dict: Optional dictionary for locals. If None, uses the same as globals.
            title: Optional title for the code panel (default: "Python")
            capture_globally: If True, updates the actual global namespace with any new variables

        Returns:
            The result of the executed code, or None if execution fails

        Example:
            display.push_python("x = 2 + 2")  # Creates x in global scope
            display.push_python("x * 2")      # Shows 4
        """
        # Show the code with syntax highlighting
        if not hide_code:
            self.push_code(code, language="python")

        # Set up execution context
        globals_dict = globals_dict or {}
        locals_dict = locals_dict or globals_dict

        # If we're capturing globally, we need to merge with actual globals
        if capture_globally:
            globals_dict = {**globals(), **globals_dict}

        try:
            # First try to compile to see if it's an expression
            try:
                # Try to compile as an expression
                code_obj = compile(code, "<string>", "eval")
                is_expression = True
            except SyntaxError:
                # If not an expression, compile as a statement
                code_obj = compile(code, "<string>", "exec")
                is_expression = False

            # Execute the code
            if is_expression:
                result = eval(code_obj, globals_dict, locals_dict)
            else:
                # For statements, we need to handle assignments specially
                # Make a copy of the locals before execution to detect changes
                before_locals = set(locals_dict.keys())
                before_globals = set(globals_dict.keys())

                # Execute the code
                exec(code_obj, globals_dict, locals_dict)

                # Find any new variables that were created
                new_locals = set(locals_dict.keys()) - before_locals
                new_globals = set(globals_dict.keys()) - before_globals

                # If we captured new variables in the global scope, update the actual globals
                if capture_globally and new_globals:
                    for name in new_globals:
                        globals()[name] = globals_dict[name]

                # Try to get a result for display
                result = None
                if "=" in code:
                    # Try to get the last assignment
                    try:
                        var_name = (
                            code.split("=")[0].strip().split()[-1]
                        )  # Get the variable name
                        if var_name in locals_dict:
                            result = locals_dict[var_name]
                        elif var_name in globals_dict:
                            result = globals_dict[var_name]
                    except:
                        pass

            # Show the result if we have one
            if result is not None:
                self.push_raw(
                    Panel(
                        str(result),
                        title="Result",
                        border_style="green",
                        box=ROUNDED,
                        expand=False,
                    )
                )
            return result

        except Exception as e:
            # Show errors in red
            self.push_raw(
                Panel(
                    f"[red]{type(e).__name__}: {str(e)}[/red]",
                    title="Error",
                    border_style="red",
                    box=ROUNDED,
                )
            )
            raise

    def push_shell(self, command: str, cwd: str = None, title: str = "Shell") -> None:
        """Execute a shell command and display its output.

        Args:
            command: The shell command to execute
            cwd: Working directory for the command (default: current directory)
            title: Optional title for the command panel (default: "Shell")

        Example:
            display.push_shell("ls -la", title="Directory Contents")
        """
        import subprocess
        from rich.panel import Panel
        from rich.syntax import Syntax

        # Show the command being executed
        self.push_code(f"$ {command}", language="bash")

        cwd = cwd or os.getcwd()

        try:
            # Run the command and capture output
            result = subprocess.run(
                command,
                shell=True,
                check=True,
                text=True,
                capture_output=True,
                cwd=cwd,
            )

            output = result.stdout
            if not output and result.stderr:
                output = (
                    f"[yellow]No output on stdout. Stderr:[/yellow]\n{result.stderr}"
                )

        except subprocess.CalledProcessError as e:
            output = (
                f"[red]Command failed with code {e.returncode}[/red]\n"
                f"[yellow]Command:[/yellow] {command}\n"
                f"[yellow]Working dir:[/yellow] {cwd}\n"
                "\n[bold]Output:[/bold]\n"
                f"{e.stdout or 'No output'}\n"
                "\n[bold]Error:[/bold]\n"
                f"{e.stderr or 'No error details'}"
            )
        except Exception as e:
            output = f"[red]Error executing command:[/red] {str(e)}"

        # Display the output in a panel
        self.push_raw(
            Panel(
                output.strip(),
                title=f"Output: {title}",
                border_style="blue",
                box=ROUNDED,
                expand=False,
            )
        )

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
def demo(ofile: str = "my-state.yjs"):
    """Run a simple example that shows off the basic functionality with rich output.

    OFILE: Path to save (and later reload) the TelepathicObject CRDT state.
    """
    """Run a simple example that shows off the basic functionality with rich output."""
    # Create a shared namespace that we'll use for all code execution
    demo_namespace = {}
    # Update it with the current globals
    demo_namespace.update(globals())
    # Add any specific imports we need
    demo_namespace["TelepathicObject"] = __import__(
        "animavox.telepathic_objects"
    ).telepathic_objects.TelepathicObject

    with LiveDisplay() as display:
        try:
            display.make_step(
                "Welcome to TelepathicObject Demo!",
                """Welcome to the TelepathicObject demonstration!

This demo showcases the core features of the TelepathicObject class,
which provides a versioned, conflict-free data structure with built-in
history tracking and merge capabilities.

In this demo, we'll explore its core features through practical examples.""",
            )

            # Simple test to verify variable sharing works
            display.push_python(
                "test_var = 'Hello, World!'", globals_dict=demo_namespace
            )
            display.push_python("print(test_var)", globals_dict=demo_namespace)

            display.make_step(
                "Creating a new TelepathicObject...",
                """
Creating TelepathicObjects is straightforward. Start by importing it:""",
            )
            display.push_code(
                "from animavox.telepathic_objects import TelepathicObject"
            )

            display.push(
                """
They can be empty or initialized with data:

1. Empty Object:
""",
            )
            display.push_python(
                "obj1 = TelepathicObject()",
                globals_dict=demo_namespace,
            )
            display.push("2. Simple Dictionary:")
            display.push_python(
                "obj2 = TelepathicObject({'foo': 'bar'})",
                globals_dict=demo_namespace,
            )
            display.push("3. Nested Structure:")
            obj3_constructor = """TelepathicObject({
                    "root": {
                        "collection": {
                            "item1": {"name": "First Item", "value": 1},
                            "item2": {"name": "Second Item", "value": 2}
                        },
                        "settings": {
                            "enabled": True,
                            "mode": "advanced"
                        }
                    }
                })"""
            display.push_python(
                f"obj3 = {obj3_constructor}",
                globals_dict=demo_namespace,
            )
            display.push("Key Features Demonstrated:")
            display.push("- Automatic versioning of all changes")
            display.push("- Built-in conflict resolution")
            display.push("- Support for complex nested structures")
            display.push("- JSON-serializable for easy storage/transmission")

            # Make some changes
            display.make_step(
                "Modifying Object State",
                """Let's modify our object using `set_field`:

- Set simple values: `set_field('name', value, 'description')`
- Use paths for nested fields: `set_field('config/theme', 'dark', 'User preference')`
- All changes are automatically tracked in the transaction log
- Each modification requires a descriptive message for audit purposes

Watch as we add several fields to our object...
                """,
            )
            display.push_python(
                'obj1.set_field("name", "Test Object", "Initial setup")',
                globals_dict=demo_namespace,
            )
            display.push_python("obj1", globals_dict=demo_namespace, hide_code=True)
            display.push_python(
                'obj1.set_field("status", "active", "Initial setup")',
                globals_dict=demo_namespace,
            )
            display.push_python("obj1", globals_dict=demo_namespace, hide_code=True)
            display.push_python(
                'obj1.set_field("config/theme", "dark", "User preference")',
                globals_dict=demo_namespace,
            )
            display.push_python("obj1", globals_dict=demo_namespace, hide_code=True)
            display.push_python(
                'obj1.set_field("config/notifications/enabled", True, "User preference")',
                globals_dict=demo_namespace,
            )
            display.push_python("obj1", globals_dict=demo_namespace, hide_code=True)
            display.push_python(
                'obj1.set_field("config/notifications/sound", "ding", "User preference")',
                globals_dict=demo_namespace,
            )
            display.push_python("obj1", globals_dict=demo_namespace, hide_code=True)

            # Show the current state
            display.make_step(
                "Current State",
                """We can now examine the current state of our object.""",
            )

            display.push_python("obj1", globals_dict=demo_namespace)
            display.push("Printing this more beautifully:")
            display.push_raw(JSON(json.dumps(demo_namespace["obj1"].to_dict())))
            display.push_raw("Next, we will see how to get data out of object again...")
            display.make_step("Getting Data out of the TelepathicObject:")
            display.push("Getting data out of the object is simple:")
            display.push_python("obj1.get_field('name')", globals_dict=demo_namespace)
            display.push_python(
                "obj1.get_field('config/theme')",
                globals_dict=demo_namespace,
            )

            display.make_step(
                "Transaction Log",
                "Each action of the data is recorded as a transaction. This is stored as part of the object.",
            )
            display.push_python(
                "obj1.get_transaction_log()",
                globals_dict=demo_namespace,
            )
            display.push("We can format that a bit more nicely:")
            display.push_python(
                "obj1.pprint_transaction_log()",
                globals_dict=demo_namespace,
            )
            display.make_step(
                "Transaction Objects",
                "Let's have a more detailed look at the transactions.",
            )
            display.push("Transactions are individual objects, and can be serialized:")
            display.push_python(
                'obj1.save_transaction_history("transactions")  # "transactions" is a directory name',
                globals_dict=demo_namespace,
            )
            display.push_raw(
                Panel(
                    "[green]✓ Transaction log saved to transactions directory.[/green]",
                    border_style="green",
                    box=ROUNDED,
                )
            )
            display.push("Let's have a look at the files we generated:")
            display.push_shell("ls -l transactions")
            display.push_shell(
                "FIRST_TRANSACTION=$(ls transactions/ | head -n 1); echo $FIRST_TRANSACTION"
            )
            display.push(
                "These are just regular JSON files, you can easily read and understand them:"
            )
            display.push_shell("cat transactions/$(ls transactions/ | head -n 1)")

            display.make_step(
                "Applying Transactions", "Let's apply our transactions to a new object."
            )
            display.push("Start with an empty new object:")
            display.push_python(
                "my_new_obj = TelepathicObject()",
                globals_dict=demo_namespace,
            )
            display.push_python(
                "my_new_obj.apply_transaction_history('transactions')",
                globals_dict=demo_namespace,
            )
            display.push_python("my_new_obj", globals_dict=demo_namespace)

            # Save the state
            display.make_step("Saving state...")
            obj1.save(ofile)

            # Show saved state info
            file_size = os.path.getsize(ofile)
            display.make_step(
                "State Saved Successfully",
                f"""[green]✓ State persisted to disk[/green]

Location: [bold]{os.path.abspath(ofile)}[/bold]
Size: {file_size} bytes

Your object's state is now safely stored and can be:
- Loaded later in another session
- Shared with other users
- Used as a backup point

Let's verify we can load it back...""",
            )

            # Save transaction log
            obj1.save_transaction_history("transactions")

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

            # Initialize the main live display
            with LiveDisplay() as loaded_display:
                try:
                    # Update the layout with loading message
                    loaded_display.make_step("Loading saved state...")

                    # Read the saved file
                    with open(ofile, "rb") as f:
                        data = f.read()

                    # Update with file check status
                    loaded_display.make_step(
                        "File Check",
                        f"[green]✓ File check passed:[/green] {len(data)} bytes; "
                        f"first 16 bytes: {data[:16]!r}",
                    )

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

                except Exception as e:
                    loaded_display.make_error(
                        "Error Loading State", f"Failed to load saved state: {str(e)}"
                    )
                    wait_for_key_press()
                    return

                # Show transaction log comparison
                loaded_display.make_step(
                    "Transaction Log Comparison",
                    "Note that this transaction log is different from what we had before in the new object",
                )

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
                                wait_for_key_press()

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
                wait_for_key_press()

        except Exception as e:
            display.make_error(
                "An Error Occurred", f"An unexpected error occurred: {str(e)}"
            )
            wait_for_key_press()


def main():
    cli()


if __name__ == "__main__":
    main()
