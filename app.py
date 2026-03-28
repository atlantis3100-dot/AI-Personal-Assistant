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

def get_sheet(sheet_id):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = json.loads(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id).get_worksheet(0)

def ai_classify(content, is_image=False):
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = "你是專業秘書。請分析以下內容應歸類為：'BUSINESS'(公務)、'PRIVATE'(私人記帳)、'CARD'(名片)或'MEMORY'(閒聊)。只需回傳大寫代碼。"
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

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    msg_id = event.message.id
    user_msg = event.message.text
    
    if user_msg.startswith("公:"): category = "BUSINESS"; clean_msg = user_msg[2:]
    elif user_msg.startswith("私:"): category = "PRIVATE"; clean_msg = user_msg[2:]
    elif user_msg.startswith("名片:"): category = "CARD"; clean_msg = user_msg[3:]
    else:
        category = ai_classify(user_msg)
        clean_msg = user_msg

    save_to_sheet(event, category, clean_msg, msg_id)

# --- [概要：處理圖片訊息，強制 Gemini 2.5 切割欄位的代碼] ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    img_data = io.BytesIO(message_content.content)
    img_b = {"mime_type": "image/jpeg", "data": img_data.getvalue()}
    
    category = ai_classify(img_b, is_image=True)
    
    if category == "CARD":
        model = genai.GenerativeModel('gemini-2.5-flash')
        # 修正：要求嚴格輸出 JSON 陣列，不准擠成一坨
        prompt = """請讀取這張名片，嚴格回傳一個 JSON 陣列格式，不要包含 ```json 等 markdown 標記。
        格式必須完全依照此順序：["姓名", "手機號碼", "公司電話", "公司名稱", "職稱與服務項目"]。
        如果找不到某項目，請填 "無" """
        res = model.generate_content([prompt, img_b])
        
        try:
            # 清理 AI 可能夾帶的標記並轉換為 List
            clean_txt = res.text.strip().replace('```json', '').replace('```', '').strip()
            clean_msg = json.loads(clean_txt)
        except:
            clean_msg = ["解析失敗", "無", "無", "無", res.text]
    else:
        clean_msg = "[圖片內容]"

    save_to_sheet(event, category, clean_msg, event.message.id)

# --- [概要：統一寫入試算表，並針對「名片庫」進行七格切分的代碼] ---
def save_to_sheet(event, category, content, msg_id):
    id_map = {
        "BUSINESS": os.environ.get('ID_BUSINESS'),
        "PRIVATE": os.environ.get('ID_PRIVATE'),
        "CARD": os.environ.get('ID_CARD'),
        "MEMORY": os.environ.get('ID_MEMORY')
    }
    target_id = id_map.get(category, os.environ.get('ID_MEMORY'))
    
    try:
        sheet = get_sheet(target_id)
        records = sheet.get_all_values()
        time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # 如果是名片，且 content 是 List (陣列)
        if category == "CARD" and isinstance(content, list):
            if not records:
                # 自動建立專業名片庫表頭
                sheet.append_row(["時間", "姓名", "手機號碼", "公司電話", "公司名稱", "職稱與服務項目", "訊息ID"])
                records = sheet.get_all_values()
                
            row_data = [time_str] + content + [msg_id]
            reply_text = f"✅ 已精準分欄存入【名片庫】\n姓名：{content[0]}\n公司：{content[3]}"
            
        else:
            if not records:
                sheet.append_row(["時間", "內容", "訊息ID"])
                records = sheet.get_all_values()
                
            row_data = [time_str, str(content), msg_id]
            reply_text = f"✅ 已自動歸類至【{category}】\n內容：{content}"
            
        # 防重複檢查 (比對最後一欄的訊息ID)
        if records and msg_id in [row[-1] for row in records]: return
        
        sheet.append_row(row_data)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"❌ 系統錯誤回報：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
