import asyncio
from playwright.async_api import async_playwright

USERNAME = "john.doe"
PASSWORD = "moqui"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

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
        except:
            pass
        
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
            print("Click First Name")
            await page.get_by_role("textbox", name="First Name").click(timeout=5000)
            await asyncio.sleep(0.5)
            # The FLT input is now active
            await page.locator("flt-text-editing-host input").fill("Playwright")
            print("Filled First Name")
            await page.keyboard.press("Tab") # or Enter
            await asyncio.sleep(0.5)

            print("Click Last Name")
            await page.get_by_role("textbox", name="Last Name").click(timeout=5000)
            await asyncio.sleep(0.5)
            await page.locator("flt-text-editing-host input").fill("TestPerson")
            print("Filled Last Name")
            await page.keyboard.press("Tab")
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print("Failed to fill form:", e)

        print("Clicking Create...")
        await page.locator("text='Create'").last.click()
        
        print("Waiting 3s ...")
        await asyncio.sleep(3)
        
        await page.screenshot(path="CREATE_TEST_FINAL.png")
            
        count = await page.locator("dialog").count()
        print(f"Dialog count: {count}")
        if count > 0:
            print("CREATE FAILED: Dialog still open")
        else:
            print("CREATE SUCCESS: Dialog closed")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
