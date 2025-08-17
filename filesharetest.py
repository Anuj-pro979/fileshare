# streamlit_sender.py
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import json, base64, zlib, uuid, time

# ---------------- Firebase Init ----------------
def init_db():
    sa_json = st.secrets.get("firebase_service_account")
    sa = json.loads(sa_json)
    if "private_key" in sa:
        sa["private_key"] = sa["private_key"].replace("\\n", "\n")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(sa)
        app = firebase_admin.initialize_app(cred)

    return firestore.client(app)

db = init_db()
st.success("✅ Firebase initialized")

# ---------------- Helper ----------------
def compress_and_encode(file_bytes):
    compressed = zlib.compress(file_bytes)
    return base64.b64encode(compressed).decode("utf-8")

def chunk_text(text, chunk_size=900000):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def send_file(file_bytes, file_name, sender_id, receiver_id):
    encoded = compress_and_encode(file_bytes)
    chunks = chunk_text(encoded)
    file_id = str(uuid.uuid4())

    # Store file chunks
    for idx, chunk in enumerate(chunks):
        db.collection("files").document(f"{file_id}_{idx}").set({
            "file_name": file_name,
            "chunk_index": idx,
            "total_chunks": len(chunks),
            "data": chunk
        })

    # Create notification
    notif_id = f"{receiver_id}_{int(time.time())}"
    db.collection("notifications").document(notif_id).set({
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "file_id": file_id,
        "file_name": file_name,
        "status": "new"
    })
    return file_id

# ---------------- UI ----------------
st.title("📤 File Sender")

sender_id = st.text_input("Your Sender ID (UUID)", value=str(uuid.uuid4()))
receiver_id = st.text_input("Receiver ID (UUID)")

uploaded_file = st.file_uploader("Upload file")
if uploaded_file and st.button("Send"):
    file_id = send_file(uploaded_file.read(), uploaded_file.name, sender_id, receiver_id)
    st.success(f"✅ File sent! ID: {file_id}")
