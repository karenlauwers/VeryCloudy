## https://cloudappreciationsociety.org/gallery/

import time
import random 
import re 
from datetime import datetime
import pandas as pd

from typing import List, Dict, Any, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, InvalidSessionIdException, WebDriverException

def setup_driver(headless: bool = False) -> webdriver.Chrome:
    """Create and return a Chrome WebDriver with sane defaults."""

    options = Options()
    if headless:
        options.add_argument("--headless=new")  # or "--headless" on older Chrome
    options.add_argument("--start-maximized")

    # No Service / webdriver_manager needed
    driver = webdriver.Chrome(options=options)  # Selenium Manager picks the right driver
    driver.set_page_load_timeout(60)

    return driver


from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def accept_cookies(driver, timeout=5):
    try:
        # If the banner is inside an iframe, switch into it first (common on some sites)
        # Try to locate a cookie iframe by common patterns; adjust if needed.
        cookie_iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='cookie'], iframe[id*='cookie'], iframe[class*='cookie']")
        if cookie_iframes:
            driver.switch_to.frame(cookie_iframes[0])

        accept_cookies = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.ID, "cookie_action_close_header"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", accept_cookies)
        try:
            accept_cookies.click()
        except Exception:
            driver.execute_script("arguments[0].click();", accept_cookies)

    except Exception:
        # Banner not shown or other consent framework used; ignore
        pass

    finally:
        # Always revert back to the main document
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

def time_lapses(min_seconds=10, max_seconds=20, reason=""):
    """Sleep between min and max seconds to respect site rate limits."""
    delay = random.uniform(min_seconds, max_seconds)
    if reason:
        print(f"Waiting {delay:.1f}s ({reason})")
    time.sleep(delay)


def get_cloud_count(driver: webdriver.Chrome) -> int:
    """Count gallery items via Selenium."""
    items = driver.find_elements(By.CSS_SELECTOR, "#cloudgallerywrapper .item.post3")
    return len(items)

def wait_for_count_increase(driver: webdriver.Chrome, prev_count: int, timeout: int = 15) -> bool:
    """Wait until the number of items in the gallery increases."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, "#cloudgallerywrapper .item.post3")) > prev_count
        )
        return True
    except TimeoutException:
        return False


def find_show_more_button(driver: webdriver.Chrome, timeout: int = 10):
    """Locate a 'Show more' button with robust XPath."""
    # Case-insensitive text match. Accepts any tag with class including 'btn'
    xpath = "//*[contains(@class, 'btn') and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show more')]"
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
    except TimeoutException:
        return None


def click_more_n_times(driver: webdriver.Chrome, n: int, verbose: bool = True) -> int:
    """
    Click 'Show more' up to n times, stopping early if no new items load.
    Returns the final number of loaded items.
    """
    clicks = 0
    prev_count = get_cloud_count(driver)

    if verbose:
        print(f"Initial clouds loaded: {prev_count}")

    while clicks < n:
        button = find_show_more_button(driver, timeout=10)
        if button is None:
            if verbose:
                print("Show more button not found (maybe no more content). Stopping.")
            break

        try:
            # Scroll into view and try normal click
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
            try:
                button.click()
            except Exception:
                # Fallback to JS click if regular click fails (overlays, etc.)
                driver.execute_script("arguments[0].click();", button)

            # Wait until new items appear
            if not wait_for_count_increase(driver, prev_count, timeout=20):
                if verbose:
                    print("No new items loaded after clicking. Stopping.")
                break

            clicks += 1
            current_count = get_cloud_count(driver)
            if verbose:
                print(f"Clicked 'Show more' {clicks}/{n} → total clouds shown: {current_count}")

            prev_count = current_count

            time_lapses(10, 20, "respecting rate limit before next click")

        except StaleElementReferenceException:
            # Try to re-find the button once
            if verbose:
                print("Button became stale; retrying once.")
            time.sleep(1)
            continue
        except TimeoutException:
            if verbose:
                print("Timeout waiting for more items; stopping.")
            break

    if verbose:
        print(f"Final clouds loaded: {prev_count}")
    return prev_count

def _clean_text(s: str) -> str:
    """Normalize whitespace and remove non-breaking spaces."""
    if not s:
        return ""
    s = s.replace("\u00a0", " ")  # NBSP to space
    return re.sub(r"\s+", " ", s).strip()

def _parse_date(text_or_attr: str) -> str:
    """
    Try to normalize dates like 'November 29, 2025' to ISO '2025-11-29'.
    Falls back to the original string if parsing fails.
    """
    raw = _clean_text(text_or_attr)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return raw  # keep as-is (you can improve later if needed)


def scrape_cloud_information(driver, seen_ids = None):  
    if seen_ids is None:
        seen_ids = set()

    cloud_information = []

    # Select both .item and .post3 cards (union), within the wrapper.
    cloud_cards = driver.find_elements(
        By.CSS_SELECTOR,
        "#cloudgallerywrapper .item, #cloudgallerywrapper .post3"
    )

    for card in cloud_cards:
        # ---------- IMAGE ----------
        image_url = ""
        raw_lightbox = "" 

        # Prefer the full-size image link on the <a> inside slideshowimagewrapper
        try:
            a_card = card.find_element(By.CSS_SELECTOR, ".slideshowimagewrapper a[href]")
            image_url = a_card.get_attribute("href") or ""
            raw_lightbox= a_card.get_attribute("data-lightbox") or ""
            # If there is an <img> inside, capture its src too (thumbnail)
            try:
                img = a_card.find_element(By.CSS_SELECTOR, "img")
            except Exception:
                pass
        except Exception:
            # Fallback: try an <img> directly inside slideshowimagewrapper
            try:
                img = card.find_element(By.CSS_SELECTOR, ".slideshowimagewrapper img")
                image_url = img.get_attribute("src") or img.get_attribute("data-src") or ""
            except Exception:
                image_url = ""

        lightbox_id = re.sub(r'\D+', '', raw_lightbox or '')  # -> "672357"
        lightbox_id = lightbox_id or None  # normalize to None if empty

        # Deduplicate
        # If no ID, fall back to image_url as a secondary unique key
        if not lightbox_id:
            # No ID -> skip (matches your intent)
            continue
        if lightbox_id in seen_ids:
            # Duplicate -> skip
            continue
        seen_ids.add(lightbox_id)

        # ---------- META BLOCK ----------
        date_iso = ""
        date_raw = ""
        author_name = ""
        author_profile = ""
        title = ""

        # The header area contains date/author/title
        try:
            header = card.find_element(By.CSS_SELECTOR, ".slideshowcontentwrapper .entry-header")

            # Date: <div class="entry-date ..."> with <strong datetime="..."> and/or text
            try:
                entry_date = header.find_element(By.CSS_SELECTOR, ".entry-date strong")
                date_raw = (entry_date.get_attribute("datetime") or entry_date.text or "").strip()
                date_iso = _parse_date(date_raw)
            except Exception:
                # Fallback: use the text of entry-date div
                try:
                    date_raw = header.find_element(By.CSS_SELECTOR, ".entry-date").text
                    date_iso = _parse_date(date_raw)
                except Exception:
                    date_iso = ""
                    date_raw = ""

            # Author: link inside entry-author
            try:
                a_author = header.find_element(By.CSS_SELECTOR, ".entry-author a")
                author_name = _clean_text(a_author.text)
                author_profile = a_author.get_attribute("href") or ""
            except Exception:
                # Fallback: any text inside the entry-author div
                try:
                    author_name = _clean_text(header.find_element(By.CSS_SELECTOR, ".entry-author").text)
                except Exception:
                    author_name = ""
                    author_profile = ""

            # Title: h2.entry-title (or any element with .entry-title)
            try:
                title_el = header.find_element(By.CSS_SELECTOR, ".entry-title")
                title = _clean_text(title_el.text)
            except Exception:
                title = ""
        except Exception:
            # No header found; leave meta fields empty
            pass

        # ---------- TAGS / CLOUD TYPES (optional) ----------
        tags = []
        try:
            for t in card.find_elements(By.CSS_SELECTOR, "footer.entry-footer .cloud-filter a"):
                txt = _clean_text(t.text)
                if txt:
                    tags.append(txt)
        except Exception:
            pass
        
        # ---------- Compose record ----------
        record = {
            "lightbox_id": lightbox_id,
            "image_url": image_url,           # full-size JPEG (from <a href=...>)
            "date_iso": date_iso,             # normalized to ISO if possible
            "date_raw": _clean_text(date_raw),
            "author_name": author_name,
            "author_profile": author_profile,
            "title": title,
            # "tags": tags,
            "tags": ", ".join(tags),          # flatten for CSV
        }
        cloud_information.append(record)

    print(f"Total clouds in cloud_information: {len(cloud_information)}")
    return cloud_information


# for safety reasons: scrape per batch, dus bv. 8x klikken en dan sla je alvast op... om te vermijden dat bij 65x klikken het na 50 clicks fout gaat...
def scrape_in_batches(
    url: str,
    total_clicks: int = 65,
    batch_size: int = 8,
    outfile: str = "C:\\Users\\karen\\Documents\\Informatica\Data_Scientist\\VeryCloudy\\data\\clouds_from_cas.csv"
    ):
    """
    Loads the gallery, clicks 'Show more' in batches, scrapes, saves after each batch,
    and auto-recovers if the driver session dies.
    """
    seen_ids = set()
    all_rows = []

    def interim_save_per_batch(rows, mode="w"):
        if not rows:
            return
        df = pd.DataFrame(rows)
        df = df.dropna(how="all")
        # Use the unique key as index for nicer CSV
        if "lightbox_id" in df.columns:
            df = df.set_index("lightbox_id")
        # df.index.name = "cloud_id" # do not do this, rename only in the end, when final df and csv
        df.to_csv(outfile, mode=mode, header=(mode == "w"), index=True, index_label="cloud_id")
        print(f"Saved {len(rows)} rows to {outfile} (mode={mode})")

    # Start a fresh driver
    driver = setup_driver(headless=False)
    saved_any = False

    try:
        driver.get(url)
        accept_cookies(driver, 5)  # your helper that clicks id cookie_action_close_header
        time_lapses(10, 20, "post-load pause")

        remaining_clicks = total_clicks
        batch_num = 0

        while remaining_clicks > 0:
            clicks_this_batch = min(batch_size, remaining_clicks)
            batch_num += 1
            print(f"\n=== Batch {batch_num}: clicking {clicks_this_batch} times (remaining {remaining_clicks}) ===")

            try:
                click_more_n_times(driver, n=clicks_this_batch, verbose=True)
            except (InvalidSessionIdException, WebDriverException) as e:
                print(f"Session issue during clicking: {e}\nAttempting to recover...")
                try:
                    driver.quit()
                except Exception:
                    pass
                # Restart the driver and resume
                driver = setup_driver(headless=False)
                driver.get(url)
                accept_cookies(driver, 5)
                time_lapses(10, 20, "post-restart pause")
                # Re-try this batch once
                click_more_n_times(driver, n=clicks_this_batch, verbose=True)

            # Scrape the loaded items
            try:
                rows = scrape_cloud_information(driver, seen_ids=seen_ids)
            except (InvalidSessionIdException, WebDriverException) as e:
                print(f"Session issue during scraping: {e}\nAttempting to recover...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = setup_driver(headless=False)
                driver.get(url)
                accept_cookies(driver, 5)
                time_lapses(10, 20, "post-restart pause")
                # No new click here; scrape the initial visible set (may be duplicate, dedupe handles it)
                rows = scrape_cloud_information(driver, seen_ids=seen_ids)

            # Append and save checkpoint
            all_rows.extend(rows)
            mode = "w" if not saved_any else "a"
            interim_save_per_batch(rows, mode=mode)
            saved_any = True

            remaining_clicks -= clicks_this_batch

            # Batch pause to be extra gentle
            time_lapses(20, 40, "batch pause")

        print(f"\n Finished: total unique rows collected: {len(all_rows)}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Return final DataFrame for interactive use
    df_final = pd.DataFrame(all_rows)

    if "lightbox_id" in df_final.columns:
        df_final = df_final.set_index("lightbox_id")
        df_final.index.name = "cloud_id"

    return df_final

# hoeft niet want de laatste batch zit ook al in de csv... Je kan wel de final df nog schrijven naar een aparte csv maar strikt genomen niet nodig
# def write_to_csv_with_index(df, filename):
#     # Write to CSV with index
#     csv_file = df.to_csv(filename, index=True)

#     print(f"Saved {len(df)} rows to {filename}")
#     return csv_file

