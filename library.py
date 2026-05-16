import hashlib
import json
import time
from pathlib import Path

import ebooklib
from ebooklib import epub

_STATE_PATH = Path.home() / '.local' / 'share' / 'canto' / 'library.json'
_COVERS_DIR = Path.home() / '.local' / 'share' / 'canto' / 'covers'


def _extract_epub_cover(epub_path: str) -> bytes | None:
    import os
    from bs4 import BeautifulSoup
    try:
        book = epub.read_epub(epub_path, options={'ignore_ncx': True})

        def _is_image(item) -> bool:
            mt = getattr(item, 'media_type', '') or ''
            return mt.startswith('image/')

        def _content(item) -> bytes | None:
            if item and _is_image(item):
                data = item.get_content()
                return data if data else None
            return None

        def _first_img_from_doc(doc_item) -> bytes | None:
            if doc_item is None:
                return None
            try:
                soup = BeautifulSoup(doc_item.get_content(), 'lxml')
                imgs = soup.find_all('img')
                if len(imgs) != 1:
                    return None
                src = imgs[0].get('src', '') or imgs[0].get('xlink:href', '')
                if not src:
                    return None
                doc_dir = os.path.dirname(doc_item.file_name)
                href = os.path.normpath(os.path.join(doc_dir, src)).replace('\\', '/')
                return _content(book.get_item_with_href(href))
            except Exception:
                return None

        def _all_images():
            return [i for i in book.get_items() if _is_image(i)]

        # 1. EPUB3: item with properties="cover-image"
        for item in _all_images():
            props = getattr(item, 'properties', '') or ''
            if isinstance(props, list):
                props = ' '.join(props)
            if 'cover-image' in props.split():
                return item.get_content()

        # 2. EPUB2: OPF <meta name="cover" content="item-id"/>
        meta_cover = book.get_metadata('OPF', 'cover')
        if meta_cover:
            ref = meta_cover[0][0] if isinstance(meta_cover[0], (list, tuple)) else meta_cover[0]
            data = _content(book.get_item_with_id(str(ref)))
            if data:
                return data

        # 3. Item ID exactly matches known cover names
        cover_ids = {'cover', 'cover-image', 'cover_image', 'coverimage', 'book-cover', 'img-cover', 'cover-img'}
        for item in _all_images():
            if item.id.lower() in cover_ids:
                return item.get_content()

        # 4. Image filename contains "cover"
        for item in _all_images():
            if 'cover' in item.file_name.lower():
                return item.get_content()

        # 5. OPF guide reference of type "cover"
        for ref in getattr(book, 'guide', []):
            if ref.get('type', '').lower() == 'cover':
                doc = book.get_item_with_href(ref.get('href', '').split('#')[0])
                data = _first_img_from_doc(doc)
                if data:
                    return data

        # 6. First two spine documents — only if document contains exactly one image
        for item_id, _ in list(book.spine)[:2]:
            data = _first_img_from_doc(book.get_item_with_id(item_id))
            if data:
                return data

    except Exception:
        pass
    return None


class Library:
    def __init__(self):
        self._state: dict = {'folders': [], 'books': {}}
        if _STATE_PATH.exists():
            try:
                self._state.update(json.loads(_STATE_PATH.read_text()))
            except Exception:
                pass

    def save(self):
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(self._state, indent=2))

    def add_folder(self, folder: str) -> list[str]:
        if folder not in self._state['folders']:
            self._state['folders'].append(folder)
        found: list[str] = []
        for ep in sorted(Path(folder).glob('**/*.epub')):
            key = str(ep)
            found.append(key)
            self._state['books'].setdefault(key, {'title': ep.stem, 'block': 0})
        self.save()
        return found

    def register_book(self, path: str, title: str, total: int):
        book = self._state['books'].setdefault(path, {})
        if title:
            book['title'] = title
        book.setdefault('title', Path(path).stem)
        book.setdefault('block', 0)
        book['total'] = total
        self.save()

    def get_progress(self, path: str) -> int:
        return self._state['books'].get(path, {}).get('block', 0)

    def set_progress(self, path: str, block: int):
        book = self._state['books'].setdefault(path, {'title': Path(path).stem})
        book['block'] = block
        book['last_read'] = time.time()
        self.save()

    def cover_path(self, path: str) -> Path | None:
        cp = self._state['books'].get(path, {}).get('cover')
        if cp and Path(cp).exists():
            return Path(cp)
        return None

    def cache_cover(self, path: str, data: bytes) -> Path:
        _COVERS_DIR.mkdir(parents=True, exist_ok=True)
        name = hashlib.md5(path.encode()).hexdigest() + '.jpg'
        cover_file = _COVERS_DIR / name
        cover_file.write_bytes(data)
        if path in self._state['books']:
            self._state['books'][path]['cover'] = str(cover_file)
            self.save()
        return cover_file

    @property
    def books(self) -> dict[str, dict]:
        return self._state['books']

    @property
    def folders(self) -> list[str]:
        return list(self._state['folders'])
