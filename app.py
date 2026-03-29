# --- [概要：負責 LINE 接收、分流，以及渲染深色高質感 Web 控制台的代碼] ---
import os
import io
from datetime import datetime
from flask import Flask, request, abort, session, render_template_string, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

import config
import sheets_handler
import brain

app = Flask(__name__)
app.secret_key = os.urandom(24) # 用於保護網頁 Session

line_bot_api = LineBotApi(config.LINE_TOKEN)
handler = WebhookHandler(config.LINE_SECRET)

# --- [概要：深色都會風 Web 控制台的 HTML/CSS 介面代碼] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A.J. Office | 私密控制台</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .container { max-width: 600px; margin-top: 10vh; }
        .card { background-color: #1e1e1e; border: 1px solid #333; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .form-control { background-color: #2c2c2c; border: 1px solid #444; color: #fff; }
        .form-control:focus { background-color: #333; color: #fff; border-color: #666; box-shadow: none; }
        .btn-primary { background-color: #4a4a4a; border: none; }
        .btn-primary:hover { background-color: #5a5a5a; }
        .upload-area { border: 2px dashed #555; border-radius: 10px; padding: 40px; text-align: center; cursor: pointer; transition: 0.3s; }
        .upload-area:hover { border-color: #888; background-color: #252525; }
        #status-box { font-size: 0.9em; color: #aaa; margin-top: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card p-4">
            <h3 class="text-center mb-4">A.J. 專屬數位中樞</h3>
            {% if not logged_in %}
            <form action="/aj-office/login" method="POST">
                <div class="mb-3">
                    <input type="password" name="pin" class="form-control text-center" placeholder="請輸入 PIN 碼解鎖" required>
                </div>
                <button type="submit" class="btn btn-primary w-100">驗證身份</button>
            </form>
            {% else %}
            <h5 class="mb-3 text-center">公務批次上傳區</h5>
            <form action="/aj-office/upload" method="POST" enctype="multipart/form-data">
                <div class="upload-area mb-3" onclick="document.getElementById('fileInput').click()">
                    <p class="mb-0">點擊此處選擇檔案，或將護照圖片拖曳至此</p>
                    <input type="file" id="fileInput" name="files" style="display: none;" multiple accept="image/*" onchange="this.form.submit()">
                </div>
            </form>
            <div id="status-box" class="text-center">{{ status_msg }}</div>
            <div class="text-center mt-4"><a href="/aj-office/logout" class="text-muted text-decoration-none">鎖定並登出</a></div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

# --- [概要：處理 Web 控制台路由與權限驗證的代碼] ---
@app.route('/aj-office', methods=['GET'])
def office_dashboard():
    logged_in = session.get('aj_logged_in', False)
    status_msg = request.args.get('status', '系統待命中，支援多檔案批次上傳。')
    return render_template_string(HTML_TEMPLATE, logged_in=logged_in, status_msg=status_msg)

@app.route('/aj-office/login', methods=['POST'])
def office_login():
    if request.form.get('pin') == config.WEB_PIN:
        session['aj_logged_in'] = True
        session.permanent = True # 配合 config 的長效設定
    return redirect('/aj-office')

@app.route('/aj-office/logout', methods=['GET'])
def office_logout():
    session.pop('aj_logged_in', None)
    return redirect('/aj-office')

@app.route('/aj-office/upload', methods=['POST'])
def office_upload():
    # --- [概要：處理電腦端上傳，辨識後寫入並釋放記憶體的代碼] ---
    if not session.get('aj_logged_in'): return abort(403)
    
    files = request.files.getlist('files')
    success_count = 0
    now_str = datetime.now(config.TW_TZ).strftime('%Y-%m-%d %H:%M')
    
    for file in files:
        if file.filename == '': continue
        img_b = {"mime_type": file.mimetype, "data": file.read()}
        
        # 交給大腦解析
        res = brain.analyze_intent(img_b, is_image=True, source="Web控制台")
        cat = res.get('category', 'BUSINESS')
        
        # 寫入試算表
        parsed_data = res.get('parsed_data', ["[圖片辨識內容]"])
        # 生成一個虛擬的 msg_id 用於防重複
        fake_msg_id = f"web_{datetime.now().timestamp()}"
        
        if sheets_handler.write_to_dynamic_sheet(cat, parsed_data, fake_msg_id, now_str):
            success_count += 1
            
        # 物理抹除：透過刪除變數釋放記憶體參考
        del img_b
        del file
        
    return redirect(f'/aj-office?status=成功處理 {success_count} 份公務檔案。')

# --- [概要：LINE Webhook 總入口代碼] ---
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

    # 1. 大腦分析與意圖判斷
    res = brain.analyze_intent(content_input, is_image=is_img, source="LINE")
    cat = res['category']
    
    # 2. 處理資料與路由
    if cat == "Chat" and res.get('is_action'):
        # 如果是查詢天氣等動作，直接回覆，並存入記憶區
        reply = res.get('reply', 'A.J.，這我處理好了。')
        sheets_handler.write_to_dynamic_sheet("Chat", [str(content_input)], event.message.id, now_str)
    else:
        # 依照分類寫入對應的動態表頭
        data = res.get('parsed_data', [str(content_input) if not is_img else "[圖片]"])
        sheets_handler.write_to_dynamic_sheet(cat, data, event.message.id, now_str)
        reply = res.get('reply', f"A.J.，{cat} 的資料已歸檔。")

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    
    # 釋放圖片記憶體
    if is_img:
        del content_input

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
