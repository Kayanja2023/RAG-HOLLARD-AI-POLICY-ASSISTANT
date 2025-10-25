import os
import hashlib
import streamlit as st
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from rag_engine import get_chat_chain, load_all_documents
from config import (get_document_list, delete_document, validate_file, 
                   clear_vector_store, atomic_write, get_unique_filename, DOCS_DIR)

load_dotenv()

# Helper function for file signature tracking
def get_file_signature(uploaded_file):
    """Create unique signature for uploaded file to track processing."""
    try:
        # Read first 1KB for content hash
        sample = uploaded_file.read(1024)
        uploaded_file.seek(0)  # Reset file pointer
        content_hash = hashlib.md5(sample).hexdigest()[:8]
    except Exception:
        # Fallback if file can't be read
        content_hash = "unknown"
    
    return (
        uploaded_file.name,
        uploaded_file.size,
        uploaded_file.type,
        content_hash
    )

def process_new_uploads(new_files):
    """Process and save new files that haven't been uploaded yet."""
    saved_count = 0
    errors = []
    
    for file in new_files:
        # Validate file
        is_valid, error_msg = validate_file(file.name, file.size)
        if not is_valid:
            errors.append(f"{file.name}: {error_msg}")
            continue
        
        # Check for duplicates and generate unique filename
        unique_name = get_unique_filename(file.name)
        if unique_name != file.name:
            st.info(f"📝 Renamed: {file.name} → {unique_name}")
        
        # Use atomic write to prevent corrupted files
        filepath = Path(DOCS_DIR) / unique_name
        success, msg = atomic_write(filepath, file.getbuffer())
        
        if success:
            saved_count += 1
        else:
            errors.append(f"{file.name}: {msg}")
    
    return saved_count, errors

st.set_page_config(page_title="RAG Chatbot", page_icon="💬", layout="wide")
st.title("💬 RAG Chatbot")

# Sidebar
with st.sidebar:
    st.header("📤 Documents")
    
    # Initialize upload tracking
    if "processed_uploads" not in st.session_state:
        st.session_state.processed_uploads = {}
    
    if "upload_generation" not in st.session_state:
        st.session_state.upload_generation = 0
    
    # File uploader with generation-based key (auto-clears after save)
    uploaded = st.file_uploader(
        "Upload files",
        type=["txt", "pdf", "docx", "md"],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.upload_generation}",
        help="Files will be saved automatically when you select them."
    )
    
    # Process new uploads only (prevents infinite loop)
    if uploaded:
        try:
            # Create signatures for all uploaded files
            current_files = {get_file_signature(f): f for f in uploaded}
            
            # Filter out already-processed files
            new_files = [
                f for sig, f in current_files.items()
                if sig not in st.session_state.processed_uploads
            ]
            
            if new_files:
                # Show progress
                with st.spinner(f"Saving {len(new_files)} new file(s)..."):
                    saved_count, errors = process_new_uploads(new_files)
                
                # Display errors
                for error in errors:
                    st.error(error)
                
                # If any files saved successfully
                if saved_count > 0:
                    st.success(f"✅ Saved {saved_count} file(s). Rebuilding index...")
                    
                    # Mark all current files as processed
                    now = datetime.now().isoformat()
                    for sig in current_files.keys():
                        st.session_state.processed_uploads[sig] = now
                    
                    # Cleanup old entries (keep last 50)
                    if len(st.session_state.processed_uploads) > 50:
                        sorted_items = sorted(
                            st.session_state.processed_uploads.items(),
                            key=lambda x: x[1]
                        )
                        st.session_state.processed_uploads = dict(sorted_items[-50:])
                    
                    # Rebuild vector store
                    success, msg = clear_vector_store()
                    if not success:
                        st.warning(f"⚠️ Vector store clear issue: {msg}")
                    
                    st.cache_resource.clear()
                    
                    # Increment generation to reset uploader
                    st.session_state.upload_generation += 1
                    
                    # Rerun to show fresh uploader
                    st.rerun()
                else:
                    st.warning("⚠️ No files were saved. Check errors above.")
            else:
                # All files already processed
                st.info("ℹ️ These files have already been uploaded in this session.")
        except Exception as e:
            st.error(f"❌ Error processing files: {str(e)}")
    
    st.divider()
    
    # List docs
    docs = get_document_list()
    if docs:
        st.subheader(f"📁 Files ({len(docs)})")
        
        # List individual documents
        for doc in docs:
            col1, col2 = st.columns([4, 1])
            col1.text(doc)
            if col2.button("🗑️", key=f"del_{doc}"):
                if delete_document(doc):
                    # Store messages before any operations
                    messages_backup = st.session_state.get("messages", []).copy()
                    session_histories_backup = st.session_state.get("session_histories", {}).copy()
                    
                    # Clean up tracking for this file (allows re-upload)
                    sigs_to_remove = [
                        sig for sig in st.session_state.get("processed_uploads", {})
                        if sig[0] == doc  # sig[0] is filename
                    ]
                    for sig in sigs_to_remove:
                        st.session_state.processed_uploads.pop(sig, None)
                    
                    # Clear cache before restoring session state
                    st.cache_resource.clear()
                    
                    # Restore chat history after cache clear
                    st.session_state.messages = messages_backup
                    st.session_state.session_histories = session_histories_backup
                    
                    st.success(f"✅ Deleted {doc}. Index will be rebuilt.")
                    st.rerun()
                else:
                    st.error(f"❌ Failed to delete {doc}")
    else:
        st.info("No documents yet")

# Main chat
chain = get_chat_chain()

st.subheader("Chat")

# Initialize messages in session state if not exists
if "messages" not in st.session_state:
    st.session_state.messages = []

# Add clear chat button
if st.session_state.messages:
    if st.button("🗑️ Clear Chat History"):
        st.session_state.messages = []
        # Also clear the LangChain message history
        if "session_histories" in st.session_state:
            st.session_state.session_histories = {}
        st.rerun()

# Display all previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# Chat input - disabled if no documents
if not chain:
    st.info("👋 Upload documents to start chatting!")
    # Display disabled input to show chat is unavailable
    st.chat_input("Upload documents first...", disabled=True)
elif user_input := st.chat_input("Ask about your documents..."):
    # Add user message to session state and display it
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)
    
    # Generate and display assistant response
    with st.chat_message("assistant"):
        try:
            with st.spinner("Thinking..."):
                response = chain.invoke(
                    {"input": user_input},
                    config={"configurable": {"session_id": "main"}}
                )
            # The response is already a string due to StrOutputParser
            st.write(response)
            # Add assistant message to session state
            st.session_state.messages.append({"role": "assistant", "content": response})
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            st.error(error_msg)
            import traceback
            st.error(traceback.format_exc())
            # Add error to session state so it persists
            st.session_state.messages.append({"role": "assistant", "content": error_msg})