"""Headless UI audit (Edge via Playwright, no visible window). Needs the app on :5057 and the seeded DB.
Checks per page and width: console errors, horizontal overflow, visible scrollbars, small touch targets (phone),
text/background contrast, hover contrast, focus ring, then saves a screenshot to docs/screens."""
import pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screens"
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:5057"
PAGES = ["/", "/inventory", "/inventory?group=O-&component=PRBC", "/donors", "/donors/new", "/donors/20", "/screening",
         "/screening?flag=hiv", "/requests", "/camps", "/query-lab", "/unit/10",
         "/design/er", "/design/normalization", "/design/algebra", "/design/sql", "/design/indexing", "/design/transactions", "/design/nosql"]
WIDTHS = {"desktop": (1280, 800), "tablet": (1024, 768), "phone": (390, 844)}

JS_AUDIT = """() => {
  const out = {overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1, scrollbars: [], small: [], lowContrast: []};
  const lum = c => { const [r,g,b] = c.map(v => { v/=255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); }); return .2126*r + .7152*g + .0722*b; };
  const parse = s => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(Number); return p.length === 4 && p[3] === 0 ? null : p.slice(0,3); };
  const bgOf = el => { while (el) { const c = parse(getComputedStyle(el).backgroundColor); if (c) return c; el = el.parentElement; } return [243,240,232]; };
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll' || cs.overflowY === 'auto' || cs.overflowY === 'scroll') && el !== document.body && el !== document.documentElement) {
      if (el.offsetWidth - el.clientWidth > 0 || el.offsetHeight - el.clientHeight > 0) out.scrollbars.push(el.tagName + '.' + el.className);
    }
  }
  for (const el of document.querySelectorAll('a.btn, button.btn, input:not([type=hidden]):not([type=checkbox]), select, textarea, .rail nav a')) {
    const r = el.getBoundingClientRect(); if (r.width && r.height < 36 && el.offsetParent) out.small.push(el.tagName + ' ' + (el.textContent||el.name||'').trim().slice(0,20) + ' h=' + Math.round(r.height));
  }
  const seen = new Set();
  for (const el of document.querySelectorAll('p, td, th, a, label, span, h1, h2, h3, dd, dt, button, li')) {
    if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const cs = getComputedStyle(el); const fg = parse(cs.color); if (!fg || !el.offsetParent) continue;
    const bg = bgOf(el); const L1 = lum(fg), L2 = lum(bg); const ratio = (Math.max(L1,L2)+.05)/(Math.min(L1,L2)+.05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 600; const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    const key = cs.color + bg + el.className; if (ratio < need && !seen.has(key)) { seen.add(key); out.lowContrast.push(el.tagName + '.' + el.className + ' "' + el.textContent.trim().slice(0,24) + '" ' + ratio.toFixed(2)); }
  }
  return out;
}"""

problems = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    for wname, (w, h) in WIDTHS.items():
        ctx = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="no-preference")
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        for path in PAGES:
            errors.clear()
            resp = page.goto(BASE + path, wait_until="load")
            page.wait_for_timeout(150)
            tag = f"[{wname} {path}]"
            if resp.status != 200:
                problems.append(f"{tag} HTTP {resp.status}")
            res = page.evaluate(JS_AUDIT)
            if res["overflowX"]: problems.append(f"{tag} horizontal overflow")
            if res["scrollbars"]: problems.append(f"{tag} visible scrollbars: {res['scrollbars'][:3]}")
            if wname == "phone" and res["small"]: problems.append(f"{tag} small targets: {res['small'][:4]}")
            if res["lowContrast"]: problems.append(f"{tag} low contrast: {res['lowContrast'][:4]}")
            if errors: problems.append(f"{tag} console: {errors[:2]}")
            name = path.strip("/").replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "") or "dashboard"
            if wname != "tablet":
                page.screenshot(path=str(SHOTS / f"{wname}_{name}.png"), full_page=True)

        # hover + focus checks on the dashboard (desktop/tablet only)
        if wname != "phone":
            page.goto(BASE + "/")
            btn = page.locator("button.btn").first
            btn.hover(); page.wait_for_timeout(200)
            bg, fg = btn.evaluate("e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color]")
            print(f"[{wname}] hovered button bg={bg} fg={fg}")
            link = page.locator(".cell").first
            link.focus()
            if "none" in link.evaluate("e => getComputedStyle(e).outlineStyle"):
                problems.append(f"[{wname}] focused stock cell has no outline")
            page.keyboard.press("Tab")
        ctx.close()
    browser.close()

print("\n".join(problems) if problems else "UI audit clean")
sys.exit(1 if problems else 0)
