# streamlit_sender_complete.py
import streamlit as st
import json
import base64
import zlib
import uuid
from time import sleep

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------- Config / Secrets ----------------------
# Put your full service-account JSON into Streamlit secrets as a single string:
# st.secrets["firebase_service_account"] = ' { "type": "...", "private_key": "-----BEGIN...\\n...\\n-----END..." , ... } '
#
# See instructions at the bottom of this file for secrets.toml format.

# ---------------------- Firebase init (safe for Streamlit reruns) ----------------------
def init_firebase_from_secrets():
    sa_json = st.secrets.get("firebase_service_account")
    if not sa_json:
        raise RuntimeError("Missing firebase_service_account in Streamlit secrets. See app docstring for instructions.")

    # load dict
    sa_dict = json.loads(sa_json)

    # Fix escaped newlines in private_key if the key was pasted with \n sequences
    if "private_key" in sa_dict and isinstance(sa_dict["private_key"], str):
        sa_dict["private_key"] = sa_dict["private_key"].replace("\\n", "\n")

    # initialize app only once per process
    try:
        app = firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(sa_dict)
        app = firebase_admin.initialize_app(cred)

    db = firestore.client(app=app)
    return db

# Initialize DB (Streamlit re-runs will reuse the same app)
try:
    db = init_firebase_from_secrets()
except Exception as e:
    st.error("Firebase init failed: " + str(e))
    st.stop()

# ---------------------- Helpers (compress, encode, chunk) ----------------------
def compress_and_encode(file_bytes: bytes) -> str:
    """Compress with zlib and return base64 text."""
    compressed = zlib.compress(file_bytes, level=9)
    encoded = base64.b64encode(compressed).decode("utf-8")
    return encoded

def chunk_text(text: str, chunk_size: int = 200_000):
    """Yield list of text chunks (chunk_size characters)."""
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def send_file_to_firestore(file_name: str, file_bytes: bytes, chunk_size: int = 200_000):
    """
    Compress+encode the file, chunk it, and write to Firestore.
    Documents layout:
      collection 'files' -> document (file_id) holds metadata
      subcollection 'chunks' -> documents '0','1','2' each hold {"data": chunk}
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

    # write chunks with progress bar
    progress = st.progress(0)
    for idx, chunk in enumerate(chunks):
        # write chunk as document under subcollection 'chunks'
        db.collection("files").document(file_id).collection("chunks").document(str(idx)).set({
            "data": chunk
        })
        # update progress
        progress.progress((idx+1) / total_chunks)
        # tiny sleep to help Firestore with burst writes in some free projects (optional)
        sleep(0.05)

    # mark uploaded
    meta_ref.update({"status": "uploaded"})
    progress.empty()
    return file_id, total_chunks

# ---------------------- Streamlit UI ----------------------
st.set_page_config(page_title="File Sender (chunks)", layout="wide")
st.title("📤 File Sender — compress → encode → chunk → Firestore")

st.markdown(
    """
    Upload a file. The app will compress (zlib) and base64-encode it, split into chunks, 
    and store chunks in Firestore under a generated `file_id`. Use that `file_id` on the receiver to reassemble.
    """
)

uploaded_file = st.file_uploader("Choose file to send", type=None)

# chunk size control (safe default keeps each Firestore document < ~1 MB)
chunk_size = st.number_input("Chunk size (characters)", min_value=50_000, max_value=900_000, value=200_000, step=50_000, help="Recommend 200k to 500k. Firestore doc max size ~1 MiB.")

if uploaded_file:
    file_bytes = uploaded_file.read()
    size_kb = len(file_bytes) / 1024
    st.write(f"File: {uploaded_file.name} — {size_kb:,.1f} KB")

    if st.button("Send file"):
        try:
            with st.spinner("Compressing, encoding and uploading chunks..."):
                fid, tot = send_file_to_firestore(uploaded_file.name, file_bytes, chunk_size=chunk_size)
            st.success(f"✅ Uploaded. File ID: `{fid}` — Chunks: {tot}")
            st.code(fid)
            st.info("Receiver can fetch chunks under collection `files/{file_id}/chunks/` and metadata at `files/{file_id}`.")
        except Exception as e:
            st.error(f"Upload failed: {e}")

st.markdown("---")
st.markdown("### Notes")
st.markdown(
    """
- **Secrets**: Put the service account JSON into Streamlit secrets under the key `firebase_service_account`.
- **Security**: Do not commit your key to a repo. Revoke and rotate if leaked.
- **Firestore quotas**: Writing many documents may be rate-limited on free projects. You can reduce frequency or increase chunk size if safe.
"""
)

# ---------------------- secrets.toml example ----------------------
st.markdown("#### Example `.streamlit/secrets.toml` entry (use Streamlit Cloud Secrets UI preferred):")
st.code(
    '''firebase_service_account = '''
    + "'''"
    + r'''{
  "type": "service_account",
  "project_id": "YOUR_PROJECT_ID",
  "private_key_id": "....",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIE....\n-----END PRIVATE KEY-----\n",
  "client_email": "....iam.gserviceaccount.com",
  ...
}'''
    + "'''"
, language="toml")
