import os
import re
import time
from contextlib import asynccontextmanager

from .logconf import account_logger

GRADE_BASE = "https://jw.shiep.edu.cn/eams/teach/grade/course/person!search.action"
GRADE_URL = f"{GRADE_BASE}?all=1"
PLAN_URL = "https://jw.shiep.edu.cn/eams/myPlanCompl.action"
EXAM_BASE = "https://jw.shiep.edu.cn/eams/stdExamTable!examTable.action"


async def _dump_debug_html(page, username: str, tag: str) -> str:
    """Save the live page (+ iframes) HTML and recorded network traffic so we
    can reverse-engineer a page we can't see ourselves. Best-effort; never raises."""
    try:
        safe_user = re.sub(r'[^A-Za-z0-9_.-]', '_', username)
        os.makedirs("debug_dumps", exist_ok=True)
        stamp = int(time.time())

        traffic = getattr(page, "_traffic", [])
        net_path = os.path.join("debug_dumps", f"{tag}_{safe_user}_{stamp}_network.log")
        with open(net_path, "w", encoding="utf-8") as f:
            f.write(f"frames: {[fr.url for fr in page.frames]}\n\n")
            f.write("\n".join(traffic))

        html_path = os.path.join("debug_dumps", f"{tag}_{safe_user}_{stamp}.html")
        chunks = [await page.content()]
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                chunks.append(f"\n<!-- ===== IFRAME {frame.url} ===== -->\n" + await frame.content())
            except Exception:
                continue
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("\n".join(chunks))
        return f"{html_path} , {net_path}"
    except Exception:
        return ""


@asynccontextmanager
async def _page(ctx, timeout_ms: int):
    """Open a page and guarantee it is closed, even on error. Also records every
    request/response and frame navigation on page._traffic so callers can dump
    it when scraping comes up empty — this is how we spot AJAX/iframe endpoints
    that the address bar never reveals."""
    page = await ctx.new_page()
    page.set_default_timeout(timeout_ms)
    traffic = []
    page._traffic = traffic  # stashed for debug dumping; not part of Playwright's API

    def _on_request(req):
        traffic.append(f"-> {req.method} {req.resource_type} {req.url}")

    def _on_response(resp):
        traffic.append(f"<- {resp.status} {resp.url}")

    def _on_frame_navigated(frame):
        traffic.append(f"== frame navigated: {frame.url}")

    page.on("request", _on_request)
    page.on("response", _on_response)
    page.on("framenavigated", _on_frame_navigated)
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


async def _trigger_default_selection(page):
    """
    Some EAMS pages (e.g. plan/exam table) only load their data table after a
    <select> (year/plan/semester picker) fires a 'change' event — something a
    real student does by hand but headless navigation never triggers. Pick the
    last non-placeholder option on every visible select, dispatch change, then
    click any obvious "query/confirm" button to mimic that interaction.
    """
    js = '''() => {
        const selects = Array.from(document.querySelectorAll('select'));
        for (const sel of selects) {
            const opts = Array.from(sel.options).filter(o => o.value && o.value !== '');
            if (!opts.length) continue;
            sel.value = opts[opts.length - 1].value;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
        }
        const btnTexts = ['查询', '确定', '显示', '提交', '搜索'];
        const candidates = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], a'));
        for (const el of candidates) {
            const text = (el.innerText || el.value || '').trim();
            if (btnTexts.some(t => text.includes(t))) {
                el.click();
                break;
            }
        }
        return selects.length;
    }'''
    try:
        await page.evaluate(js)
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                await frame.evaluate(js)
            except Exception:
                continue
    except Exception:
        pass


_FIND_TABS_FN = '''
    function _findTabs() {
        // jQuery UI Tabs (confirmed: ui-tabs / ui-tabs-anchor / role="tab" /
        // ui-tabs-panel classes seen on the real page) binds its click handler
        // to the <a class="ui-tabs-anchor">, not the <li> that wraps it — click
        // the anchor specifically so the widget's handler actually fires.
        const jqueryUiTabs = Array.from(document.querySelectorAll('a.ui-tabs-anchor'));
        if (jqueryUiTabs.length) return jqueryUiTabs;

        const isTabLike = (el) => {
            const cls = (el.className || '') + '';
            const role = el.getAttribute('role') || '';
            const href = el.getAttribute('href') || '';
            if (!/tab/i.test(cls) && role !== 'tab' && !el.hasAttribute('data-tab')
                && !/tab/i.test(href) && !el.closest('[class*="tab"],[role="tablist"]')) {
                return false;
            }
            if (el.closest('table')) return false;          // don't touch data tables themselves
            const text = (el.innerText || '').trim();
            if (!text || text.length > 30) return false;     // tab labels are short
            if (el.offsetParent === null && el.tagName !== 'A') return false;  // skip hidden, anchors can be 0-size
            return true;
        };
        return Array.from(document.querySelectorAll('li, span, div, a')).filter(isTabLike);
    }
'''

_TAB_COUNT_JS = f'''() => {{
    {_FIND_TABS_FN}
    return _findTabs().length;
}}'''

_TAB_CLICK_JS = f'''(i) => {{
    {_FIND_TABS_FN}
    const el = _findTabs()[i];
    if (!el) return false;
    el.click();
    return true;
}}'''


async def _collect_across_tabs(page, extract_js, max_tabs: int = 12) -> list:
    """
    Some EAMS pages render their tabs as #hash anchor links (e.g. href="#tab1-1")
    handled entirely client-side — the address bar never changes, but each click
    populates that tab's panel (often a different semester's course table).

    Some implementations keep every panel in the DOM (hidden via CSS); others
    AJAX-replace a single shared container on every click, so an old tab's rows
    vanish the moment you click the next one. To be safe for either case, we
    run extract_js once before touching any tab, then again immediately after
    every tab click, and merge everything.
    """
    all_rows = []

    async def _extract_now():
        try:
            data = await page.evaluate(extract_js)
        except Exception:
            data = None
        if data:
            all_rows.extend(data)
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                data = await frame.evaluate(extract_js)
            except Exception:
                continue
            if data:
                all_rows.extend(data)

    await _extract_now()

    for target in [page, *[f for f in page.frames if f != page.main_frame]]:
        try:
            count = await target.evaluate(_TAB_COUNT_JS)
        except Exception:
            continue
        for i in range(min(count, max_tabs)):
            try:
                clicked = await target.evaluate(_TAB_CLICK_JS, i)
            except Exception:
                continue
            if not clicked:
                continue
            # AJAX-loaded tabs (ajax_container) need real time for the request
            # to land; wait for network idle first, then a fixed settle delay.
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            await page.wait_for_timeout(600)
            await _extract_now()

    return all_rows


def _dedup_rows(rows: list) -> list:
    """Collapse identical rows produced by re-extracting after every tab click."""
    seen = set()
    out = []
    for row in rows:
        key = tuple(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


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


async def fetch_exams(ctx, username: str, timeout_ms: int, semester: str = "") -> list:
    log = account_logger(username)
    url = f"{EXAM_BASE}?semester.id={semester}" if semester else EXAM_BASE
    async with _page(ctx, timeout_ms) as page:
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await _trigger_default_selection(page)
            await _wait_for_tables(page, min_rows=2)
            await _auto_scroll(page)

            extract_js = '''() => {
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
            }'''
            rows = _dedup_rows(await _collect_across_tabs(page, extract_js))
            log.info("Got %d exam rows", len(rows))
            return rows
        except Exception as e:
            log.warning("Exam fetch error: %s", e)
            return []


async def fetch_plan(ctx, username: str, timeout_ms: int) -> list:
    log = account_logger(username)
    async with _page(ctx, timeout_ms) as page:
        try:
            await page.goto(PLAN_URL, wait_until="domcontentloaded")
            await _trigger_default_selection(page)
            await _wait_for_tables(page, min_rows=2)
            await _auto_scroll(page)

            extract_js = '''() => {
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
            }'''
            rows = _dedup_rows(await _collect_across_tabs(page, extract_js))
            log.info("Got %d plan rows", len(rows))
            if not rows:
                dump_path = await _dump_debug_html(page, username, "plan")
                if dump_path:
                    log.warning("No plan rows extracted; dumped page HTML to %s", dump_path)
            return rows
        except Exception as e:
            log.warning("Plan fetch error: %s", e)
            return []


