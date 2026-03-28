import os
import json
import gspread
import io
import pytz
from datetime import datetime
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
import google.generativeai as genai

app = Flask(__name__)

# --- [初始化 LINE 與 Gemini API] ---
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# --- [時區與人格設定] ---
TW_TZ = pytz.timezone('Asia/Taipei')
try:
    with open('persona.txt', 'r', encoding='utf-8') as f:
        PERSONA_SETUP = f.read().strip()
except:
    PERSONA_SETUP = "你是一位30歲專業男性特助，老闆是 A.J。相處像朋友，俐落溫暖且帶幽默感。嚴禁Markdown。"

def get_sheet(sheet_id):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = json.loads(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id).get_worksheet(0)

# --- [關鍵功能：抓取最後 50 行對話記憶] ---
def get_chat_history():
    try:
        sheet = get_sheet(os.environ.get('ID_MEMORY'))
        values = sheet.get_all_values()
        if len(values) > 1:
            # 抓取最後 50 筆，僅保留時間與內容
            history = values[-50:]
            formatted_history = "\n".join([f"{row[0]}: {row[1]}" for row in history])
            return formatted_history
    except:
        return "尚無過去對話紀錄。"
    return ""

# --- [核心邏輯：AI 動態對齊與對話生成] ---
def ai_brain_process(category, content, headers=None, is_image=False):
    model = genai.GenerativeModel('gemini-2.5-flash')
    history = get_chat_history()
    
    # 根據分類切換不同指令
    if category == "MEMORY":
        # 閒聊模式：帶入 50 行記憶與人格設定
        prompt = f"系統設定：{PERSONA_SETUP}\n\n過去 50 筆紀錄：\n{history}\n\n老闆 A.J 剛才說：{content}\n請以特助身份自然回覆。不要 Markdown。"
        res = model.generate_content(prompt)
        return res.text.strip(), None
    else:
        # 資料處理模式：動態對齊表頭
        header_str = "、".join(headers) if headers else "內容"
        prompt = f"分析內容並對應到表頭：[{header_str}]。回傳 JSON 陣列，順序一致。找不到填'無'。不准有 Markdown 標記。"
        if is_image:
            res = model.generate_content([prompt, content])
        else:
            res = model.generate_content(f"{prompt}\n內容：{content}")
        
        try:
            clean_txt = res.text.strip().replace('```json', '').replace('```', '').strip()
            return f"A.J，{category} 資料我處理好了。", json.loads(clean_txt)
        except:
            return f"A.J，這筆資料我先幫你記在最後了。", [res.text] + ["無"] * (len(headers)-1)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=(TextMessage, ImageMessage))
def handle_message(event):
    now_str = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
    is_img = event.message.type == "image"
    
    if is_img:
        msg_content = line_bot_api.get_message_content(event.message.id)
        content_input = {"mime_type": "image/jpeg", "data": io.BytesIO(msg_content.content).getvalue()}
    else:
        content_input = event.message.text

    # 1. 快速分類 (2.5 API)
    model = genai.GenerativeModel('gemini-2.5-flash')
    cat_prompt = f"將內容分類為 BUSINESS, PRIVATE, CARD, MEMORY。只回傳代碼：{content_input if not is_img else '[圖片]'}"
    category = model.generate_content(cat_prompt).text.strip()

    # 2. 獲取目標表頭並處理
    id_map = {"BUSINESS": os.environ.get('ID_BUSINESS'), "PRIVATE": os.environ.get('ID_PRIVATE'), 
              "CARD": os.environ.get('ID_CARD'), "MEMORY": os.environ.get('ID_MEMORY')}
    target_id = id_map.get(category, os.environ.get('ID_MEMORY'))
    
    try:
        sheet = get_sheet(target_id)
        headers = sheet.row_values(1) or ["時間", "內容", "訊息ID"]
        
        # 3. AI 處理：回覆文字與分欄數據
        reply_text, parsed_row = ai_brain_process(category, content_input, headers[1:-1], is_img)
        
        # 4. 寫入資料
        if category == "MEMORY" and not parsed_row:
            final_row = [now_str, content_input if not is_img else "[圖片]", event.message.id]
        else:
            final_row = [now_str] + parsed_row + [event.message.id]
            
        sheet.append_row(final_row)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"A.J，我這出了點狀況：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
