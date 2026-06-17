import json

from rich.console import Console
from rich.table import Table

from .models import ScanResult  # noqa: F401


def _parse_score(s) -> float | None:
    try:
        return float(str(s).strip())
    except (ValueError, AttributeError):
        return None


def _cell(cells: list, i: int, default: str = "") -> str:
    """Safe indexed access into a row of string cells."""
    return cells[i] if 0 <= i < len(cells) else default


# ─── Plan formatting ──────────────────────────────────────────────────────────

def _format_plan_row(cells: list) -> tuple[str, str] | None:
    """Returns (line, rich_style) or None to skip."""
    cells = [str(c).strip() for c in cells]
    if not cells:
        return None

    if cells[0].isdigit():  # Type B: individual course row
        course_name = _cell(cells, 2)
        credit = _cell(cells, 3)

        if any("在读" in c for c in cells):
            return f"{course_name} {credit}学分 在读", "[bold blue]"

        # 成绩在 cells[5]（cells[4] 是已获学分占位值，不可当成绩）
        score_raw = _cell(cells, 5).strip()
        score = _parse_score(score_raw)

        if not score_raw or score_raw == "--":         # 未出分 / 未修
            return f"{course_name} {credit}学分 未修", "[dim]"
        if score is None:                               # 等第制 / 非数字
            if score_raw in ("不及格", "差"):
                return f"{course_name} {credit}学分 重修", "[bold yellow]"
            return f"{course_name} {credit}学分 {score_raw}", "[blue]"
        if score <= 60:                                 # 数字且不及格 → 重修
            return f"{course_name} {credit}学分 重修", "[bold yellow]"
        return None                                     # 数字且及格 → 隐藏

    # Type A: category summary row
    name = cells[0]
    nums, deficit = [], ""
    for c in cells[1:]:
        if "缺" in c:
            deficit = c
        else:
            try:
                float(c)
                nums.append(c)
            except ValueError:
                pass

    credit_part = (f"学分:{nums[0]}/{nums[1]}" if len(nums) >= 2
                   else f"学分:{nums[0]}" if nums else "")
    if deficit:
        return "  ".join(p for p in [name, credit_part, deficit] if p), "[bold yellow]"
    if len(nums) >= 2 and nums[0] == nums[1]:
        return "  ".join(p for p in [name, credit_part, "已修满"] if p), "[green]"
    return "  ".join(p for p in [name, credit_part] if p), ""


# ─── Grade formatting ─────────────────────────────────────────────────────────

def _grade_style(cells: list) -> str:
    """补考过→紫, 挂科/补考没过→红, 正常→蓝"""
    if len(cells) < 8:
        return ""
    s1, s2 = _parse_score(_cell(cells, 6)), _parse_score(_cell(cells, 7))
    if s1 is None or s2 is None:
        return ""
    if s1 != s2:
        return "[bold magenta]"
    return "[bold red]" if s1 < 60 else "[bold blue]"


def _format_grade_row(cells: list) -> str | None:
    """cols: semester|course_id|course_code|name|type|credits|score1|score2|gpa"""
    if len(cells) < 9 or _parse_score(_cell(cells, 6)) is None:
        return None
    s1, s2 = _cell(cells, 6), _cell(cells, 7)
    score_part = f"成绩:{s1}" if s1 == s2 else f"成绩:{s1}→{s2}"
    return (f"{_cell(cells, 2)} {_cell(cells, 3)} {_cell(cells, 4)} "
            f"学分:{_cell(cells, 5)} {score_part} 绩点:{_cell(cells, 8)}")


# ─── Exam formatting ───────────────────────────────────────────────────────────

def _build_credit_map(grades: list, plan_credits: list) -> dict:
    """course name → credit, gathered from grade rows and plan rows."""
    credit_map: dict[str, str] = {}
    for row in grades:
        name, credit = _cell(row, 3).strip(), _cell(row, 5).strip()
        if name and credit:
            credit_map[name] = credit
    for row in plan_credits:
        cells = [str(c).strip() for c in row]
        if cells and cells[0].isdigit():
            name, credit = _cell(cells, 2), _cell(cells, 3)
            if name and credit:
                credit_map[name] = credit
    return credit_map


def _format_exam_row(cells: list, credit_map: dict | None = None) -> str | None:
    """cols: course_code|course_name|exam_type|date|time|location"""
    cells = [str(c).strip() for c in cells]
    if len(cells) < 5 or not any(cells):
        return None
    if cells[0] in ("课程序号", "序号") or "课程名称" in cells:
        return None
    course_code, name, exam_type, date, time = (
        _cell(cells, 0), _cell(cells, 1), _cell(cells, 2),
        _cell(cells, 3), _cell(cells, 4),
    )
    location = _cell(cells, 5)
    credit = (credit_map or {}).get(name, "")
    parts = [course_code, name, exam_type, date, time, location]
    line = " ".join(p for p in parts if p)
    if credit:
        line += f" {credit}学分"
    return line


# ─── Output ───────────────────────────────────────────────────────────────────

def print_results(results, console=None):
    console = console or Console()

    table = Table(title="Scan Results")
    table.add_column("User", style="magenta")
    table.add_column("Proxy", style="cyan")
    table.add_column("Cookies", style="yellow", justify="right")
    table.add_column("Grades", style="green", justify="right")
    table.add_column("Plan", style="blue", justify="right")
    table.add_column("Exams", style="bright_yellow", justify="right")
    table.add_column("Status", style="bold")

    for r in results:
        status = f"[red]{r.error[:50]}[/red]" if r.error else "[green]OK[/green]"
        table.add_row(r.username, r.proxy or "direct",
                      str(len(r.cookies)), str(len(r.grades)),
                      str(len(r.plan_credits)), str(len(r.exams)), status)
    console.print(table)

    for r in results:
        if r.cookies:
            console.print(f"\n[bold cyan]{r.username} - Cookies:[/bold cyan]")
            for c in r.cookies:
                console.print(f"  {c['name']} = {c['value'][:80]}")

    for r in results:
        if r.grades:
            console.print(f"\n[bold green]{r.username} - 成绩:[/bold green]")
            for row in r.grades:
                line = _format_grade_row(row)
                if line is None:
                    continue
                style = _grade_style(row)
                console.print(f"  {style}{line}[/]" if style else f"  {line}")

    for r in results:
        if r.plan_credits:
            console.print(f"\n[bold blue]{r.username} - 培养方案:[/bold blue]")
            for row in r.plan_credits:
                result = _format_plan_row(row)
                if result is None:
                    continue
                line, style = result
                console.print(f"  {style}{line}[/]" if style else f"  {line}")

    for r in results:
        if r.exams:
            console.print(f"\n[bold bright_yellow]{r.username} - 期末考试:[/bold bright_yellow]")
            credit_map = _build_credit_map(r.grades, r.plan_credits)
            for row in r.exams:
                line = _format_exam_row(row, credit_map)
                if line is None:
                    continue
                console.print(f"  {line}")


def export_json(results, path):
    data = [{"username": r.username, "proxy": r.proxy, "cookies": r.cookies}
            for r in results if r.cookies]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
