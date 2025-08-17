# sender_streamlit.py
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import zlib
import math
import uuid

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")  # Replace with your Firebase key
firebase_admin.initialize_app(cred)
db = firestore.client()

def compress_and_encode(file_bytes):
    compressed = zlib.compress(file_bytes, level=9)
    encoded = base64.b64encode(compressed).decode('utf-8')
    return encoded

def chunk_text(text, chunk_size=10000):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

st.title("📤 File Sender")
uploaded_file = st.file_uploader("Upload a file")

if uploaded_file:
    file_id = str(uuid.uuid4())  # unique ID for transfer
    file_bytes = uploaded_file.read()
    encoded = compress_and_encode(file_bytes)
    chunks = chunk_text(encoded)

    # Store chunks in Firestore
    for idx, chunk in enumerate(chunks):
        db.collection("files").document(file_id).collection("chunks").document(str(idx)).set({
            "data": chunk
        })

    db.collection("files").document(file_id).set({
        "filename": uploaded_file.name,
        "total_chunks": len(chunks),
        "status": "uploaded"
    })

    st.success(f"✅ File uploaded & sent! File ID: {file_id}")
    st.code(file_id)
