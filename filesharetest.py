# streamlit_sender.py
import streamlit as st
import json
import base64
import zlib
import math
import uuid
import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------- Firebase Initialization ----------------------
def init_firebase(sa_dict):
    try:
        app = firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(sa_dict)
        app = firebase_admin.initialize_app(cred)
    db = firestore.client(app=app)
    return db

# Load Firebase credentials from Streamlit secrets
sa_json = st.secrets["firebase_service_account"]
sa_dict = json.loads(sa_json)
db = init_firebase(sa_dict)

# ---------------------- Helper Functions ----------------------
def compress_and_encode(file_bytes):
    compressed = zlib.compress(file_bytes)
    encoded = base64.b64encode(compressed).decode("utf-8")
    return encoded

def chunk_text(text, chunk_size=500000):  # ~500KB per chunk
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def send_file_to_firestore(file_name, file_bytes):
    encoded_text = compress_and_encode(file_bytes)
    chunks = chunk_text(encoded_text)
    file_id = str(uuid.uuid4())

    for idx, chunk in enumerate(chunks):
        doc_ref = db.collection("files").document(f"{file_id}_{idx}")
        doc_ref.set({
            "file_name": file_name,
            "chunk_index": idx,
            "total_chunks": len(chunks),
            "data": chunk
        })
    return file_id, len(chunks)

# ---------------------- Streamlit UI ----------------------
st.title("📤 File Sender")

uploaded_file = st.file_uploader("Choose a file to send", type=None)

if uploaded_file:
    file_bytes = uploaded_file.read()
    st.write(f"File size: {len(file_bytes)/1024:.2f} KB")
    
    if st.button("Send File"):
        with st.spinner("Uploading..."):
            file_id, total_chunks = send_file_to_firestore(uploaded_file.name, file_bytes)
            st.success(f"✅ File sent! ID: {file_id}, Chunks: {total_chunks}")
