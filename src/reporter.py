import json
from dataclasses import asdict
from rich.console import Console
from rich.table import Table


def _is_failing(cells):
    """Check if a grade row has a failing indicator (0 or contains 0 with chars)."""
    for cell in cells:
        cell = cell.strip()
        if not cell:
            continue
        # Exact "0"
        if cell == '0':
            return True
        # "0.0", "0.00" etc
        try:
            if float(cell) == 0:
                return True
        except ValueError:
            pass
        if cell.startswith('0') and len(cell) > 1 and not cell.startswith('0.'):
            if not cell[1].isdigit():
                return True
    return False


def print_results(results, console=None):
    console = console or Console()

    # Summary table
    table = Table(title="Scan Results")
    table.add_column("User", style="magenta")
    table.add_column("Proxy", style="cyan")
    table.add_column("Cookies", style="yellow", justify="right")
    table.add_column("Grades", style="green", justify="right")
    table.add_column("Plan", style="blue", justify="right")
    table.add_column("Status", style="bold")

    for r in results:
        status = f"[red]{r.error[:50]}[/red]" if r.error else "[green]OK[/green]"
        table.add_row(
            r.username, r.proxy or "direct",
            str(len(r.cookies)), str(len(r.grades)),
            str(len(r.plan_credits)), status,
        )
    console.print(table)

    # Cookies
    for r in results:
        if r.cookies:
            console.print(f"\n[bold cyan]{r.username} - Cookies:[/bold cyan]")
            for c in r.cookies:
                console.print(f"  {c['name']} = {c['value'][:80]}")

    # Grades (failing grades in red, 在读 in blue)
    for r in results:
        if r.grades:
            console.print(f"\n[bold green]{r.username} - Grades:[/bold green]")
            for row in r.grades:
                line = ' | '.join(str(c) for c in row)
                if any('在读' in str(c) for c in row):
                    console.print(f"  [bold blue]{line}[/bold blue]")
                elif _is_failing(row):
                    console.print(f"  [bold red]{line}[/bold red]")
                else:
                    console.print(f"  {line}")

    # Plan completion (在读 in blue, 缺 in yellow)
    for r in results:
        if r.plan_credits:
            console.print(f"\n[bold blue]{r.username} - Plan Credits:[/bold blue]")
            for row in r.plan_credits:
                line = ' | '.join(str(c) for c in row)
                if any('在读' in str(c) for c in row):
                    console.print(f"  [bold blue]{line}[/bold blue]")
                elif any('缺' in str(c) for c in row):
                    console.print(f"  [bold yellow]{line}[/bold yellow]")
                else:
                    console.print(f"  {line}")


def export_json(results, path):
    data = [asdict(r) for r in results]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)