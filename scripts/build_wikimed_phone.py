#!/usr/bin/env python3
"""Render the phone editions from the catalog-pinned WikiMed ZIM."""
from __future__ import annotations

import argparse
from hashlib import file_digest, sha256
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

PIN = "6f67340a7cd7665bb57c27d2bbff97e26f2037477c9ea597345a118286820331"
LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"

# In volume order. Article paths and revisions are verified against the ZIM.
VOLUMES = {
    "emergencies": ("Emergencies and first aid", """
        First_aid Cardiopulmonary_resuscitation Choking Drowning
        Bleeding Shock_(circulatory) Burn Electrical_injury
        Carbon_monoxide_poisoning Heat_stroke Hypothermia Frostbite
        Anaphylaxis Seizure Stroke Myocardial_infarction
        Bone_fracture Concussion Snakebite Poisoning
        Chemical_eye_injury Spinal_cord_injury
    """),
    "illnesses": ("Common illnesses and symptoms", """
        Fever Dehydration Diarrhea Gastroenteritis Influenza Common_cold
        Pneumonia Asthma Acute_otitis_media Urinary_tract_infection
        Diabetes Hypoglycemia Headache Hypertension Anemia
        Constipation Abdominal_pain Strep_throat Toothache
        Cellulitis Malaria Dengue_fever Cholera
    """),
    "medicines": ("Medicines and fluids", """
        Oral_rehydration_therapy Paracetamol Ibuprofen Aspirin
        Amoxicillin Doxycycline Metronidazole Cetirizine
        Epinephrine_autoinjector Salbutamol Insulin Naloxone
        Antibiotic Antimicrobial_resistance Adverse_effect
    """),
    "family-health": ("Pregnancy, birth and child health", """
        Pregnancy Prenatal_care Childbirth Midwifery Umbilical_cord_prolapse
        Preeclampsia Ectopic_pregnancy Miscarriage Postpartum_bleeding
        Postpartum_infections Breastfeeding Mastitis
        Newborn_care Neonatal_jaundice Preterm_birth
        Febrile_seizure Croup Bronchiolitis Measles Rotavirus
    """),
}

BLOCKS = {"p", "h2", "h3", "h4", "h5", "h6", "li", "tr", "dt", "dd", "blockquote"}
VOID = set("area base br col embed hr img input link meta param source track wbr".split())
SKIP_TAGS = {"script", "style", "noscript", "figure", "audio", "video", "math"}
SKIP_CLASSES = {
    "infobox", "navbox", "sidebar", "mbox", "ambox", "mw-editsection", "noprint",
    "reflist", "refbegin", "reference", "hatnote", "shortdescription", "thumb",
    "mw-empty-elt", "metadata", "sistersitebox", "portal", "succession-box",
}
END_SECTIONS = {
    "see also", "notes", "references", "citations", "external links",
    "further reading", "bibliography", "sources",
}


class Article(HTMLParser):
    """Extract the prose and simple tables of the article, keeping inline links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.blocks = []
        self.pending = []
        self.kind = None
        self.revision = ""
        self.finished = False

    def flush(self):
        text = " ".join("".join(value for value, _ in self.pending).split())
        if text and self.kind:
            if self.kind == "h2" and text.casefold() in END_SECTIONS:
                self.finished = True
            elif not self.finished:
                self.blocks.append((self.kind, self.pending))
        self.pending = []
        self.kind = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        parent = self.stack[-1] if self.stack else ("", False, False, "", False)
        _, active, hidden, link, footer = parent
        active = active or "mw-parser-output" in classes
        footer = footer or "zim-footer" in classes
        hidden = (hidden or tag in SKIP_TAGS or bool(classes & SKIP_CLASSES)
                  or "mw-references-wrap" in classes or "hidden" in attrs
                  or "display:none" in attrs.get("style", "").replace(" ", "").lower())
        if tag == "a":
            link = attrs.get("href", "")
            if footer and link.startswith("https://en.wikipedia.org/") and "oldid=" in link:
                self.revision = link
        if tag not in VOID:
            self.stack.append((tag, active, hidden, link, footer))
        if not active or hidden or self.finished:
            return
        if tag in BLOCKS and not any(entry[0] == "tr" for entry in self.stack[:-1]):
            self.flush()
            self.kind = tag
        elif tag in {"td", "th", "br"} and self.pending:
            self.pending.append((" • " if tag != "br" else " ", ""))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                _, active, hidden, _, _ = self.stack[index]
                if active and not hidden and tag == self.kind:
                    self.flush()
                del self.stack[index:]
                return

    def handle_data(self, text):
        if self.kind and self.stack:
            _, active, hidden, link, _ = self.stack[-1]
            if active and not hidden and not self.finished:
                if self.pending and self.pending[-1][1] == link:
                    self.pending[-1] = (self.pending[-1][0] + text, link)
                else:
                    self.pending.append((text, link))


def articles(archive, paths):
    seen = set()
    for path in paths:
        entry = archive.get_entry_by_path(path)
        while entry.is_redirect:
            entry = entry.get_redirect_entry()
        if entry.path in seen:
            raise ValueError(f"Duplicate article after redirect: {path} → {entry.path}")
        seen.add(entry.path)
        parser = Article()
        parser.feed(bytes(entry.get_item().content).decode("utf-8"))
        parser.close()
        parser.flush()
        if not parser.blocks or not parser.revision:
            raise ValueError(f"Missing article text or source revision: {entry.path}")
        yield path, entry.path, entry.title, parser.blocks, parser.revision


def render(file, title, entries, font):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate

    pdfmetrics.registerFont(TTFont("WikiMed", font))
    body = ParagraphStyle("Body", fontName="WikiMed", fontSize=11, leading=15, spaceAfter=8)
    heading = ParagraphStyle("Heading", parent=body, fontSize=14, leading=18, spaceBefore=8,
                             textColor=colors.HexColor("#154E55"), keepWithNext=True)
    article_style = ParagraphStyle("Article", parent=heading, fontSize=19, leading=24)
    cover = ParagraphStyle("Cover", parent=article_style, fontSize=24, leading=29, spaceAfter=13)
    credit = ParagraphStyle("Credit", parent=body, fontSize=9, leading=13, spaceAfter=10)
    contents = ParagraphStyle("Contents", parent=body, fontSize=10, leading=13, spaceAfter=4)
    names = {path: f"article-{i}" for i, row in enumerate(entries) for path in row[:2]}
    article_headings = {}

    class Volume(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            if flowable in article_headings:
                destination, label = article_headings[flowable]
                self.canv.bookmarkPage(destination)
                self.canv.addOutlineEntry(label, destination)

    def footer(canvas, document):
        canvas.setFillColor(colors.HexColor("#465962"))
        canvas.setFont("WikiMed", 8)
        canvas.drawString(30, 21, f"WikiMed | {title}")
        canvas.drawRightString(390, 21, str(document.page))

    def linked(text, destination):
        return f'<link href="#{destination}" color="#155B72">{escape(text)}</link>'

    def inline(chunks, current):
        parts = []
        for text, raw in chunks:
            text = re.sub(r"\s+", " ", text)
            parsed = urlsplit(raw)
            path = unquote(parsed.path).removeprefix("./").removeprefix("/wiki/").replace(" ", "_")
            dest = names.get(path) if not parsed.netloc and not parsed.scheme else None
            parts.append(linked(text, dest) if dest and dest != current else escape(text))
        return "".join(parts).strip()

    story = [
        Paragraph("WikiMed", cover),
        Paragraph(escape(title), article_style),
        Paragraph("Wikipedia medical reference articles from the April 2026 WikiMed archive.", body),
        Paragraph("This is a text edition. Images, infoboxes, navigation and reference lists were omitted. "
                  "Use the source revision for complete citations and the article history.", credit),
        Paragraph("Contents", heading),
    ]
    for _, path, label, _, _ in entries:
        story.append(Paragraph(linked(label, names[path]), contents))
    for _, path, label, blocks, revision in entries:
        destination = names[path]
        story.append(PageBreak())
        headline = Paragraph(escape(label), article_style)
        article_headings[headline] = (destination, label)
        story.append(headline)
        story.append(Paragraph(
            f'Wikipedia contributors · <link href="{escape(revision, quote=True)}" color="#155B72">'
            f'Source revision</link> · <link href="{LICENSE}" color="#155B72">CC BY-SA 4.0</link> · '
            f'{linked("Volume contents", "contents")}', credit))
        for tag, chunks in blocks:
            markup = inline(chunks, destination)
            if not markup:
                continue
            if tag == "li":
                markup = "• " + markup
            style = heading if tag.startswith("h") else body
            story.append(Paragraph(markup, style))
    def first(canvas, document):
        canvas.bookmarkPage("contents")
        footer(canvas, document)

    Volume(str(file), pagesize=(420, 660), topMargin=32, bottomMargin=36,
           leftMargin=30, rightMargin=30, title=f"WikiMed: {title}",
           author="Wikipedia contributors; PDF adaptation, Offline Wandering Library",
           subject=f"CC BY-SA 4.0; April 2026; WikiMed SHA-256 {PIN}",
           invariant=1, pageCompression=1).build(story, onFirstPage=first, onLaterPages=footer)


def main():
    from libzim.reader import Archive
    import reportlab

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zim", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font", default=str(Path(reportlab.__file__).with_name("fonts") / "Vera.ttf"))
    args = parser.parse_args()
    with args.zim.open("rb") as source:
        if file_digest(source, "sha256").hexdigest() != PIN:
            parser.error("WikiMed ZIM differs from the April 2026 source pin")
    archive = Archive(args.zim)
    args.output.mkdir(parents=True, exist_ok=True)
    volumes = []
    for volume, (title, paths) in VOLUMES.items():
        entries = list(articles(archive, paths.split()))
        filename = f"wikimed-{volume}.pdf"
        path = args.output / filename
        render(path, title, entries, args.font)
        data = path.read_bytes()
        volumes.append({"file": filename, "title": title, "bytes": len(data),
                        "sha256": sha256(data).hexdigest(),
                        "articles": [{"path": article, "title": name, "revision": revision}
                                     for _, article, name, _, revision in entries]})
    manifest = {"source_sha256": PIN, "source_id": "wikimed_en", "volumes": volumes}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
