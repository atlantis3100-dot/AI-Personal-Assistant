# --- [概要：處理 50 行對話記憶抓取、讀取動態表頭與執行安全寫入的代碼] ---
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_JSON, SHEET_IDS

def get_sheet_client():
    # 建立與 Google Sheets 的安全連線
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON), scope)
    return gspread.authorize(creds)

def get_last_50_chats():
    # --- [從 Chat 表中抓取最後 50 行紀錄，提供給 2.5 API 作為情境記憶] ---
    try:
        client = get_sheet_client()
        sheet = client.open_by_key(SHEET_IDS["Chat"]).get_worksheet(0)
        values = sheet.get_all_values()
        if len(values) > 1:
            # 僅保留時間與內容欄位
            history = values[-50:]
            return "\n".join([f"{r[0]}: {r[1]}" for r in history])
    except:
        return "尚無過去紀錄。"
    return ""

def write_to_dynamic_sheet(category, data_content, msg_id, time_str):
    # --- [依照表頭自動對齊並寫入資料，具備重複 ID 檢查機制] ---
    try:
        client = get_sheet_client()
        sheet = client.open_by_key(SHEET_IDS[category]).get_worksheet(0)
        headers = sheet.row_values(1) or ["時間", "內容", "訊息ID"]
        
        # 檢查是否已存在相同的訊息 ID，避免重複寫入
        existing_ids = sheet.col_values(len(headers))
        if msg_id in existing_ids:
            return False
            
        # 組合行資料 (時間 + AI 解析的各欄位資料 + ID)
        row = [time_str] + data_content + [msg_id]
        sheet.append_row(row)
        return True
    except Exception as e:
        print(f"寫入出錯: {e}")
        return False
