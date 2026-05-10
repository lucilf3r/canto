import os
import re
from dataclasses import dataclass, field
from typing import Optional

import warnings

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)


@dataclass
class ContentBlock:
    type: str           # 'text' | 'image' | 'code' | 'table'
    content: str        # sentence text, image href, raw code text, or ''
    image_data: Optional[bytes] = None
    image_mime: str = ''
    table_rows: Optional[list[list[str]]] = None   # all rows (header first if present)
    table_has_header: bool = False


BLOCK_TAGS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li'}


class EpubParser:
    def __init__(self, filepath: str):
        self.book = epub.read_epub(filepath, options={'ignore_ncx': True})
        self.blocks: list[ContentBlock] = []
        self.chapters: list[tuple[str, int]] = []   # (title, first_block_idx)
        self._doc_start: dict[str, int] = {}        # file_name → block idx at parse time
        self._parse()
        self._build_chapters()

    def _parse(self):
        for item_id, _ in self.book.spine:
            item = self.book.get_item_with_id(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                self._doc_start[item.file_name] = len(self.blocks)
                self._parse_document(item)

    def _parse_document(self, item):
        soup = BeautifulSoup(item.get_content(), 'lxml')
        for tag in soup.find_all(['script', 'style']):
            tag.decompose()
        body = soup.find('body')
        if not body:
            return

        processed: set[int] = set()

        for element in body.find_all(True):
            eid = id(element)
            if eid in processed:
                continue

            if element.name == 'img':
                self._handle_image(element, item)
                processed.add(eid)

            elif element.name == 'table':
                rows, has_header = _parse_table(element)
                if rows:
                    self.blocks.append(ContentBlock(
                        type='table',
                        content='',
                        table_rows=rows,
                        table_has_header=has_header,
                    ))
                for child in element.find_all(True):
                    processed.add(id(child))
                processed.add(eid)

            elif element.name == 'pre':
                code = element.get_text()
                if code.strip():
                    self.blocks.append(ContentBlock(type='code', content=code))
                for child in element.find_all(True):
                    processed.add(id(child))
                processed.add(eid)

            elif element.name in BLOCK_TAGS:
                for img in element.find_all('img'):
                    self._handle_image(img, item)
                    processed.add(id(img))

                text = element.get_text(separator=' ', strip=True)
                for sentence in _split_sentences(text):
                    self.blocks.append(ContentBlock(type='text', content=sentence))

                for child in element.find_all(True):
                    processed.add(id(child))
                processed.add(eid)

    def _build_chapters(self):
        entries = self._flatten_toc(self.book.toc)
        seen_idx: set[int] = set()
        for title, href in entries:
            idx = self._resolve_href(href)
            if idx is not None and idx not in seen_idx:
                seen_idx.add(idx)
                self.chapters.append((title, idx))
        self.chapters.sort(key=lambda x: x[1])

    def _flatten_toc(self, items) -> list[tuple[str, str]]:
        result = []
        for item in items:
            if isinstance(item, tuple):
                section, children = item
                title = getattr(section, 'title', '') or ''
                href  = getattr(section, 'href',  '') or ''
                if title:
                    result.append((title, href))
                result.extend(self._flatten_toc(children))
            elif hasattr(item, 'href'):
                result.append((getattr(item, 'title', '') or 'Chapter', item.href or ''))
        return result

    def _resolve_href(self, href: str) -> Optional[int]:
        doc = href.split('#')[0].strip('/')
        basename = os.path.basename(doc)
        if doc in self._doc_start:
            return self._doc_start[doc]
        for stored, idx in self._doc_start.items():
            if stored == doc or os.path.basename(stored) == basename:
                return idx
        return None

    def _handle_image(self, img_tag: Tag, item):
        src = img_tag.get('src', '') or img_tag.get('xlink:href', '')
        if not src:
            return
        doc_dir = os.path.dirname(item.file_name)
        href = os.path.normpath(os.path.join(doc_dir, src)).replace('\\', '/')
        image_item = self.book.get_item_with_href(href)
        if image_item:
            self.blocks.append(ContentBlock(
                type='image',
                content=href,
                image_data=image_item.get_content(),
                image_mime=image_item.media_type or 'image/jpeg',
            ))


# ── Table & sentence helpers ──────────────────────────────────────────────────

def _parse_table(table_tag: Tag) -> tuple[list[list[str]], bool]:
    rows: list[list[str]] = []
    has_header = False
    for tr in table_tag.find_all('tr'):
        cells = tr.find_all(['th', 'td'])
        if cells:
            rows.append([c.get_text(' ', strip=True) for c in cells])
            if any(c.name == 'th' for c in cells):
                has_header = True
    return rows, has_header


MAX_CHUNK = 160


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?])\s+', text)
    result: list[str] = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= MAX_CHUNK:
            result.append(sent)
        else:
            clauses = re.split(r'(?<=[,;:—])\s+', sent)
            chunk = ''
            for clause in clauses:
                if not chunk:
                    chunk = clause
                elif len(chunk) + 1 + len(clause) <= MAX_CHUNK:
                    chunk += ' ' + clause
                else:
                    result.append(chunk.strip().rstrip(',;:—'))
                    chunk = clause
            if chunk:
                result.append(chunk.strip().rstrip(',;:—'))

    return [s for s in result if len(s) > 2]
