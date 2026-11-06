#!/usr/bin/env python3
"""Sync the publication list in README.md from OpenAlex + ORCID.

Sources
  * OpenAlex  works linked to the ORCID (venue versions *and* arXiv preprints)
  * ORCID     public works list (catches anything OpenAlex has not indexed yet)
  * config    manual "extra" entries in scripts/papers.config.json

Dedup
  Records are clustered when any of these hold:
    - same DOI
    - normalized titles are near-identical (>= 0.90 similarity)
    - abstracts overlap strongly AND author lists overlap
      (catches a preprint whose title changed for the camera-ready)
  From each cluster the best version is kept:
    journal / conference / workshop  >  unknown  >  preprint (arXiv)  >  repository (Zenodo, ...)
  The arXiv link of a dropped preprint is kept as an extra link on the entry.

Only the standard library is used, so the GitHub Action needs no pip install.
Run:  python3 scripts/update_papers.py [--dry-run]
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CONFIG = json.loads((ROOT / "scripts" / "papers.config.json").read_text())
START, END = "<!--START_SECTION:papers-->", "<!--END_SECTION:papers-->"
UA = "Rui0828-profile-papers/1.0 (+https://github.com/Rui0828/Rui0828)"

RANK = {"journal": 4, "conference": 4, "workshop": 4, "unknown": 2, "preprint": 1, "repository": 0}
BADGE_COLOR = {"journal": "9D00FF", "conference": "FF3366", "workshop": "00B4D8", "unknown": "555555",
               "preprint": "6E7681", "repository": "6E7681"}


# ---------------------------------------------------------------- helpers
def get_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def norm_name(n: str) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower())


def norm_doi(d: str | None) -> str | None:
    if not d:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", d.strip(), flags=re.I).lower()


def words(text: str) -> set[str]:
    return {w for w in norm_title(text).split() if len(w) > 3}


def surname_set(authors: list[str]) -> set[str]:
    return {norm_name(a.split()[-1]) for a in authors if a.strip()}


SELF = {norm_name(n) for n in CONFIG["self_names"]}


def is_self(name: str, orcid: str | None = None) -> bool:
    if orcid and orcid.rstrip("/").endswith(CONFIG["orcid"]):
        return True
    return norm_name(name) in SELF


def classify(venue: str, source_type: str | None, work_type: str | None, doi: str | None) -> str:
    v = (venue or "").lower()
    if (doi or "").startswith("10.48550/") or "arxiv" in v or work_type == "preprint":
        return "preprint"
    if (doi or "").startswith("10.5281/") or "zenodo" in v or source_type == "repository":
        return "repository"
    if "workshop" in v:
        return "workshop"
    if source_type == "journal" or work_type in ("journal-article",):
        return "journal"
    if source_type == "conference" or work_type in ("conference-paper",):
        return "conference"
    return "unknown"


def short_venue(venue: str) -> str:
    if not venue:
        return ""
    for full, short in sorted(CONFIG["venue_aliases"].items(), key=lambda kv: -len(kv[0])):
        if full.lower() in venue.lower():
            return short
    m = re.search(r"\(([^()]{2,25})\)\s*$", venue)
    return m.group(1) if m else venue


# ---------------------------------------------------------------- records
@dataclass
class Paper:
    title: str
    year: int | None
    venue: str
    kind: str
    doi: str | None = None
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    self_idx: int | None = None
    abstract: str = ""
    citations: int = 0
    source: str = ""
    arxiv: str | None = None
    code: str | None = None

    @property
    def score(self):
        publisher_doi = bool(self.doi) and not self.doi.startswith(("10.48550/", "10.5281/"))
        return (RANK[self.kind], publisher_doi, bool(self.venue), self.year or 0)


def from_openalex() -> list[Paper]:
    params = {"filter": f"author.orcid:{CONFIG['orcid']}", "per-page": "200",
              "select": "title,doi,publication_year,type,primary_location,authorships,"
                        "abstract_inverted_index,cited_by_count,ids"}
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    data = get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
    out = []
    for w in data.get("results", []):
        if w.get("type") in ("paratext", "erratum", "retraction") or not w.get("title"):
            continue
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        venue = src.get("display_name") or ""
        doi = norm_doi(w.get("doi"))
        authors, self_idx = [], None
        for i, a in enumerate(w.get("authorships") or []):
            name = (a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
            if name.count(",") == 1:  # "Liao, You-Cheng" -> "You-Cheng Liao"
                last, first = (x.strip() for x in name.split(","))
                name = f"{first} {last}"
            if is_self(name, (a.get("author") or {}).get("orcid")):
                self_idx, name = i, CONFIG["self_names"][0]
            authors.append(name)
        inv = w.get("abstract_inverted_index") or {}
        abstract = " ".join(k for k, _ in sorted(((k, p) for k, ps in inv.items() for p in ps), key=lambda x: x[1]))
        out.append(Paper(
            title=w["title"].strip(), year=w.get("publication_year"), venue=venue,
            kind=classify(venue, src.get("type"), w.get("type"), doi), doi=doi,
            url=f"https://doi.org/{doi}" if doi else loc.get("landing_page_url"),
            authors=authors, self_idx=self_idx, abstract=abstract,
            citations=w.get("cited_by_count") or 0, source="openalex"))
    return out


def from_orcid() -> list[Paper]:
    data = get_json(f"https://pub.orcid.org/v3.0/{CONFIG['orcid']}/works")
    out = []
    for g in data.get("group", []):
        s = g["work-summary"][0]
        title = ((s.get("title") or {}).get("title") or {}).get("value")
        if not title:
            continue
        doi = next((norm_doi(e["external-id-value"]) for e in (s.get("external-ids") or {}).get("external-id", [])
                    if e.get("external-id-type") == "doi"), None)
        venue = (s.get("journal-title") or {}).get("value") or ""
        year = ((s.get("publication-date") or {}).get("year") or {}).get("value")
        out.append(Paper(
            title=title.strip(), year=int(year) if year else None, venue=venue,
            kind=classify(venue, None, s.get("type"), doi), doi=doi,
            url=f"https://doi.org/{doi}" if doi else (s.get("url") or {}).get("value"),
            source="orcid"))
    return out


def from_config() -> list[Paper]:
    out = []
    for e in CONFIG.get("extra", []):
        authors = e.get("authors", [])
        idx = next((i for i, a in enumerate(authors) if is_self(a)), None)
        doi = norm_doi(e.get("doi"))
        out.append(Paper(title=e["title"], year=e.get("year"), venue=e.get("venue", ""),
                         kind=e.get("kind") or classify(e.get("venue", ""), None, None, doi), doi=doi,
                         url=e.get("url") or (f"https://doi.org/{doi}" if doi else None), authors=authors,
                         self_idx=idx, source="config", code=e.get("code")))
    return out


# ---------------------------------------------------------------- dedup
def same_paper(a: Paper, b: Paper) -> bool:
    if a.doi and a.doi == b.doi:
        return True
    ta, tb = norm_title(a.title), norm_title(b.title)
    if ta == tb or difflib.SequenceMatcher(None, ta, tb).ratio() >= 0.90:
        return True
    # Title changed between preprint and camera-ready: compare content + people.
    wa, wb = words(a.abstract), words(b.abstract)
    if len(wa) >= 30 and len(wb) >= 30 and len(wa & wb) / len(wa | wb) >= 0.6:
        sa, sb = surname_set(a.authors), surname_set(b.authors)
        if sa and sb and len(sa & sb) / min(len(sa), len(sb)) >= 0.5:
            return True
    return False


def dedup(papers: list[Paper]) -> list[Paper]:
    clusters: list[list[Paper]] = []
    for p in papers:
        hits = [c for c in clusters if any(same_paper(p, q) for q in c)]
        merged = [p] + [q for c in hits for q in c]
        clusters = [c for c in clusters if all(c is not h for h in hits)] + [merged]

    result = []
    for c in clusters:
        best = max(c, key=lambda p: p.score)
        # Borrow missing details from the other copies.
        richest = max(c, key=lambda p: len(p.authors))
        if not best.authors:
            best.authors, best.self_idx = richest.authors, richest.self_idx
        best.citations = max(p.citations for p in c)
        best.code = next((p.code for p in c if p.code), None)
        if best.kind != "preprint":
            arx = next((p for p in c if p.kind == "preprint" and p.doi and p.doi.startswith("10.48550/")), None)
            if arx:
                best.arxiv = "https://arxiv.org/abs/" + arx.doi.split("arxiv.", 1)[-1]
        result.append(best)
    return result


# ---------------------------------------------------------------- render
def esc(s: str) -> str:
    return urllib.parse.quote(s.replace("-", "--").replace("_", "__"), safe="")


def render(papers: list[Paper]) -> str:
    papers.sort(key=lambda p: (-(p.year or 0), -RANK[p.kind], p.title.lower()))
    n_first = sum(1 for p in papers if p.self_idx == 0)
    n_cite = sum(p.citations for p in papers)
    lines = [
        '<p align="center">',
        f'  <img src="https://img.shields.io/badge/papers-{len(papers)}-FF3366?style=for-the-badge&labelColor=0d1117" />',
        f'  <img src="https://img.shields.io/badge/first--author-{n_first}-00D9FF?style=for-the-badge&labelColor=0d1117" />',
        f'  <img src="https://img.shields.io/badge/citations-{n_cite}-9D00FF?style=for-the-badge&labelColor=0d1117" />',
        "</p>", "",
    ]
    year = None
    for p in papers:
        if p.year != year:
            year = p.year
            lines += ["", f"#### `{year or 'n.d.'}`", ""]
        venue = short_venue(p.venue) or p.kind
        tag = venue if not p.year else f"{venue} {p.year}"
        badge = (f'<img src="https://img.shields.io/badge/{esc(tag)}-{BADGE_COLOR[p.kind]}'
                 f'?style=flat-square" alt="{tag}" />')
        title = f"[{p.title}]({p.url})" if p.url else p.title
        authors = list(p.authors)
        if p.self_idx is not None and p.self_idx < len(authors):
            authors[p.self_idx] = f"<b>{authors[p.self_idx]}</b>"
        if len(authors) > CONFIG["max_authors"]:
            authors = authors[:CONFIG["max_authors"]] + ["et al."]
        links = [f"[arXiv]({p.arxiv})"] if p.arxiv else []
        if p.code:
            links.append(f"[Code]({p.code})")
        meta = ", ".join(authors)
        if links:
            meta += (" &nbsp;·&nbsp; " if meta else "") + " · ".join(links)
        lines.append(f"- {badge} **{title}**" + (f"  \n  <sub>{meta}</sub>" if meta else ""))
    lines += ["", '<sub><i>Auto-synced from <a href="https://openalex.org">OpenAlex</a> &amp; '
                  f'<a href="https://orcid.org/{CONFIG["orcid"]}">ORCID</a> by GitHub Actions · '
                  'conference / journal versions take priority over preprints.</i></sub>']
    return "\n".join(lines)


def main():
    dry = "--dry-run" in sys.argv
    papers: list[Paper] = []
    for fetch in (from_openalex, from_orcid, from_config):
        try:
            got = fetch()
            print(f"{fetch.__name__}: {len(got)} records", file=sys.stderr)
            papers += got
        except Exception as e:  # one source down should not wipe the list
            print(f"{fetch.__name__} failed: {e}", file=sys.stderr)
    if not papers:
        sys.exit("No papers fetched from any source; leaving README untouched.")

    excluded = {norm_title(t) for t in CONFIG.get("exclude_titles", [])}
    papers = [p for p in papers if norm_title(p.title) not in excluded]
    final = dedup(papers)
    print(f"after dedup: {len(final)} papers", file=sys.stderr)
    block = render(final)

    if dry:
        print(block)
        return
    text = README.read_text()
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: f"{START}\n{block}\n{END}", text, flags=re.S)
    if new == text:
        print("README already up to date.", file=sys.stderr)
    else:
        README.write_text(new)
        print("README updated.", file=sys.stderr)


if __name__ == "__main__":
    main()
