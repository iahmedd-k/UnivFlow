import asyncio
import json
import urllib.request
from playwright.async_api import async_playwright

async def verify():
    # Login
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/v1/auth/manual/login',
        data=json.dumps({'email': '232530@students.au.edu.pk', 'password': 'password123'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    token = data['token']
    user = data['user']

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        await context.add_cookies([{"name": "uniflow_manual_token", "value": token, "domain": "localhost", "path": "/"}])
        page = await context.new_page()

        await page.goto("http://localhost:3000/dashboard/rag-assistant", wait_until="domcontentloaded")
        await page.evaluate(f"""() => {{
            localStorage.setItem('uniflow_manual_token', '{token}');
            localStorage.setItem('uniflow_manual_user', JSON.stringify({json.dumps(user)}));
        }}""")
        await page.goto("http://localhost:3000/dashboard/rag-assistant", wait_until="networkidle")
        await asyncio.sleep(2)

        content = await page.content()
        has_unlimited_tier = "Unlimited Tier" in content
        has_signout = "Sign out" in content
        has_clerk_avatar = "clerk-user-button" in content or "clerk-avatar" in content or "UserButton" in content
        
        print("Has 'Unlimited Tier':", has_unlimited_tier)
        print("Has 'Sign out':", has_signout)
        print("Has UserButton/avatar in TopBar:", has_clerk_avatar)

        assert not has_unlimited_tier, "Unlimited Tier is still present!"
        assert not has_signout, "Sign out button is still present!"
        assert not has_clerk_avatar, "Profile icon is still present!"

        await browser.close()
        print("SUCCESS: Unlimited Tier, Sign out, and Profile icon successfully removed from Study Assistant!")

asyncio.run(verify())

