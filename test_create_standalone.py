import asyncio
from playwright.async_api import async_playwright

USERNAME = "john.doe"
PASSWORD = "moqui"

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
            await page.get_by_role("textbox", name="Username").click(timeout=3000)
        except:
            pass
        for ch in USERNAME:
            await page.keyboard.press(ch)
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.3)
        await page.evaluate(
            """() => {
                const host = document.querySelector('flt-text-editing-host');
                const input = host ? host.querySelector('input') : null;
                if (input) {
                    input.value = '%s';
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                }
            }""" % PASSWORD
        )
        await page.keyboard.press("Enter")
        
        try:
            await page.wait_for_url("**/marble**", timeout=10000)
            print("Logged in")
        except:
            print("Login timeout but proceeding")
        
        print("Navigating to FindParty...")
        await page.goto("http://localhost:8181/?FLUTTER_WEB_ENABLE_SEMANTICS=true#/fapps/marble/Party/FindParty")
        
        try:
            await page.wait_for_selector("text='New Person'", timeout=15000)
        except:
            pass
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
            await page.keyboard.press("Tab")
        except Exception as e:
            print("Failed to fill via standard keys:", e)

        await asyncio.sleep(1)

        print("Clicking Create...")
        await page.locator("text='Create'").last.click()
        
        print("Waiting 5s for network/response...")
        await asyncio.sleep(5)
        
        await page.screenshot(path="CREATE_FINAL.png")
            
        count = await page.locator("dialog").count()
        print(f"Dialog count: {count}")
        if count > 0:
            print("Create Failed: Dialog still open")
        else:
            print("Create Success: Dialog closed")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
