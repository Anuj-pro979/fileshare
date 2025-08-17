# streamlit_sender_full.py
import streamlit as st
import json
import base64
import zlib
import uuid
from time import sleep

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------- Firebase init (safe for Streamlit reruns) ----------------------
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

# initialize
try:
    db = init_db_from_secrets()
    st.sidebar.success("Firebase initialized")
except Exception as e:
    st.sidebar.error("Firebase init failed: " + str(e))
    st.stop()

# ---------------------- Helpers ----------------------
def compress_and_encode(file_bytes: bytes) -> str:
    """Compress with zlib and return base64 text."""
    compressed = zlib.compress(file_bytes, level=9)
    encoded = base64.b64encode(compressed).decode("utf-8")
    return encoded

def chunk_text(text: str, chunk_size: int = 200_000):
    """Return list of chunks (chunk_size characters)."""
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def send_file_to_firestore(db, file_name: str, file_bytes: bytes, chunk_size: int = 200_000, throttle: float = 0.03):
    """
    Write metadata doc files/{file_id}, and subcollection files/{file_id}/chunks/{idx}
    Returns (file_id, total_chunks)
    """
    encoded = compress_and_encode(file_bytes)
    chunks = chunk_text(encoded, chunk_size=chunk_size)
    total_chunks = len(chunks)
    file_id = str(uuid.uuid4())

    # metadata doc
    meta_ref = db.collection("files").document(file_id)
    meta_ref.set({
        "file_name": file_name,
        "total_chunks": total_chunks,
        "status": "uploading"
    })

    # write chunks
    progress = st.progress(0)
    for idx, chunk in enumerate(chunks):
        doc_ref = db.collection("files").document(file_id).collection("chunks").document(str(idx))
        doc_ref.set({ "data": chunk })
        progress.progress((idx + 1) / total_chunks)
        # small throttle to avoid burst write errors on free projects
        if throttle:
            sleep(throttle)

    meta_ref.update({"status": "uploaded"})
    progress.empty()
    return file_id, total_chunks

# ---------------------- Streamlit UI ----------------------
st.set_page_config(page_title="Sender (Firestore chunks)", layout="wide")
st.title("📤 Sender — compress → base64 → chunk → Firestore")

st.markdown("""
Upload a file. This app compresses (zlib) and base64-encodes it, splits into chunks,
and stores chunks under `files/{file_id}/chunks/{idx}` and metadata at `files/{file_id}`.
""")

uploaded_file = st.file_uploader("Choose file to send", type=None)
chunk_size = st.number_input("Chunk size (characters)", min_value=50_000, max_value=900_000, value=200_000, step=50_000,
                             help="200k chars ≈ ~150KB base64 text chunk. Keep chunks small enough for Firestore doc limits (1 MiB)")

if uploaded_file:
    file_bytes = uploaded_file.read()
    st.write(f"File: **{uploaded_file.name}** — {len(file_bytes)/1024:.1f} KB")

    if st.button("Send file"):
        try:
            with st.spinner("Compressing, encoding and uploading..."):
                fid, tot = send_file_to_firestore(db, uploaded_file.name, file_bytes, chunk_size=chunk_size)
            st.success(f"Uploaded. File ID: `{fid}` — Chunks: {tot}")
            st.code(fid)
            st.info("Receiver should read metadata at `files/{file_id}` and chunks at `files/{file_id}/chunks/`.")
        except Exception as exc:
            st.error("Upload failed: " + str(exc))

st.markdown("---")
st.markdown("**Notes:**")
st.markdown("- Use Streamlit Secrets to store your service account JSON under `firebase_service_account` (do not commit the key).")
st.markdown("- If you see permission errors, ensure the service account has Firestore permission and the JSON is for the correct project.")
st.markdown("- Free Firestore projects may rate-limit many small writes; increase `chunk_size` or add a small `throttle` if you see errors.")

# optional health check
if st.sidebar.button("Run quick Firestore health check"):
    try:
        db.collection("health_check").document("ping").set({"ok": True})
        st.sidebar.success("health_check write OK")
    except Exception as e:
        st.sidebar.error("health_check failed: " + str(e))
