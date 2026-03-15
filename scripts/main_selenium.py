
# main.py
from scraping_by_selenium import scrape_in_batches

def main():
    url = "https://cloudappreciationsociety.org/gallery/"
    df_cas_clouds = scrape_in_batches(
        url=url,
        total_clicks=65,
        batch_size=8,  
        outfile=r"C:\Users\karen\Documents\Informatica\Data_Scientist\VeryCloudy\data\clouds_from_cas.csv"
    )

    return df_cas_clouds

if __name__ == "__main__":
    main()
    