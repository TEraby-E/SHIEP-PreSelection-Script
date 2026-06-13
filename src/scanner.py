import asyncio
from dataclasses import dataclass, field
from playwright.async_api import async_playwright


@dataclass
class ScanResult:
    proxy: str
    username: str
    cookies: list = field(default_factory=list)
    grades: list = field(default_factory=list)
    plan_credits: list = field(default_factory=list)
    error: str = ""


class CookieScanner:
    def __init__(self, login_url: str, target_url: str,
                 cookie_filter: str = "", headless: bool = True,
                 timeout: int = 30, semester: str = ""):
        self.login_url = login_url
        self.target_url = target_url
        self.cookie_filter = cookie_filter
        self.headless = headless
        self.timeout = timeout * 1000
        self.semester = semester

        self.grade_url = "https://jw.shiep.edu.cn/eams/teach/grade/course/person!search.action?all=1"
        self.plan_url = "https://jw.shiep.edu.cn/eams/myPlanCompl.action"

    async def _auto_scroll(self, page):
        """Scroll page to trigger lazy loading."""
        await page.evaluate('''async () => {
            await new Promise(resolve => {
                let totalHeight = 0;
                const distance = 300;
                const timer = setInterval(() => {
                    window.scrollBy(0, distance);
                    totalHeight += distance;
                    if (totalHeight >= document.body.scrollHeight) {
                        clearInterval(timer);
                        resolve();
                    }
                }, 200);
                setTimeout(() => { clearInterval(timer); resolve(); }, 10000);
            });
        }''')
        await page.wait_for_timeout(2000)

    async def _extract_from_frames(self, page, js_code):
        """Try extracting data from main page, then iframes."""
        data = await page.evaluate(js_code)
        if not data:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    data = await frame.evaluate(js_code)
                    if data:
                        break
                except Exception:
                    continue
        return data or []

    async def scan_account(self, account: dict) -> ScanResult:
        proxy = account.get("proxy", "")
        username = account["username"]
        password = account["password"]
        result = ScanResult(proxy=proxy, username=username)

        try:
            async with async_playwright() as p:
                launch_opts = {
                    "headless": self.headless,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if proxy:
                    launch_opts["proxy"] = {"server": proxy}

                browser = await p.chromium.launch(**launch_opts)
                ctx = await browser.new_context(
                    ignore_https_errors=True,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                )
                page = await ctx.new_page()
                page.set_default_timeout(self.timeout)

                # ===== Login =====
                login_with_service = f"{self.login_url}?service={self.target_url}"
                print(f"[{username}] Navigating to IDS login...")
                await page.goto(login_with_service, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                if "ids.shiep.edu.cn" in page.url or "authserver" in page.url:
                    try:
                        await page.wait_for_selector('input#username', timeout=15000)
                    except Exception:
                        result.error = "Login form did not load"
                        await browser.close()
                        return result

                    await page.fill('input#username', username)
                    await page.fill('input#password', password)

                    if await page.is_visible('#captchaResponse'):
                        result.error = "Captcha required"
                        await browser.close()
                        return result

                    for sel in ['button[type="submit"]', 'input[type="submit"]',
                                '#login_submit', 'button:has-text("登录")', 'a:has-text("登录")']:
                        try:
                            await page.click(sel, timeout=3000)
                            print(f"[{username}] Logged in")
                            break
                        except Exception:
                            continue

                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(3000)

                    if "jw.shiep.edu.cn" not in page.url:
                        await page.goto(self.target_url, wait_until="domcontentloaded")
                        await page.wait_for_timeout(2000)

                # ===== Extract cookies =====
                cookies = await ctx.cookies()
                if self.cookie_filter:
                    want = {n.strip() for n in self.cookie_filter.split(",")}
                    cookies = [c for c in cookies if c["name"] in want]
                result.cookies = [
                    {"name": c["name"], "value": c["value"],
                     "domain": c["domain"], "path": c["path"]}
                    for c in cookies
                ]
                print(f"[{username}] Got {len(result.cookies)} cookies")

                # ===== Scrape grades =====
                print(f"[{username}] Fetching grades...")
                try:
                    # If semester specified, add semester param
                    grade_url = self.grade_url
                    if self.semester:
                        grade_url = f"https://jw.shiep.edu.cn/eams/teach/grade/course/person!search.action?semesterId={self.semester}"

                    await page.goto(grade_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    await self._auto_scroll(page)

                    grade_js = '''() => {
                        const rows = [];
                        const tables = document.querySelectorAll('table');
                        for (const table of tables) {
                            const trs = table.querySelectorAll('tbody tr, tr');
                            for (const tr of trs) {
                                const tds = tr.querySelectorAll('td');
                                if (tds.length >= 4) {
                                    const cells = Array.from(tds).map(td => td.innerText.trim());
                                    if (cells.some(c => c.length > 0)) {
                                        rows.push(cells);
                                    }
                                }
                            }
                        }
                        return rows;
                    }'''
                    result.grades = await self._extract_from_frames(page, grade_js)
                    print(f"[{username}] Got {len(result.grades)} grade rows")

                except Exception as e:
                    print(f"[{username}] Grade fetch error: {e}")

                # ===== Scrape plan completion =====
                print(f"[{username}] Fetching plan completion...")
                try:
                    await page.goto(self.plan_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    await self._auto_scroll(page)

                    plan_js = '''() => {
                        const rows = [];
                        const cnNums = ['一','二','三','四','五','六','七','八','九','十',
                                        '十一','十二','十三','十四','十五'];

                        // Type A: starts with Chinese numeral (一 二...) or parenthesized Chinese (（一）（二）...)
                        function isTypeA(text) {
                            if (/^[（(][一二三四五六七八九十百]+[）)]/.test(text)) return true;
                            return cnNums.some(n => text.startsWith(n));
                        }

                        // Type B: starts with Arabic numeral (1 2 3...)
                        function isTypeB(text) {
                            return /^\d+[\s\t\.\、]/.test(text);
                        }

                        const tables = document.querySelectorAll('table');
                        for (const table of tables) {
                            const trs = table.querySelectorAll('tbody tr, tr');
                            for (const tr of trs) {
                                const tds = tr.querySelectorAll('td');
                                if (tds.length === 0) continue;
                                const cells = Array.from(tds).map(td => td.innerText.trim());
                                const first = cells[0] || '';
                                if (!cells.some(c => c.length > 0)) continue;

                                if (isTypeA(first)) {
                                    // Keep all Type A rows
                                    rows.push(cells);
                                } else if (isTypeB(first)) {
                                    // Keep Type B rows unless any cell equals exactly "是"
                                    if (!cells.some(c => c === '是')) {
                                        rows.push(cells);
                                    }
                                } else {
                                    // Non-title rows: only keep 学分 / GPA rows
                                    if (first.includes('学分') || first.toUpperCase().includes('GPA')) {
                                        rows.push(cells);
                                    }
                                }
                            }
                        }
                        return rows;
                    }'''

                    plan_raw = await self._extract_from_frames(page, plan_js)
                    if isinstance(plan_raw, list):
                        result.plan_credits = plan_raw
                    print(f"[{username}] Got {len(result.plan_credits)} plan rows")

                except Exception as e:
                    print(f"[{username}] Plan fetch error: {e}")

                await browser.close()

        except Exception as e:
            result.error = str(e)

        return result

    async def scan_all(self, accounts: list[dict],
                       max_concurrency: int = 5) -> list[ScanResult]:
        sem = asyncio.Semaphore(max_concurrency)

        async def limited(acc):
            async with sem:
                return await self.scan_account(acc)

        return await asyncio.gather(*[limited(a) for a in accounts])