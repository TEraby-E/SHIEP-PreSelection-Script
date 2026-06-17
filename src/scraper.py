from contextlib import asynccontextmanager

from .logconf import account_logger

GRADE_BASE = "https://jw.shiep.edu.cn/eams/teach/grade/course/person!search.action"
GRADE_URL = f"{GRADE_BASE}?all=1"
PLAN_URL = "https://jw.shiep.edu.cn/eams/myPlanCompl.action"


@asynccontextmanager
async def _page(ctx, timeout_ms: int):
    """Open a page and guarantee it is closed, even on error."""
    page = await ctx.new_page()
    page.set_default_timeout(timeout_ms)
    try:
        yield page
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def _auto_scroll(page):
    """Scroll to bottom to trigger lazy rendering; bounded by a hard timeout."""
    await page.evaluate('''async () => {
        await new Promise(resolve => {
            let total = 0;
            const distance = 300;
            const timer = setInterval(() => {
                window.scrollBy(0, distance);
                total += distance;
                if (total >= document.body.scrollHeight) {
                    clearInterval(timer);
                    resolve();
                }
            }, 150);
            setTimeout(() => { clearInterval(timer); resolve(); }, 5000);
        });
    }''')


async def _wait_for_tables(page, min_rows: int = 1, timeout: int = 8000):
    """Wait until at least one table with data rows exists, instead of a fixed sleep."""
    try:
        await page.wait_for_function(
            '''(min) => {
                for (const t of document.querySelectorAll('table')) {
                    if (t.querySelectorAll('tr').length >= min) return true;
                }
                return false;
            }''',
            arg=min_rows,
            timeout=timeout,
        )
    except Exception:
        pass  # fall through; extraction will just return [] if nothing is there


async def _extract_from_frames(page, js_code):
    """Try the main document first, then iframes (EAMS often renders into a frame)."""
    data = await page.evaluate(js_code)
    if data:
        return data
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            data = await frame.evaluate(js_code)
            if data:
                return data
        except Exception:
            continue
    return []


async def fetch_grades(ctx, username: str, timeout_ms: int, semester: str = "") -> list:
    log = account_logger(username)
    url = f"{GRADE_BASE}?semesterId={semester}" if semester else GRADE_URL
    async with _page(ctx, timeout_ms) as page:
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await _wait_for_tables(page, min_rows=2)
            await _auto_scroll(page)

            rows = await _extract_from_frames(page, '''() => {
                const rows = [];
                for (const table of document.querySelectorAll('table')) {
                    for (const tr of table.querySelectorAll('tbody tr, tr')) {
                        const tds = tr.querySelectorAll('td');
                        if (tds.length >= 4) {
                            const cells = Array.from(tds).map(td => td.innerText.trim());
                            if (cells.some(c => c.length > 0)) rows.push(cells);
                        }
                    }
                }
                return rows;
            }''')
            log.info("Got %d grade rows", len(rows))
            return rows
        except Exception as e:
            log.warning("Grade fetch error: %s", e)
            return []


async def fetch_plan(ctx, username: str, timeout_ms: int) -> list:
    log = account_logger(username)
    async with _page(ctx, timeout_ms) as page:
        try:
            await page.goto(PLAN_URL, wait_until="domcontentloaded")
            await _wait_for_tables(page, min_rows=2)
            await _auto_scroll(page)

            rows = await _extract_from_frames(page, '''() => {
                const cnNums = ["一","二","三","四","五","六","七","八","九","十",
                                "十一","十二","十三","十四","十五"];
                function isTypeA(t) {
                    return /^[（(][一二三四五六七八九十百]+[）)]/.test(t)
                        || cnNums.some(n => t.startsWith(n));
                }
                const rows = [];
                for (const table of document.querySelectorAll('table')) {
                    for (const tr of table.querySelectorAll('tbody tr, tr')) {
                        const tds = tr.querySelectorAll('td');
                        if (!tds.length) continue;
                        const cells = Array.from(tds).map(td => td.innerText.trim());
                        const first = cells[0] || '';
                        if (!cells.some(c => c.length > 0)) continue;
                        if (isTypeA(first)) {
                            rows.push(cells);
                        } else if (/^\\d/.test(first)) {
                            if (cells.some(c => c === '否')) rows.push(cells);
                        } else if (first.includes('学分') || first.toUpperCase().includes('GPA')) {
                            rows.push(cells);
                        }
                    }
                }
                return rows;
            }''')
            log.info("Got %d plan rows", len(rows))
            return rows
        except Exception as e:
            log.warning("Plan fetch error: %s", e)
            return []
