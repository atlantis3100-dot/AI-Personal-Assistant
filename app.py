# --- [概要：總調度中心。更新了介面配色，改為乾淨專業、帶有「Gemini藍」點綴的明亮 Google 風格。] ---
import os
import io
import uuid
import time
from datetime import datetime
from flask import Flask, request, abort, session, render_template_string, redirect
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

import config
import sheets_handler
import brain

app = Flask(__name__)
app.secret_key = os.urandom(24) 

line_bot_api = LineBotApi(config.LINE_TOKEN)
handler = WebhookHandler(config.LINE_SECRET)

secure_tokens = {}

# --- [CSS 更新概要：參考 Gemini/GAS 風格，改為純白背景、俐落 Cool-gray 字體、搭配明亮 Gemini-blue 作為 Active 顏色] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A.J. Office | 專屬數位中樞</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        body { 
            background-color: #FFFFFF; /* 純白背景，明亮俐落 */
            color: #202124; /* Google 標準深灰文字 */
            font-family: 'Roboto', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            -webkit-font-smoothing: antialiased;
        }
        .container { max-width: 650px; margin-top: 10vh; }
        .card { 
            background-color: #FFFFFF; 
            border: 1px solid #DADCE0; /* 極淡的框線，符合 Google 原生 Material 質感 */
            border-radius: 16px; /* 更圓潤的角，更有現代 App 感 */
            box-shadow: 0 4px 6px rgba(0,0,0,0.05), 0 1px 3px rgba(0,0,0,0.1); /* 柔和的陰影 */
        }
        h3.title { 
            color: #1A73E8; /* 特有的明亮 Gemini-blue / GCP-blue */
            font-weight: 500;
        }
        .btn-primary { 
            background-color: #1A73E8; /* Gemini-blue */
            border: none; 
            border-radius: 8px;
            padding: 10px 24px;
            font-weight: 500; 
            transition: 0.2s background-color;
        }
        .btn-primary:hover { background-color: #174EA6; }
        .upload-area { 
            border: 2px dashed #DADCE0; 
            border-radius: 12px; 
            padding: 60px 20px; 
            text-align: center; 
            cursor: pointer; 
            transition: 0.3s background-color, 0.3s border-color; 
            background-color: #F8F9FA; /* cool-gray 淺灰背景 */
            color: #5F6368; /* secondary text cool-gray */
        }
        .upload-area:hover { 
            border-color: #1A73E8; /* 懸停時亮起藍色框線 */
            background-color: #E8F0FE; /* 懸停時染上一層極淡的藍色，專業互動感 */
            color: #1967D2;
        }
        .error-box { text-align: center; padding: 40px 20px; }
        .error-icon { font-size: 3.5rem; color: #D93025; margin-bottom: 25px; } /* Google-red 錯誤圖示 */
        #status-box { font-size: 0.95em; color: #616161; margin-top: 20px; }
        .footer-link { font-size: 0.9em; color: #70757A; }
        .footer-link:hover { color: #202124; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card p-4 p-md-5">
            <h3 class="text-center mb-5 title">A.J. Office</h3>
            
            {% if error_msg %}
            <div class="error-box">
                <div class="error-icon">⚠️</div>
                <h5 style="color: #202124; font-weight: 500;">存取被拒絕</h5>
                <p class="text-muted mt-3" style="color: #5F6368;">{{ error_msg }}</p>
            </div>
            {% else %}
            <h6 class="mb-4 text-center" style="color: #5F6368; font-weight: 500;">公務批次安全上傳區 (Gemini 解析)</h6>
            <form action="/aj-office/upload" method="POST" enctype="multipart/form-data">
                <div class="upload-area mb-3" onclick="document.getElementById('fileInput').click()">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="mb-3">
                        <path d="M14 2H6C4.89 2 4 2.9 4 4V20C4 21.1 4.89 22 6 22H18C19.1 22 20 21.1 20 20V8L14 2Z" fill="#E8F0FE"/>
                        <path d="M14 2V8H20L14 2Z" fill="#AECBFA"/>
                        <path d="M16 13H8V15H16V13Z" fill="#1A73E8"/>
                        <path d="M16 17H8V19H16V17Z" fill="#1A73E8"/>
                        <path d="M12 9H8V11H12V9Z" fill="#1A73E8"/>
                    </svg>
                    <p class="mb-0" style="color: #3C4043; font-weight: 500;">將護照或公務圖片拖曳至此</p>
                    <p class="text-muted mt-1" style="font-size: 0.9em;">或點擊此處選擇檔案</p>
                    <input type="file" id="fileInput" name="files" style="display: none;" multiple accept="image/*" onchange="this.form.submit()">
                </div>
            </form>
            <div id="status-box" class="text-center">{{ status_msg }}</div>
            <div class="text-center mt-5 pt-4" style="border-top: 1px solid #DADCE0;">
                <a href="/aj-office/logout" class="footer-link">🔒 銷毀憑證並登出</a>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

# --- [以下邏輯維持不變，僅更新了上傳成功的回報訊息，強調安全性] ---
@app.route('/aj-office', methods=['GET'])
def office_dashboard():
    token = request.args.get('token')
    now = time.time()
    
    if token:
        if token in secure_tokens and secure_tokens[token] > now:
            session['aj_logged_in'] = True
            session.permanent = True
            del secure_tokens[token]
            return redirect('/aj-office')
        else:
            return render_template_string(HTML_TEMPLATE, error_msg="安全憑證已失效或過期，請重新索取。")

    if not session.get('aj_logged_in'):
        return render_template_string(HTML_TEMPLATE, error_msg="未經授權的存取。此為私密通道，請從 LINE 獲取鑰匙。")
        
    status_msg = request.args.get('status', '系統待命中。圖片將於辨識寫入 Sheets 後立即物理抹除，不留痕跡。')
    return render_template_string(HTML_TEMPLATE, status_msg=status_msg)

@app.route('/aj-office/logout', methods=['GET'])
def office_logout():
    session.pop('aj_logged_in', None)
    return redirect('/aj-office')

@app.route('/aj-office/upload', methods=['POST'])
def office_upload():
    if not session.get('aj_logged_in'): 
        return abort(403)
    
    files = request.files.getlist('files')
    success_count = 0
    now_str = datetime.now(config.TW_TZ).strftime('%Y-%m-%d %H:%M')
    
    for file in files:
        if file.filename == '': continue
        img_b = {"mime_type": file.mimetype, "data": file.read()}
        
        # 傳遞給大腦解析 (Web 來源強制歸類為 BUSINESS 邏輯)
        res = brain.analyze_intent(img_b, is_image=True, source="Web控制台")
        cat = res.get('category', 'BUSINESS')
        
        parsed_data = res.get('parsed_data', ["[圖片辨識內容]"])
        # 生成虛擬的 msg_id 用於防重複
        fake_msg_id = f"web_{uuid.uuid4().hex[:8]}"
        
        if sheets_handler.write_to_dynamic_sheet(cat, parsed_data, fake_msg_id, now_str):
            success_count += 1
            
        # 物理抹除機密資料，釋放記憶體
        del img_b
        del file
        
    return redirect(f'/aj-office?status=✅ 成功辨識 {success_count} 份檔案，個資已從伺服器抹除。')

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
def handle_msg(event):
    now_str = datetime.now(config.TW_TZ).strftime('%Y-%m-%d %H:%M')
    is_img = event.message.type == "image"
    
    if is_img:
        msg_content = line_bot_api.get_message_content(event.message.id)
        content_input = {"mime_type": "image/jpeg", "data": io.BytesIO(msg_content.content).getvalue()}
    else:
        content_input = event.message.text

    # 1. 呼叫大腦進行意圖判斷
    res = brain.analyze_intent(content_input, is_image=is_img, source="LINE")
    cat = res.get('category', 'Chat')
    
    # 2. 處理資料與路由
    if cat == "SYSTEM_LINK":
        new_token = str(uuid.uuid4())
        secure_tokens[new_token] = time.time() + 3600
        base_url = request.host_url.rstrip('/')
        secure_link = f"{base_url}/aj-office?token={new_token}"
        reply = res.get('reply', 'A.J.，為您開啟專屬安全通道（1小時效期）：') + f"\n{secure_link}"
        
    elif cat == "Chat" and res.get('is_action'):
        # 查詢天氣等動作，直接回覆，並存入記憶區
        reply = res.get('reply', 'A.J.，這我處理好了。')
        sheets_handler.write_to_dynamic_sheet("Chat", [str(content_input)], event.message.id, now_str)
        
    else:
        # 依照分類寫入對應的動態表頭
        data = res.get('parsed_data', [str(content_input) if not is_img else "[圖片已處理]"])
        sheets_handler.write_to_dynamic_sheet(cat, data, event.message.id, now_str)
        reply = res.get('reply', f"A.J.，{cat} 的資料已歸檔。")

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    
    if is_img:
        del content_input

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
