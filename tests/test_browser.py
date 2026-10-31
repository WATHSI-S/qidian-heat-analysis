"""Offline browser checks against the exact publication artifact."""
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def latest_snapshot():
    folder = ROOT / "dist/site/data"
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    return json.loads((folder / index["weeks"][-1]["file"]).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def browser_site():
    from playwright.sync_api import sync_playwright
    folder = ROOT / "dist/site"
    assert (folder / "index.html").exists(), "Run python scripts/build_site.py first"
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(folder))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            yield browser, f"http://127.0.0.1:{server.server_port}"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def new_page(browser, **kwargs):
    page = browser.new_page(**kwargs)
    page.route("https://**/*", lambda route: route.abort())
    return page


@pytest.mark.parametrize("route", ["rankings", "categories", "topics", "report"])
def test_workspace_routes(browser_site, route):
    browser, base = browser_site
    page = new_page(browser)
    errors=[]
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(base + "/#/" + route)
        page.wait_for_selector("nav a.active")
        assert page.locator("#content").inner_text()
        assert latest_snapshot()["week"] in page.locator("#week").inner_text()
        assert not errors
    finally: page.close()


def test_table_drawer_and_navigation(browser_site):
    browser, base=browser_site
    page=new_page(browser)
    try:
        page.goto(base)
        page.wait_for_selector("tbody tr")
        assert page.locator("tbody tr").count()==20
        page.locator("#next").click()
        first=page.locator("tbody tr").first.inner_text()
        page.locator("[data-book]").first.click()
        assert page.locator("dialog").is_visible()
        page.keyboard.press("Escape")
        assert not page.locator("dialog").is_visible()
        assert page.locator("tbody tr").first.inner_text()==first
        page.locator("nav a[href='#/categories']").click()
        page.wait_for_selector("#categoryMetric")
        page.go_back()
        page.wait_for_selector("tbody tr")
        assert page.locator("tbody tr").first.inner_text()==first
        page.locator("[data-drawer=research]").click()
        page.wait_for_selector("#researchStatus")
        page.locator("[data-research=authors]").click()
        assert page.locator("#research-chart svg").count()==1
        page.locator("#closeDrawer").click()
        assert page.evaluate("async()=> (await import('/js/shared.js')).chartCount()") == 0
    finally: page.close()


@pytest.mark.parametrize("filename,route", [("analysis.html","rankings"),("trends.html","categories"),("ai-report.html","report")])
def test_legacy_routes(browser_site, filename, route):
    browser,base=browser_site
    page=new_page(browser)
    try:
        page.goto(base+'/'+filename)
        page.wait_for_url('**#/'+route)
        page.wait_for_selector('nav a.active')
    finally: page.close()


@pytest.mark.parametrize("route", ["rankings","categories","topics","report"])
def test_mobile_workspace(browser_site,route):
    browser,base=browser_site
    page=new_page(browser,viewport={"width":375,"height":812})
    try:
        page.goto(base+'/#/'+route)
        page.wait_for_selector('nav a.active')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        page.locator('#menu').click()
        assert page.locator('nav a').first.is_visible()
        page.locator('#navShade').click(position={"x":350,"y":100})
        page.locator('#quality').click()
        page.wait_for_selector('dialog[open] dl')
        assert page.locator('dialog').bounding_box()['width'] <= 375
    finally: page.close()
