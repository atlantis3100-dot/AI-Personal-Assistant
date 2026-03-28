import os
import json
import gspread
import io
from datetime import datetime
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
import google.generativeai as genai

app = Flask(__name__)

# --- [概要：初始化 LINE 與 Gemini API 的代碼] ---
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# --- [概要：Google 試算表連線邏輯的代碼] ---
def get_sheet(sheet_id):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = json.loads(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id).get_worksheet(0)

# --- [概要：智慧大腦 - 判斷訊息分類的代碼（省 Token 版）] ---
def ai_classify(content, is_image=False):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = "你是專業秘書。請分析以下內容應歸類為：'BUSINESS'(公務)、'PRIVATE'(私人)、'CARD'(名片)或'MEMORY'(記憶)。只需回傳大寫代碼。"
    if is_image:
        response = model.generate_content([prompt, content])
    else:
        response = model.generate_content(f"{prompt}\n內容：{content}")
    return response.text.strip()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- [概要：處理文字訊息（自動分類）的代碼] ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    msg_id = event.message.id
    user_msg = event.message.text
    
    # 判斷是否有手動標籤
    if user_msg.startswith("公:"): category = "BUSINESS"; clean_msg = user_msg[2:]
    elif user_msg.startswith("私:"): category = "PRIVATE"; clean_msg = user_msg[2:]
    elif user_msg.startswith("名片:"): category = "CARD"; clean_msg = user_msg[3:]
    else:
        # 沒標籤？交給 AI 判斷 (原則 5)
        category = ai_classify(user_msg)
        clean_msg = user_msg

    save_to_sheet(event, category, clean_msg, msg_id)

# --- [概要：處理圖片訊息（視覺辨識）的代碼] ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    img_data = io.BytesIO(message_content.content)
    img_b = {"mime_type": "image/jpeg", "data": img_data.getvalue()}
    
    # AI 辨識圖片性質 (原則 2: 分析完不儲存)
    category = ai_classify(img_b, is_image=True)
    
    # 如果是名片，進行 OCR 辨識
    if category == "CARD":
        model = genai.GenerativeModel('gemini-1.5-flash')
        res = model.generate_content(["請讀取這張名片，整理成：姓名、電話、公司。單行輸出。", img_b])
        clean_msg = res.text
    else:
        clean_msg = "[圖片內容]"

    save_to_sheet(event, category, clean_msg, event.message.id)

# --- [概要：統一寫入試算表與防重複的代碼] ---
def save_to_sheet(event, category, clean_msg, msg_id):
    id_map = {
        "BUSINESS": os.environ.get('ID_BUSINESS'),
        "PRIVATE": os.environ.get('ID_PRIVATE'),
        "CARD": os.environ.get('ID_CARD'),
        "MEMORY": os.environ.get('ID_MEMORY')
    }
    target_id = id_map.get(category, os.environ.get('ID_MEMORY'))
    
    try:
        sheet = get_sheet(target_id)
        if not sheet.get_all_values():
            sheet.append_row(["時間", "內容", "訊息ID"])
            
        # 防重複檢查 (原則 5)
        if msg_id in sheet.col_values(3): return
        
        sheet.append_row([datetime.now().strftime('%Y-%m-%d %H:%M'), clean_msg, msg_id])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已自動歸類至【{category}】\n內容：{clean_msg}"))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 寫入失敗，請檢查 ID 與權限。"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
