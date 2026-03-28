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

# --- [概要：初始化 LINE 與 Gemini API] ---
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# --- [概要：讀取助理人格設定] ---
try:
    with open('persona.txt', 'r', encoding='utf-8') as f:
        PERSONA_SETUP = f.read().strip()
except:
    PERSONA_SETUP = "你是一位30歲專業男性特助，老闆是 A.J。語氣溫暖俐落，像朋友般幽默。"

def get_sheet(sheet_id):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = json.loads(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id).get_worksheet(0)

# --- [概要：動態對齊表頭的 AI 核心邏輯] ---
def ai_dynamic_parse(content, headers, is_image=False):
    model = genai.GenerativeModel('gemini-2.5-flash')
    header_str = "、".join(headers)
    prompt = f"""你是一位專業助理。請分析提供的內容，並將資訊對應到以下表頭欄位：[{header_str}]。
    請嚴格回傳一個 JSON 陣列，順序必須與表頭完全一致。找不到的填"無"。
    如果是記帳，請自動拆分品項與金額。如果資訊超出表頭定義，請整理在最後一個欄位。
    不要包含任何 markdown 標記，直接回傳 JSON 陣列。"""
    
    if is_image:
        res = model.generate_content([prompt, content])
    else:
        res = model.generate_content(f"{prompt}\n內容：{content}")
    
    try:
        clean_txt = res.text.strip().replace('```json', '').replace('```', '').strip()
        return json.loads(clean_txt)
    except:
        return [res.text] + ["無"] * (len(headers) - 1)

def generate_human_reply(details):
    model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=PERSONA_SETUP)
    prompt = f"老闆 A.J 傳了：{details}。請用你的人設回覆他。嚴禁 Markdown，要口語自然。"
    try:
        return model.generate_content(prompt).text.strip()
    except:
        return f"A.J，幫你記好了！"

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
def handle_any_message(event):
    # --- [概要：統一處理邏輯，包含時區校正] ---
    tz = pytz.timezone('Asia/Taipei')
    now_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M')
    
    if event.message.type == "text":
        user_msg = event.message.text
        # 初步判斷分類
        model = genai.GenerativeModel('gemini-2.5-flash')
        cat_res = model.generate_content(f"將此內容分類為 BUSINESS, PRIVATE, CARD, 或 MEMORY。只需回傳代碼：{user_msg}")
        category = cat_res.text.strip()
        content_to_parse = user_msg
    else:
        # 處理圖片
        msg_content = line_bot_api.get_message_content(event.message.id)
        img_data = io.BytesIO(msg_content.content)
        img_b = {"mime_type": "image/jpeg", "data": img_data.getvalue()}
        model = genai.GenerativeModel('gemini-2.5-flash')
        cat_res = model.generate_content(["判斷圖片分類：BUSINESS, PRIVATE, CARD, MEMORY。只回傳代碼。", img_b])
        category = cat_res.text.strip()
        content_to_parse = img_b

    save_dynamic(event, category, content_to_parse, now_str)

def save_dynamic(event, category, content, time_str):
    id_map = {
        "BUSINESS": os.environ.get('ID_BUSINESS'),
        "PRIVATE": os.environ.get('ID_PRIVATE'),
        "CARD": os.environ.get('ID_CARD'),
        "MEMORY": os.environ.get('ID_MEMORY')
    }
    target_id = id_map.get(category, os.environ.get('ID_MEMORY'))
    
    try:
        sheet = get_sheet(target_id)
        headers = sheet.row_values(1)
        
        # 如果表是空的，建立預設表頭
        if not headers:
            headers = ["時間", "內容", "訊息ID"]
            sheet.append_row(headers)
        
        # 呼叫 AI 依照表頭分欄
        is_img = isinstance(content, dict)
        parsed_data = ai_dynamic_parse(content, headers[1:-1], is_image=is_img) # 扣掉時間跟 ID
        
        final_row = [time_str] + parsed_data + [event.message.id]
        
        # 防重複
        ids = sheet.col_values(len(headers))
        if event.message.id in ids: return
        
        sheet.append_row(final_row)
        
        # 回覆邏輯
        if category == "MEMORY":
            reply = generate_human_reply(str(content) if not is_img else "[圖片]")
        else:
            reply = f"A.J，{category} 資料已依照你的表頭分類存好囉！"
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"A.J，寫入有點卡住：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
