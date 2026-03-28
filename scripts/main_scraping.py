from verycloudy.config import FILEPATH_CLOUDS_CSV, FILEPATH_CLOUDS_JSON, FILEPATH_JSON_CHECKPOINT, FILEPATH_CSV_CHECKPOINT, BASE_URL, GALLERY, AJAX, FILEPATH_JSON_CHECKPOINT2, FILEPATH_CSV_CHECKPOINT2, FILEPATH_CLOUDS_APPEND_CSV, FILEPATH_CLOUDS_APPEND_JSON 
from scraping_by_api import load_seen_ids_from_csv, crawl_all_clouds, save_csv, save_jsonl

if __name__ == "__main__":
    # If you need your login/session cookies, paste the Cookie header string here.
    COOKIE = "aelia_customer_country=BE; aelia_cs_selected_currency=EUR; _fbp=fb.1.1766520637694.334427161.AQ"  # e.g., "wordpress_logged_in_xxx=...; aelia_cs_selected_currency=EUR; ..."

    # Load previously scraped IDs from final (previous) file
    seen_ids = load_seen_ids_from_csv(FILEPATH_CLOUDS_CSV)

    rows = crawl_all_clouds(
        cats="",               # all categories
        photographer="",       # all photographers
        sleep_sec=0.8,
        max_pages=None,        # None => keep going until exhausted
        cookie_string=COOKIE,
        seen_ids=seen_ids,
        stop_when_all_seen_pages=3, 
    )

    # Let op: save csv of jsonl overschrijft de hele csv, dat is niet append dus gebruik dat niet op de originele file als je de nieuwe cloud_cards gaat scrapen!!!
    # Ik zet hier nu een filename die niet bestaat, om te vermijden dat je de huidige file helemaal gaat overschrijven...
    save_csv(rows, FILEPATH_CLOUDS_APPEND_CSV)
    save_jsonl(rows, FILEPATH_CLOUDS_APPEND_JSON)
