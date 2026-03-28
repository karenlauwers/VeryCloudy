
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import requests 
from html import unescape
from typing import List, Dict, Optional, Set

from verycloudy.config import FILEPATH_CLOUDS_CSV, FILEPATH_CLOUDS_JSON, FILEPATH_JSON_CHECKPOINT, FILEPATH_CSV_CHECKPOINT, BASE_URL, GALLERY, AJAX, FILEPATH_JSON_CHECKPOINT2, FILEPATH_CSV_CHECKPOINT2, FILEPATH_CLOUDS_APPEND_CSV, FILEPATH_CLOUDS_APPEND_JSON 


# ======================================================================================================
# Helpers: text & date utils
# ======================================================================================================
def _clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()

_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12
}

def _parse_date(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip()
    # ISO first
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        pass
    # Month DD, YYYY
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})", s)
    if m:
        month_name, day, year = m.groups()
        try:
            dt = datetime(int(year), _MONTHS[month_name], int(day))
            return dt.date().isoformat()
        except Exception:
            return ""
    return ""

# ======================================================================================================
# Helpers: to scrape the website again for new clouds - and load the ids already seen in the previous file
# ======================================================================================================
def load_seen_ids_from_csv(path: str) -> Set[str]:
    ids: Set[str] = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                lbid = str(row.get("lightbox_id", "")).strip()
                if lbid:
                    ids.add(lbid)
    except FileNotFoundError:
        return set()
    return ids

# ======================================================================================================
# Helpers: to save to files
# ======================================================================================================
# Write (append) new ids to jsonl and csv (used to append to the checkpoint-files, which are safety measures)
def append_jsonl(rows: List[Dict[str, str]], path: str):
    if not rows:
        return
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def append_csv(rows: List[Dict[str, str]], path: str):
    if not rows:
        return
    fieldnames = [
        "lightbox_id", "image_url", "date_iso", "date_raw",
        "author_name", "author_profile", "title", "tags"
    ]
    p = Path(path)
    file_exists = p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            w.writeheader()
        for r in rows:
            w.writerow(r)

# Write the final files and save (at the end of the crawl)
# Be aware: this writes a new csv, and overwrites if you use the same filepath!!! Dus als je dan save gebruikt, geeft het bestand dan een andere naam!  
def save_csv(rows: List[Dict[str, str]], path: str):
    if not rows:
        print("No data to save.")
        return
    fieldnames = [
        "lightbox_id", "image_url", "date_iso", "date_raw",
        "author_name", "author_profile", "title", "tags"
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Saved {len(rows)} rows to {path}")

def save_jsonl(rows: List[Dict[str, str]], path: str):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Saved {len(rows)} rows to {path}")


# ==================================================================================
# Create a http session and fetch content with AJAX API from Worldpress Gallery
# ==================================================================================

# Create a session and set server cookies 
def make_session(cookie_string: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    # Browser-like headers
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/143.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": BASE_URL,
        "Referer": GALLERY,
    })
    # Warm-up visit to set server cookies
    try:
        r = session.get(GALLERY, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"Warm-up GET failed: {e}")

    # If you captured a working Cookie header from DevTools/Postman, set it here
    if cookie_string:
        session.headers.update({"Cookie": cookie_string})

    return session

# Fetch ready-to-read html-fragment by sending POST-request to AJAX-endpoint
# Wat je hier doet: skip de browser UI (zoals bij Selenium) - gebruik makend van wat standaard is voor World Press dinges, waar je met een AJAX post de endpoint rechtstreeks aanspreekt.
def fetch_slideshow_page(
    session: requests.Session,
    offset: int,
    cats: str = "",
    photographer: str = "",
    timeout: int = 30,
) -> tuple[str, bool]:


    # Building the POST payload - what to ask for 
    data = {
        "action": "get_slideshow",
        "cats": cats,
        "offset": str(offset),
        "photographer": photographer
    }

    # POST to the AJAX endpoint with the POST payload created and get response
    resp = session.post(AJAX, data=data, timeout=timeout)

    # Receive and handle json in response

    try:
        j = resp.json()
        # als de response niet in json is: 
    except Exception:
        print(f"Non-JSON response at offset={offset}. Status={resp.status_code}")
        print(resp.text[:800])
        return "", False

    # Create two variables that will be returned and used later on in the actual reading of the content 
    # Je zal "more" gebruiken om later te kijken of je verder moet kijken (zijn er nog clouds in de gallery) en "content" is het html-fragment dat je gaat uilezen en bevat de uiteindelijke data die je nodig hebt om dataset te bouwen 
    content = ""
    more : Optional[bool] = None

    # Handle responses in different json-formats: World Press Gallery responses kunnen nogal eens van vorm verschillen
    # Json-format 1: ziet er als volgt uit: nested under data  {"success": true, "data": {"more": true, "content": "..."}}
    # Je wil uit de dict "data" de value voor de key "more" en de value van de key "content"
    if isinstance(j.get("data"), dict):
        content = j["data"].get("content") or ""
        more = bool(j["data"].get("more"))
    else:
        # Json-format 2: ziet er als volgt uit, 1 dict zonder een key data die op zichzelf ook een dict is, maar een platte dict: {"success": true, "content": "...", "more": true}
        content = j.get("content") or ""
        more = bool(j.get("more"))

        # Soms zit de html rechtstreeks in een string 
        # In dit geval heb je niks om "more" te bepalen - als dat zo is zetten we straks "more" op True en rekenen we op de rest van de logica om te stoppen als dat niet blijkt te kloppen 
        if not content and isinstance(j.get("data"), str):
            content = j["data"]

    if not content:
        print(f"Empty 'content' at offset={offset}. JSON keys={list(j.keys())}")
        # peek at payload for diagnostics
        print((json.dumps(j, ensure_ascii=False)[:800]))

        return "", more

    # Convert &lt; &gt; &amp; … into real tags/text
    content = unescape(content)
    
    if more is None:
        print(f"Warning: 'more' missing at offset={offset}; assuming more=True and relying on safety stops.")
        more = True

    return content, more

# ==================================================================================
# Read the information from the html-fragments fetched 
# ==================================================================================
def scrape_cloud_information_from_html(
    html: str, seen_ids: Optional[Set[str]] = None
) -> List[Dict[str, str]]:
    
    # To avoid duplicates - create a set for images/information already covered
    if seen_ids is None:
        seen_ids = set()

    # List where the information gathered will be stored 
    cloud_information: List[Dict[str, str]] = []

    # Create an instance of BeautifulSoup to scrape the html-fragments 
    soup = BeautifulSoup(html, "html.parser")

    # Set the selectors (discovered with Inspect)
    cloud_cards = soup.select("#cloudgallerywrapper .item, #cloudgallerywrapper .post3")
    if not cloud_cards:
        # It happens that there is no outer wrapper; fall back to inner classes
        cloud_cards = soup.select(".item, .post3")
    if not cloud_cards:
        # last resort 
        cloud_cards = soup.select("article, div.entry")

    raw_card_count = len(cloud_cards)  # how many cards the server returned on this page - will be used in the crawl-function, because I do not want to work with a fixed size of images/cloud_information per page - en dan moet ik weten hoeveel "kaarten" hij opgehaald heeft op een 'page'

    for card in cloud_cards:
        # Image url and id 
        image_url = ""
        raw_lightbox = "" # format f.ex = image648751

        a_card = card.select_one(".slideshowimagewrapper a[href]")
        if a_card:
            image_url = a_card.get("href") or ""
            raw_lightbox = a_card.get("data-lightbox") or ""
        else:
            img = card.select_one(".slideshowimagewrapper img")
            if img:
                image_url = img.get("src") or img.get("data-src") or ""

        lightbox_id = re.sub(r"\D+", "", raw_lightbox or "") or None

        if not lightbox_id:
            # if no raw_lightbox, lightbox_id will be None and will not be taken into account - ik wil alleen rijen met een zuivere index, ik ga er zelf geen maken 
            continue

        if lightbox_id in seen_ids:
            continue

        seen_ids.add(lightbox_id)

        # Meta-data
        date_iso = ""
        date_raw = ""
        author_name = ""
        author_profile = ""
        title = ""

        header = card.select_one(".slideshowcontentwrapper .entry-header")
        if header:
            entry_date_strong = header.select_one(".entry-date strong")
            if entry_date_strong:
                date_raw = _clean_text(entry_date_strong.get("datetime") or entry_date_strong.get_text())
                date_iso = _parse_date(date_raw)
            else:
                entry_date_div = header.select_one(".entry-date")
                if entry_date_div:
                    date_raw = _clean_text(entry_date_div.get_text())
                    date_iso = _parse_date(date_raw)

            a_author = header.select_one(".entry-author a[href]")
            if a_author:
                author_name = _clean_text(a_author.get_text())
                author_profile = a_author.get("href") or ""
            else:
                entry_author_div = header.select_one(".entry-author")
                if entry_author_div:
                    author_name = _clean_text(entry_author_div.get_text())

            title_el = header.select_one(".entry-title")
            if title_el:
                title = _clean_text(title_el.get_text())

        # Tags
        tags = []
        for t in card.select("footer.entry-footer .cloud-filter a"):
            txt = _clean_text(t.get_text())
            if txt:
                tags.append(txt)

        # put all information about 1 cloud_card together into a dict
        record = {
            "lightbox_id": lightbox_id,
            "image_url": image_url,
            "date_iso": date_iso,
            "date_raw": _clean_text(date_raw),
            "author_name": author_name,
            "author_profile": author_profile,
            "title": title,
            "tags": ", ".join(tags),
        }

        # append the record to the list cloud_information (basis voor de dataset)
        cloud_information.append(record)

    return cloud_information, raw_card_count

# ==================================================================================
# Scrape until pages are exhausted 
# ==================================================================================
def crawl_all_clouds(
    cats: str = "",
    photographer: str = "",
    sleep_sec: float = 0.8,
    max_pages: Optional[int] = None,
    cookie_string: Optional[str] = None,
    checkpoint_every: int = 25,
    seen_ids: Optional[Set[str]] = None,
    stop_when_all_seen_pages: int = 3,  # stop after 3 consecutive pages with 0 new IDs
) -> List[Dict[str, str]]:
    
    # Create a http session and set server cookies 
    session = make_session(cookie_string=cookie_string)

    all_rows: List[Dict[str, str]] = []

    if seen_ids is None:
        seen_ids = set()

    # page_size = 16  # optie: there are 16 images on a page on the website, but it is not needed to do it this way... and it is more robust to count the number of cards taken in the fetch (raw_card_count)

    # track how many pages in a row yielded 0 new IDs
    consecutive_all_seen = 0

    offset = 0 
    pages_done = 0
    last_ckpt_n = 0  # index in all_rows of last checkpoint

    while True:
        if max_pages is not None and pages_done >= max_pages:
            print(f"Stop: max_pages={max_pages} reached.")
            break

        html, more = fetch_slideshow_page(
            session=session,
            offset=offset,
            cats=cats,
            photographer=photographer
        )

        if not html.strip():
            print(f"Stop: empty 'content' at offset={offset}.")
            break

        before_count = len(seen_ids)
        rows, raw_card_count = scrape_cloud_information_from_html(html, seen_ids=seen_ids)
        after_count = len(seen_ids)
        new_count = after_count - before_count

        print(f"Offset {offset}: parsed {len(rows)} rows, new unique IDs={new_count}, more={more}")

        all_rows.extend(rows)

        # Checkpoint every N pages (e.g., 25)
        pages_done += 1


        # Adjust consecutive_all_seen voor already-seen-pages logic
        if new_count == 0:
            consecutive_all_seen += 1
        else:
            consecutive_all_seen = 0


        # Checkpoint (append only the delta since last checkpoint)
        if checkpoint_every and (pages_done % checkpoint_every == 0) and all_rows:
            print("Checkpoint: appending partial results...")
            delta = all_rows[last_ckpt_n:]
            append_jsonl(delta, FILEPATH_JSON_CHECKPOINT2)
            append_csv(delta, FILEPATH_CSV_CHECKPOINT2)
            last_ckpt_n = len(all_rows)

        # Stop conditions
        if not more:
            # Server says no more pages
            print(f"Stop: last page detected at offset={offset}.")
            break

        if raw_card_count == 0:
            print(f"Stop: server returned zero cards at offset={offset}.")
            break


        if stop_when_all_seen_pages and (consecutive_all_seen >= stop_when_all_seen_pages):
            print(f"Stop: encountered {consecutive_all_seen} consecutive pages with no new IDs.")
            break

        # --- Advance offset by what the server actually returned ---
        offset += raw_card_count

        time.sleep(sleep_sec)

    return all_rows


