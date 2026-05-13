import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file (if present)
load_dotenv()

# Load credentials from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# Bot token check
if not BOT_TOKEN:
    print("❌ BOT_TOKEN is not set")
    raise ValueError("BOT_TOKEN is required")

print(f"✅ Bot token loaded: {BOT_TOKEN[:10]}...")

# MongoDB configuration
if not MONGO_URI:
    print("❌ MONGO_URI is not set")
    raise ValueError("MONGO_URI is required")

if MONGO_URI.startswith("mongodb+srv://"):
    print("✅ Using MongoDB Atlas connection")
else:
    print("✅ Using local MongoDB connection")

# SSH configuration
SSH_TIMEOUT = int(os.getenv("SSH_TIMEOUT", 15))
MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", 10))

# File manager configuration
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 50 * 1024 * 1024))  # default 50MB
ALLOWED_EXTENSIONS = os.getenv("ALLOWED_EXTENSIONS", None)

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

print("✅ Configuration loaded successfully")
print(f"  - SSH Timeout: {SSH_TIMEOUT}s")
print(f"  - Max Connections: {MAX_CONNECTIONS}")
print(f"  - Max File Size: {MAX_FILE_SIZE // (1024*1024)}MB")
print(f"  - Log Level: {LOG_LEVEL}")
