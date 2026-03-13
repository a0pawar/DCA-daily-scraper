from playwright.sync_api import sync_playwright, Playwright
import pandas as pd
import numpy as np
import datetime as dt
import easyocr
import os
import time

# -------------------------------------------------
# Utility
# -------------------------------------------------

def get_yesterday_date():
    return (dt.date.today() - dt.timedelta(days=1)).strftime("%d/%m/%Y")

def parse_date_column(column_name):
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(str(column_name), fmt).date()
        except ValueError:
            continue
    return None

def get_dates_to_process(excel_path):
    yesterday = dt.date.today() - dt.timedelta(days=1)

    if not os.path.exists(excel_path):
        return [get_yesterday_date()], set()

    columns = pd.read_excel(excel_path, nrows=0).columns
    parsed_dates = []
    existing_keys = set()

    for column in columns:
        parsed_date = parse_date_column(column)
        if parsed_date:
            parsed_dates.append(parsed_date)
            existing_keys.add(parsed_date.strftime("%d-%m-%Y"))

    if not parsed_dates:
        return [get_yesterday_date()], existing_keys

    last_date = max(parsed_dates)
    start_date = last_date + dt.timedelta(days=1)

    if start_date > yesterday:
        return [], existing_keys

    date_range = [
        (start_date + dt.timedelta(days=offset)).strftime("%d/%m/%Y")
        for offset in range((yesterday - start_date).days + 1)
    ]

    return date_range, existing_keys

# -------------------------------------------------
# CAPTCHA handling
# -------------------------------------------------

def select_report_options(page, date):
    """Select report options with proper waits"""
    try:
        page.get_by_text("Price report").click()
        page.wait_for_load_state("networkidle", timeout=5000)
        
        page.locator("#ctl00_MainContent_Ddl_Rpt_Option0").select_option("Daily Prices")
        page.wait_for_load_state("networkidle", timeout=5000)
        
        page.locator("#ctl00_MainContent_Txt_FrmDate").fill(date)
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception as e:
        print(f"Error selecting report options: {e}")
        raise


def read_captcha(page, reader):
    """Read CAPTCHA with error handling"""
    try:
        captcha_img = page.locator("#ctl00_MainContent_captchalogin")
        # Wait for the image to be visible
        captcha_img.wait_for(state="visible", timeout=5000)
        screenshot = captcha_img.screenshot()

        results = reader.readtext(
            screenshot,
            detail=0,
            paragraph=False,
            allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        )

        return results[0].strip() if results else None
    except Exception as e:
        print(f"Error reading CAPTCHA: {e}")
        return None


def handle_captcha(page, reader, date, max_attempts=5):
    """Enhanced CAPTCHA handling with better retry logic"""
    for attempt in range(max_attempts):
        try:
            print(f"CAPTCHA attempt {attempt + 1}/{max_attempts}")
            
            captcha_text = read_captcha(page, reader)
            if not captcha_text:
                print(f"Could not read CAPTCHA text on attempt {attempt + 1}")
                time.sleep(2)
                page.reload(wait_until="domcontentloaded")
                time.sleep(2)
                continue

            page.locator("#ctl00_MainContent_Captcha").fill(captcha_text)
            page.get_by_role("button", name="Get Data").click()

            try:
                page.wait_for_selector("#gv0", timeout=30000)
                print("CAPTCHA solved successfully!")
                return True
            except:
                print("CAPTCHA validation failed, retrying...")
                page.reload(wait_until="domcontentloaded")
                time.sleep(3)
                try:
                    select_report_options(page, date)
                except:
                    pass
                
        except Exception as e:
            print(f"CAPTCHA attempt {attempt + 1} exception: {e}")
            time.sleep(2)
            try:
                page.reload(wait_until="domcontentloaded")
                time.sleep(2)
            except:
                pass

    print("Failed to solve CAPTCHA after all attempts")
    return False

# -------------------------------------------------
# Scraping logic
# -------------------------------------------------

def run(playwright: Playwright, date: str):
    """Main scraping function with enhanced error handling"""
    browser = playwright.chromium.launch(headless=True)

    try:
        # Set longer timeout at context level
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(60000)  # 60 seconds default timeout

        print(f"Navigating to website for date {date}")
        page.goto("https://fcainfoweb.nic.in/reports/report_menu_web.aspx", 
                  wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)  # Initial page load wait
        
        select_report_options(page, date)
        time.sleep(2)

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        if not handle_captcha(page, reader, date):
            raise RuntimeError("CAPTCHA could not be solved")

        # Wait for table to load
        page.wait_for_selector("#gv0", timeout=30000)
        page.wait_for_selector("#gv0 tr", timeout=15000)
        time.sleep(2)

        table_html = page.locator("#gv0").evaluate("el => el.outerHTML")
        df = pd.read_html(table_html, header=0)[0]

        if df.empty:
            print(f"No data rows returned for date {date}.")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[-1] for col in df.columns]

        # ---- Extract "Average Price" row safely
        first_col = df.columns[0]
        avg_row = df[df[first_col].astype(str).str.contains("Average Price", case=False, na=False)]

        if avg_row.empty:
            print(
                "'Average Price' row not found. "
                f"Found rows: {df[first_col].unique()}"
            )
            return None

        price_series = (
            avg_row
            .iloc[0, 1:]
            .replace(["", "-", "NA", "N/A"], np.nan)
        )
        price_series = pd.to_numeric(price_series, errors="coerce")

        price_series.index = df.columns[1:]

        # ---- Save daily CSV
        os.makedirs("data", exist_ok=True)
        out_file = f"data/DCA_price_{date.replace('/', '-')}.csv"

        price_series.to_frame(name=f"Date {date}").to_csv(out_file)
        print(f"Successfully saved data to {out_file}")

        return out_file

    except Exception as e:
        print(f"Error in scraping process: {e}")
        return None
    finally:
        browser.close()

# -------------------------------------------------
# Excel updater (idempotent & backfilling)
# -------------------------------------------------

def update_excel(csv_file):
    """Update Excel file with new data"""
    try:
        df_new = pd.read_csv(csv_file, index_col=0)

        date_col = df_new.columns[0]
        date_key = date_col.replace("Date ", "").replace("/", "-")

        price_series = df_new[date_col]

        if os.path.exists("dca_test.xlsx"):
            df_master = pd.read_excel("dca_test.xlsx", index_col=0)
        else:
            df_master = pd.DataFrame()

        # Add new commodities automatically
        all_items = df_master.index.union(price_series.index)
        df_master = df_master.reindex(all_items)

        # Add date column if missing
        if date_key not in df_master.columns:
            df_master[date_key] = np.nan

        # Fill values safely (idempotent)
        df_master.loc[price_series.index, date_key] = price_series

        # Sort dates chronologically
        df_master = df_master.sort_index(axis=1)

        df_master.to_excel("dca_test.xlsx")
        print(f"Successfully updated dca_test.xlsx with data from {csv_file}")
    except Exception as e:
        print(f"Error updating Excel: {e}")

# -------------------------------------------------
# Main
# -------------------------------------------------

def main():
    try:
        dates_to_process, existing_keys = get_dates_to_process("dca_test.xlsx")

        if not dates_to_process:
            print("No dates to process.")
            return

        with sync_playwright() as playwright:
            for date in dates_to_process:
                date_key = date.replace("/", "-")
                if date_key in existing_keys:
                    print(f"Skipping {date_key} - already processed")
                    continue

                print(f"\nProcessing date: {date}")
                csv_file = run(playwright, date)
                if not csv_file:
                    print(f"Skipping update for {date}; no data returned.")
                    continue

                update_excel(csv_file)
                existing_keys.add(date_key)
    except Exception as e:
        print(f"Critical error in main: {e}")


if __name__ == "__main__":
    main()