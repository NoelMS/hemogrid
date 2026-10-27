"""End-to-end flows through the real forms (headless Edge). Mutates the seeded DB: re-run scripts/seed.py afterwards."""
import sys
from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:5057"
steps = 0


def ok(msg):
    global steps
    steps += 1
    print(f"  ok   {msg}")


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.on("dialog", lambda d: d.accept())
    flash = lambda: pg.locator(".msg").first

    # 1. register donor (validation first: future DOB must be rejected by the CHECK constraint)
    pg.goto(BASE + "/donors/new")
    pg.fill("#n", "Test Donor Flow"); pg.fill("#d", "2999-01-01"); pg.select_option("#g", "O-"); pg.fill("#p", "+919876543210")
    pg.evaluate("document.querySelector('#d').removeAttribute('max')")
    pg.click("text=Register >> nth=-1")
    expect(flash()).to_contain_text("dob"); ok("future date of birth is rejected by the database")
    pg.fill("#d", "1999-05-04"); pg.click("button.btn")
    expect(flash()).to_contain_text("Registered Test Donor Flow"); ok("donor registered")

    # 2. record donation, then a second one is refused by the gap trigger
    pg.click("text=Record donation")
    expect(flash()).to_contain_text("quarantined"); ok("donation recorded")
    pg.click("text=Record donation")
    expect(flash()).to_contain_text("next eligible"); ok("second donation blocked by the 90-day trigger")

    # 3. screening: a reactive marker fails and defers the donor
    pg.goto(BASE + "/screening")
    row = pg.locator("tr", has_text="Test Donor Flow")
    row.locator("select[name=reactive]").select_option("hcv"); row.locator("button").click()
    expect(flash()).to_contain_text("FAILED screening"); ok("reactive marker fails screening, donor deferred")
    pg.goto(BASE + "/donors?q=Test+Donor+Flow")
    expect(pg.locator(".tag.FAIL").first).to_contain_text("deferred"); ok("donor list shows the deferral")

    # 4. a passing donation creates units
    pg.goto(BASE + "/donors?eligible=1&group=B%2B")
    pg.locator("tbody a").first.click()
    name = pg.locator("h1").inner_text()
    pg.click("text=Record donation")
    expect(flash()).to_contain_text("quarantined")
    pg.goto(BASE + "/screening")
    pg.locator("tr", has_text=name).locator("button").click()
    expect(flash()).to_contain_text("PASSED"); ok(f"screening PASS releases units ({name})")

    # 5. emergency request auto-allocates; issue it; cancel another
    pg.goto(BASE + "/requests")
    pg.select_option("#c", "PRBC"); pg.select_option("#g", "EMERGENCY"); pg.fill("#u", "1")
    pg.select_option("#p", index=0)
    pg.click("text=Raise request")
    expect(flash()).to_contain_text("auto-allocation reserved"); ok("emergency request auto-allocates")
    got = "reserved 1" in flash().inner_text()
    if got:
        pg.locator("tr", has=pg.locator(".tag.EMERGENCY")).first.locator("text=Issue to hospital").first.click()
        expect(flash()).to_contain_text("issued to the hospital"); ok("request issued")
    pg.locator("button:has-text('Cancel')").first.click()
    expect(flash()).to_contain_text("cancelled"); ok("request cancelled, units released")

    # 6. barcode lookup and unknown barcode
    pg.goto(BASE + "/inventory")
    code = pg.locator("tbody a.mono").first.inner_text()
    pg.fill("#bc", code); pg.click("text=Find unit")
    expect(pg.locator("h1")).to_have_text(code); ok("barcode lookup opens the unit")
    pg.goto(BASE + "/inventory"); pg.fill("#bc", "NOPE"); pg.click("text=Find unit")
    expect(flash()).to_contain_text("No unit with barcode NOPE"); ok("unknown barcode explained")

    # 7. sweep + empty state
    pg.goto(BASE + "/"); pg.click("text=Run expiry sweep")
    expect(flash()).to_contain_text("Expiry sweep complete"); ok("expiry sweep runs")
    pg.goto(BASE + "/donors?q=zzzzzz"); expect(pg.locator(".empty")).to_contain_text("No donors match"); ok("empty search state")
    b.close()
print(f"{steps} flow checks passed")
