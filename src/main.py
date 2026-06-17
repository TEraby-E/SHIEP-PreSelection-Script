import asyncio
import os
import sys

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from .scanner import CookieScanner
from .reporter import print_results, export_json
from .logconf import setup_logging

console = Console()

# ─── Semester conversion ──────────────────────────────────────────────────────
# Anchor: 2026上=404, 2026下=424  →  每半年 +20, 每整年 +40
_BASE_YEAR, _BASE_HALF, _BASE_ID = 2026, 1, 404


def parse_semester(s: str) -> str:
    """'26-1' → '404' (2026上), '26-2' → '424' (2026下). 无法识别则原样返回。"""
    s = s.strip()
    if not s:
        return s
    try:
        year_str, half_str = s.split("-")
        year = int(year_str)
        if year < 100:
            year += 2000
        half = int(half_str)
        if half not in (1, 2):
            raise ValueError
        sid = _BASE_ID + (year - _BASE_YEAR) * 40 + (half - _BASE_HALF) * 20
        return str(sid)
    except Exception:
        return s


def semester_hint(sid: str) -> str:
    try:
        n = int(sid)
        delta = n - _BASE_ID
        year = _BASE_YEAR + delta // 40
        half = _BASE_HALF + (delta % 40) // 20
        label = "上半学期" if half == 1 else "下半学期"
        return f"{year}{label}（ID={n}）"
    except Exception:
        return ""


# ─── Menu ─────────────────────────────────────────────────────────────────────

FUNCTIONS = [
    ("1", "获取 Cookie", "do_cookies"),
    ("2", "抓取成绩", "do_grades"),
    ("3", "抓取培养方案", "do_plan"),
    ("4", "抓取期末考试安排", "do_exams"),
]
VALID_KEYS = {k for k, _, _ in FUNCTIONS} | {"0"}


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_config_path(path: str) -> str:
    """Accept the given path; if missing, try common alternatives."""
    if os.path.exists(path):
        return path
    base, _ = os.path.splitext(path)
    for alt in (f"{base}.yaml", f"{base}.yml", f"{base}.toml"):
        if os.path.exists(alt):
            return alt
    return path  # let the caller raise FileNotFoundError


def show_menu(cfg: dict):
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold yellow", width=4)
    table.add_column(style="white")
    for key, label, _ in FUNCTIONS:
        table.add_row(f"[{key}]", label)
    table.add_row("[0]", "退出")

    accounts = cfg.get("accounts", [])
    console.print(Panel(
        table,
        title=f"[bold cyan]SHIEP 预选课工具[/bold cyan]  "
              f"[dim]账号: {len(accounts)}[/dim]",
        border_style="cyan",
    ))
    console.print("[dim]可输入多个编号同时执行，例如：[bold]1 2[/bold] 或 [bold]1,2[/bold][/dim]")


def ask_semester(cfg: dict) -> str:
    default_raw = cfg.get("semester", "")
    console.print(
        "\n[dim]学期格式：[bold]YY-H[/bold]"
        "  例如 [bold]26-1[/bold]（2026上半学期）、[bold]26-2[/bold]（2026下半学期）"
        "  留空则不按学期过滤[/dim]"
    )
    if default_raw:
        console.print(f"[dim]配置默认学期：{semester_hint(parse_semester(default_raw)) or default_raw}[/dim]")

    raw = Prompt.ask("请输入学期", default=default_raw or "").strip()
    if not raw:
        return ""

    sid = parse_semester(raw)
    hint = semester_hint(sid)
    if hint:
        console.print(f"[dim]→ {hint}[/dim]")
    return sid


async def run(cfg: dict, ops: dict, semester: str):
    scanner = CookieScanner(
        login_url=cfg["login_url"],
        target_url=cfg["target_url"],
        cookie_filter=cfg.get("cookie_filter", ""),
        headless=cfg.get("headless", True),
        timeout=cfg.get("timeout", 30),
        semester=semester,
    )

    accounts = cfg.get("accounts", [])
    if not accounts:
        console.print("[red]配置中没有账号。[/red]")
        return

    active = [label for _, label, flag in FUNCTIONS if ops.get(flag)]
    console.print(f"\n开始执行：[bold]{' + '.join(active)}[/bold]，共 {len(accounts)} 个账号...\n")

    results = await scanner.scan_all(
        accounts,
        max_concurrency=cfg.get("max_concurrency", 5),
        **ops,
    )
    print_results(results, console)

    if ops.get("do_cookies"):
        output = cfg.get("output", "")
        if output:
            export_json(results, output)
            console.print(f"\n结果已保存至 [bold]{output}[/bold]")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="SHIEP 预选课工具")
    parser.add_argument("--config", "-c", default="config.yaml")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示调试日志")
    args = parser.parse_args()

    import logging
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    config_path = resolve_config_path(args.config)
    try:
        cfg = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]找不到配置文件: {args.config}[/red]")
        sys.exit(1)

    while True:
        console.print()
        show_menu(cfg)

        raw = Prompt.ask("请选择").strip()
        keys = [k for k in raw.replace(",", " ").split() if k in VALID_KEYS]

        if not keys or "0" in keys:
            console.print("[dim]已退出。[/dim]")
            break

        ops = {flag: False for _, _, flag in FUNCTIONS}
        for key in keys:
            flag = next(flag for k, _, flag in FUNCTIONS if k == key)
            ops[flag] = True

        semester = ask_semester(cfg) if ops.get("do_grades") or ops.get("do_exams") else ""

        asyncio.run(run(cfg, ops, semester))

        if not Confirm.ask("\n继续操作？", default=True):
            console.print("[dim]已退出。[/dim]")
            break


if __name__ == "__main__":
    main()
