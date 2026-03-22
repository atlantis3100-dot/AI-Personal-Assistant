import os
import time
import re
import json
import hashlib
import gspread
from flask import Flask, request, abort
from google.oauth2.service_account import Credentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage, FileMessage

app = Flask(__name__)

# --- 資安強化：金鑰鎖入環境變數 (符合原則 3) ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
# Google Sheets Credentials JSON 字符串存於環境變數中
GOOGLE_SHEETS_CREDS_JSON = os.environ.get('GOOGLE_SHEETS_CREDS_JSON')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 資料庫配置 (雙 Sheets 分流) ---
# 這些名稱需要與老闆建立的實體 Sheets 一致
BRAIN_DB_NAME = "助理大腦資料庫"
WORK_DB_NAME = "公務作業中心"

#正規表達式：護照格式 (英文字母+8位數字)
PASSPORT_REGEX = re.compile(r'[A-Z][0-9]{8}')

# --- Google Sheets 授權 (記憶不失憶核心) ---
def get_sheets_client():
    creds_dict = json.loads(GOOGLE_SHEETS_CREDS_JSON)
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

# --- 完善步驟：隱私指紋化 & 查重 (Hashing) ---
def generate_fingerprint(text):
    """產生不可逆的 SHA-256 指紋。"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def check_duplicate_and_save_work(passport_id):
    """(私有) 比對指紋防重複，兼顧功能與隱私。"""
    sheets_client = get_sheets_client()
    sh = sheets_client.open(BRAIN_DB_NAME)
    # 分頁 4: 隱私指紋表
    ws_fingerprint = sh.worksheet("隱私指紋表")
    
    fingerprint = generate_fingerprint(passport_id)
    existing_fingerprints = ws_fingerprint.col_values(1) # 假設指紋在第一欄

    if fingerprint in existing_fingerprints:
        return True # 重複了
    
    # 若不重複，記錄指紋 (不存原碼)
    ws_fingerprint.append_row([fingerprint, time.strftime("%Y-%m-%d %H:%M:%S")])
    return False

# --- 完善步驟：關鍵字遮罩與記憶儲存 ---
def mask_sensitive_info(text):
    """將護照號碼替換為遮罩文字。"""
    return PASSPORT_REGEX.sub("[敏感資訊已遮蔽]", text)

def save_chat_history(user_id, role, content):
    """將對話紀錄存入 Sheets (分頁 1: 對話紀錄)。"""
    # 執行遮罩
    safe_content = mask_sensitive_info(content)
    
    sheets_client = get_sheets_client()
    sh = sheets_client.open(BRAIN_DB_NAME)
    ws_history = sh.worksheet("對話紀錄")
    
    # 只存 50 句邏輯需要在 Sheets 端手動維護或另寫清理代碼，
    # 這邊先實作簡單寫入，以不失憶為優先。
    ws_history.append_row([user_id, role, safe_content, time.strftime("%Y-%m-%d %H:%M:%S")])

# --- 完善步驟：模擬真人延遲 (Anti-Bot) ---
def simulate_human_delay():
    """原則 5：模擬真人行為，隨機延遲 1-3 秒。"""
    import random
    time.sleep(random.uniform(1.0, 3.0))

# ---身分鎖 ---
MY_UID = 'U89456930d66887538a7c645b0a3bebd4'

# --- Webhook 主程序 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 文字訊息處理 (含遮罩、記憶、查重、增欄詢問概念) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    simulate_human_delay() # 模擬延遲
    
    user_id = event.source.user_id
    user_message = event.message.text
    
    # 身分鎖檢查
    if user_id != MY_UID:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="[偽裝] 哈哈，你好，期待為您服務！"))
        return

    # 保存老闆的訊息 (已遮罩)
    save_chat_history(user_id, "user", user_message)

    # 查重邏輯實測 (假設老闆傳來護照號碼)
    passport_match = PASSPORT_REGEX.search(user_message)
    if passport_match:
        passport_id = passport_match.group(0)
        is_duplicate = check_duplicate_and_save_work(passport_id)
        
        if is_duplicate:
            response_text = f"老闆，這本護照 ({mask_sensitive_info(passport_id)}) 之前辨識過了喔！"
        else:
            response_text = f"收到，護照 ({mask_sensitive_info(passport_id)}) 指紋已記錄，防重複偵測已啟動。"
            # 這邊之後要縫合「寫入公務作業中心」的邏輯
    
    # 動態增欄詢問概念 (模擬情境)
    elif "統編" in user_message and "增加欄位" not in user_message:
         response_text = "老闆，偵測到訊息含有『統編』，需要幫您在支出試算表自動增加一欄嗎？"

    else:
        response_text = "收到老闆指令！大腦與 Sheets 記憶連線正常。"

    # 保存並回應助理的訊息 (已遮罩)
    save_chat_history(user_id, "assistant", response_text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))

@app.route("/", methods=['GET'])
def index():
    return "AI特助永久雲端屋 - 連線正常"

if __name__ == "__main__":
    app.run()
