# --- [概要：總調度中心。更新為「護照辨識系統」風格：深色高科技質感、毛玻璃卡片與漸層按鈕。] ---
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

# --- [UI 更新概要：完全移植「護照辨識系統」之配色與質感設定] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A.J. Office | 專業公務中樞</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
      /* 參考背景設定：深色漸層 [cite: 228] */
      body {
        font-family: 'Noto Sans TC', sans-serif;
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        margin: 0;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
        color: #f8fafc;
      }
      /* 參考卡片設定：毛玻璃質感與深色漸層 [cite: 230, 231, 232] */
      .card {
        background: linear-gradient(145deg, rgba(45, 55, 72, 0.95), rgba(26, 32, 44, 0.95));
        backdrop-filter: blur(12px);
        padding: 40px 35px;
        border-radius: 20px;
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6), inset 0 1px 1px rgba(255, 255, 255, 0.15);
        border: 1px solid rgba(148, 163, 184, 0.2);
        width: 100%;
        max-width: 450px;
        text-align: center;
      }
      h2 {
        color: #38bdf8; /* 參考標題色 [cite: 233] */
        font-weight: 500;
        letter-spacing: 1.5px;
        margin-bottom: 30px;
        text-shadow: 0 2px 4px rgba(0,0,0,0.5);
      }
      /* 參考上傳區域設定 [cite: 238, 239, 241] */
      .upload-area {
        padding: 45px 20px;
        background: linear-gradient(145deg, rgba(30, 41, 59, 0.6), rgba(15, 23, 42, 0.8));
        border: 2px dashed #475569;
        border-radius: 16px;
        cursor: pointer;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
        margin-bottom: 25px;
      }
      .upload-area:hover {
        border-color: #10b981;
        transform: scale(1.02);
        background: linear-gradient(145deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 1));
      }
      .upload-area span { display: block; font-size: 18px; color: #cbd5e1; font-weight: 500; }
      .upload-area small { display: block; margin-top: 10px; color: #64748b; font-size: 13px; }

      /* 參考按鈕設定：藍綠漸層 [cite: 246, 247, 248, 250] */
      button {
        background: linear-gradient(135deg, #0ea5e9 0%, #10b981 100%);
        color: white;
        border: none;
        padding: 16px 28px;
        border-radius: 12px;
        font-size: 18px;
        font-weight: 500;
        cursor: pointer;
        width: 100%;
        transition: all 0.3s ease;
        box-shadow: 0 6px 15px rgba(16, 185, 129, 0.2);
      }
      button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 20px rgba(16, 185, 129, 0.3);
      }
      /* 參考狀態列設定 [cite: 254] */
      .status-item {
        margin-top: 25px;
        padding: 14px 16px;
        background: rgba(15, 23, 42, 0.8);
        border-radius: 10px;
        border-left: 4px solid #38bdf8;
        font-size: 14px;
        text-align: left;
      }
      .logout-link { margin-top: 30px; display: block; color: #64748b; text-decoration: none; font-size: 13px; }
      .logout-link:hover { color: #38bdf8; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2>🗄️ A.J. 專業公務中樞</h2>
      
      {% if error_msg %}
      <div class="status-item" style="border-left-color: #ef4444; text-align: center;">
        <div style="font-size: 2rem; margin-bottom: 10px;">⚠️</div>
        {{ error_msg }}
      </div>
      <a href="/" class="logout-link">返回</a>
      {% else %}
      <form action="/aj-office/upload" method="POST" enctype="multipart/form-data">
        <div class="upload-area" onclick="document.getElementById('fileInput').click()">
          <span>📁 點擊或拖曳檔案至此</span>
          <small>支援護照、公務文件批次辨識</small>
          <input type="file" id="fileInput" name="files" style="display: none;" multiple accept="image/*" onchange="this.form.submit()">
        </div>
        <button type="button" onclick="document.getElementById('fileInput').click()">啟動智慧辨識</button>
      </form>
      
      <div class="status-item">
        {{ status_msg }}
      </div>
      
      <a href="/aj-office/logout" class="logout-link">🔒 銷毀憑證並登出</a>
      {% endif %}
    </div>
  </body>
</html>
"""

# --- [下方的邏輯代碼維持不變，確保功能穩定] ---
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
            return render_template_string(HTML_TEMPLATE, error_msg="安全憑證已失效或過期，請透過 LINE 重新索取。")

    if not session.get('aj_logged_in'):
        return render_template_string(HTML_TEMPLATE, error_msg="未經授權的存取。此為私密通道，請從 LINE 獲取鑰匙。")
        
    status_msg = request.args.get('status', '系統待命中。資料辨識後將立即物理抹除。')
    return render_template_string(HTML_TEMPLATE, status_msg=status_msg)

@app.route('/aj-office/logout', methods=['GET'])
def office_logout():
    session.pop('aj_logged_in', None)
    return redirect('/aj-office')

@app.route('/aj-office/upload', methods=['POST'])
def office_upload():
    if not session.get('aj_logged_in'): return abort(403)
    files = request.files.getlist('files')
    success_count = 0
    now_str = datetime.now(config.TW_TZ).strftime('%Y-%m-%d %H:%M')
    for file in files:
        if file.filename == '': continue
        img_b = {"mime_type": file.mimetype, "data": file.read()}
        res = brain.analyze_intent(img_b, is_image=True, source="Web控制台")
        cat = res.get('category', 'BUSINESS')
        parsed_data = res.get('parsed_data', ["[圖片辨識內容]"])
        fake_msg_id = f"web_{uuid.uuid4().hex[:8]}"
        if sheets_handler.write_to_dynamic_sheet(cat, parsed_data, fake_msg_id, now_str):
            success_count += 1
        del img_b
        del file
    return redirect(f'/aj-office?status=✅ 成功辨識 {success_count} 筆資料並存入試算表。')

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
    res = brain.analyze_intent(content_input, is_image=is_img, source="LINE")
    cat = res.get('category', 'Chat')
    if cat == "SYSTEM_LINK":
        new_token = str(uuid.uuid4())
        secure_tokens[new_token] = time.time() + 3600
        base_url = request.host_url.rstrip('/')
        secure_link = f"{base_url}/aj-office?token={new_token}"
        reply = res.get('reply', 'A.J.，為您開啟專屬安全通道（1小時效期）：') + f"\n{secure_link}"
    elif cat == "Chat" and res.get('is_action'):
        reply = res.get('reply', 'A.J.，這我處理好了。')
        sheets_handler.write_to_dynamic_sheet("Chat", [str(content_input)], event.message.id, now_str)
    else:
        data = res.get('parsed_data', [str(content_input) if not is_img else "[圖片已處理]"])
        sheets_handler.write_to_dynamic_sheet(cat, data, event.message.id, now_str)
        reply = res.get('reply', f"A.J.，{cat} 的資料已歸檔。")
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    if is_img: del content_input

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
