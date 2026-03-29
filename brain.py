# 概要：這是系統的大腦核心，負責判斷 A.J. 的意圖，並加入了辨識「索取辦公室連結」的新功能代碼。
import json
import google.generativeai as genai
import config
import sheets_handler

genai.configure(api_key=config.GEMINI_KEY)

def analyze_intent(content, is_image=False, source="LINE"):
    # 概要：讀取過去 50 行記憶，並透過 2.5 API 進行語意分析與路由分類的代碼。
    model = genai.GenerativeModel('gemini-2.5-flash')
    history = sheets_handler.get_last_50_chats()
    
    system_prompt = f"""
    系統設定：{config.PERSONA}
    現在老闆 A.J. 傳來了一則訊息。來源是：{source}。
    請嚴格依照以下邏輯判斷意圖：
    1. 如果內容是買東西、花錢、收支，分類為 '帳務'。
    2. 如果是名片照片，分類為 'CARD'。
    3. 如果是公務、護照、移工相關，分類為 'BUSINESS'。
    4. 如果老闆要求「給辦公室連結、上傳公務、開啟控制台」，分類為 'SYSTEM_LINK'。
    5. 其餘如問天氣、查資料、純聊天，一律為 'Chat'。
    
    【動作指令】：
    如果是 'Chat' 且老闆在詢問資訊（如天氣、翻譯），請直接為他解答，將 is_action 設為 true，並把答案寫在 reply 中。
    如果是 'SYSTEM_LINK'，請將 is_action 設為 true，reply 寫「A.J.，為您開啟專屬安全通道：」。
    
    請回傳嚴格的 JSON 格式：
    {{"category": "代碼", "is_action": true/false, "reply": "回覆給老闆的話", "parsed_data": ["依照表頭解析的陣列資料"]}}
    嚴禁使用任何 Markdown 標記。
    """
    
    try:
        if is_image:
            res = model.generate_content([system_prompt, content])
        else:
            res = model.generate_content(f"{system_prompt}\n過去對話記憶：\n{history}\n\n當前內容：{content}")
            
        clean_json = res.text.strip().replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        # 概要：防止 API 發生錯誤時系統崩潰的備用回覆代碼。
        print(f"大腦解析錯誤: {e}")
        return {"category": "Chat", "is_action": False, "reply": "A.J.，我稍微恍神了一下，這筆資料我先記下來了。", "parsed_data": []}
