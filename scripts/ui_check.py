"""Drive the dashboard in Microsoft Edge and check that every interaction works.

Needs the API (port 8000) and the dashboard (port 5173) running, plus:
    pip install -r requirements-dev.txt
Usage:
    python scripts/ui_check.py

It confirms the first pending finding with the keyboard and then undoes it through
the toast, so the data ends exactly as it started. Screenshots go to the folder in
the UI_SHOTS environment variable (default: the system temp folder).
"""

import json
import os
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
SHOTS = os.environ.get("UI_SHOTS", tempfile.gettempdir())
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def api(path):
    return json.load(urllib.request.urlopen(f"http://localhost:8000{path}"))


for _ in range(40):
    try:
        api("/api/health")
        break
    except Exception:
        time.sleep(2)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme="light")
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))

    # Dashboard: count-up ends on the real numbers.
    page.goto(BASE + "/")
    page.wait_for_selector(".stat-value")
    page.wait_for_timeout(1200)
    values = page.locator(".stat-value").all_inner_texts()
    check("stat cards count up to real values", values[0] == str(api("/api/stats")["documents"]), str(values))
    page.screenshot(path=f"{SHOTS}/i-dashboard.png")

    # Command palette: Ctrl+K, type, Enter navigates.
    page.keyboard.press("Control+k")
    page.wait_for_selector(".palette")
    page.keyboard.type("INV-2026")
    page.wait_for_timeout(400)
    page.screenshot(path=f"{SHOTS}/i-palette.png")
    page.keyboard.press("Enter")
    page.wait_for_url("**/documents/*")
    check("Ctrl+K palette opens and navigates", "/documents/" in page.url, page.url)

    # Document page: linked highlighting, field source, collapse, lightbox.
    page.wait_for_selector(".finding")
    page.wait_for_timeout(600)
    page.locator(".finding").first.hover()
    page.wait_for_timeout(300)
    check("hovering a finding highlights its table row", page.locator("tr.linked").count() == 1,
          page.locator("tr.linked td").first.inner_text() if page.locator("tr.linked").count() else "")
    page.screenshot(path=f"{SHOTS}/i-linked.png", full_page=True)
    page.locator("tr.row-match").first.hover()
    page.wait_for_timeout(300)
    check("hovering the bolts row highlights its passed checks, not the pump issue",
          page.locator(".finding-critical.highlighted").count() == 0
          and page.locator(".finding.highlighted").count() > 0)

    page.locator(".field-row").filter(has=page.locator(".field-label", has_text="Total")).last.click()
    page.wait_for_timeout(450)
    check("clicking a field reveals its source line", page.locator(".field.open .field-source code").count() == 1,
          page.locator(".field.open .field-source").inner_text().replace("\n", " ") if page.locator(".field.open").count() else "")

    page.locator("button.toggle").click()
    page.wait_for_timeout(450)
    check("passed checks expand smoothly", page.locator(".collapse.open").count() == 1)

    page.locator(".page-thumb").first.click()
    page.wait_for_selector(".lightbox img")
    page.wait_for_timeout(350)
    page.screenshot(path=f"{SHOTS}/i-lightbox.png")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check("scan opens in a zoom lightbox and Esc closes it", page.locator(".lightbox").count() == 0)

    # Reviews: keyboard confirm, toast, collapse, then Undo through the toast.
    finding_id = api("/api/findings")[0]["id"]
    page.goto(BASE + "/reviews")
    page.wait_for_selector(".finding.active")
    page.keyboard.press("c")
    page.wait_for_selector(".toast")
    toast_text = page.locator(".toast").first.inner_text()
    page.screenshot(path=f"{SHOTS}/i-toast.png")
    check("C key confirms and shows a toast with Undo", "Issue confirmed" in toast_text and "Undo" in toast_text, toast_text.replace("\n", " "))
    page.wait_for_timeout(700)
    status_after = next(f for f in api("/api/findings?review_status=approved") if f["id"] == finding_id)["review_status"]
    check("finding saved as confirmed", status_after == "approved")
    check("card collapsed out of the queue", page.locator(".finding").count() == 0)
    page.locator(".toast button.link", has_text="Undo").click()
    page.wait_for_timeout(1000)
    back = [f["id"] for f in api("/api/findings")]
    check("Undo puts it back in the queue", finding_id in back)
    check("restored card is visible again", page.locator(".finding").count() == 1)

    # Theme switch.
    page.goto(BASE + "/documents")
    page.wait_for_selector("table")
    page.locator(".search-field input").fill("purchase")
    page.wait_for_timeout(200)
    check("document filter narrows the table", page.locator("tbody tr").count() == 1)
    page.locator(".theme-button").click()
    page.wait_for_timeout(300)
    theme = page.evaluate("document.documentElement.dataset.theme")
    page.screenshot(path=f"{SHOTS}/i-documents-{theme}.png")
    page.locator(".theme-button").click()
    page.wait_for_timeout(300)
    theme2 = page.evaluate("document.documentElement.dataset.theme")
    check("theme button cycles light -> dark", (theme, theme2) == ("light", "dark"), f"{theme} -> {theme2}")
    page.locator(".theme-button").click()  # back to "system"

    # Ask: word-by-word answer, citation chip scrolls to and flashes its source.
    page.goto(BASE + "/ask")
    page.locator(".ask-bar input").fill("What is the total amount due on the invoice?")
    page.keyboard.press("Enter")
    page.wait_for_selector(".bubble-q")
    page.wait_for_selector(".thinking")
    page.screenshot(path=f"{SHOTS}/i-ask-thinking.png")
    page.wait_for_selector(".fade-in-after.visible", timeout=120000)
    answer = page.locator(".answer-text").inner_text()
    check("answer appears word by word, then sources fade in", "5,100" in answer, answer)
    page.locator(".answer-text button.cite").first.click()
    page.wait_for_timeout(150)
    check("clicking a citation flashes its source", page.locator(".source.flash").count() == 1)
    page.wait_for_timeout(1300)
    page.screenshot(path=f"{SHOTS}/i-ask.png")

    check("no JavaScript errors in the console", not errors, "; ".join(errors[:3]))
    browser.close()

passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} interaction checks passed")
sys.exit(0 if passed == len(results) else 1)
