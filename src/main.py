import argparse
import asyncio
import yaml
from rich.console import Console

from .scanner import CookieScanner
from .reporter import print_results, export_json

console = Console()


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


async def run(cfg: dict, cookie_override: str = None, semester: str = ""):
    scanner = CookieScanner(
        login_url=cfg["login_url"],
        target_url=cfg["target_url"],
        cookie_filter=cookie_override or cfg.get("cookie_filter", ""),
        headless=cfg.get("headless", True),
        timeout=cfg.get("timeout", 30),
        semester=semester or cfg.get("semester", ""),
    )

    accounts = cfg.get("accounts", [])
    if not accounts:
        console.print("[red]No accounts configured.[/red]")
        return

    console.print(f"Scanning with {len(accounts)} accounts...")
    if semester:
        console.print(f"Semester filter: [bold]{semester}[/bold]")

    results = await scanner.scan_all(accounts, cfg.get("max_concurrency", 5))
    print_results(results, console)

    output = cfg.get("output", "")
    if output:
        export_json(results, output)
        console.print(f"\nResults saved to [bold]{output}[/bold]")


def main():
    parser = argparse.ArgumentParser(description="CookieJar - Multi-IP Cookie Scanner")
    parser.add_argument("--config", "-c", default="config.yaml")
    parser.add_argument("--cookie-name", "-k", default=None)
    parser.add_argument("--semester", "-s", default="",
                        help="Semester ID to filter grades (e.g. 404)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    asyncio.run(run(cfg, args.cookie_name, args.semester))


if __name__ == "__main__":
    main()