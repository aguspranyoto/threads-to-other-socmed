"""Headless Threads post screenshot (no UI, runs in background).

Captures the real post card (avatar + username + text + counts) exactly as
seen on threads.com, using headless Chromium. Login dialogs, dim veils and
cookie bars are stripped via JS before capture. Cards are grabbed with
element screenshots, so side rails never leak in.

Modes per URL:
    plain        only the target post card
    with_comment target card + parent card stacked (else first reply below)
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

STRIP_JS = """([sc, cardW]) => {
  const anchor = document.querySelector('a[href*="/post/' + sc + '"]');
  // login / signup dialogs always go
  document.querySelectorAll('[role="dialog"]').forEach(e => e.remove());
  // floating "Scroll up to see original post" pill
  document.querySelectorAll('div,span,button').forEach(e => {
    if (e.children.length === 0
        && e.textContent.includes('Scroll up to see original post')) {
      let n = e;
      for (let i = 0; i < 4 && n && n !== document.body; i++) {
        const p = getComputedStyle(n).position;
        if (p === 'fixed' || p === 'sticky' || p === 'absolute') {
          n.remove();
          break;
        }
        n = n.parentElement;
      }
    }
  });
  // cookie consent bar (contains "Threads Terms of Use")
  document.querySelectorAll('div').forEach(e => {
    if (e.children.length === 0
        && e.textContent.includes('Threads Terms of Use')) {
      let n = e;
      for (let i = 0; i < 6 && n && n !== document.body; i++) {
        const cs = getComputedStyle(n);
        const r = n.getBoundingClientRect();
        if ((cs.position === 'fixed' || cs.position === 'sticky')
            && r.bottom >= innerHeight - 2) {
          n.remove();
          break;
        }
        n = n.parentElement;
      }
    }
  });
  // any big fixed/sticky overlay that does NOT contain the target card
  document.querySelectorAll('div').forEach(e => {
    try {
      const cs = getComputedStyle(e);
      if (cs.position !== 'fixed' && cs.position !== 'sticky') return;
      const r = e.getBoundingClientRect();
      if (r.width < innerWidth * 0.5 || r.height < innerHeight * 0.3) return;
      if (anchor && e.contains(anchor)) return;
      e.style.setProperty('display', 'none', 'important');
    } catch (err) {}
  });
  // sticky -> static so nothing floats over the card capture
  document.querySelectorAll('*').forEach(e => {
    try {
      if (getComputedStyle(e).position === 'sticky') e.style.position = 'static';
    } catch (err) {}
  });
  window.scrollTo(0, 0);
  const col = document.querySelector('[data-column-scrollable]');
  if (col) col.scrollTo(0, 0);
}"""

NARROW_JS = """(cardW) => {
  if (!cardW || cardW <= 0) return 'skip';
  const col = document.querySelector('[data-column-scrollable]');
  if (!col) return 'no-col';
  col.style.setProperty('max-width', cardW + 'px', 'important');
  col.style.setProperty('margin-left', 'auto', 'important');
  col.style.setProperty('margin-right', 'auto', 'important');
  // remove back-to-top pill (small fixed/sticky box with svg, no text)
  const cards = [...document.querySelectorAll(
    'div[data-pressable-container="true"]')];
  const cr = cards.length ? cards[0].getBoundingClientRect() : null;
  const px = cr ? cr.x + cr.width - 60 : innerWidth * 0.45;
  const py = cr ? cr.y + 100 : 200;
  const els = document.elementsFromPoint(px, py);
  for (const e of els) {
    const r = e.getBoundingClientRect();
    const hasSvg = e.tagName === 'svg' || !!e.querySelector('svg');
    const noText = !(e.innerText || '').trim();
    if (r.width >= 40 && r.width <= 160 && r.height >= 18 && r.height <= 90
        && hasSvg && noText) {
      e.remove();
      return 'pill-removed';
    }
  }
  return 'ok';
}""";

PILL_JS = """() => {
  // back-to-top pill by accessible label
  document.querySelectorAll('[aria-label]').forEach(e => {
    const l = (e.getAttribute('aria-label') || '').toLowerCase();
    if (/back to top|scroll (to top|up)|go to top/.test(l)) e.remove();
  });
  // back-to-top pill by geometry: small fixed box with svg, no text,
  // overlapping the card's horizontal band
  const cards = [...document.querySelectorAll(
    'div[data-pressable-container="true"]')];
  const cr = cards.length ? cards[0].getBoundingClientRect() : null;
  document.querySelectorAll('div,button,a').forEach(e => {
    try {
      const cs = getComputedStyle(e);
      if (cs.position !== 'fixed' && cs.position !== 'sticky'
          && cs.position !== 'absolute') return;
      const r = e.getBoundingClientRect();
      if (r.width < 40 || r.width > 160 || r.height < 18 || r.height > 90)
        return;
      if (!e.querySelector('svg')) return;
      if ((e.innerText || '').trim()) return;
      if (cr && (r.right < cr.x || r.left > cr.right)) return;
      e.remove();
    } catch (err) {}
  });
  return 'ok';
}""";

OBSERVER_JS = """() => {
  if (window.__t2sObs) return 'already';
  const kill = () => {
    document.querySelectorAll('div,button,a').forEach(e => {
      try {
        const cs = getComputedStyle(e);
        if (cs.position !== 'fixed' && cs.position !== 'sticky'
            && cs.position !== 'absolute') return;
        const r = e.getBoundingClientRect();
        if (r.width < 40 || r.width > 160
            || r.height < 18 || r.height > 90) return;
        if (!e.querySelector('svg')) return;
        if ((e.innerText || '').trim()) return;
        e.remove();
      } catch (err) {}
    });
  };
  window.__t2sKillPill = kill;
  kill();
  const obs = new MutationObserver(() => kill());
  obs.observe(document.body, {childList: true, subtree: true});
  window.__t2sObs = true;
  return 'installed';
}""";

SCROLL_LOAD_JS = """async () => {
  const col = document.querySelector('[data-column-scrollable]');
  for (let i = 0; i < 12; i++) {
    if (col) col.scrollTop += 900; else window.scrollBy(0, 900);
    await new Promise(r => setTimeout(r, 180));
  }
  if (col) col.scrollTo(0, 0);
  window.scrollTo(0, 0);
}"""

TEXT_JS = """(sc) => {
  const ctrs = [...document.querySelectorAll(
    'div[data-pressable-container="true"]')];
  let card = null;
  for (const c of ctrs) {
    const links = [...c.querySelectorAll('a[href*="/post/"]')];
    if (links.some(x => x.href.includes('/post/' + sc)
                     && !x.href.includes('/media'))) {
      card = c;
      break;
    }
  }
  if (!card) return '';
  return (card.innerText || '').slice(0, 2500);
}""";

ENUM_JS = """() => [...document.querySelectorAll(
    'div[data-pressable-container="true"]'
  )].map((e, i) => {
    const r = e.getBoundingClientRect();
    const codes = [...new Set(
      [...e.querySelectorAll('a[href*="/post/"]')]
        .filter(x => !x.href.includes('/media'))
        .map(x => (x.href.match(/\\/post\\/([A-Za-z0-9_-]+)/) || [])[1])
        .filter(Boolean)
    )];
    return {i, x: r.x, y: r.y, w: r.width, h: r.height, codes};
  }).filter(o => o.w > 200 && o.codes.length)"""


def shortcode_of(url: str) -> str | None:
    m = re.search(r"/post/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


def screenshot_many(jobs: list[tuple[str, Path, bool]],
                    card_width: int = 0
                    ) -> dict[str, dict]:
    """Screenshot post cards headless, one shared browser.

    jobs: list of (url, out_png, with_comment).
    card_width: narrow the Threads column to this CSS px (text wraps down).
    Returns {url: {"ok": bool, "author": str, "text": str}}.
    """
    from playwright.sync_api import sync_playwright

    results: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for url, out, with_comment in jobs:
                try:
                    results[url] = _screenshot_one(browser, url, out,
                                                   with_comment, card_width)
                except Exception as e:  # noqa: BLE001
                    print(f"    ! screenshot gagal: {e}")
                    results[url] = {"ok": False, "author": "",
                                     "text": ""}
        finally:
            browser.close()
    return results


def _pick(pcs: list[dict], sc: str, with_comment: bool):
    target = next((c for c in pcs if sc in c["codes"]), None)
    if target is None or not with_comment:
        return target, None
    cand = [c for c in pcs
            if sc not in c["codes"]
            and abs(c["x"] - target["x"]) < 120]
    above = [c for c in cand if c["y"] + c["h"] <= target["y"] + 4]
    below = [c for c in cand if c["y"] >= target["y"] + target["h"] - 4]
    neighbour = (max(above, key=lambda c: c["y"]) if above
                 else (min(below, key=lambda c: c["y"]) if below else None))
    return target, neighbour


def _screenshot_one(browser, url: str, out: Path,
                    with_comment: bool, card_width: int = 0) -> dict:
    sc = shortcode_of(url)
    if not sc:
        print("    ! URL bukan link post threads.com")
        return {"ok": False, "author": "", "text": ""}
    page = browser.new_page(viewport={"width": 1280, "height": 900},
                            device_scale_factor=2,
                            color_scheme="dark")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(f'a[href*="/post/{sc}"]', timeout=30000)
        except Exception:
            print("    ! postingan ga ke-load (timeout)")
            return {"ok": False, "author": "", "text": ""}
        page.wait_for_timeout(2500)
        page.evaluate(STRIP_JS, [sc, 0])
        page.evaluate(OBSERVER_JS)  # kill pill on sight for the rest
        page.evaluate(SCROLL_LOAD_JS)
        page.wait_for_timeout(1500)
        page.evaluate(STRIP_JS, [sc, 0])
        page.evaluate(NARROW_JS, card_width)
        page.wait_for_timeout(900)
        page.evaluate(PILL_JS)
        page.wait_for_timeout(400)
        raw_text = page.evaluate(TEXT_JS, sc) or ""
        pcs = page.evaluate(ENUM_JS)
        target, neighbour = _pick(pcs, sc, with_comment)
        if target is None:
            print(f"    ! shortcode {sc} ga ketemu "
                  f"(ada: {[c['codes'] for c in pcs][:5]})")
            return {"ok": False, "author": "", "text": ""}

        out = Path(out)
        loc = page.locator('div[data-pressable-container="true"]')
        if neighbour is None:
            if with_comment:
                print("    ! kartu tetangga ga ketemu, pakai postingan aja")
            loc.nth(target["i"]).screenshot(path=str(out))
            _clean_shot(out)
            _pad_top(out)
        else:
            tmp_a, tmp_b = (Path(str(out) + ".a.png"),
                            Path(str(out) + ".b.png"))
            try:
                first, second = ((neighbour, target)
                                  if neighbour["y"] < target["y"]
                                  else (target, neighbour))
                loc.nth(first["i"]).screenshot(path=str(tmp_a))
                loc.nth(second["i"]).screenshot(path=str(tmp_b))
                _clean_shot(tmp_a)
                _clean_shot(tmp_b)
                a_img, b_img = Image.open(tmp_a), Image.open(tmp_b)
                w = max(a_img.width, b_img.width)
                combo = Image.new("RGB", (w, a_img.height + b_img.height),
                                  (0, 0, 0))
                combo.paste(a_img, (0, 0))
                combo.paste(b_img, (0, a_img.height))
                combo.save(out)
                _pad_top(out)
            finally:
                tmp_a.unlink(missing_ok=True)
                tmp_b.unlink(missing_ok=True)

        ok = out.exists() and out.stat().st_size > 0
        if ok:
            im = Image.open(out)
            mode = ("post+komen" if neighbour else "post")
            print(f"    ok: screenshot {mode} ({im.width}x{im.height}px)")
        author, text = _split_card_text(raw_text)
        return {"ok": ok, "author": author, "text": text}
    finally:
        page.close()


def _clean_shot(png: Path):
    """Paint over the back-to-top pill (top-right of card) with card bg.

    The pill can't be removed reliably via DOM (it re-renders on scroll),
    so cover it in the captured image instead: find the bright (whitish)
    blob in the card's top-right corner and fill its bounding box.
    """
    img = Image.open(png).convert("RGB")
    w, h = img.size
    px = img.load()
    x0, x1 = int(w * 0.60), w
    y1 = int(h * 0.30)
    bright = []
    for y in range(0, y1, 2):
        for x in range(x0, x1, 2):
            r, g, b = px[x, y]
            if r > 100 and g > 100 and b > 100:
                bright.append((x, y))
    if not bright:
        return
    xs = [b[0] for b in bright]
    ys = [b[1] for b in bright]
    pad = 6
    box = (max(0, min(xs) - pad), 0,
           min(w, max(xs) + pad), min(h, max(ys) + pad))
    # background fill: most common dark pixel in the row band
    import collections
    bg = collections.Counter()
    for x in range(int(w * 0.40), int(w * 0.60), 4):
        for y in (box[1], box[3] - 1):
            bg[px[x, min(h - 1, y)]] += 1
    fill = bg.most_common(1)[0][0] if bg else (0, 0, 0)
    from PIL import ImageDraw
    ImageDraw.Draw(img).rectangle(box, fill=fill)
    img.save(png)


def _pad_top(png: Path):
    """Tambah padding atas = jarak ikon love ke ujung bawah kartu.

    Ukur bottom pad (baris konten terakhir -> bawah image), lalu tempel
    strip setinggi itu di atas dengan warna bg kartu.
    """
    import collections
    img = Image.open(png).convert("RGB")
    w, h = img.size
    px = img.load()
    bg = collections.Counter(
        px[x, y] for y in (0, h - 1) for x in range(0, w, 8)
    ).most_common(1)[0][0]

    def is_bg(p):
        return (abs(p[0] - bg[0]) + abs(p[1] - bg[1])
                + abs(p[2] - bg[2])) < 36

    last_content = h - 1
    min_content = max(3, w // 300)  # abaikan noise 1-2px di tepi
    for y in range(h - 1, -1, -1):
        nbg = sum(1 for x in range(0, w, 2)
                  if not is_bg(px[x, y]))
        if nbg >= min_content:
            last_content = y
            break
    pad = h - 1 - last_content
    if pad <= 0:
        return
    taller = Image.new("RGB", (w, h + pad), bg)
    taller.paste(img, (0, pad))
    taller.save(png)


def _split_card_text(raw: str) -> tuple[str, str]:
    """Split card innerText into (author, post text).

    Card text looks like: "<user>  11h\\nPost body...\\n1.1K 48 166 42".
    We take the first line's first token as author and drop the trailing
    engagement-count line.
    """
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return "@threads", ""
    author = lines[0].split()[0] if lines[0].split() else "@threads"
    if not author.startswith("@"):
        author = "@" + author
    body = lines[1:]
    # drop leading timestamp line Threads puts on its own row ("14h", "4h"...)
    while body and re.match(r"^(\d+\s*[smhdw]|now|yesterday)$",
                            body[0], re.I):
        body = body[1:]
    # drop trailing engagement-count lines (may be one per icon row)
    while body:
        toks = body[-1].split()
        numish = sum(1 for t in toks
                     if re.fullmatch(r"[\d.,KkMm]+", t))
        if toks and numish / len(toks) >= 0.5:
            body = body[:-1]
        else:
            break
    text = "\n".join(body).strip()
    # drop "Translate" link text Threads appends
    text = re.sub(r"\s*Translate\s*$", "", text).strip()
    return author, text
