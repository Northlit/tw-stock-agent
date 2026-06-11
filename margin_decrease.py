import os
import re
import datetime
import time
import requests
from bs4 import BeautifulSoup

def get_line_credentials():
  # 從 GitHub Secrets 安全地讀取金鑰
  line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
  line_user_id = os.environ.get("LINE_USER_ID")
  return line_token, line_user_id

def check_margin_and_institutions(code):
  """
  同時檢查:
  1. 最近 10 個交易日內，融資餘額是否大減 (減少 > 100張 或 減幅 > 3%)
  2. 最近 10 個交易日內，外資或投信是否呈現淨買超 (擇一即可)
  """
  fm_url = "https://api.finmindtrade.com/api/v4/data"
  start_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
  
  # A. 檢查融資融券參數
  margin_params = {
    "dataset": "TaiwanStockMarginPurchaseShortSale",
    "data_id": code,
    "start_date": start_date
  }
  
  # B. 檢查三大法人參數
  inst_params = {
    "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
    "data_id": code,
    "start_date": start_date
  }
  
  try:
    # 1. 撈取融資與法人資料
    res_margin = requests.get(fm_url, params=margin_params, timeout=10)
    res_inst = requests.get(fm_url, params=inst_params, timeout=10)
    
    if res_margin.status_code != 200 or res_inst.status_code != 200:
      return False, {}
      
    margin_res = res_margin.json()
    inst_res = res_inst.json()
    
    if margin_res.get("status") != 200 or not margin_res.get("data") or inst_res.get("status") != 200 or not inst_res.get("data"):
      return False, {}
      
    # --- 1. 運算融資餘額變化 ---
    margin_raw = margin_res["data"]
    # 過濾出融資數據 (MarginPurchase)
    margin_data = [item for item in margin_raw if item["name"] == "MarginPurchase"]
    
    # 找出最後10個交易日的資料
    all_dates_margin = sorted(list(set(item["date"] for item in margin_data)))
    last_10_dates_margin = all_dates_margin[-10:] if len(all_dates_margin) >= 10 else all_dates_margin
    
    margin_10 = sorted([item for item in margin_data if item["date"] in last_10_dates_margin], key=lambda x: x["date"])
    
    if len(margin_10) < 2:
      return False, {}
      
    start_margin = float(margin_10 0 ["YesBalance"]) # 10天前的融資餘額 (股)
    end_margin = float(margin_10[-1]["TodayBalance"])   # 今日的融資餘額 (股)
    
    # 計算增減 (負數代表減少)
    margin_change = (end_margin - start_margin) / 1000.0
    margin_change_percent = (margin_change * 1000.0 / start_margin) * 100 if start_margin > 0 else 0.0
    
    # 篩選條件：融資餘額減少超過 100 張，或者減幅大於 3.0% (負數代表減少，所以用 <= )
    is_margin_decrease = (margin_change <= -100.0) or (margin_change_percent <= -3.0)
    
    # --- 2. 運算法人買賣超 ---
    inst_raw = inst_res["data"]
    all_dates_inst = sorted(list(set(item["date"] for item in inst_raw)))
    last_10_dates_inst = all_dates_inst[-10:] if len(all_dates_inst) >= 10 else all_dates_inst
    
    foreign_net = 0.0
    trust_net = 0.0
    
    for item in inst_raw:
      if item["date"] in last_10_dates_inst:
        net_sheets = (item["buy"] - item["sell"]) / 1000.0
        if item["name"] == "Foreign_Investor":
          foreign_net += net_sheets
        elif item["name"] == "Investment_Trust":
          trust_net += net_sheets
          
    # 法人條件：外資淨買超 或者是 投信淨買超 (擇一即可)
    is_inst_buy = (foreign_net > 0) or (trust_net > 0)
    
    # 打包數據回傳
    stats = {
      "margin_change": round(margin_change, 1),
      "margin_change_percent": round(margin_change_percent, 2),
      "foreign_net": round(foreign_net, 1),
      "trust_net": round(trust_net, 1)
    }
    
    if is_margin_decrease and is_inst_buy:
      return True, stats
    else:
      return False, stats
      
  except Exception as e:
    print(f"計算 {code} 籌碼資料失敗: {e}")
    
  return False, {}

def fetch_margin_decrease_stocks():
  """
  爬取 Yahoo 股市的「成交值排行」，過濾出符合近 10 日融資大減 ＋ 法人買超的強勢沉澱股。
  """
  url = "https://tw.stock.yahoo.com/rank/turnover"
  headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
  }
   
  stocks = []
  seen = set()
  
  try:
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code != 200:
      return "❌ 無法取得 Yahoo 股市數據"
       
    soup = BeautifulSoup(res.text, "html.parser")
    links = soup.find_all('a', href=re.compile(r'/quote/\d+'))
    
    print(f"📋 開始進行 10 日【融資減肥 + 法人吃貨】選股過濾...\n")
     
    for link in links:
      href = link.get('href', '')
      match = re.search(r'/quote/(\d+)', href)
      if match:
        code = match.group(1)
        if code in seen:
          continue
        seen.add(code)
         
        parent = link.find_parent('li') or link.find_parent('div', class_='D(f)')
        if parent:
          text_content = parent.get_text(separator='|')
          parts = [p.strip() for p in text_content.split('|') if p.strip()]
           
          if len(parts) >= 6:
            name = parts 1  if parts 1  != code else parts 0 
            price = parts 2 
            change_percent = parts 4 
            turnover_value = parts 5 
            
            # 執行核心條件檢查
            passed, stats = check_margin_and_institutions(code)
            
            # 實時進度 Log 列印
            if stats:
              print(f"🔍 檢查 {code} {name}: 融資增減 {stats['margin_change']}張({stats['margin_change_percent']}%) | 外資 {stats['foreign_net']}張 | 投信 {stats['trust_net']}張 -> {'[符合條件 ✅]' if passed else '[不符合 ❌]'}")
            
            if passed:
              f_sign = "+" if stats['foreign_net'] > 0 else ""
              t_sign = "+" if stats['trust_net'] > 0 else ""
              
              stocks.append(
                f"📉 {code} {name} (融資減肥股)\n"
                f"  💰 股價: {price} ({change_percent})\n"
                f"  📊 今日成交值: {turnover_value}\n"
                f"  🔥 近10日融資: {stats['margin_change']}張 ({stats['margin_change_percent']}%)\n"
                f"  🔥 近10日籌碼: 外資 {f_sign}{stats['foreign_net']}張 | 投信 {t_sign}{stats['trust_net']}張"
              )
            
            # 由於一次撈取兩個 API，加裝 0.3 秒限速延遲，保護 IP 安全
            time.sleep(0.3)
         
        # 抓到 10 檔就停止，避免推播太長
        if len(stocks) >= 10:
          break
           
    if not stocks:
      return "🔔 台股融資減肥股提醒 🔔\n\n今日成交主流股中，無任何一檔符合「近 10 日融資大減 ＋ 法人買超」的籌碼洗盤條件。"
     
    message = "🔔 台股 09:05 籌碼洗盤：融資大減 + 法人接盤排行 🔔\n\n" + "\n\n".join(stocks)
    return message
     
  except Exception as e:
    return f"❌ 執行爬蟲時發生錯誤: {str(e)}"

def send_to_line(message):
  token, user_id = get_line_credentials()
  if not token or not user_id:
    print("錯誤：未設定 LINE 金鑰與 User ID")
    return
     
  url = "https://api.line.me/v2/bot/message/push"
  headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
  }
  payload = {
    "to": user_id,
    "messages": [
      {
        "type": "text",
        "text": message
      }
    ]
  }
   
  response = requests.post(url, json=payload, headers=headers)
  if response.status_code == 200:
    print("✅ LINE 訊息發送成功！")
  else:
    print(f"❌ 訊息發送失敗，狀態碼：{response.status_code}，錯誤訊息：{response.text}")

if __name__ == "__main__":
  report = fetch_margin_decrease_stocks()
  send_to_line(report)
🛠️ 步驟二：建立專屬的定時工作流程 .github/workflows/margin_decrease.yml
我們建立一個獨立的排程，一樣定在 台灣時間每天晚上 21:00 自動執行（這時當天的信用交易融資餘額都已經全數公佈完畢了，數據最精確）：

請在專案中點選 Add file $\rightarrow$ Create new file，檔名輸入（⚠️ 請注意完整目錄與小寫）： .github/workflows/margin_decrease.yml

並貼入以下 2026 最新規格的排程設定：

name: Daily Margin Decrease Run

on:
  schedule:
    # 每天晚上 21:00 自動執行一次 (13:00 UTC)
    - cron: '0 13 * * *'
  workflow_dispatch: # 支援手動點擊「Run workflow」測試

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.9'

      - name: Install dependencies
        run: |
          pip install requests beautifulsoup4

      - name: Run margin_decrease.py
        env:
          LINE_CHANNEL_ACCESS_TOKEN: ${{ secrets.LINE_CHANNEL_ACCESS_TOKEN }}
          LINE_USER_ID: ${{ secrets.LINE_USER_ID }}
        run: python margin_decrease.py
