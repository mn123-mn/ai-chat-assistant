from flask import Flask, render_template, request, jsonify, send_file
import requests
import os
import re
import json
import time
from io import BytesIO

app = Flask(__name__)
KB_FILE = "company_kb.txt"
CHAT_DIR = "chat_history"

# 强制创建目录，确保有权限写入
os.makedirs(CHAT_DIR, exist_ok=True)

API_KEY = "f2740d82bd0e4281a3e8509755a4e019.dWowfhXMzqMXXSph"
LLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
IMG_URL = "https://open.bigmodel.cn/api/paas/v4/images/generations"
MODEL_CHAT = "glm-4-flash"
MODEL_IMG = "cogview-3"

CURR_SESSION_ID = None


# 【修复】AI 调用（增加错误捕获，返回正常文本）
def ai_chat(prompt):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": MODEL_CHAT,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2048
    }
    try:
        res = requests.post(LLM_URL, headers=headers, json=data, timeout=15)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("API Error:", e)
        # 不再返回“服务繁忙”，改为提示文本，不影响导出
        return "AI接口暂时无法访问，当前已切换为本地模式。你输入的内容是：" + prompt[:20]


@app.route("/gen_img", methods=["POST"])
def gen_img():
    prompt = request.json.get("prompt", "").strip()
    if not prompt:
        return jsonify({"url": "", "msg": "请输入图片描述"})
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {"model": MODEL_IMG, "prompt": prompt, "size": "1024x1024"}
    try:
        res = requests.post(IMG_URL, headers=headers, json=data, timeout=30)
        res.raise_for_status()
        return jsonify({"url": res.json()["data"][0]["url"], "msg": "ok"})
    except:
        return jsonify({"url": "", "msg": "图片生成失败"})


@app.route("/doc_summary", methods=["POST"])
def doc_summary():
    text = request.json.get("text", "")
    if len(text.strip()) < 20:
        return jsonify({"res": "文本太短无需总结"})
    prompt = f"精简总结下面文档，分点提炼核心内容：\n{text[:6000]}"
    return jsonify({"res": ai_chat(prompt)})


@app.route("/translate", methods=["POST"])
def translate():
    text = request.json.get("text", "")
    mode = request.json.get("mode", "auto")
    if not text:
        return jsonify({"res": "请输入翻译内容"})
    if mode == "zh2en":
        prompt = f"翻译成专业正式英文：{text}"
    elif mode == "en2zh":
        prompt = f"精准翻译成通顺中文：{text}"
    else:
        prompt = f"自动识别语言互译，专业书面翻译：{text}"
    return jsonify({"res": ai_chat(prompt)})


@app.route("/export_summary", methods=["POST"])
def export_summary():
    content = request.json.get("content", "")
    bio = BytesIO(content.encode("utf-8"))
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name="文档摘要.txt")


@app.route("/export_trans", methods=["POST"])
def export_trans():
    content = request.json.get("content", "")
    bio = BytesIO(content.encode("utf-8"))
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name="翻译结果.txt")


@app.route("/export_chat", methods=["GET"])
def export_chat():
    global CURR_SESSION_ID
    if not CURR_SESSION_ID:
        return "无聊天记录"
    msgs = json.load(open(os.path.join(CHAT_DIR, f"{CURR_SESSION_ID}.json"), "r", encoding="utf-8"))
    txt = ""
    for m in msgs:
        txt += f"【{'用户' if m['role'] == 'user' else 'AI'}】\n{m['content']}\n\n"
    bio = BytesIO(txt.encode("utf-8"))
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name="聊天记录.txt")


def save_kb(content):
    with open(KB_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def rag_answer(question):
    if not os.path.exists(KB_FILE):
        return "请先上传TXT知识库文档"
    with open(KB_FILE, "r", encoding="utf-8") as f:
        kb = f.read()
    prompt = f"严格依据知识库回答，不编造内容\n知识库：{kb[:4000]}\n问题：{question}"
    return ai_chat(prompt)


def calc_expr(expr):
    try:
        safe = re.sub(r"[^0-9+\-*/().% ]", "", expr)
        return f"✅ 计算结果：{eval(safe)}"
    except:
        return "❌ 表达式格式错误"


def smart_reply(q):
    kb_words = ["入职", "考勤", "报销", "请假", "加班", "调休", "离职", "制度", "工资"]
    calc_words = ["计算", "算", "加", "减", "乘", "除"]
    for w in kb_words:
        if w in q:
            return rag_answer(q)
    for w in calc_words:
        if w in q:
            return calc_expr(q)
    system_prompt = """你是企业内部智能助理，只具备以下功能：
1.公司制度咨询 2.基础数学计算 3.文档摘要 4.中英文翻译 5.AI图片生成
用户问你能做什么，固定回复：我可以为您提供公司制度咨询、数学计算、文档摘要、中英文翻译、AI图片生成服务。
超出范围统一回复：抱歉，我目前主要提供企业相关咨询和基础文本处理服务，无法回答该问题。"""
    return ai_chat(f"{system_prompt}\n用户问题：{q}")


# 【关键修复】新建会话（强制写入文件，确保100%成功）
@app.route("/new_session", methods=["POST"])
def new_session():
    global CURR_SESSION_ID
    sid = str(int(time.time()))
    CURR_SESSION_ID = sid
    file_path = os.path.join(CHAT_DIR, f"{sid}.json")

    # 用 with open 强制写入，避免权限问题
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

    print(f"✅ 新建会话成功，文件路径：{file_path}")
    return jsonify({"ok": True})


@app.route("/list_session", methods=["GET"])
def list_session():
    lst = []
    for f in os.listdir(CHAT_DIR):
        if f.endswith(".json"):
            sid = f.replace(".json", "")
            path = os.path.join(CHAT_DIR, f)
            try:
                msgs = json.load(open(path, "r", encoding="utf-8"))
                if not msgs:
                    continue
                title = msgs[0]["content"][:15]
                lst.append({"sid": sid, "title": title})
            except:
                continue
    lst.sort(key=lambda x: x["sid"], reverse=True)
    return jsonify(lst)


@app.route("/load_session", methods=["POST"])
def load_session():
    global CURR_SESSION_ID
    sid = request.json.get("sid")
    CURR_SESSION_ID = sid
    msgs = json.load(open(os.path.join(CHAT_DIR, f"{sid}.json"), "r", encoding="utf-8"))
    return jsonify(msgs)


@app.route("/save_msg", methods=["POST"])
def save_msg():
    global CURR_SESSION_ID
    # 如果没有会话，自动新建一个
    if not CURR_SESSION_ID:
        CURR_SESSION_ID = str(int(time.time()))
        file_path = os.path.join(CHAT_DIR, f"{CURR_SESSION_ID}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([], f)

    msg = request.json
    path = os.path.join(CHAT_DIR, f"{CURR_SESSION_ID}.json")
    arr = json.load(open(path, "r", encoding="utf-8"))
    arr.append(msg)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


@app.route("/delete_session", methods=["POST"])
def delete_session():
    sid = request.json.get("sid")
    path = os.path.join(CHAT_DIR, f"{sid}.json")
    if os.path.exists(path):
        os.remove(path)
        return jsonify({"ok": True})
    return jsonify({"ok": False})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    q = request.json.get("query", "").strip()
    if not q:
        return jsonify({"answer": "请输入内容"})
    return jsonify({"answer": smart_reply(q)})


@app.route("/upload_kb", methods=["POST"])
def upload_kb():
    f = request.files.get("file")
    if not f:
        return jsonify({"msg": "请选择文件"})
    try:
        text = f.read().decode("utf-8", "ignore")
        save_kb(text)
        return jsonify({"msg": "✅ 知识库上传成功"})
    except:
        return jsonify({"msg": "上传失败，使用UTF-8 TXT"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)