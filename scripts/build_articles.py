#!/usr/bin/env python3
"""Scrape Truth or Fables articles and generate local dark-theme pages."""
from __future__ import annotations

import hashlib
import html as htmlmod
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path("/root/projects/truth-or-fables")
LIB = ROOT / "library"
ART_DIR = LIB / "articles"
MEDIA = LIB / "media"
ART_DIR.mkdir(parents=True, exist_ok=True)
MEDIA.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

NAV_SKIP = {
    "home", "subjects", "books", "testimonies", "contact", "faq",
    "former pastors/employees", "index of subjects", "free magazine",
    "other sites we recommend", "contact informaton", "contact information",
    "robert k. sanders",
}


def fetch(url: str) -> bytes:
    r = subprocess.run(
        [
            "curl", "-sL", "-A", UA,
            "-H", "Accept: text/html,application/xhtml+xml,image/*,*/*;q=0.8",
            "--compressed", "--max-time", "45", url,
        ],
        capture_output=True,
    )
    return r.stdout


def fetch_text(url: str) -> str:
    return fetch(url).decode("utf-8", "replace")


def normalize_tof_url(href: str, base: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("#") or href.lower().startswith("mailto:"):
        return href
    if href.startswith("//"):
        href = "http:" + href
    full = urljoin(base, href)
    full = full.replace("https://www.truthorfables.com/", "http://truthorfables.com/")
    full = full.replace("https://truthorfables.com/", "http://truthorfables.com/")
    full = full.replace("http://www.truthorfables.com/", "http://truthorfables.com/")
    # fix bad double paths
    full = re.sub(r"http://truthorfables\.com/menu/(https?://)", r"\1", full)
    return full


def slugify(url: str, title: str) -> str:
    path = urlparse(url).path
    base = Path(unquote(path)).stem or "article"
    base = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("-").lower()
    if not base or base in {"index", "menu"}:
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "article"
    # short hash for uniqueness
    h = hashlib.md5(url.encode()).hexdigest()[:6]
    return f"{base}-{h}"


def is_css_junk(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t.count("{") >= 2 and ("font-" in t or "margin:" in t or "color:" in t):
        return True
    if t.startswith("form {") or "margin:0px" in t[:80]:
        return True
    return False


def download_image(src_url: str) -> str | None:
    """Download image; return relative path library/media/xxx or None."""
    if not src_url or src_url.startswith("data:"):
        return None
    src_url = normalize_tof_url(src_url, "http://truthorfables.com/")
    if "truthorfableslog" in src_url.lower() or "facebooklink" in src_url.lower():
        return None
    parsed = urlparse(src_url)
    name = Path(unquote(parsed.path)).name or "image.bin"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name)
    # unique by hash prefix
    h = hashlib.md5(src_url.encode()).hexdigest()[:8]
    stem, suf = Path(name).stem[:40], Path(name).suffix.lower() or ".jpg"
    if suf not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}:
        suf = ".jpg"
    out_name = f"{stem}-{h}{suf}"
    out_path = MEDIA / out_name
    if out_path.exists() and out_path.stat().st_size > 500:
        return f"media/{out_name}"
    data = fetch(src_url)
    if len(data) < 200:
        return None
    if data[:1] == b"<" or data[:15].lower().find(b"html") >= 0:
        return None
    out_path.write_bytes(data)
    return f"media/{out_name}"


def extract_article(url: str) -> dict:
    raw = fetch_text(url)
    if "Not Acceptable" in raw[:200] or len(raw) < 400:
        return {"ok": False, "error": "fetch_failed", "url": url}
    soup = BeautifulSoup(raw, "lxml")
    title_el = soup.find("title")
    title = title_el.get_text(strip=True) if title_el else "Article"
    # remove noise
    for t in soup(["script", "style", "noscript"]):
        t.decompose()

    # Collect content from meaningful leafy tags, preserving order
    body = soup.body or soup
    parts: list[str] = []
    seen_text = set()
    images_local: list[dict] = []

    # Prefer walking p/h/li/blockquote/td with real prose
    candidates = body.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"])
    # If very few, also scan divs with direct text
    if len(candidates) < 8:
        candidates = body.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "div", "td"])

    for el in candidates:
        # skip nested duplicates: if parent already a candidate block handled... use only if no block parent among candidates
        if el.name in {"div", "td"}:
            # only take div/td if it has direct substantial text and few children blocks
            if el.find(["p", "h1", "h2", "h3"]):
                continue
        text = el.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 25 and el.name not in {"h1", "h2", "h3"}:
            continue
        if is_css_junk(text):
            continue
        low = text.lower().strip(" |")
        if low in NAV_SKIP:
            continue
        if text.upper().startswith("HOME |") or "FORMER PASTORS/EMPLOYEES" in text:
            continue
        if text.startswith("AND THEY SHALL TURN AWAY THEIR EARS"):
            # keep verse once
            key = "verse-2tim"
            if key in seen_text:
                continue
            seen_text.add(key)
            parts.append(f'<p class="verse-banner">{htmlmod.escape(text)}</p>')
            continue
        # dedupe exact
        if text in seen_text:
            continue
        # skip near-duplicate huge parent dumps (>15k) if we already have many parts
        if len(text) > 12000 and len(parts) > 5:
            continue
        seen_text.add(text)

        # rebuild inline HTML with links/images inside element
        chunk = render_inline(el, url, images_local)
        if not chunk:
            continue
        tag = el.name if el.name in {"h1", "h2", "h3", "h4", "p", "li", "blockquote"} else "p"
        if tag == "li":
            parts.append(f"<li>{chunk}</li>")
        elif tag == "blockquote":
            parts.append(f"<blockquote>{chunk}</blockquote>")
        elif tag.startswith("h"):
            # demote h1
            htag = "h2" if tag == "h1" else tag
            parts.append(f"<{htag}>{chunk}</{htag}>")
        else:
            parts.append(f"<p>{chunk}</p>")

    # Images not captured inline
    for img in body.find_all("img"):
        src = img.get("src") or ""
        full = normalize_tof_url(src, url)
        if "truthorfableslog" in full.lower():
            continue
        local = download_image(full)
        if local and not any(x.get("local") == local for x in images_local):
            alt = img.get("alt") or ""
            images_local.append({"local": local, "alt": alt, "src": full})
            parts.append(
                f'<figure class="article-figure"><img src="{htmlmod.escape(local)}" alt="{htmlmod.escape(alt)}" loading="lazy" />'
                f"{f'<figcaption>{htmlmod.escape(alt)}</figcaption>' if alt else ''}</figure>"
            )

    # group consecutive li
    html_body = group_lists(parts)

    # Outbound links inventory
    links = []
    for a in body.find_all("a", href=True):
        href = normalize_tof_url(a["href"], url)
        text = a.get_text(" ", strip=True)
        if href and text and not href.startswith("#"):
            links.append({"text": text, "href": href})

    return {
        "ok": True,
        "url": url,
        "title": title,
        "html": html_body,
        "images": images_local,
        "links": links,
        "text_len": len(BeautifulSoup(html_body, "lxml").get_text()) if html_body else 0,
    }


def render_inline(el: Tag, base_url: str, images_local: list) -> str:
    bits: list[str] = []

    def walk(node):
        if isinstance(node, NavigableString):
            t = str(node)
            if t.strip():
                bits.append(htmlmod.escape(t))
            elif t:
                bits.append(" ")
            return
        if not isinstance(node, Tag):
            return
        name = node.name.lower()
        if name in {"script", "style"}:
            return
        if name == "br":
            bits.append("<br />")
            return
        if name == "img":
            src = normalize_tof_url(node.get("src") or "", base_url)
            local = download_image(src)
            alt = node.get("alt") or ""
            if local:
                images_local.append({"local": local, "alt": alt, "src": src})
                bits.append(
                    f'</p><figure class="article-figure"><img src="{htmlmod.escape(local)}" alt="{htmlmod.escape(alt)}" loading="lazy" /></figure><p>'
                )
            return
        if name == "a" and node.get("href"):
            href = normalize_tof_url(node["href"], base_url)
            label = node.get_text(" ", strip=True)
            if not label:
                return
            # external stay absolute; local rewrite later in second pass via map
            bits.append(
                f'<a href="{htmlmod.escape(href)}" data-orig="{htmlmod.escape(href)}">{htmlmod.escape(label)}</a>'
            )
            return
        if name in {"strong", "b"}:
            bits.append("<strong>")
            for ch in node.children:
                walk(ch)
            bits.append("</strong>")
            return
        if name in {"em", "i"}:
            bits.append("<em>")
            for ch in node.children:
                walk(ch)
            bits.append("</em>")
            return
        for ch in node.children:
            walk(ch)

    for ch in el.children:
        walk(ch)
    out = "".join(bits)
    out = re.sub(r"(?:<br\s*/?>\s*){3,}", "<br /><br />", out)
    out = re.sub(r"\s+</", "</", out)
    # clean empty p wrappers from figure injection
    out = out.replace("<p></p>", "").replace("<p> </p>", "")
    return out.strip()


def group_lists(parts: list[str]) -> str:
    out: list[str] = []
    buf: list[str] = []
    for p in parts:
        if p.startswith("<li>"):
            buf.append(p)
        else:
            if buf:
                out.append("<ul>" + "".join(buf) + "</ul>")
                buf = []
            out.append(p)
    if buf:
        out.append("<ul>" + "".join(buf) + "</ul>")
    return "\n".join(out)


ARTICLE_CSS = """
.article-wrap { width: min(760px, calc(100% - 2rem)); margin: 0 auto; padding: 2rem 0 4rem; }
.article-meta { color: var(--gold); font-size: 0.72rem; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 700; margin-bottom: 0.75rem; }
.article-wrap h1 {
  font-family: var(--font-display); font-weight: 500;
  font-size: clamp(2rem, 4.5vw, 3rem); line-height: 1.1; letter-spacing: -0.03em;
  margin: 0 0 1rem;
}
.article-source { color: var(--dim); font-size: 0.9rem; margin-bottom: 2rem; }
.article-source a { color: var(--muted); }
.article-body { font-size: 1.05rem; line-height: 1.75; color: var(--muted); }
.article-body h2, .article-body h3, .article-body h4 {
  font-family: var(--font-display); color: var(--text); font-weight: 500;
  letter-spacing: -0.02em; margin: 2rem 0 0.75rem; line-height: 1.15;
}
.article-body h2 { font-size: 1.75rem; }
.article-body h3 { font-size: 1.4rem; }
.article-body p { margin: 0 0 1rem; }
.article-body a { color: var(--gold-2); }
.article-body a:hover { color: #fff; }
.article-body ul { margin: 0 0 1.1rem; padding-left: 1.2rem; }
.article-body li { margin: 0.35rem 0; }
.article-body blockquote {
  margin: 1.25rem 0; padding: 1rem 1.15rem;
  border-left: 3px solid var(--gold);
  background: rgba(255,255,255,0.03);
  font-family: var(--font-display); font-style: italic;
  font-size: 1.2rem; color: var(--text);
}
.article-body strong { color: var(--text); }
.article-figure { margin: 1.5rem 0; border: 1px solid var(--line); background: #000; }
.article-figure img { width: 100%; height: auto; display: block; }
.article-figure figcaption {
  padding: 0.65rem 0.85rem; font-size: 0.82rem; color: var(--dim);
  border-top: 1px solid var(--line);
}
.verse-banner {
  font-family: var(--font-display); font-style: italic; color: var(--gold-2) !important;
  text-align: center; border: 1px solid var(--line); padding: 1rem; background: rgba(196,165,116,0.06);
}
.article-nav {
  display: flex; flex-wrap: wrap; gap: 0.75rem; justify-content: space-between;
  margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--line);
}
.related { margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid var(--line); }
.related h2 { font-family: var(--font-display); font-size: 1.5rem; font-weight: 500; margin: 0 0 1rem; color: var(--text); }
.empty-note {
  border: 1px solid var(--line); padding: 1.25rem; background: var(--panel); color: var(--muted);
}
"""


def page_shell(title: str, body: str, crumb: str = "Article") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{htmlmod.escape(title)} — Truth or Fables</title>
  <meta name="description" content="{htmlmod.escape(title[:160])}" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="../../assets/styles.css" />
  <style>{ARTICLE_CSS}</style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to main content</a>
  <div class="page-bar">
    <div class="wrap nav">
      <a class="brand" href="../../index.html">
        <img class="brand-mark" src="../../assets/logo.jpeg" alt="" width="38" height="38" />
        <span class="brand-text"><strong>Truth or Fables</strong><span>Article</span></span>
      </a>
      <button class="nav-toggle" type="button" id="navToggle" aria-label="Open menu">☰</button>
      <nav class="nav-links" id="navLinks">
        <a href="../../index.html">Home</a>
        <a href="../../subjects.html" aria-current="page">Subjects</a>
        <a href="../../books.html">Books</a>
        <a href="../../testimonies.html">Testimonies</a>
        <a class="cta" href="../../contact.html">Contact</a>
      </nav>
    </div>
  </div>
{body}
  <footer>
    <div class="wrap footer-bottom" style="border:0;margin:0;padding:2rem 0">
      <span><a href="../../index.html">Truth or Fables</a> · {htmlmod.escape(crumb)}</span>
      <span>Content © original authors / Life Assurance Ministries archive</span>
    </div>
  </footer>
  <script>document.getElementById("navToggle")?.addEventListener("click",()=>document.getElementById("navLinks").classList.toggle("open"));</script>
</body>
</html>"""


def main():
    cats = json.loads((LIB / "subjects.json").read_text())
    # unique articles with context
    by_url: dict[str, dict] = {}
    for c in cats:
        for s in c["sections"]:
            for a in s["articles"]:
                href = a["href"].replace("https://www.truthorfables.com/", "http://truthorfables.com/")
                href = href.replace("https://truthorfables.com/", "http://truthorfables.com/")
                href = href.replace("http://www.truthorfables.com/", "http://truthorfables.com/")
                if href not in by_url:
                    by_url[href] = {
                        "title": a["text"],
                        "href": href,
                        "cats": [],
                    }
                by_url[href]["cats"].append(
                    {"id": c["id"], "name": c["name"], "section": s["title"]}
                )

    urls = sorted(by_url.keys())
    print(f"Fetching {len(urls)} unique articles…")
    url_to_slug: dict[str, str] = {}
    results = []

    for i, url in enumerate(urls, 1):
        meta = by_url[url]
        slug = slugify(url, meta["title"])
        url_to_slug[url] = slug
        print(f"[{i}/{len(urls)}] {slug} <- {url[:70]}")
        try:
            data = extract_article(url)
        except Exception as e:
            data = {"ok": False, "error": str(e), "url": url}
        data["slug"] = slug
        data["nav_title"] = meta["title"]
        data["cats"] = meta["cats"]
        results.append(data)
        # polite pause every few
        if i % 5 == 0:
            time.sleep(0.4)

    # second pass: rewrite internal links in HTML to local pages
    def rewrite_html(h: str) -> str:
        def repl(m):
            orig = m.group(1)
            # data-orig preferred
            return m.group(0)

        # replace href="http://truthorfables.com/..." when mapped
        def href_repl(m):
            full = m.group(1)
            norm = normalize_tof_url(full, "http://truthorfables.com/")
            if norm in url_to_slug:
                return f'href="{url_to_slug[norm]}.html"'
            # pdfs and external stay
            return f'href="{htmlmod.escape(norm, quote=True)}" target="_blank" rel="noopener"'

        h = re.sub(r'href="([^"]+)"', href_repl, h)
        h = re.sub(r"\s*data-orig=\"[^\"]*\"", "", h)
        return h

    manifest = []
    for data in results:
        slug = data["slug"]
        title = data.get("title") or data.get("nav_title") or "Article"
        cat = data.get("cats", [{}])[0]
        cat_id = cat.get("id", 1)
        cat_name = cat.get("name", "Subjects")
        section = cat.get("section", "")

        if data.get("ok") and data.get("text_len", 0) > 80:
            body_html = rewrite_html(data.get("html") or "")
        else:
            err = data.get("error", "thin_content")
            body_html = (
                f'<div class="empty-note"><p>We could not fully extract this article automatically '
                f"({htmlmod.escape(str(err))}).</p>"
                f'<p><a class="btn btn-gold" href="{htmlmod.escape(data.get("url", "#"))}" target="_blank" rel="noopener">'
                f"Open original article ↗</a></p></div>"
            )

        # related: other articles in same category
        related = []
        for other in results:
            if other["slug"] == slug:
                continue
            ocats = {c.get("id") for c in other.get("cats", [])}
            if cat_id in ocats:
                related.append(other)
            if len(related) >= 6:
                break
        rel_html = ""
        if related:
            items = "".join(
                f'<li><a href="{htmlmod.escape(r["slug"])}.html">{htmlmod.escape(r.get("title") or r.get("nav_title") or r["slug"])}</a></li>'
                for r in related
            )
            rel_html = f'<div class="related"><h2>More in this collection</h2><ul>{items}</ul></div>'

        body = f"""
  <main id="main">
    <article class="article-wrap">
      <p class="article-meta"><a href="../{cat_id:02d}.html" style="color:inherit;text-decoration:none">{htmlmod.escape(cat_name)}</a>
      {(' · ' + htmlmod.escape(section)) if section else ''}</p>
      <h1>{htmlmod.escape(title)}</h1>
      <p class="article-source">Source: <a href="{htmlmod.escape(data.get('url') or '#')}" target="_blank" rel="noopener">{htmlmod.escape(data.get('url') or '')}</a></p>
      <div class="article-body">
{body_html}
      </div>
      {rel_html}
      <div class="article-nav">
        <a class="btn btn-outline" href="../{cat_id:02d}.html">← Back to category</a>
        <a class="btn btn-gold" href="../../subjects.html">All subjects</a>
      </div>
    </article>
  </main>"""
        (ART_DIR / f"{slug}.html").write_text(page_shell(title, body, title[:40]), encoding="utf-8")
        manifest.append(
            {
                "slug": slug,
                "title": title,
                "url": data.get("url"),
                "path": f"articles/{slug}.html",
                "ok": bool(data.get("ok") and data.get("text_len", 0) > 80),
                "text_len": data.get("text_len", 0),
                "images": len(data.get("images") or []),
                "cats": data.get("cats"),
            }
        )

    # rewrite category pages to local article links
    for c in cats:
        for s in c["sections"]:
            for a in s["articles"]:
                href = normalize_tof_url(a["href"], "http://truthorfables.com/")
                if href in url_to_slug:
                    a["local"] = f"articles/{url_to_slug[href]}.html"
                    a["slug"] = url_to_slug[href]
                else:
                    a["local"] = None
    (LIB / "subjects.json").write_text(json.dumps(cats, indent=2))
    (LIB / "articles-manifest.json").write_text(json.dumps(manifest, indent=2))
    (LIB / "url-to-slug.json").write_text(json.dumps(url_to_slug, indent=2))

    # regenerate category HTML with local links
    regenerate_categories(cats)

    ok = sum(1 for m in manifest if m["ok"])
    print(f"DONE pages={len(manifest)} ok={ok} media={len(list(MEDIA.glob('*')))}")


def regenerate_categories(cats):
    out = LIB

    def shell(title, body):
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{htmlmod.escape(title)} — Truth or Fables</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="../assets/styles.css" />
</head>
<body>
  <a class="skip-link" href="#main">Skip to main content</a>
  <div class="page-bar">
    <div class="wrap nav">
      <a class="brand" href="../index.html">
        <img class="brand-mark" src="../assets/logo.jpeg" alt="" width="38" height="38" />
        <span class="brand-text"><strong>Truth or Fables</strong><span>Library</span></span>
      </a>
      <button class="nav-toggle" type="button" id="navToggle" aria-label="Open menu">☰</button>
      <nav class="nav-links" id="navLinks">
        <a href="../index.html">Home</a>
        <a href="../subjects.html" aria-current="page">Subjects</a>
        <a href="../books.html">Books</a>
        <a href="../testimonies.html">Testimonies</a>
        <a class="cta" href="../contact.html">Contact</a>
      </nav>
    </div>
  </div>
{body}
  <footer>
    <div class="wrap footer-bottom" style="border:0;margin:0;padding:2rem 0">
      <span><a href="../index.html">Truth or Fables</a> · Library</span>
      <span>Local article pages</span>
    </div>
  </footer>
  <script>document.getElementById("navToggle")?.addEventListener("click",()=>document.getElementById("navLinks").classList.toggle("open"));</script>
</body>
</html>"""

    for c in cats:
        slug = f"{c['id']:02d}"
        sections_html = []
        count = sum(len(s["articles"]) for s in c["sections"])
        for s in c["sections"]:
            rows = []
            for i, a in enumerate(s["articles"], 1):
                local = a.get("local")
                href = local if local else a["href"]
                external = not local
                arrow = "→" if local else "↗"
                note = "Read on this site" if local else "Original archive"
                target = "" if local else ' target="_blank" rel="noopener"'
                rows.append(
                    f"""          <a class="list-row" href="{htmlmod.escape(href)}"{target}>
            <span class="n">{i:02d}</span>
            <span><h3>{htmlmod.escape(a['text'])}</h3><p>{note}</p></span>
            <span class="arrow">{arrow}</span>
          </a>"""
                )
            if not rows:
                rows = ["          <p class='section-copy'>No articles in this section.</p>"]
            sections_html.append(
                f"""
      <div class="wrap" style="margin-top:2rem">
        <h2 class="section-title" style="font-size:1.8rem;margin-bottom:0.35rem">{htmlmod.escape(s['title'])}</h2>
        <p class="section-copy" style="margin-bottom:1rem">{len(s['articles'])} articles</p>
        <div class="list-stack">
{chr(10).join(rows)}
        </div>
      </div>"""
            )
        body = f"""  <header class="page-hero">
    <div class="page-hero-bg" aria-hidden="true"><img src="../assets/old-books.jpg" alt="" /></div>
    <div class="wrap">
      <p class="section-label">Library · {c['id']:02d} / 10</p>
      <h1>{htmlmod.escape(c['name'])}</h1>
      <p>{count} articles — each opens as its own page on this site.</p>
    </div>
  </header>
  <main id="main">
    <section style="padding-top:1.5rem">
{''.join(sections_html)}
      <div class="wrap" style="margin-top:2.5rem;display:flex;flex-wrap:wrap;gap:0.75rem">
        <a class="btn btn-gold" href="../subjects.html">← All subjects</a>
      </div>
    </section>
  </main>"""
        (out / f"{slug}.html").write_text(shell(c["name"], body), encoding="utf-8")


if __name__ == "__main__":
    main()
