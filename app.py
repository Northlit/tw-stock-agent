import os
import re
import requests
from bs4 import BeautifulSoup

def get_line_credentials():
  # 從 GitHub Secrets 安全地讀取金鑰
  line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
  line_user_id = os.environ.get("LINE_USER_ID")
  return line_token, line_user_id

def fetch_high_volume_stocks():
  """
  抓取 Yahoo 股市台股成交量排行
  """
  url = "https://tw.stock.yahoo.com/rank/volume"
  headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
  }
   
  try:
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code != 200:
      return "❌ 無法取得 Yahoo 股市數據"
       
    soup = BeautifulSoup(res.text, "html.parser")
     
    # 利用 regex 尋找含有股票代號連結的 a 標籤 (確保 Yahoo 改版時仍有高容錯率)
    links = soup.find_all('a', href=re.compile(r'/quote/\d+'))
     
    stocks = []
    seen = set()
     
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
           
          # ⭐ 安全修正：因為需要讀取到索引 5 (第 6 個元素)，長度必須大於等於 6，否則會當機
          if len(parts) >= 6:
            # 格式通常為： [代號, 名字, 股價, 漲跌, 漲跌幅, 成交量...]
            name = parts[1] if parts[1] != code else parts[0]
            price = parts[2]
            change_percent = parts[4]
            volume = parts[5] if 'K' in parts[5] or parts[5].isdigit() else "讀取中"
             
            stocks.append(f"📈 {code} {name}\n  💰 股價: {price} ({change_percent})\n  📊 成交量: {volume} 張")
         
        if len(stocks) >= 8: # 抓取開盤成交量前 8 名
          break
           
    if not stocks:
      return "⚠️ 未能成功解析爆量股，請檢查網頁結構。"
       
    message = "🔔 台股 09:05 開盤爆量股排行 🔔\n\n" + "\n\n".join(stocks)
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
