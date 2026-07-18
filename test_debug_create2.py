import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        def intercept_res(r):
            if "createPerson" in r.url:
                print(f"-> NETWORK RESPONSE: {r.status} {r.url}")

        page.on("response", intercept_res)
        
        print("Logging in...")
        await page.goto("http://localhost:8181/?FLUTTER_WEB_ENABLE_SEMANTICS=true")
        await asyncio.sleep(2)
        try:
            await page.get_by_placeholder("john.doe").fill("john.doe", timeout=5000)
            await page.get_by_placeholder("moqui").fill("moqui", timeout=5000)
        except:
            await page.locator("input").nth(0).fill("john.doe")
            await page.locator("input").nth(1).fill("moqui")
        await page.locator("text='Login'").click()
        await page.wait_for_url("**/marble**", timeout=10000)
        print("Logged in")
        
        print("Navigating to FindParty...")
        await page.goto("http://localhost:8181/?FLUTTER_WEB_ENABLE_SEMANTICS=true#/fapps/marble/Party/FindParty")
        
        # We need to wait for something on that page to ensure it loaded
        await page.wait_for_selector("text='New Person'", timeout=10000)
        await asyncio.sleep(2)
        
        print("Clicking New Person...")
        await page.locator("text='New Person'").first.click()
        await asyncio.sleep(2)
        
        print("Filling Form...")
        try:
            await page.get_by_role("textbox", name="First Name").click(timeout=5000)
            await page.keyboard.type("Playwright")
            
            await page.keyboard.press("Tab")
            await page.keyboard.type("Testing")
        except Exception as e:
            print("Failed to click First Name:", e)
            print("Trying generic input locator...")
            inputs = page.locator("input")
            count = await inputs.count()
            print(f"Found {count} inputs globally.")
            if count >= 3:
                # the first might be search, the others are dialog
                await inputs.nth(count - 2).fill("Playwright")
                await inputs.nth(count - 1).fill("Testing")
            else:
                # Fallback to keyboard
                await page.keyboard.press("Shift+Tab")
                await page.keyboard.type("Playwright")
                await page.keyboard.press("Tab")
                await page.keyboard.type("Testing")

        await asyncio.sleep(1)

        print("Clicking Create...")
        await page.locator("text='Create'").last.click()
        
        print("Waiting 5s for network/response...")
        await asyncio.sleep(5)
        
        count = await page.locator("dialog").count()
        print(f"Dialog count: {count}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
