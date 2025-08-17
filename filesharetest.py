# streamlit_sender.py
import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import zlib
import uuid
import hashlib

# ---------- CONFIG ----------
CHUNK_TEXT_SIZE = 900_000
COLLECTION = "files"

# ---------- FIREBASE INIT ----------
def init_db():
    sa_json = st.secrets.get("firebase_service_account") if st.secrets else None
    if sa_json:
        sa = json.loads(sa_json)
    else:
        fallback_path = st.secrets.get("service_account_file") if st.secrets else None
        if not fallback_path:
            raise RuntimeError("Provide firebase_service_account in Streamlit secrets or service_account_file path.")
        with open(fallback_path, "r", encoding="utf-8") as f:
            sa = json.load(f)

    if "private_key" in sa and isinstance(sa["private_key"], str):
        sa["private_key"] = sa["private_key"].replace("\\n", "\n")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(sa)
        app = firebase_admin.initialize_app(cred)

    return firestore.client(app=app)

try:
    db = init_db()
    st.success("✅ Firebase initialized")
except Exception as e:
    st.error("❌ Firebase init failed: " + str(e))
    st.stop()

# ---------- HELPERS ----------
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def compress_and_encode_bytes(b: bytes) -> str:
    return base64.b64encode(zlib.compress(b)).decode("utf-8")

def chunk_text(text: str, size: int = CHUNK_TEXT_SIZE):
    return [text[i:i+size] for i in range(0, len(text), size)]

# ---------- SENDER ----------
def send_file_to_firestore(file_bytes: bytes, file_name: str) -> tuple[str, int]:
    file_sha = sha256_bytes(file_bytes)
    full_b64 = compress_and_encode_bytes(file_bytes)
    chunks = chunk_text(full_b64, CHUNK_TEXT_SIZE)
    total_chunks = len(chunks)
    file_id = str(uuid.uuid4())

    # Batch write with periodic commits to avoid huge batches
    batch = db.batch()
    written = 0
    for idx, piece in enumerate(chunks):
        doc_ref = db.collection(COLLECTION).document(f"{file_id}_{idx}")
        # ensure file_name is present in each chunk doc for robustness
        batch.set(doc_ref, {
            "file_name": file_name,
            "chunk_index": idx,
            "total_chunks": total_chunks,
            "data": piece
        })
        written += 1
        if written % 300 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()

    # Create manifest (guarantees receiver can get filename + sha)
    db.collection(COLLECTION).document(f"{file_id}_meta").set({
        "file_id": file_id,
        "file_name": file_name,
        "total_chunks": total_chunks,
        "sha256": file_sha,
        "size_bytes": len(file_bytes),
        "uploaded_at": firestore.SERVER_TIMESTAMP
    })

    # Optional health ping
    try:
        db.collection("health_check").document("ping").set({"ok": True})
    except Exception:
        pass

    return file_id, total_chunks

# ---------- STREAMLIT UI ----------
st.title("📤 File sender → Firestore (compress → base64 → chunk)")

uploaded = st.file_uploader("Choose a file to upload (PDF etc.)", accept_multiple_files=False)
if uploaded:
    st.write("Filename:", uploaded.name)
    if st.button("Send to Firestore"):
        with st.spinner("Compressing, encoding and uploading..."):
            try:
                b = uploaded.read()
                fid, total = send_file_to_firestore(b, uploaded.name)
                st.success(f"Uploaded ✅ File ID: `{fid}` — chunks: {total}")
                st.code(fid, language="text")
                st.info("Save the File ID for the receiver to download.")
            except Exception as e:
                st.error("Upload failed: " + str(e))

st.markdown(
    """
**Notes**
- Sender stores `file_name` (including extension) in every chunk and in a manifest `{file_id}_meta`.
- Receiver will reassemble Base64, decode, decompress, and verify SHA256.
"""
)
