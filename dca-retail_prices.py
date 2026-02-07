# from playwright.sync_api import Playwright, sync_playwright, expect
# import time
# import pandas as pd
# import numpy as np
# from bs4 import BeautifulSoup
# import datetime as dt
# import re
# import os
# import easyocr

# def get_yesterday_date():
#     yesterday = dt.date.today() - dt.timedelta(days=1)
#     return yesterday.strftime("%d/%m/%Y")

# def read_captcha(page, reader):
#     try:
#         # Get CAPTCHA image
#         captcha_img = page.locator("#ctl00_MainContent_captchalogin")
#         screenshot = captcha_img.screenshot()
        
#         # Perform OCR directly on the screenshot
#         results = reader.readtext(screenshot)
        
#         # Extract text from results
#         if results:
#             # Take the text from the first result
#             captcha_text = ''.join(c for c in results[0][1] if c.isalnum())
#             print(f"Detected CAPTCHA text: {captcha_text}")
#             return captcha_text
            
#         return None
        
#     except Exception as e:
#         print(f"Error reading CAPTCHA: {str(e)}")
#         return None

# def handle_captcha(page, reader, max_attempts=3):
#     for attempt in range(max_attempts):
#         try:
#             captcha_input = page.locator("#ctl00_MainContent_Captcha")
#             captcha_text = read_captcha(page, reader)
            
#             if not captcha_text:
#                 print(f"Failed to read CAPTCHA on attempt {attempt + 1}")
#                 continue
                
#             print(f"Attempting CAPTCHA with text: {captcha_text}")
#             captcha_input.fill(captcha_text)
#             time.sleep(1)
            
#             page.get_by_role("button", name="Get Data").click()
            
#             try:
#                 page.wait_for_selector("#gv0", timeout=5000)
#                 print("CAPTCHA solved successfully!")
#                 return True
#             except:
#                 print("CAPTCHA validation failed, trying again...")
#                 page.reload()
#                 time.sleep(2)
#                 continue
                
#         except Exception as e:
#             print(f"CAPTCHA attempt {attempt + 1} failed: {str(e)}")
#             if attempt < max_attempts - 1:
#                 page.reload()
#                 time.sleep(2)
#             continue
    
#     return False

# def run(playwright: Playwright, date, reader) -> None:
#     browser = playwright.chromium.launch(headless=True)
#     context = browser.new_context()
#     page = context.new_page()
#     page.goto("https://fcainfoweb.nic.in/reports/report_menu_web.aspx")
#     time.sleep(1)
    
#     # Select report options
#     page.get_by_text("Price report").click()
#     page.locator("#ctl00_MainContent_Ddl_Rpt_Option0").select_option("Daily Prices")
#     page.locator("#ctl00_MainContent_Txt_FrmDate").click()
#     time.sleep(2)
#     page.locator("#ctl00_MainContent_Txt_FrmDate").fill(date)
#     time.sleep(2)
    
#     # Handle CAPTCHA
#     if not handle_captcha(page, reader):
#         print("Failed to solve CAPTCHA after maximum attempts")
#         context.close()
#         browser.close()
#         return
    
#     # Get page content
#     htm = page.content()
#     html_soup = BeautifulSoup(htm, 'lxml')
   
#     # Parse tables and process data
#     first_table = html_soup.find('table')
#     thead_rows = first_table.find('thead').find_all('b')
#     heads = [re.sub(r'[^0-9a-zA-Z./(): ]', '', t.text) for t in thead_rows]
    
#     second_table = html_soup.find('table', {'id': 'gv0'})
#     headers = [header.text.strip() for header in second_table.find_all('th')]
#     data = []
#     for row in second_table.find_all('tr')[1:]:
#         row_data = [cell.text.strip() for cell in row.find_all(['td', 'th'])]
#         data.append(row_data)
    
#     # Create DataFrame
#     df_head = pd.DataFrame(heads)
#     df = pd.DataFrame(data, columns=headers)
#     df = pd.concat([df_head, df], axis=1)
#     df = df.T.reset_index()
#     daily_date = df.iloc[0,2].strip().split("e")[1]
#     daily_date = "Date "+daily_date
#     unit = "Unit:(Rs./Kg.)"
#     verbose = "Daily Retail Prices Of Essential Commodities"
#     df.columns = df.iloc[1,:]
#     df = df.iloc[2:,:]
#     df[daily_date] = [verbose, unit] + [np.nan] * (len(df) - 2)
#     cols = [daily_date] + [col for col in df.columns if col != daily_date]
#     df = df[cols]
    
#     # Save to CSV
#     os.makedirs('data', exist_ok=True)
#     output_file = os.path.join('data', f'DCA_price_{date.replace("/", "-")}.csv')
#     df.to_csv(output_file, index=False)
    
#     context.close()
#     browser.close()

# def update_excel(date):
#     ofile = os.path.join('data', f'DCA_price_{date.replace("/", "-")}.csv')
#     dt_temp = pd.read_csv(ofile)
#     date_add = dt_temp.columns[0].split(" ")[1].replace("/","-")
#     vals = dt_temp['Average Price'].values
    
#     df = pd.read_excel('dca_test.xlsx')
#     df[f'{date_add}'] = vals
#     df.to_excel('dca_test.xlsx', index=False)

# def main():
#     # Initialize EasyOCR reader once
#     reader = easyocr.Reader(['en'])
    
#     date = get_yesterday_date()
#     with sync_playwright() as playwright:
#         run(playwright, date, reader)
#     update_excel(date)

# if __name__ == "__main__":
#     main()

from playwright.sync_api import sync_playwright, Playwright
import pandas as pd
import numpy as np
import datetime as dt
import easyocr
import os

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
    page.get_by_text("Price report").click()
    page.locator("#ctl00_MainContent_Ddl_Rpt_Option0").select_option("Daily Prices")
    page.locator("#ctl00_MainContent_Txt_FrmDate").fill(date)


def read_captcha(page, reader):
    captcha_img = page.locator("#ctl00_MainContent_captchalogin")
    screenshot = captcha_img.screenshot()

    results = reader.readtext(
        screenshot,
        detail=0,
        paragraph=False,
        allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    )

    return results[0].strip() if results else None


def handle_captcha(page, reader, date, max_attempts=3):
    for _ in range(max_attempts):
        captcha_text = read_captcha(page, reader)
        if not captcha_text:
            continue

        page.locator("#ctl00_MainContent_Captcha").fill(captcha_text)
        page.get_by_role("button", name="Get Data").click()

        try:
            page.wait_for_selector("#gv0", timeout=10000)
            print("CAPTCHA solved successfully!")
            return True
        except:
            page.reload(wait_until="domcontentloaded")
            select_report_options(page, date)

    return False

# -------------------------------------------------
# Scraping logic
# -------------------------------------------------

def run(playwright: Playwright, date: str):
    browser = playwright.chromium.launch(headless=True)

    try:
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://fcainfoweb.nic.in/reports/report_menu_web.aspx")
        select_report_options(page, date)

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        if not handle_captcha(page, reader, date):
            raise RuntimeError("CAPTCHA could not be solved")

        page.wait_for_function(
            "() => {"
            "const table = document.querySelector('#gv0');"
            "if (!table) return false;"
            "const rows = table.querySelectorAll('tr');"
            "if (rows.length <= 1) return false;"
            "return Array.from(rows).some(row => row.querySelector('td, th'));"
            "}",
            timeout=20000,
        )

        rows = page.eval_on_selector_all(
            "#gv0 tr",
            "trs => trs.map(tr => Array.from(tr.querySelectorAll('th, td'))"
            ".map(cell => cell.innerText.trim()))",
        )
        rows = [row for row in rows if any(cell for cell in row)]
        if len(rows) < 2:
            print(f"No data rows returned for date {date}.")
            return None

        headers = rows[0]
        data_rows = rows[1:]
        max_len = max(len(headers), max(len(row) for row in data_rows))
        if len(headers) < max_len:
            headers.extend([f"Column {idx + 1}" for idx in range(len(headers), max_len)])
        normalized_rows = []
        for row in data_rows:
            if len(row) < max_len:
                row = row + [""] * (max_len - len(row))
            normalized_rows.append(row)

        df = pd.DataFrame(normalized_rows, columns=headers)

        if df.empty:
            print(f"No data rows returned for date {date}.")
            return None

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

        return out_file

    finally:
        browser.close()

# -------------------------------------------------
# Excel updater (idempotent & backfilling)
# -------------------------------------------------

def update_excel(csv_file):
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

# -------------------------------------------------
# Main
# -------------------------------------------------

def main():
    dates_to_process, existing_keys = get_dates_to_process("dca_test.xlsx")

    with sync_playwright() as playwright:
        for date in dates_to_process:
            date_key = date.replace("/", "-")
            if date_key in existing_keys:
                continue

            csv_file = run(playwright, date)
            if not csv_file:
                print(f"Skipping update for {date}; no data returned.")
                continue

            update_excel(csv_file)
            existing_keys.add(date_key)


if __name__ == "__main__":
    main()
