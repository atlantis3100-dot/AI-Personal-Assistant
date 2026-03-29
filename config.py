# --- [概要：統一管理身分驗證 PIN 碼、API 金鑰與改名後的試算表映射代碼] ---
import os
import pytz

# 時區設定
TW_TZ = pytz.timezone('Asia/Taipei')

# 隱私安全設定
WEB_PIN = "123456"  # 這是電腦版控制台的密碼，A.J. 之後可以在這裡修改
ADMIN_SESSION_TIME = 3600  # 登入有效時間 (秒)，目前設為 1 小時

# API 金鑰 (由 Render 環境變數讀取)
LINE_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')

# 試算表 ID 映射 (已依 A.J. 要求改名)
SHEET_IDS = {
    "BUSINESS": os.environ.get('ID_BUSINESS'),
    "帳務": os.environ.get('ID_PRIVATE'),  # 原 PRIVATE
    "CARD": os.environ.get('ID_CARD'),
    "Chat": os.environ.get('ID_MEMORY')    # 原 MEMORY
}

# 助理人設
try:
    with open('persona.txt', 'r', encoding='utf-8') as f:
        PERSONA = f.read().strip()
except:
    PERSONA = "你是一位30歲專業男性特助，老闆是 A.J。相處像朋友，語氣溫暖俐落帶點幽默。嚴禁使用 Markdown。"
