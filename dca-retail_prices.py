from playwright.sync_api import Playwright, sync_playwright, expect
import time
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup
import datetime as dt
import re
import os

def get_yesterday_date():
    yesterday = dt.date.today() - dt.timedelta(days=1)
    return yesterday.strftime("%d/%m/%Y")

def run(playwright: Playwright, date) -> None:
    browser = playwright.chromium.launch(headless=True)  # Changed to headless=True for GitHub Actions
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://fcainfoweb.nic.in/reports/report_menu_web.aspx")
    time.sleep(1)
    page.get_by_text("Price report").click()
    page.locator("#ctl00_MainContent_Ddl_Rpt_Option0").select_option("Daily Prices")
    page.locator("#ctl00_MainContent_Txt_FrmDate").click()
    time.sleep(2)
    page.locator("#ctl00_MainContent_Txt_FrmDate").fill(date)
    time.sleep(2)
    page.get_by_role("button", name="Get Data").click()
    time.sleep(2)
    htm = page.content()
    html_soup = BeautifulSoup(htm, 'lxml')
   
    first_table = html_soup.find('table')
    thead_rows = first_table.find('thead').find_all('b')
    heads = [re.sub(r'[^0-9a-zA-Z./(): ]', '', t.text) for t in thead_rows]

    second_table = html_soup.find('table', {'id': 'gv0'})
    headers = [header.text.strip() for header in second_table.find_all('th')]
    data = []
    for row in second_table.find_all('tr')[1:]:
        row_data = [cell.text.strip() for cell in row.find_all(['td', 'th'])]
        data.append(row_data)

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
    
    # Create data directory if it doesn't exist
    os.makedirs('data', exist_ok=True)
    output_file = os.path.join('data', f'DCA_price_{date.replace("/", "-")}.csv')
    df.to_csv(output_file, index=False)
    
    context.close()
    browser.close()

if __name__ == "__main__":
    date = get_yesterday_date()
    with sync_playwright() as playwright:
        run(playwright, date)


dt_temp = pd.read_csv(f'data\DCA_price_{date.replace("/", "-")}.csv')
date_add = dt_temp.columns[0].split(" ")[1].replace("/","-")
vals = dt_temp['Average Price'].values

# Read Excel file
df = pd.read_excel('dca_test.xlsx')

# Add new column
df[f'{date_add}'] = vals

# Save updated file
df.to_excel('dca_test.xlsx', index=False)