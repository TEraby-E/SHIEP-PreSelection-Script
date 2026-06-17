import asyncio

from playwright.async_api import async_playwright, Browser

from .models import ScanResult
from .auth import login, fetch_cookies
from .scraper import fetch_grades, fetch_plan, fetch_exams
from .logconf import account_logger

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/130.0.0.0 Safari/537.36")


class CookieScanner:
    def __init__(self, login_url: str, target_url: str,
                 cookie_filter: str = "", headless: bool = True,
                 timeout: int = 30, semester: str = ""):
        self.login_url = login_url
        self.target_url = target_url
        self.cookie_filter = cookie_filter
        self.headless = headless
        self.timeout_ms = timeout * 1000
        self.semester = semester

    async def scan_account(self, browser: Browser, account: dict,
                           do_cookies: bool = True,
                           do_grades: bool = True,
                           do_plan: bool = True,
                           do_exams: bool = True) -> ScanResult:
        username = account["username"]
        log = account_logger(username)
        result = ScanResult(proxy=account.get("proxy", ""), username=username)

        ctx_opts = {"ignore_https_errors": True, "user_agent": _USER_AGENT}
        if result.proxy:
            ctx_opts["proxy"] = {"server": result.proxy}

        ctx = await browser.new_context(**ctx_opts)
        try:
            login_page = await ctx.new_page()
            login_page.set_default_timeout(self.timeout_ms)

            login_ok, login_error = await login(
                login_page, username, account["password"],
                self.login_url, self.target_url,
            )
            if login_error:
                result.add_error(login_error)
            if not login_ok:
                log.warning("Not logged in — skipping all operations")
                await login_page.close()
                return result

            # Build the task list. Cookie fetch reuses the login page (same
            # session is already there); grades/plan each open their own page
            # inside the fetcher and clean it up. return_exceptions=True so one
            # failure can't cancel the siblings.
            labels: list[str] = []
            coros = []
            if do_cookies:
                labels.append("cookies")
                coros.append(fetch_cookies(
                    ctx, login_page, self.target_url, self.cookie_filter, username))
            if do_grades:
                labels.append("grades")
                coros.append(fetch_grades(ctx, username, self.timeout_ms, self.semester))
            if do_plan:
                labels.append("plan")
                coros.append(fetch_plan(ctx, username, self.timeout_ms))
            if do_exams:
                labels.append("exams")
                coros.append(fetch_exams(ctx, username, self.timeout_ms, self.semester))

            outcomes = await asyncio.gather(*coros, return_exceptions=True)
            data = dict(zip(labels, outcomes))

            if "cookies" in data:
                val = data["cookies"]
                if isinstance(val, Exception):
                    result.add_error(f"Cookie fetch failed: {val}")
                else:
                    cookies, cookie_error = val
                    result.cookies = cookies
                    if cookie_error:
                        result.add_error(f"Cookie fetch failed: {cookie_error}")

            if "grades" in data:
                val = data["grades"]
                if isinstance(val, Exception):
                    result.add_error(f"Grade fetch failed: {val}")
                else:
                    result.grades = val

            if "plan" in data:
                val = data["plan"]
                if isinstance(val, Exception):
                    result.add_error(f"Plan fetch failed: {val}")
                else:
                    result.plan_credits = val

            if "exams" in data:
                val = data["exams"]
                if isinstance(val, Exception):
                    result.add_error(f"Exam fetch failed: {val}")
                else:
                    result.exams = val

            # login_page no longer needed after cookie extraction.
            await login_page.close()

        except Exception as e:
            result.add_error(str(e))
            log.error("Unexpected error: %s", e)
        finally:
            await ctx.close()

        return result

    async def scan_all(self, accounts: list[dict], max_concurrency: int = 5,
                       do_cookies: bool = True,
                       do_grades: bool = True,
                       do_plan: bool = True,
                       do_exams: bool = True) -> list[ScanResult]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            sem = asyncio.Semaphore(max_concurrency)

            async def limited(acc):
                async with sem:
                    try:
                        return await self.scan_account(
                            browser, acc,
                            do_cookies=do_cookies,
                            do_grades=do_grades,
                            do_plan=do_plan,
                            do_exams=do_exams,
                        )
                    except Exception as e:
                        r = ScanResult(proxy=acc.get("proxy", ""),
                                       username=acc.get("username", "?"))
                        r.add_error(str(e))
                        return r

            try:
                results = await asyncio.gather(*[limited(a) for a in accounts])
            finally:
                await browser.close()
        return results
