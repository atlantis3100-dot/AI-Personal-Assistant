import os
import json
import gspread
from datetime import datetime
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- [概要：從 Render 讀取環境變數的代碼] ---
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# --- [概要：設定 Google API 存取權限的代碼] ---
def get_sheet(sheet_id):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/contacts']
    creds_json = json.loads(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id).get_worksheet(0)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # --- [概要：防重複機制：記錄 LINE 訊息 ID 的代碼] ---
    msg_id = event.message.id
    user_msg = event.message.text
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # --- [概要：四向分流邏輯判斷的代碼] ---
    try:
        if user_msg.startswith("公:"):
            target_id = os.environ.get('ID_BUSINESS')
            clean_msg = user_msg[2:]
            category = "公務"
        elif user_msg.startswith("私:"):
            target_id = os.environ.get('ID_PRIVATE')
            clean_msg = user_msg[2:]
            category = "私人"
        elif user_msg.startswith("名片:"):
            target_id = os.environ.get('ID_CARD')
            clean_msg = user_msg[3:]
            category = "名片"
            # 這裡預留 Google People API 同步邏輯
        else:
            target_id = os.environ.get('ID_MEMORY')
            clean_msg = user_msg
            category = "記憶"

        sheet = get_sheet(target_id)
        
        # --- [概要：自動建立表頭邏輯（若表為空）的代碼] ---
        if not sheet.get_all_values():
            sheet.append_row(["時間", "內容", "訊息ID", "分類"])

        # --- [概要：檢查是否重複輸入的代碼] ---
        existing_ids = sheet.col_values(3)
        if msg_id in existing_ids:
            return # 已存在則不執行

        # --- [概要：單次任務：將資料寫入試算表的代碼] ---
        sheet.append_row([now, clean_msg, msg_id, category])
        
        # --- [概要：調用 Gemini 2.5 進行極簡回覆（省 Token）的代碼] ---
        model = genai.GenerativeModel('gemini-1.5-flash') # 使用 Flash 以節省費用
        response = model.generate_content(f"請簡短回覆老闆這則{category}紀錄已完成：{clean_msg}")
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        
    except Exception as e:
        print(f"Error: {str(e)}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="助理暫時失聯，請檢查試算表 ID 或共用權限。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
