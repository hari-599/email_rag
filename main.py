from flask import Flask, jsonify, render_template, request

from Services.chat_application import Chat_Application

app = Flask(__name__)
chat_app = Chat_Application()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/threads")
def list_threads():
    return jsonify(chat_app.list_threads())


@app.post("/start_session")
def start_session():
    payload = request.get_json(force=True)
    return jsonify(chat_app.start_session(payload["thread_id"]))


@app.post("/ask")
def ask():
    payload = request.get_json(force=True)
    search_outside_thread = request.args.get("search_outside_thread", "false").lower() == "true"
    return jsonify(chat_app.ask(payload["session_id"], payload["text"], search_outside_thread=search_outside_thread))


@app.post("/switch_thread")
def switch_thread():
    payload = request.get_json(force=True)
    return jsonify(chat_app.switch_thread(payload["session_id"], payload["thread_id"]))


@app.post("/reset_session")
def reset_session():
    payload = request.get_json(force=True)
    return jsonify(chat_app.reset_session(payload["session_id"]))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
