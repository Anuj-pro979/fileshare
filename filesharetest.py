# streamlit_sender.py
import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import zlib
import math
import uuid

# ---------------- Firebase Init ----------------
def init_db_from_secrets():
    sa_json = st.secrets.get("firebase_service_account")
    if not sa_json:
        raise RuntimeError("Missing firebase_service_account in Streamlit secrets")
    sa = json.loads(sa_json)

    # fix escaped newlines if the key was pasted with literal backslash-n
    if "private_key" in sa and isinstance(sa["private_key"], str):
        sa["private_key"] = sa["private_key"].replace("\\n", "\n")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(sa)
        app = firebase_admin.initialize_app(cred)

    db = firestore.client(app=app)
    return db

# initialize Firebase
try:
    db = init_db_from_secrets()
    st.success("✅ Firebase initialized")
except Exception as e:
    st.error("❌ Firebase init failed: " + str(e))
    st.stop()

# ---------------- Helper Functions ----------------
def compress_and_encode(file_bytes):
    compressed = zlib.compress(file_bytes)
    encoded = base64.b64encode(compressed).decode('utf-8')
    return encoded

def chunk_text(text, chunk_size=900000):  # 900k per document ~ safe for Firestore
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def send_file_to_firestore(file_bytes, file_name):
    encoded_text = compress_and_encode(file_bytes)
    chunks = chunk_text(encoded_text)
    file_id = str(uuid.uuid4())

    # Write chunks
    for idx, chunk in enumerate(chunks):
        doc_ref = db.collection("files").document(f"{file_id}_{idx}")
        doc_ref.set({
            "file_name": file_name,
            "chunk_index": idx,
            "total_chunks": len(chunks),
            "data": chunk
        })

    # Health check
    try:
        db.collection("health_check").document("ping").set({"ok": True})
    except:
        pass

    return file_id, len(chunks)

# ---------------- Streamlit UI ----------------
st.title("🔥 File Uploader to Firestore")

uploaded_file = st.file_uploader("Select a file to upload")
if uploaded_file:
    if st.button("Send File"):
        with st.spinner("Uploading and encoding..."):
            file_bytes = uploaded_file.read()
            file_id, total_chunks = send_file_to_firestore(file_bytes, uploaded_file.name)
            st.success(f"✅ File sent! ID: {file_id}, Chunks: {total_chunks}")
