#!/usr/bin/env python3
"""
Book cover picker - two-step GUI:
  1. Search OpenLibrary by title, show matching works (title + author)
  2. Click a work to browse its English edition covers, with "Next 10" paging
  3. Click a cover to download it

Usage:
  nix-shell -p "python3.withPackages(ps: [ps.requests ps.pillow ps.tkinter])" \
    --run "python3 pick_covers.py"

Pass --all to re-pick existing covers.
Pass --debug to print API responses to the terminal.
"""

import os
import sys
import re
import json
import tkinter as tk
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image, ImageTk

BOOKS_DIR = "content/books"
COVERS_DIR = "static/images/books"
SEARCH_URL = "https://openlibrary.org/search.json"
EDITIONS_URL = "https://openlibrary.org{}/editions.json"
COVER_URL_ID_M = "https://covers.openlibrary.org/b/id/{}-M.jpg"
COVER_URL_ID_L = "https://covers.openlibrary.org/b/id/{}-L.jpg"
COVER_URL_OLID_L = "https://covers.openlibrary.org/b/olid/{}-L.jpg"

DEBUG = False


def debug(msg):
    if DEBUG:
        print(f"  [DEBUG] {msg}")


def safe_filename(title):
    name = title.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def get_books():
    books = []
    for fname in sorted(os.listdir(BOOKS_DIR)):
        if fname.endswith(".md") and not fname.startswith("_"):
            books.append(fname[:-3])
    return books


def search_works(title):
    """Search OpenLibrary by title, return list of work dicts."""
    try:
        params = {
            "q": title,
            "limit": 15,
            "fields": "key,title,author_name,first_publish_year,edition_count",
        }
        debug(f"Search URL: {SEARCH_URL}")
        debug(f"Search params: {json.dumps(params)}")
        resp = requests.get(SEARCH_URL, params=params, timeout=10)
        debug(f"HTTP {resp.status_code}, Content-Length: {len(resp.content)}")
        data = resp.json()
        docs = data.get("docs", [])
        debug(f"numFound: {data.get('numFound', '?')}, returned: {len(docs)} docs")
        if DEBUG:
            for i, doc in enumerate(docs):
                t = doc.get("title", "?")
                a = ", ".join(doc.get("author_name", ["?"]))
                y = doc.get("first_publish_year", "?")
                ec = doc.get("edition_count", 0)
                debug(f"  [{i}] \"{t}\" by {a} ({y}) — {ec} editions")
        return docs
    except Exception as e:
        print(f"  Search error: {e}")
        return []


def fetch_english_editions_with_covers(work_key, offset=0, batch_size=50, want=10):
    """Page through a work's editions, return English ones that have covers.

    Returns (results, new_offset, exhausted) where results is a list of
    dicts with keys: olid, cover_id, title, languages.
    """
    url = EDITIONS_URL.format(work_key)
    results = []
    exhausted = False

    while len(results) < want:
        debug(f"Editions API: offset={offset}, batch={batch_size}")
        try:
            resp = requests.get(url, params={"limit": batch_size, "offset": offset}, timeout=15)
            data = resp.json()
            entries = data.get("entries", [])
            debug(f"  Got {len(entries)} entries (total: {data.get('size', '?')})")
        except Exception as e:
            debug(f"  Editions API error: {e}")
            exhausted = True
            break

        if not entries:
            exhausted = True
            break

        offset += len(entries)

        for e in entries:
            langs = [l.get("key", "").split("/")[-1] for l in e.get("languages", [])]
            covers = e.get("covers", [])
            # Accept English or unspecified language
            is_english = "eng" in langs or not langs
            has_cover = covers and any(c > 0 for c in covers)

            if is_english and has_cover:
                olid = e["key"].split("/")[-1]
                cover_id = next(c for c in covers if c > 0)
                results.append({
                    "olid": olid,
                    "cover_id": cover_id,
                    "title": e.get("title", "?"),
                    "languages": langs,
                })
                debug(f"  Found: {olid} cover={cover_id} lang={langs} title={e.get('title','?')}")
                if len(results) >= want:
                    break

    return results, offset, exhausted


def fetch_cover_by_id(cover_id):
    """Download a cover thumbnail by cover ID. Returns (cover_id, PIL.Image) or None."""
    try:
        url = COVER_URL_ID_M.format(cover_id)
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            debug(f"Cover id={cover_id}: HTTP {resp.status_code}")
            return None
        img = Image.open(BytesIO(resp.content))
        if img.size[0] < 5 or img.size[1] < 5:
            debug(f"Cover id={cover_id}: too small ({img.size})")
            return None
        debug(f"Cover id={cover_id}: OK ({img.size[0]}x{img.size[1]})")
        return (cover_id, img)
    except Exception as e:
        debug(f"Cover id={cover_id}: error {e}")
        return None


def fetch_cover_thumbnails(editions):
    """Fetch cover thumbnails for a list of edition dicts. Returns list of (edition, img)."""
    results = []
    cover_ids = [e["cover_id"] for e in editions]
    with ThreadPoolExecutor(max_workers=5) as pool:
        for edition, result in zip(editions, pool.map(fetch_cover_by_id, cover_ids)):
            if result is not None:
                results.append((edition, result[1]))
    return results


def download_full_cover(olid, cover_id, output_path):
    """Download the large version of a cover, trying cover ID first, then OLID."""
    urls = [
        COVER_URL_ID_L.format(cover_id),
        COVER_URL_OLID_L.format(olid),
    ]
    for url in urls:
        try:
            debug(f"Downloading: {url}")
            resp = requests.get(url, timeout=15)
            debug(f"HTTP {resp.status_code}, size: {len(resp.content)}")
            if resp.status_code == 200 and len(resp.content) > 500:
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                return True
        except Exception as e:
            print(f"  Download error: {e}")
    return False


# ---------------------------------------------------------------------------
# Step 1: Pick a work from search results
# ---------------------------------------------------------------------------

class WorkPicker:
    """Shows a list of works (title + author) from search results."""

    def __init__(self, search_title, works):
        self.selected_work = None
        self.skipped = False

        self.root = tk.Tk()
        self.root.title(f"Search results: {search_title}")
        self.root.configure(bg="#1a1a2e")
        self.root.geometry("700x600")

        header = tk.Frame(self.root, bg="#1a1a2e", pady=10, padx=15)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=f"Results for: {search_title}",
            font=("Helvetica", 16, "bold"),
            fg="#e0e0e0",
            bg="#1a1a2e",
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"{len(works)} works found. Click one to browse its covers.",
            font=("Helvetica", 11),
            fg="#888",
            bg="#1a1a2e",
        ).pack(anchor="w")

        container = tk.Frame(self.root, bg="#1a1a2e")
        container.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        canvas = tk.Canvas(container, bg="#1a1a2e", highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.list_frame = tk.Frame(canvas, bg="#1a1a2e")

        self.list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for i, work in enumerate(works):
            title = work.get("title", "Unknown")
            authors = ", ".join(work.get("author_name", ["Unknown"]))
            year = work.get("first_publish_year", "")
            editions = work.get("edition_count", 0)
            year_str = f" ({year})" if year else ""

            row = tk.Frame(self.list_frame, bg="#2a2a3e", padx=12, pady=8, cursor="hand2")
            row.pack(fill=tk.X, pady=2)

            tk.Label(
                row,
                text=f"{title}{year_str}",
                font=("Helvetica", 13, "bold"),
                fg="#e0e0e0",
                bg="#2a2a3e",
                anchor="w",
            ).pack(fill=tk.X)
            tk.Label(
                row,
                text=f"by {authors}  —  {editions} editions",
                font=("Helvetica", 10),
                fg="#aaa",
                bg="#2a2a3e",
                anchor="w",
            ).pack(fill=tk.X)

            for widget in [row] + row.winfo_children():
                widget.bind("<Button-1>", lambda e, w=work: self._select(w))

        bottom = tk.Frame(self.root, bg="#1a1a2e", pady=10)
        bottom.pack(fill=tk.X)
        tk.Button(
            bottom,
            text="Skip this book",
            command=self._skip,
            font=("Helvetica", 12),
            bg="#444",
            fg="white",
            activebackground="#666",
            padx=20,
            pady=5,
            cursor="hand2",
        ).pack()

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 700) // 2
        y = (self.root.winfo_screenheight() - 600) // 2
        self.root.geometry(f"700x600+{x}+{y}")

    def _select(self, work):
        self.selected_work = work
        self.root.destroy()

    def _skip(self):
        self.skipped = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.selected_work


# ---------------------------------------------------------------------------
# Step 2: Browse English edition covers with paging
# ---------------------------------------------------------------------------

class EditionBrowser:
    """Fetches English editions with covers from the editions API, shows them in a grid."""

    def __init__(self, work):
        self.work = work
        self.work_key = work.get("key", "")
        self.edition_count = work.get("edition_count", 0)
        self.editions_offset = 0
        self.selected = None  # will be {"olid": ..., "cover_id": ...}
        self.skipped = False

        title = work.get("title", "Unknown")
        authors = ", ".join(work.get("author_name", ["Unknown"]))

        self.root = tk.Tk()
        self.root.title(f"Covers: {title}")
        self.root.configure(bg="#1a1a2e")

        header = tk.Frame(self.root, bg="#1a1a2e", pady=10, padx=10)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=f"{title}",
            font=("Helvetica", 16, "bold"),
            fg="#e0e0e0",
            bg="#1a1a2e",
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"by {authors}  —  {self.edition_count} editions total",
            font=("Helvetica", 11),
            fg="#888",
            bg="#1a1a2e",
        ).pack(anchor="w")

        self.status_label = tk.Label(
            header,
            text="Loading English editions with covers...",
            font=("Helvetica", 10),
            fg="#666",
            bg="#1a1a2e",
        )
        self.status_label.pack(anchor="w", pady=(5, 0))

        self.grid_frame = tk.Frame(self.root, bg="#1a1a2e", padx=10, pady=5)
        self.grid_frame.pack(fill=tk.BOTH, expand=True)

        bottom = tk.Frame(self.root, bg="#1a1a2e", pady=10)
        bottom.pack(fill=tk.X)

        btn_row = tk.Frame(bottom, bg="#1a1a2e")
        btn_row.pack()

        tk.Button(
            btn_row,
            text="Skip this book",
            command=self._skip,
            font=("Helvetica", 12),
            bg="#444",
            fg="white",
            activebackground="#666",
            padx=20,
            pady=5,
            cursor="hand2",
        ).pack(side="left", padx=10)

        self.next_btn = tk.Button(
            btn_row,
            text="Next 10 >>",
            command=self._load_next,
            font=("Helvetica", 12),
            bg="#336",
            fg="white",
            activebackground="#558",
            padx=20,
            pady=5,
            cursor="hand2",
        )
        self.next_btn.pack(side="left", padx=10)

        self.tk_images = []

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 900) // 2
        y = (self.root.winfo_screenheight() - 700) // 2
        self.root.geometry(f"900x700+{x}+{y}")

        self.root.after(100, self._load_next)

    def _load_next(self):
        """Fetch the next batch of English edition covers."""
        self.next_btn.config(state=tk.DISABLED)
        self.status_label.config(
            text=f"Scanning editions from offset {self.editions_offset} for English covers..."
        )
        self.root.update()

        editions, new_offset, exhausted = fetch_english_editions_with_covers(
            self.work_key, offset=self.editions_offset, batch_size=50, want=10
        )
        self.editions_offset = new_offset

        # Clear grid
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.tk_images.clear()

        if not editions:
            self.status_label.config(
                text=f"No English covers found in this batch. Scanned {self.editions_offset}/{self.edition_count} editions."
            )
            if not exhausted:
                self.next_btn.config(state=tk.NORMAL)
            else:
                self.next_btn.config(state=tk.DISABLED)
            return

        # Fetch thumbnails
        self.status_label.config(text=f"Fetching {len(editions)} cover thumbnails...")
        self.root.update()
        covers = fetch_cover_thumbnails(editions)

        if not covers:
            self.status_label.config(
                text=f"Covers failed to load. Scanned {self.editions_offset}/{self.edition_count} editions."
            )
            if not exhausted:
                self.next_btn.config(state=tk.NORMAL)
            return

        self.status_label.config(
            text=f"Showing {len(covers)} English edition covers (scanned {self.editions_offset}/{self.edition_count} editions)"
        )

        cols = 5
        thumb_h = 250
        for i, (edition, img) in enumerate(covers):
            ratio = thumb_h / img.height
            thumb = img.resize((int(img.width * ratio), thumb_h), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(thumb)
            self.tk_images.append(tk_img)

            frame = tk.Frame(self.grid_frame, bg="#1a1a2e", padx=4, pady=4)
            frame.grid(row=i // cols, column=i % cols, sticky="n")
            tk.Button(
                frame,
                image=tk_img,
                command=lambda ed=edition: self._select(ed),
                bd=2,
                relief=tk.FLAT,
                bg="#2a2a3e",
                activebackground="#4a4a6e",
                cursor="hand2",
            ).pack()
            label_text = edition["olid"]
            if edition.get("title"):
                label_text = f"{edition['title'][:30]}\n{edition['olid']}"
            tk.Label(
                frame, text=label_text, fg="#666", bg="#1a1a2e",
                font=("Helvetica", 8), justify=tk.CENTER,
            ).pack()

        if not exhausted:
            self.next_btn.config(state=tk.NORMAL)
        else:
            self.next_btn.config(state=tk.DISABLED)

    def _select(self, edition):
        self.selected = edition
        self.root.destroy()

    def _skip(self):
        self.skipped = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.selected


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def process_book(title, reprocess=False):
    safe = safe_filename(title)
    output_path = os.path.join(COVERS_DIR, f"{safe}.jpg")

    if not reprocess and os.path.exists(output_path):
        print(f"SKIP (exists): {title}")
        return

    print(f"\nSearching: {title}...")
    works = search_works(title)

    if not works:
        print("  No results found on OpenLibrary")
        return

    print(f"  Found {len(works)} works, showing picker...")
    picker = WorkPicker(title, works)
    work = picker.run()

    if picker.skipped or work is None:
        print("  Skipped (no work selected)")
        return

    work_title = work.get("title", "Unknown")
    edition_count = work.get("edition_count", 0)
    print(f"  Selected: {work_title} ({edition_count} editions)")
    print(f"  Browsing English edition covers...")

    browser = EditionBrowser(work)
    selected = browser.run()

    if browser.skipped or selected is None:
        print("  Skipped (no cover selected)")
        return

    olid = selected["olid"]
    cover_id = selected["cover_id"]
    print(f"  Downloading full-size cover (OLID: {olid}, cover_id: {cover_id})...")
    os.makedirs(COVERS_DIR, exist_ok=True)
    if download_full_cover(olid, cover_id, output_path):
        print(f"  Saved: {output_path} ({os.path.getsize(output_path):,}B)")
    else:
        print("  Failed to download full-size cover")


def main():
    global DEBUG
    DEBUG = "--debug" in sys.argv
    reprocess = "--all" in sys.argv
    books = get_books()
    print(f"Found {len(books)} books in {BOOKS_DIR}/")
    if DEBUG:
        print("Debug mode ON — API responses will be printed to terminal.")
    if not reprocess:
        print("(Skipping books with existing covers. Use --all to re-pick.)")

    os.makedirs(COVERS_DIR, exist_ok=True)
    for title in books:
        process_book(title, reprocess=reprocess)
    print("\nAll done!")


if __name__ == "__main__":
    main()
