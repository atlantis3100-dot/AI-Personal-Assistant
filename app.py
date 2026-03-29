# --- [概要：這是系統的總調度中心，負責接收 LINE 訊息、生成動態安全連結，並渲染高質感 Web 控制台的代碼] ---
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
# 概要：用於保護網頁 Session 的隨機金鑰
app.secret_key = os.urandom(24) 

line_bot_api = LineBotApi(config.LINE_TOKEN)
handler = WebhookHandler(config.LINE_SECRET)

# 概要：存放動態安全連結的暫存區。格式為 { "token_字串": 過期時間戳 }
secure_tokens = {}

# --- [概要：深色都會風 Web 控制台的 HTML/CSS 介面代碼，確保視覺專業俐落] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A.J. Office | 專屬數位中樞</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0f1015; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
        .container { max-width: 650px; margin-top: 8vh; }
        .card { background-color: #1a1c23; border: 1px solid #2d3139; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.6); }
        .btn-primary { background-color: #3b82f6; border: none; font-weight: 500; transition: 0.3s; }
        .btn-primary:hover { background-color: #2563eb; }
        .upload-area { border: 2px dashed #4b5563; border-radius: 12px; padding: 50px 20px; text-align: center; cursor: pointer; transition: 0.3s; background-color: #13141a; }
        .upload-area:hover { border-color: #3b82f6; background-color: #1a1f2e; }
        .error-box { text-align: center; padding: 40px 20px; }
        .error-icon { font-size: 3rem; color: #ef4444; margin-bottom: 20px; }
        #status-box { font-size: 0.9em; color: #9ca3af; margin-top: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card p-4 p-md-5">
            <h3 class="text-center mb-4" style="color: #f3f4f6; font-weight: 600;">A.J. Office</h3>
            
            {% if error_msg %}
            <div class="error-box">
                <div class="error-icon">⚠️</div>
                <h5 style="color: #f3f4f6;">存取被拒絕</h5>
                <p class="text-muted mt-3">{{ error_msg }}</p>
            </div>
            {% else %}
            <h5 class="mb-4 text-center" style="color: #9ca3af;">公務批次安全上傳區</h5>
            <form action="/aj-office/upload" method="POST" enctype="multipart/form-data">
                <div class="upload-area mb-3" onclick="document.getElementById('fileInput').click()">
                    <div style="font-size: 2rem; margin-bottom: 10px;">📄</div>
                    <p class="mb-0" style="color: #d1d5db;">點擊此處選擇檔案，或將護照 / 公務圖片拖曳至此</p>
                    <input type="file" id="fileInput" name="files" style="display: none;" multiple accept="image/*" onchange="this.form.submit()">
                </div>
            </form>
            <div id="status-box" class="text-center">{{ status_msg }}</div>
            <div class="text-center mt-5">
                <a href="/aj-office/logout" class="text-muted text-decoration-none" style="font-size: 0.85em;">🔒 鎖定並登出系統</a>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

# --- [概要：處理 Web 控制台路由、動態 token 驗證與權限管理的代碼] ---
@app.route('/aj-office', methods=['GET'])
def office_dashboard():
    # 檢查網址是否有帶 token
    token = request.args.get('token')
    now = time.time()
    
    # 驗證 Token 邏輯
    if token:
        if token in secure_tokens and secure_tokens[token] > now:
            # 驗證成功，核發 Session，並把該 token 刪除（確保一次性使用）
            session['aj_logged_in'] = True
            session.permanent = True
            del secure_tokens[token]
            return redirect('/aj-office') # 重新導向以隱藏網址上的 token
        else:
            return render_template_string(HTML_TEMPLATE, error_msg="連結已失效或過期，請透過 LINE 重新索取。")

    # 檢查是否已登入
    if not session.get('aj_logged_in'):
        return render_template_string(HTML_TEMPLATE, error_msg="未授權的存取。此為私密通道，請從 LINE 獲取專屬鑰匙。")
        
    status_msg = request.args.get('status', '系統待命中，支援多檔案批次上傳。資料將於分析後立即物理抹除。')
    return render_template_string(HTML_TEMPLATE, status_msg=status_msg)

@app.route('/aj-office/logout', methods=['GET'])
def office_logout():
    session.pop('aj_logged_in', None)
    return redirect('/aj-office')

@app.route('/aj-office/upload', methods=['POST'])
def office_upload():
    # --- [概要：處理電腦端上傳圖片，交由大腦辨識後寫入試算表，並徹底釋放記憶體的代碼] ---
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
            
        # 概要：物理抹除機密資料，釋放 Render 記憶體
        del img_b
        del file
        
    return redirect(f'/aj-office?status=✅ 成功處理並銷毀 {success_count} 份公務檔案。')

# --- [概要：處理 LINE Webhook 總入口與分流的代碼] ---
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
        # 概要：生成一次性、限時 1 小時的專屬連結代碼
        new_token = str(uuid.uuid4())
        secure_tokens[new_token] = time.time() + 3600
        base_url = request.host_url.rstrip('/')
        secure_link = f"{base_url}/aj-office?token={new_token}"
        reply = res.get('reply', 'A.J.，為您開啟專屬安全通道：') + f"\n{secure_link}"
        
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
    
    # 釋放圖片記憶體
    if is_img:
        del content_input

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
