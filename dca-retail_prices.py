from playwright.sync_api import sync_playwright, Playwright
import pandas as pd
import numpy as np
import datetime as dt
import easyocr
import os
import io
import time

# -------------------------------------------------
# Commodity name mapping: old Excel names -> new website names
# Used to migrate the existing Excel index on first run after the
# website expanded its commodity list (~Jan 2026).
# -------------------------------------------------
COMMODITY_NAME_MAP = {
    "Atta(wheat)":    "Atta (Wheat)",
    "Milk":           "Milk @",
    "Ground Nut Oil": "Groundnut Oil (Packed)",
    "Mustard Oil":    "Mustard Oil (Packed)",
    "Vanaspati":      "Vanaspati (Packed)",
    "Soya Oil":       "Soya Oil (Packed)",
    "Sunflower Oil":  "Sunflower Oil (Packed)",
    "Palm Oil":       "Palm Oil (Packed)",
    "Tea":            "Tea Loose",
    "Salt":           "Salt Pack (Iodised)",
}

# -------------------------------------------------
# Utility
# -------------------------------------------------

def get_yesterday_date():
    return (dt.date.today() - dt.timedelta(days=1)).strftime("%d/%m/%Y")

def parse_date_column(column_name):
    # Handle datetime objects stored directly as column headers
    if isinstance(column_name, (dt.datetime, dt.date)):
        return column_name.date() if isinstance(column_name, dt.datetime) else column_name
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
    try:
        captcha_img = page.locator("#ctl00_MainContent_captchalogin")
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
    browser = playwright.chromium.launch(headless=True)

    try:
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(60000)

        print(f"Navigating to website for date {date}")
        page.goto("https://fcainfoweb.nic.in/reports/report_menu_web.aspx",
                  wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        select_report_options(page, date)
        time.sleep(2)

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        if not handle_captcha(page, reader, date):
            raise RuntimeError("CAPTCHA could not be solved")

        page.wait_for_selector("#gv0", timeout=30000)
        page.wait_for_selector("#gv0 tr", timeout=15000)
        time.sleep(2)

        table_html = page.locator("#gv0").evaluate("el => el.outerHTML")

        # FIX 1: wrap in StringIO — newer pandas requires this for HTML strings
        df = pd.read_html(io.StringIO(table_html), header=0)[0]

        if df.empty:
            print(f"No data rows returned for date {date}.")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[-1] for col in df.columns]

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
# Excel updater
# -------------------------------------------------

def migrate_index_names(df_master):
    """Rename old commodity labels to match current website names (one-time migration)."""
    rename_needed = {k: v for k, v in COMMODITY_NAME_MAP.items() if k in df_master.index}
    if rename_needed:
        print(f"Migrating {len(rename_needed)} commodity name(s): {list(rename_needed.keys())}")
        df_master = df_master.rename(index=rename_needed)
    return df_master


def normalise_date_columns(df_master):
    """Convert all column headers to uniform 'DD-MM-YYYY' strings."""
    new_cols = []
    for col in df_master.columns:
        parsed = parse_date_column(col)
        new_cols.append(parsed.strftime("%d-%m-%Y") if parsed else str(col))
    df_master.columns = new_cols
    return df_master


def update_excel(csv_file, excel_path="dca_test.xlsx"):
    try:
        df_new = pd.read_csv(csv_file, index_col=0)

        date_col = df_new.columns[0]
        date_key = date_col.replace("Date ", "").replace("/", "-")

        price_series = df_new[date_col]

        if os.path.exists(excel_path):
            df_master = pd.read_excel(excel_path, index_col=0)
            # FIX 2: migrate old commodity names to new website names
            df_master = migrate_index_names(df_master)
            # FIX 3: normalise all date column headers to uniform string format
            df_master = normalise_date_columns(df_master)
        else:
            df_master = pd.DataFrame()

        all_items = df_master.index.union(price_series.index)
        df_master = df_master.reindex(all_items)

        if date_key not in df_master.columns:
            df_master[date_key] = np.nan

        df_master.loc[price_series.index, date_key] = price_series

        # Sort columns chronologically (safe now that all are DD-MM-YYYY strings)
        def col_sort_key(c):
            try:
                return dt.datetime.strptime(c, "%d-%m-%Y")
            except ValueError:
                return dt.datetime.max

        df_master = df_master[sorted(df_master.columns, key=col_sort_key)]

        df_master.to_excel(excel_path)
        print(f"Successfully updated {excel_path} with data from {csv_file}")
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
