# server.py
import os, json, time, base64, requests
from flask import Flask, request, redirect, jsonify
from dotenv import load_dotenv

load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")       # will be set to your ngrok url + /callback
# PORT = int(os.getenv("PORT", "8888"))
TOKENS_FILE = "tokens.json"

app = Flask(__name__)

# in-memory cache
access_token = None
access_expires = 0
refresh_token = None

def save_tokens():
    with open(TOKENS_FILE, "w") as f:
        json.dump({
            "refresh_token": refresh_token,
            "access_token": access_token,
            "access_expires": access_expires
        }, f)

def load_tokens():
    global refresh_token, access_token, access_expires
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, "r") as f:
            data = json.load(f)
            refresh_token = data.get("refresh_token")
            access_token = data.get("access_token")
            access_expires = data.get("access_expires", 0)

def exchange_code_for_token(code):
    token_url = "https://accounts.spotify.com/api/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    r = requests.post(token_url, data=payload)
    r.raise_for_status()
    return r.json()

def refresh_access_token_if_needed():
    global access_token, access_expires, refresh_token
    if not refresh_token:
        return False
    if access_token and time.time() < access_expires - 60:
        return True
    token_url = "https://accounts.spotify.com/api/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    r = requests.post(token_url, data=payload)
    r.raise_for_status()
    tok = r.json()
    access_token = tok.get("access_token")
    expires_in = tok.get("expires_in", 3600)
    access_expires = time.time() + expires_in
    save_tokens()
    return True

@app.route("/")
def index():
    return "Spotify small backend. Visit /login to authenticate."

@app.route("/login")
def login():
    scope = "user-read-currently-playing user-read-playback-state"
    auth_url = (
        "https://accounts.spotify.com/authorize"
        f"?response_type=code&client_id={CLIENT_ID}"
        f"&scope={scope}&redirect_uri={REDIRECT_URI}"
    )
    return redirect(auth_url)

@app.route("/callback")
def callback():
    global refresh_token, access_token, access_expires
    code = request.args.get("code")
    if not code:
        return "Missing code parameter", 400
    try:
        tok = exchange_code_for_token(code)
    except Exception as e:
        return f"Token exchange failed: {e}", 500
    refresh_token = tok.get("refresh_token")
    access_token = tok.get("access_token")
    expires_in = tok.get("expires_in", 3600)
    access_expires = time.time() + expires_in
    save_tokens()
    return "Login successful. You can close this tab."

@app.route("/track")
def track():
    load_tokens()
    if not refresh_token:
        return jsonify({"error": "no_refresh_token", "msg": "Please visit /login to authenticate first."}), 400
    try:
        if not refresh_access_token_if_needed():
            return jsonify({"error": "refresh_failed"}), 500
    except Exception as e:
        return jsonify({"error":"refresh_error","msg":str(e)}), 500

    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://api.spotify.com/v1/me/player/currently-playing", headers=headers)
    if r.status_code == 204:
        return jsonify({"error":"no_content","msg":"Nothing playing"}), 204
    if r.status_code != 200:
        return jsonify({"error":"spotify_error","status": r.status_code, "body": r.text}), r.status_code
    data = r.json()
    item = data.get("item", {})
    song = item.get("name", "")
    artists = ", ".join([a.get("name","") for a in item.get("artists",[])])
    album = item.get("album",{}).get("name","")
    image = item.get("album",{}).get("images",[{}])[0].get("url","")
    is_playing = data.get("is_playing", False)
    progress_ms = data.get("progress_ms", 0)
    duration_ms = item.get("duration_ms", 0)
    return jsonify({
        "song": song,
        "artist": artists,
        "album": album,
        "image": image,
        "is_playing": is_playing,
        "progress_ms": progress_ms,
        "duration_ms": duration_ms
    })

@app.route("/cover")
def cover():
    load_tokens()
    if not refresh_access_token_if_needed():
        return "Auth error", 401

    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://api.spotify.com/v1/me/player/currently-playing", headers=headers)
    if r.status_code != 200:
        return "Spotify error", r.status_code
    data = r.json()
    item = data.get("item", {})
    image_url = item.get("album", {}).get("images", [{}])[0].get("url", "")
    if not image_url:
        return "No image", 404

    # Fetch the image bytes directly
    img_r = requests.get(image_url)
    if img_r.status_code != 200:
        return "Image fetch failed", img_r.status_code

    # Return raw JPEG with correct headers
    from flask import Response
    return Response(img_r.content, mimetype="image/jpeg")

if __name__ == "__main__":
    load_tokens()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=5000)
