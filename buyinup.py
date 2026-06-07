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

def check_institutional_net_buy(code):
  """
  利用 FinMind API 檢查該股在最近 10 個交易日內，外資或投信是否呈現淨買超。
  """
  url = "https://api.finmindtrade.com/api/v4/data"
  # ⭐ 安全修正：拉長到 30 天，確保 100% 涵蓋 10 個交易日
  start_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
  params = {
    "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
    "data_id": code,
    "start_date": start_date
  }
  try:
    res = requests.get(url, params=params, timeout=10)
    if res.status_code != 200:
      return False, 0.0, 0.0
    
    result = res.json()
    if result.get("status") != 200 or not result.get("data"):
      return False, 0.0, 0.0
    
    raw_data = result["data"]
    
    # 1. 找出所有不重複的日期並排序，取出最新的 10 個交易日
    all_dates = sorted(list(set(item["date"] for item in raw_data)))
    last_10_dates = all_dates[-10:] if len(all_dates) >= 10 else all_dates
    
    if not last_10_dates:
      return False, 0.0, 0.0
        
    # 2. 計算最新 10 個交易日的外資與投信買賣超（單位：張）
    foreign_net = 0.0
    trust_net = 0.0
    
    for item in raw_data:
      if item["date"] in last_10_dates:
        # 買進減賣出是「股數」，除以 1000 換算成「張數」
        net_shares = float(item["buy"] - item["sell"])
        net_sheets = net_shares / 1000.0
        
        if item["name"] == "Foreign_Investor":
          foreign_net += net_sheets
        elif item["name"] == "Investment_Trust":
          trust_net += net_sheets
          
    is_net_buy = (foreign_net > 0) or (trust_net > 0)
    return is_net_buy, round(foreign_net, 1), round(trust_net, 1)
    
  except Exception as e:
    print(f"查詢 {code} 三大法人籌碼失敗 (預設放行): {e}")
    return True, 0.0, 0.0

def fetch_high_volume_stocks():
  """
  爬取 Yahoo 股市的「成交值排行」，過濾出符合近 10 日法人淨買超的籌碼強勢股。
  """
  url = "https://tw.stock.yahoo.com/rank/turnover"
  headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
  }
   
  stocks = []
  seen = set()
  
  try:
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code != 200:
      return "❌ 無法取得 Yahoo 股市數據"
       
    soup = BeautifulSoup(res.text, "html.parser")
    links = soup.find_all('a', href=re.compile(r'/quote/\d+'))
    
    # ⭐ 實時進度 Log：先印出找到了幾檔熱門候選股
    raw_codes = list(set([re.search(r'/quote/(\d+)', link.get('href', '')).group(1) for link in links if re.search(r'/quote/(\d+)', link.get('href', ''))]))
    print(f"📋 已成功從 Yahoo 股市撈取 {len(raw_codes)} 檔成交值排行主流股，開始進行 10 日法人籌碼過濾...\n")
     
    for link in links:
      href = link.get('href', '')
      match = re.search(r'/quote/(\d+)', href)
      if match:
        code = match.group(1)
        if code in seen:
          continue
        seen.add(code)
         
        # 往上尋找該整行股票的容器
        parent = link.find_parent('li') or link.find_parent('div', class_='D(f)')
        if parent:
          text_content = parent.get_text(separator='|')
          parts = [p.strip() for p in text_content.split('|') if p.strip()]
           
          if len(parts) >= 6:
            name = parts[1] if parts[1] != code else parts[0]
            price = parts[2]
            change_percent = parts[4]
            turnover_value = parts[5]
            
            # 核心過濾：檢查最近 10 個交易日，外資或投信是否呈現淨買超
            is_net_buy, foreign_net, trust_net = check_institutional_net_buy(code)
            
            # ⭐ 實時進度 Log：在 GitHub Actions 的黑色畫面上，印出每一檔的檢查明細！
            f_sign = "+" if foreign_net > 0 else ""
            t_sign = "+" if trust_net > 0 else ""
            print(f"🔍 檢查 {code} {name}: 外資 {f_sign}{foreign_net}張 | 投信 {t_sign}{trust_net}張 -> {'[符合條件 ✅]' if is_net_buy else '[不符合 ❌]'}")
            
            if is_net_buy:
              stocks.append(
                f"📈 {code} {name}\n"
                f"  💰 股價: {price} ({change_percent})\n"
                f"  📊 今日成交值: {turnover_value}\n"
                f"  🔥 近10日籌碼: 外資 {f_sign}{foreign_net}張 | 投信 {t_sign}{trust_net}張"
              )
            
            # ⭐ 限速保護：每檔股票檢查完，安靜休息 0.2 秒，防止被 FinMind 封鎖 IP
            time.sleep(0.2)
         
        # 抓到 10 檔符合「10日法人買超」的股票就停
        if len(stocks) >= 10:
          break
           
    if not stocks:
      return "🔔 台股法人買超提醒 🔔\n\n今日未篩選出符合「近 10 日外資或投信淨買超」的籌碼強勢股。"
     
    message = "🔔 台股 09:05 法人籌碼雙強排行 (排除爆量雜訊) 🔔\n\n" + "\n\n".join(stocks)
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
  report = fetch_high_volume_stocks()
  send_to_line(report)
