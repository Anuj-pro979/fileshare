# streamlit_sender.py
import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import zlib
import uuid
import hashlib
import math

# ---------- CONFIG ----------
# Size of base64 text per Firestore document (characters). Keep below ~1,000,000 to be safe.
CHUNK_TEXT_SIZE = 900_000
COLLECTION = "files"

# ---------- FIREBASE INIT ----------
def init_db():
    """
    Initialize Firebase using st.secrets['firebase_service_account'] (preferred)
    or fallback to a local file path provided in st.secrets['service_account_file'].
    """
    sa_json = st.secrets.get("firebase_service_account") if st.secrets else None
    if sa_json:
        sa = json.loads(sa_json)
    else:
        # fallback: local file path in secrets or env-like setting
        fallback_path = st.secrets.get("service_account_file") if st.secrets else None
        if not fallback_path:
            raise RuntimeError("Provide firebase_service_account in Streamlit secrets or service_account_file path.")
        with open(fallback_path, "r", encoding="utf-8") as f:
            sa = json.load(f)

    # fix literal "\n" in private key
    if "private_key" in sa and isinstance(sa["private_key"], str):
        sa["private_key"] = sa["private_key"].replace("\\n", "\n")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(sa)
        app = firebase_admin.initialize_app(cred)

    return firestore.client(app=app)

# lazy init
try:
    db = init_db()
    st.success("✅ Firebase initialized")
except Exception as e:
    st.error("❌ Firebase initialization failed: " + str(e))
    st.stop()

# ---------- HELPERS ----------
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def compress_and_encode_bytes(b: bytes) -> str:
    compressed = zlib.compress(b)
    encoded = base64.b64encode(compressed).decode("utf-8")
    return encoded

def chunk_text(text: str, size: int = CHUNK_TEXT_SIZE):
    return [text[i:i+size] for i in range(0, len(text), size)]

# ---------- SENDER ----------
def send_file_to_firestore(file_bytes: bytes, file_name: str) -> tuple[str, int]:
    """
    Returns (file_id, total_chunks)
    Pipeline:
      original bytes -> zlib.compress -> base64.encode (string) -> split -> store chunks
    """
    # compute sha256 for verification
    file_sha = sha256_bytes(file_bytes)

    # compress + base64 encode whole blob
    full_b64 = compress_and_encode_bytes(file_bytes)

    # split the base64 text into chunks that fit Firestore documents
    chunks = chunk_text(full_b64, CHUNK_TEXT_SIZE)
    total_chunks = len(chunks)
    file_id = str(uuid.uuid4())

    # batch write chunks
    batch = db.batch()
    written = 0
    for idx, piece in enumerate(chunks):
        doc_ref = db.collection(COLLECTION).document(f"{file_id}_{idx}")
        batch.set(doc_ref, {
            "file_name": file_name,
            "chunk_index": idx,
            "total_chunks": total_chunks,
            "data": piece
        })
        written += 1
        # commit periodically to avoid huge batches
        if written % 300 == 0:
            batch.commit()
            batch = db.batch()

    # final commit
    batch.commit()

    # manifest (helps verification on receiver)
    db.collection(COLLECTION).document(f"{file_id}_meta").set({
        "file_id": file_id,
        "file_name": file_name,
        "total_chunks": total_chunks,
        "sha256": file_sha,
        "size_bytes": len(file_bytes),
        "uploaded_at": firestore.SERVER_TIMESTAMP
    })

    # health check (optional)
    try:
        db.collection("health_check").document("ping").set({"ok": True})
    except Exception:
        pass

    return file_id, total_chunks

# ---------- STREAMLIT UI ----------
st.title("📤 File sender → Firestore (compress → base64 → chunk)")

uploaded = st.file_uploader("Choose a file to upload (PDF, images, etc.)", accept_multiple_files=False)
if uploaded:
    st.write("Filename:", uploaded.name)
    if st.button("Send to Firestore"):
        with st.spinner("Compressing, encoding and uploading..."):
            try:
                b = uploaded.read()
                fid, total = send_file_to_firestore(b, uploaded.name)
                st.success(f"Uploaded ✅ File ID: `{fid}` — chunks: {total}")
                st.code(f"{fid}", language="text")
                st.info("Keep the File ID to download from the receiver.")
            except Exception as e:
                st.error("Upload failed: " + str(e))

# Optional: quick instructions
st.markdown(
    """
**Notes**
- This sender compresses the entire file with `zlib` then base64-encodes the compressed blob and splits the base64 string into chunks stored as documents.
- The receiver must **reassemble the Base64 string**, then decode, then decompress.
- A manifest (`{file_id}_meta`) is created with `sha256` for verification.
"""
)
