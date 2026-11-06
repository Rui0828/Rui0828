#!/usr/bin/env python3
"""Build the website-style GitHub profile.

A README cannot carry CSS, so every section is rendered as an SVG "component"
(light + dark variant) into assets/site/, and README.md is assembled from them.

Content lives in site.json; publications come from scripts/papers.py.
Run:  python3 scripts/build_site.py
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from html import escape as _esc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import papers as P  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "site"
SITE = json.loads((ROOT / "site.json").read_text())
PROFILE = SITE["profile"]
USER = PROFILE["github"]
RAW = f"https://raw.githubusercontent.com/{USER}/{USER}/main/assets/site"
W = 880
TODAY = dt.date.today()
SEEN_FILE = ROOT / "assets" / "seen.json"  # first time each paper appeared

SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

THEMES = {
    "light": dict(bg="#ffffff", surface="#f6f8fa", border="#d0d7de", text="#1f2328", muted="#59636e",
                  faint="#eaeef2", a1="#6366f1", a2="#ec4899", a3="#0891b2", chip_text="#ffffff"),
    "dark": dict(bg="#0d1117", surface="#151b23", border="#30363d", text="#f0f6fc", muted="#9198a1",
                 faint="#21262d", a1="#818cf8", a2="#f472b6", a3="#22d3ee", chip_text="#0d1117"),
}
KIND_COLOR = {"conference": "a1", "journal": "a2", "workshop": "a3", "unknown": "muted",
              "preprint": "muted", "repository": "muted"}


def esc(s) -> str:
    return _esc(str(s), quote=True)


# ---------------------------------------------------------------- text layout
def text_width(s: str, size: float, bold=False, mono=False) -> float:
    if mono:
        return len(s) * size * 0.61
    w = 0.0
    for ch in s:
        if ch in "il.,:;'|!·":
            w += 0.28
        elif ch in " ftjr()-[]":
            w += 0.34
        elif ch.isupper() or ch in "mwMW@":
            w += 0.70
        elif ord(ch) > 0x2E80:  # CJK
            w += 1.0
        else:
            w += 0.55
    return w * size * (1.06 if bold else 1.0)


def wrap(s: str, size: float, max_w: float, bold=False, max_lines=99) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        if text_width(trial, size, bold) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;") + "…"
    return lines


def svg(w: int, h: int, body: str, t: dict, extra_style="") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<style>text{{font-family:{SANS}}} .m{{font-family:{MONO}}}'
            f'@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}{extra_style}</style>'
            f'{body}</svg>')


def card(w, h, t, r=16, fill=None):
    return (f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="{r}" '
            f'fill="{fill or t["bg"]}" stroke="{t["border"]}"/>')


def grad(t, gid="g"):
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{t["a1"]}"/><stop offset=".55" stop-color="{t["a2"]}"/>'
            f'<stop offset="1" stop-color="{t["a3"]}"/></linearGradient>')


# ---------------------------------------------------------------- data
def http_get(url, binary=False):
    headers = {"User-Agent": "profile-site-builder"}
    if "api.github.com" in url and os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        data = r.read()
    return data if binary else json.loads(data.decode())


def avatar_data_uri() -> str:
    try:
        raw = http_get(f"https://github.com/{USER}.png?size=320", binary=True)
        mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(raw).decode()
    except Exception as e:
        print(f"  avatar failed: {e}", file=sys.stderr)
        return ""


def repos() -> list[dict]:
    out = []
    for item in SITE.get("projects", []):
        name, desc = (item, None) if isinstance(item, str) else (item["repo"], item.get("desc"))
        try:
            r = http_get(f"https://api.github.com/repos/{USER}/{name}")
            out.append(dict(name=r["name"], desc=desc or r.get("description") or "", lang=r.get("language") or "",
                            stars=r.get("stargazers_count", 0), url=r["html_url"]))
        except Exception as e:
            print(f"  repo {name} failed: {e}", file=sys.stderr)
    return out


LANG_COLOR = {"Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Lua": "#000080",
              "Shell": "#89e051", "Jupyter Notebook": "#DA5B0B", "Go": "#00ADD8", "Rust": "#dea584",
              "Dockerfile": "#384d54", "C++": "#f34b7d"}


def fmt_date(d: str) -> str:
    if not d:
        return ""
    y, m, _ = (d.split("-") + ["01", "01"])[:3]
    if d.endswith("-01-01"):
        return y
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(m) - 1] + " " + y


def short_name(title: str) -> str:
    head = title.split(":")[0].strip()
    return head if len(head) <= 24 else " ".join(head.split()[:4]) + "…"


def build_news(papers) -> list[tuple[str, str, str]]:
    """(sort_date, date_label, text) — custom entries + one entry per venue/year."""
    items = [(n["date"], fmt_date(n["date"]) if re.match(r"\d{4}-\d\d", n["date"]) else n["date"], n["text"])
             for n in SITE.get("news", [])]
    groups: dict[tuple, list] = {}
    for p in papers:
        if p.kind in ("conference", "journal", "workshop"):
            groups.setdefault((P.short_venue(p.venue), p.year), []).append(p)
    for (venue, year), ps in groups.items():
        date = max(p.date for p in ps)
        names = ", ".join(short_name(p.title) for p in ps)
        n = "a paper" if len(ps) == 1 else f"{len(ps)} papers"
        items.append((date, fmt_date(date), f"Published {n} at {venue} {year}: {names}"))
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:6]


def mark_new(papers) -> None:
    """p.is_new = first seen (or precise publication date) within `new_days`."""
    days = SITE.get("new_days", 90)
    first_run = not SEEN_FILE.exists()
    seen = {} if first_run else json.loads(SEEN_FILE.read_text())
    for p in papers:
        key = P.norm_title(p.title)
        if key not in seen:
            # first build: seed with the publication date so old papers aren't all "new"
            seen[key] = (p.date or f"{p.year}-01-01") if first_run else TODAY.isoformat()
        dates = [seen[key]] + ([p.date] if p.date and not p.date.endswith("-01-01") else [])
        latest = max(dt.date.fromisoformat(d) for d in dates)
        p.is_new = (TODAY - latest).days <= days
    SEEN_FILE.write_text(json.dumps(dict(sorted(seen.items())), indent=1, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- components
def c_hero(t, avatar) -> str:
    h = 340
    ax, ay, ar = W - 170, 170, 104
    lines = wrap(PROFILE["tagline"], 19, 520)
    status = PROFILE.get("status", "")
    sw = text_width(status, 13) + 44
    tag = "".join(f'<text x="48" y="{190 + i*28}" font-size="19" fill="{t["muted"]}">{esc(l)}</text>'
                  for i, l in enumerate(lines))
    sy = 190 + len(lines) * 28 + 22
    av = (f'<clipPath id="av"><circle cx="{ax}" cy="{ay}" r="{ar}"/></clipPath>'
          f'<image href="{avatar}" x="{ax-ar}" y="{ay-ar}" width="{ar*2}" height="{ar*2}" '
          f'preserveAspectRatio="xMidYMid slice" clip-path="url(#av)"/>') if avatar else \
        f'<circle cx="{ax}" cy="{ay}" r="{ar}" fill="{t["surface"]}"/>'
    body = f'''
<defs>{grad(t)}
  <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="40"/></filter>
  <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="{t["border"]}"/></pattern>
  <clipPath id="cardclip"><rect width="{W}" height="{h}" rx="20"/></clipPath>
</defs>
<g clip-path="url(#cardclip)">
  <rect width="{W}" height="{h}" fill="{t["bg"]}"/>
  <rect width="{W}" height="{h}" fill="url(#dots)" opacity=".7"/>
  <circle class="blob1" cx="{ax-40}" cy="{ay-40}" r="110" fill="{t["a1"]}" opacity=".35" filter="url(#blur)"/>
  <circle class="blob2" cx="{ax+60}" cy="{ay+60}" r="100" fill="{t["a2"]}" opacity=".3" filter="url(#blur)"/>
</g>
<rect x=".5" y=".5" width="{W-1}" height="{h-1}" rx="20" fill="none" stroke="{t["border"]}"/>
<text class="m" x="48" y="72" font-size="13" letter-spacing="2.5" fill="{t["a1"]}" font-weight="600">{esc(PROFILE["kicker"].upper())}</text>
<text x="45" y="140" font-size="62" font-weight="800" letter-spacing="-1.5" fill="url(#g)">{esc(PROFILE["name"])}</text>
{tag}
<g transform="translate(48 {sy})">
  <rect width="{sw}" height="32" rx="16" fill="{t["surface"]}" stroke="{t["border"]}"/>
  <circle cx="18" cy="16" r="9" fill="#2da44e" opacity=".25" class="ping"/>
  <circle cx="18" cy="16" r="4.5" fill="#2da44e"/>
  <text x="32" y="20.5" font-size="13" fill="{t["text"]}">{esc(status)}</text>
</g>
<g class="ring"><circle cx="{ax}" cy="{ay}" r="{ar+12}" fill="none" stroke="url(#g)" stroke-width="2.5" stroke-dasharray="6 10" stroke-linecap="round"/></g>
<circle cx="{ax}" cy="{ay}" r="{ar+3}" fill="{t["bg"]}"/>
{av}'''
    style = (f".ring{{transform-origin:{ax}px {ay}px;animation:spin 24s linear infinite}}"
             "@keyframes spin{to{transform:rotate(360deg)}}"
             ".ping{transform-origin:18px 16px;transform-box:fill-box;animation:ping 2s ease-out infinite}"
             "@keyframes ping{0%{transform:scale(.6);opacity:.6}100%{transform:scale(1.8);opacity:0}}"
             ".blob1{animation:drift 9s ease-in-out infinite alternate}"
             ".blob2{animation:drift 11s ease-in-out infinite alternate-reverse}"
             "@keyframes drift{to{transform:translate(-30px,20px)}}")
    return svg(W, h, body, t, style)


def c_pill(t, label, primary=False) -> tuple[str, int]:
    w = int(text_width(label, 14, bold=True) + 36)
    h = 38
    if primary:
        body = (f'<defs>{grad(t)}</defs><rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="19" fill="url(#g)"/>'
                f'<text x="{w/2}" y="24" font-size="14" font-weight="700" text-anchor="middle" fill="#fff">{esc(label)}</text>')
    else:
        body = (f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="19" fill="{t["bg"]}" stroke="{t["border"]}"/>'
                f'<text x="{w/2}" y="24" font-size="14" font-weight="600" text-anchor="middle" fill="{t["text"]}">{esc(label)}</text>')
    return svg(w, h, body, t), w


def c_button(t, label) -> str:
    w = int(text_width(label, 12, bold=True, mono=True) + 26)
    body = (f'<rect x=".5" y=".5" width="{w-1}" height="25" rx="7" fill="{t["surface"]}" stroke="{t["border"]}"/>'
            f'<text class="m" x="{w/2}" y="17" font-size="12" font-weight="600" text-anchor="middle" fill="{t["text"]}">{esc(label)}</text>')
    return svg(w, 26, body, t)


def c_section(t, num, title, meta="") -> str:
    h = 76
    tw = text_width(title, 30, bold=True)
    x2 = W - (text_width(meta, 13, mono=True) + 20 if meta else 0)
    body = (f'<defs>{grad(t)}</defs>'
            f'<text class="m" x="0" y="50" font-size="15" font-weight="700" fill="url(#g)">{num}</text>'
            f'<text x="38" y="52" font-size="30" font-weight="800" letter-spacing="-.5" fill="{t["text"]}">{esc(title)}</text>'
            f'<line x1="{38 + tw + 20}" y1="42" x2="{x2}" y2="42" stroke="{t["border"]}"/>'
            + (f'<text class="m" x="{W}" y="47" font-size="13" text-anchor="end" fill="{t["muted"]}">{esc(meta)}</text>'
               if meta else ""))
    return svg(W, h, body, t)


def c_about(t) -> str:
    bio = PROFILE["bio"]
    y0 = 34
    parts = [f'<text x="0" y="{y0 + i*28}" font-size="17" fill="{t["text"]}">{esc(l)}</text>' for i, l in enumerate(bio)]
    top = y0 + len(bio) * 28 + 12
    cols, gap = 2, 16
    tw_ = (W - gap) / cols
    th = 128
    for i, r in enumerate(SITE["research"]):
        x = (i % cols) * (tw_ + gap)
        y = top + (i // cols) * (th + gap)
        color = t[["a1", "a2", "a3", "a1"][i % 4]]
        lines = wrap(r["text"], 14, tw_ - 56, max_lines=2)
        parts.append(f'<g transform="translate({x} {y})">'
                     f'<rect x=".5" y=".5" width="{tw_-1}" height="{th-1}" rx="14" fill="{t["surface"]}" stroke="{t["border"]}"/>'
                     f'<rect x="24" y="26" width="28" height="4" rx="2" fill="{color}"/>'
                     f'<text class="m" x="{tw_-24}" y="34" font-size="12" text-anchor="end" fill="{t["muted"]}">0{i+1}</text>'
                     f'<text x="24" y="62" font-size="18" font-weight="700" fill="{t["text"]}">{esc(r["title"])}</text>'
                     + "".join(f'<text x="24" y="{88 + j*20}" font-size="14" fill="{t["muted"]}">{esc(l)}</text>'
                               for j, l in enumerate(lines)) + "</g>")
    rows = (len(SITE["research"]) + cols - 1) // cols
    h = int(top + rows * (th + gap))
    return svg(W, h, "".join(parts), t)


def c_news(t, items) -> str:
    row = 46
    h = 16 + len(items) * row + 8
    parts = [card(W, h, t, 16)]
    for i, (_, label, text) in enumerate(items):
        y = 16 + i * row
        if i:
            parts.append(f'<line x1="24" y1="{y}" x2="{W-24}" y2="{y}" stroke="{t["faint"]}"/>')
        text = wrap(text, 15, W - 200, max_lines=1)[0]
        parts.append(f'<circle cx="32" cy="{y+row/2}" r="4" fill="{t[["a1", "a2", "a3"][i % 3]]}"/>'
                     f'<text class="m" x="50" y="{y+row/2+5}" font-size="13" fill="{t["muted"]}">{esc(label)}</text>'
                     f'<text x="150" y="{y+row/2+5}" font-size="15" fill="{t["text"]}">{esc(text)}</text>')
    return svg(W, h, "".join(parts), t)


def c_paper(t, p) -> str:
    venue = P.short_venue(p.venue) or p.kind
    chip = f"{venue} {p.year}" if p.year else venue
    color = t[KIND_COLOR[p.kind]]
    title_lines = wrap(p.title, 18, W - 72, bold=True, max_lines=3)
    authors = list(p.authors)
    if len(authors) > P.CONFIG["max_authors"]:
        authors = authors[:P.CONFIG["max_authors"]] + ["et al."]
    # authors as tspans so the owner can be bold
    spans, line_w, author_lines = [], 0.0, [[]]
    for i, a in enumerate(authors):
        piece = a + (", " if i < len(authors) - 1 else "")
        wpx = text_width(piece, 13.5, bold=(i == p.self_idx))
        if line_w + wpx > W - 72 and author_lines[-1]:
            author_lines.append([])
            line_w = 0
        author_lines[-1].append((piece, i == p.self_idx))
        line_w += wpx
    author_lines = author_lines[:2]
    h = 74 + len(title_lines) * 25 + len(author_lines) * 20 + 18
    cw = text_width(chip, 12, bold=True, mono=True) + 20
    kind_label = {"conference": "Conference", "journal": "Journal", "workshop": "Workshop"}.get(p.kind, p.kind.title())
    parts = [card(W, h, t, 14),
             f'<rect x="0" y="16" width="4" height="{h-32}" rx="2" fill="{color}"/>',
             f'<rect x="32" y="22" width="{cw}" height="24" rx="6" fill="{color}"/>',
             f'<text class="m" x="{32+cw/2}" y="38.5" font-size="12" font-weight="700" text-anchor="middle" fill="{t["chip_text"]}">{esc(chip)}</text>',
             f'<text class="m" x="{32+cw+12}" y="38.5" font-size="12" fill="{t["muted"]}">{esc(kind_label)} · {esc(fmt_date(p.date))}</text>',
             *([f'<defs>{grad(t)}</defs><g transform="translate({W-82} 22)"><rect class="glow" width="50" height="24" rx="12" fill="url(#g)"/>'
                f'<text class="m" x="25" y="16.5" font-size="11.5" font-weight="800" letter-spacing="1" text-anchor="middle" fill="#fff">NEW</text></g>']
               if getattr(p, "is_new", False) else []),
             ]
    for i, l in enumerate(title_lines):
        parts.append(f'<text x="32" y="{78 + i*25}" font-size="18" font-weight="700" fill="{t["text"]}">{esc(l)}</text>')
    ay = 78 + len(title_lines) * 25 + 6
    for j, line in enumerate(author_lines):
        tsp = "".join(f'<tspan font-weight="{700 if me else 400}" fill="{t["text"] if me else t["muted"]}">{esc(s)}</tspan>'
                      for s, me in line)
        parts.append(f'<text x="32" y="{ay + j*20}" font-size="13.5">{tsp}</text>')
    style = (".glow{animation:glow 2.4s ease-in-out infinite}"
             "@keyframes glow{50%{opacity:.6}}") if getattr(p, "is_new", False) else ""
    return svg(W, h, "".join(parts), t, style)


def c_project(t, r, w=432, h=168) -> str:
    desc = wrap(r["desc"] or "No description yet.", 13.5, w - 48, max_lines=3)
    name = r["name"] if text_width(r["name"], 17, True) < w - 90 else r["name"][:30] + "…"
    parts = [card(w, h, t, 14),
             f'<g transform="translate(24 24)" fill="{t["muted"]}"><path d="M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z"/></g>',
             f'<text x="48" y="37" font-size="17" font-weight="700" fill="{t["a1"]}">{esc(name)}</text>',
             f'<text x="{w-24}" y="37" font-size="15" text-anchor="end" fill="{t["muted"]}">↗</text>']
    for i, l in enumerate(desc):
        parts.append(f'<text x="24" y="{70 + i*20}" font-size="13.5" fill="{t["muted"]}">{esc(l)}</text>')
    if r["lang"]:
        parts.append(f'<circle cx="30" cy="{h-26}" r="6" fill="{LANG_COLOR.get(r["lang"], t["muted"])}"/>'
                     f'<text x="44" y="{h-21.5}" font-size="13" fill="{t["muted"]}">{esc(r["lang"])}</text>')
    parts.append(f'<text x="{w-24}" y="{h-21.5}" font-size="13" text-anchor="end" fill="{t["muted"]}">★ {r["stars"]}</text>')
    return svg(w, h, "".join(parts), t)


def c_contact(t) -> str:
    h = 200
    email = next((l["url"][7:] for l in SITE["links"] if l["url"].startswith("mailto:")), "")
    body = (f'<defs>{grad(t)}<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
            f'<circle cx="2" cy="2" r="1.1" fill="{t["border"]}"/></pattern></defs>'
            + card(W, h, t, 20, t["surface"])
            + f'<rect x="1" y="1" width="{W-2}" height="{h-2}" rx="19" fill="url(#dots)" opacity=".6"/>'
            f'<text x="{W/2}" y="84" font-size="40" font-weight="800" letter-spacing="-1" text-anchor="middle" fill="url(#g)">{esc(SITE.get("contact", {}).get("title", "Get in touch"))}</text>'
            f'<text x="{W/2}" y="122" font-size="16" text-anchor="middle" fill="{t["muted"]}">{esc(SITE.get("contact", {}).get("text", ""))}</text>'
            f'<text class="m" x="{W/2}" y="160" font-size="15" text-anchor="middle" fill="{t["text"]}">{esc(email)}</text>')
    return svg(W, h, body, t)


# ---------------------------------------------------------------- assemble
def write(name: str, make) -> None:
    for mode, t in THEMES.items():
        (OUT / f"{name}-{mode}.svg").write_text(make(t))


def pic(name: str, alt: str, width: str | None = None) -> str:
    wattr = f' width="{width}"' if width else ""
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}/{name}-dark.svg" />'
            f'<img src="{RAW}/{name}-light.svg" alt="{esc(alt)}"{wattr} /></picture>')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.svg"):
        f.unlink()
    print("papers:", file=sys.stderr)
    papers = P.collect()
    if not papers:
        sys.exit("No papers fetched; refusing to build an empty site.")
    mark_new(papers)
    avatar = avatar_data_uri()
    projects = repos()
    news = build_news(papers)
    md = []

    # nav
    nav = [("about", "About"), ("news", "News"), ("publications", "Publications"),
           ("projects", "Projects"), ("contact", "Contact")]
    write("nav-home", lambda t: c_pill(t, PROFILE["name"], primary=True)[0])
    for anchor, label in nav:
        write(f"nav-{anchor}", lambda t, l=label: c_pill(t, l)[0])
    md.append('<p align="center">\n  <a href="#readme">' + pic("nav-home", PROFILE["name"]) + "</a>&nbsp;&nbsp;\n  "
              + "\n  ".join(f'<a href="#{a}">{pic(f"nav-{a}", l)}</a>' for a, l in nav) + "\n</p>\n")

    # hero
    write("hero", lambda t: c_hero(t, avatar))
    md.append(f'<p align="center">{pic("hero", PROFILE["name"] + " — " + PROFILE["kicker"], "100%")}</p>\n')

    def section(num, anchor, title, meta=""):
        write(f"sec-{anchor}", lambda t: c_section(t, num, title, meta))
        md.append(f'<a id="{anchor}"></a>\n\n{pic(f"sec-{anchor}", title, "100%")}\n')

    section("01", "about", "About")
    write("about", c_about)
    md.append(pic("about", "About: " + " ".join(PROFILE["bio"]), "100%") + "\n")

    section("02", "news", "News")
    write("news", lambda t: c_news(t, news))
    md.append(pic("news", "News: " + " / ".join(n[2] for n in news), "100%") + "\n")

    n_first = sum(1 for p in papers if p.self_idx == 0)
    n_new = sum(1 for p in papers if p.is_new)
    n_cite = sum(p.citations for p in papers)
    section("03", "publications", "Publications",
            f"{len(papers)} papers · {n_first} first-author · {n_cite} citations" + (f" · {n_new} new" if n_new else ""))
    for label in ("Paper ↗", "arXiv ↗", "Code ↗"):
        write("btn-" + label.split()[0].lower(), lambda t, l=label: c_button(t, l))
    for i, p in enumerate(papers):
        write(f"paper-{i}", lambda t, p=p: c_paper(t, p))
        link = p.url or p.arxiv or "#publications"
        btns = [(link, "paper")] + ([(p.arxiv, "arxiv")] if p.arxiv else []) + ([(p.code, "code")] if p.code else [])
        row = " ".join(f'<a href="{u}">{pic("btn-" + b, b)}</a>' for u, b in btns)
        md.append(f'<a href="{link}">{pic(f"paper-{i}", p.title, "100%")}</a>\n<p align="right">{row}</p>\n')
    md.append('<p align="right"><sub><i>Auto-synced daily from OpenAlex &amp; ORCID · '
              'conference / journal versions take priority over preprints.</i></sub></p>\n')

    if projects:
        section("04", "projects", "Projects")
        cells = []
        for r in projects:
            slug = "proj-" + re.sub(r"[^a-z0-9]+", "-", r["name"].lower())
            write(slug, lambda t, r=r: c_project(t, r))
            cells.append(f'<a href="{r["url"]}">{pic(slug, r["name"], "49%")}</a>')
        md.append('<p align="center">\n' + "\n".join(
            "  " + "&nbsp;".join(cells[i:i + 2]) + "<br/>" for i in range(0, len(cells), 2)) + "\n</p>\n")

    section("05", "activity", "Activity")
    md.append(f'<picture><source media="(prefers-color-scheme: dark)" '
              f'srcset="https://raw.githubusercontent.com/{USER}/{USER}/output/profile-night-rainbow.svg" />'
              f'<img src="https://raw.githubusercontent.com/{USER}/{USER}/output/profile-gitblock.svg" '
              f'alt="3D contribution graph" width="100%" /></picture>\n')

    section("06", "contact", "Contact")
    write("contact", c_contact)
    mail = next((l["url"] for l in SITE["links"] if l["url"].startswith("mailto:")), "#contact")
    md.append(f'<a href="{mail}">{pic("contact", "Contact")}</a>\n')
    link_md = []
    for l in SITE["links"]:
        slug = "link-" + re.sub(r"[^a-z0-9]+", "-", l["label"].lower())
        write(slug, lambda t, l=l: c_pill(t, l["label"])[0])
        link_md.append(f'<a href="{l["url"]}">{pic(slug, l["label"])}</a>')
    md.append('<p align="center">\n  ' + "\n  ".join(link_md) + "\n</p>\n")
    md.append(f'<p align="center"><sub>© {PROFILE["name"]} · this page is generated by '
              f'<a href="scripts/build_site.py">a script</a> and rebuilt daily by GitHub Actions</sub></p>\n')

    readme = "<!-- Generated by scripts/build_site.py from site.json — edit those, not this file. -->\n\n" + "\n".join(md)
    (ROOT / "README.md").write_text(readme)
    print(f"built README + {len(list(OUT.glob('*.svg')))} svgs", file=sys.stderr)


if __name__ == "__main__":
    main()
