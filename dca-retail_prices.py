from playwright.sync_api import Playwright, sync_playwright, expect
import time
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup
import datetime as dt
import re
import os
import easyocr

def get_yesterday_date():
    yesterday = dt.date.today() - dt.timedelta(days=1)
    return yesterday.strftime("%d/%m/%Y")

def read_captcha(page, reader):
    try:
        # Get CAPTCHA image
        captcha_img = page.locator("#ctl00_MainContent_captchalogin")
        screenshot = captcha_img.screenshot()
        
        # Perform OCR directly on the screenshot
        results = reader.readtext(screenshot)
        
        # Extract text from results
        if results:
            # Take the text from the first result
            captcha_text = ''.join(c for c in results[0][1] if c.isalnum())
            print(f"Detected CAPTCHA text: {captcha_text}")
            return captcha_text
            
        return None
        
    except Exception as e:
        print(f"Error reading CAPTCHA: {str(e)}")
        return None

def handle_captcha(page, reader, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            captcha_input = page.locator("#ctl00_MainContent_Captcha")
            captcha_text = read_captcha(page, reader)
            
            if not captcha_text:
                print(f"Failed to read CAPTCHA on attempt {attempt + 1}")
                continue
                
            print(f"Attempting CAPTCHA with text: {captcha_text}")
            captcha_input.fill(captcha_text)
            time.sleep(1)
            
            page.get_by_role("button", name="Get Data").click()
            
            try:
                page.wait_for_selector("#gv0", timeout=5000)
                print("CAPTCHA solved successfully!")
                return True
            except:
                print("CAPTCHA validation failed, trying again...")
                page.reload()
                time.sleep(2)
                continue
                
        except Exception as e:
            print(f"CAPTCHA attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_attempts - 1:
                page.reload()
                time.sleep(2)
            continue
    
    return False

def run(playwright: Playwright, date, reader) -> None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://fcainfoweb.nic.in/reports/report_menu_web.aspx")
    time.sleep(1)
    
    # Select report options
    page.get_by_text("Price report").click()
    page.locator("#ctl00_MainContent_Ddl_Rpt_Option0").select_option("Daily Prices")
    page.locator("#ctl00_MainContent_Txt_FrmDate").click()
    time.sleep(2)
    page.locator("#ctl00_MainContent_Txt_FrmDate").fill(date)
    time.sleep(2)
    
    # Handle CAPTCHA
    if not handle_captcha(page, reader):
        print("Failed to solve CAPTCHA after maximum attempts")
        context.close()
        browser.close()
        return
    
    # Get page content
    htm = page.content()
    html_soup = BeautifulSoup(htm, 'lxml')
   
    # Parse tables and process data
    first_table = html_soup.find('table')
    thead_rows = first_table.find('thead').find_all('b')
    heads = [re.sub(r'[^0-9a-zA-Z./(): ]', '', t.text) for t in thead_rows]
    
    second_table = html_soup.find('table', {'id': 'gv0'})
    headers = [header.text.strip() for header in second_table.find_all('th')]
    data = []
    for row in second_table.find_all('tr')[1:]:
        row_data = [cell.text.strip() for cell in row.find_all(['td', 'th'])]
        data.append(row_data)
    
    # Create DataFrame
    df_head = pd.DataFrame(heads)
    df = pd.DataFrame(data, columns=headers)
    df = pd.concat([df_head, df], axis=1)
    df = df.T.reset_index()
    daily_date = df.iloc[0,2].strip().split("e")[1]
    daily_date = "Date "+daily_date
    unit = "Unit:(Rs./Kg.)"
    verbose = "Daily Retail Prices Of Essential Commodities"
    df.columns = df.iloc[1,:]
    df = df.iloc[2:,:]
    df[daily_date] = [verbose, unit] + [np.nan]*20
    cols = [daily_date] + [col for col in df.columns if col != daily_date]
    df = df[cols]
    
    # Save to CSV
    os.makedirs('data', exist_ok=True)
    output_file = os.path.join('data', f'DCA_price_{date.replace("/", "-")}.csv')
    df.to_csv(output_file, index=False)
    
    context.close()
    browser.close()

def update_excel(date):
    ofile = os.path.join('data', f'DCA_price_{date.replace("/", "-")}.csv')
    dt_temp = pd.read_csv(ofile)
    date_add = dt_temp.columns[0].split(" ")[1].replace("/","-")
    vals = dt_temp['Average Price'].values
    
    df = pd.read_excel('dca_test.xlsx')
    df[f'{date_add}'] = vals
    df.to_excel('dca_test.xlsx', index=False)

def main():
    # Initialize EasyOCR reader once
    reader = easyocr.Reader(['en'])
    
    date = get_yesterday_date()
    with sync_playwright() as playwright:
        run(playwright, date, reader)
    update_excel(date)

if __name__ == "__main__":
    main()
