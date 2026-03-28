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

# --- [概要：讀取 persona.txt 作為 30 歲專業男性特助人設的代碼] ---
try:
    with open('persona.txt', 'r', encoding='utf-8') as f:
        PERSONA_SETUP = f.read().strip()
except Exception:
    PERSONA_SETUP = "你現在是一位30歲的男性專業特助。你的老闆叫做「A.J」。風格俐落、高效率，但待人溫暖。嚴禁使用Markdown。"

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

# --- [概要：專為 MEMORY 類別設計，根據人設生成自然口語回覆的代碼] ---
def generate_human_reply(details):
    model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=PERSONA_SETUP)
    prompt = f"老闆 A.J 剛才傳了這段內容給我：{details}。請用你的人設（30歲男性特助，幽默溫暖的事業夥伴）簡短地回覆他。嚴禁使用任何 Markdown 符號（如 ** 或 ```），語氣要自然。"
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return f"A.J，這件事我幫你記下來了！"

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

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    img_data = io.BytesIO(message_content.content)
    img_b = {"mime_type": "image/jpeg", "data": img_data.getvalue()}
    
    category = ai_classify(img_b, is_image=True)
    
    if category == "CARD":
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = """請讀取這張名片，嚴格回傳一個 JSON 陣列格式，不要包含 ```json 等 markdown 標記。
        格式必須完全依照此順序：["姓名", "手機號碼", "公司電話", "公司名稱", "職稱與服務項目"]。
        如果找不到某項目，請填 "無" """
        res = model.generate_content([prompt, img_b])
        try:
            clean_txt = res.text.strip().replace('```json', '').replace('```', '').strip()
            clean_msg = json.loads(clean_txt)
        except:
            clean_msg = ["解析失敗", "無", "無", "無", res.text]
    else:
        clean_msg = "[圖片內容]"

    save_to_sheet(event, category, clean_msg, event.message.id)

# --- [概要：統一寫入試算表，並根據 B 選項進行效率與閒聊分離回覆的代碼] ---
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
        
        # 名片處理
        if category == "CARD" and isinstance(content, list):
            if not records:
                sheet.append_row(["時間", "姓名", "手機號碼", "公司電話", "公司名稱", "職稱與服務項目", "訊息ID"])
                records = sheet.get_all_values()
            row_data = [time_str] + content + [msg_id]
            reply_text = f"A.J，名片建檔好囉！\n姓名：{content[0]}\n公司：{content[3]}"
            
        else:
            if not records:
                sheet.append_row(["時間", "內容", "訊息ID"])
                records = sheet.get_all_values()
            row_data = [time_str, str(content), msg_id]
            
            # 選項 B：分離邏輯
            if category == "MEMORY":
                reply_text = generate_human_reply(str(content))
            elif category == "BUSINESS":
                reply_text = f"A.J，公務資料已記錄。\n內容：{content}"
            elif category == "PRIVATE":
                reply_text = f"A.J，這筆帳幫你記下了。\n內容：{content}"
            else:
                reply_text = f"已記錄：{content}"
            
        if records and msg_id in [row[-1] for row in records]: return
        
        sheet.append_row(row_data)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"A.J，有點小狀況喔，稍等我一下：{str(e)}"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
