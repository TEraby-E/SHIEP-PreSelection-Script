from .logconf import account_logger


async def login(page, username: str, password: str,
                login_url: str, target_url: str) -> tuple[bool, str]:
    """
    Navigate to the IDS login page and authenticate.

    Returns (login_ok, error).
      - If we land directly on jw.shiep.edu.cn (session already valid / SSO
        skipped the form), we treat that as logged-in and return early.
      - login_ok=True does NOT guarantee no error; check error separately.
    """
    log = account_logger(username)
    log.info("Navigating to IDS login...")

    await page.goto(f"{login_url}?service={target_url}", wait_until="domcontentloaded")

    # SSO may have bounced us straight through to the target.
    if "ids.shiep.edu.cn" not in page.url and "authserver" not in page.url:
        already = "jw.shiep.edu.cn" in page.url
        if already:
            log.info("SSO session already valid — skipped login form")
        return already, "" if already else "Unexpected page, no login form"

    try:
        await page.wait_for_selector("input#username", timeout=15000)
    except Exception:
        return False, "Login form did not load"

    if await page.is_visible("#captchaResponse"):
        return False, "Captcha required"

    await page.fill("input#username", username)
    await page.fill("input#password", password)

    clicked = False
    for sel in ('button[type="submit"]', 'input[type="submit"]',
                "#login_submit", 'button:has-text("登录")', 'a:has-text("登录")'):
        try:
            await page.click(sel, timeout=3000)
            log.info("Clicked login button")
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        return False, "No login button found"

    # Wait for navigation to a jw page rather than a fixed sleep.
    try:
        await page.wait_for_url("**/jw.shiep.edu.cn/**", timeout=15000)
    except Exception:
        # Fall back to load-state in case the URL pattern differs slightly.
        try:
            await page.wait_for_load_state("load", timeout=5000)
        except Exception:
            pass

    if "jw.shiep.edu.cn" in page.url:
        return True, ""
    # Still on the auth server → bad credentials or a server-side error.
    return False, "Login did not complete (still on auth server)"


async def fetch_cookies(ctx, page, target_url: str,
                        cookie_filter: str, username: str) -> tuple[list, str]:
    """Navigate to target_url and extract filtered cookies. Returns (cookies, error)."""
    log = account_logger(username)
    try:
        if page.url != target_url:
            await page.goto(target_url, wait_until="domcontentloaded")

        cookies = await ctx.cookies()
        if cookie_filter:
            want = {n.strip() for n in cookie_filter.split(",") if n.strip()}
            cookies = [c for c in cookies if c["name"] in want]

        result = [{"name": c["name"], "value": c["value"],
                   "domain": c["domain"], "path": c["path"]} for c in cookies]
        log.info("Got %d cookies", len(result))
        return result, ""
    except Exception as e:
        log.warning("Cookie fetch failed: %s", e)
        return [], str(e)
