# 🖥️ Multi Server Manager (Telegram SSH Bot)

A powerful **Telegram-based multi-server management bot** that lets you control Linux servers remotely via SSH — including **file management, service control (Systemd / Docker / PM2 / processes), server stats, and a web dashboard**.

Manage everything directly from Telegram without opening an SSH client.

---

## 🚀 Features

### 🔧 Server Management

* Add unlimited remote Linux servers
* SSH key-based authentication (RSA / ECDSA / Ed25519)
* Persistent SSH session reuse
* Real-time server status indicators

### 📊 Live Server Stats

* OS detection
* CPU usage
* RAM usage
* Disk usage
* Uptime
* Load average

### 🤖 Bot & Service Manager

Manage services remotely:

Supports:

* Systemd services
* Docker containers
* PM2 processes
* Running processes (Python / Node / Java / Go)

Available actions:

* Start
* Stop
* Restart
* View logs
* Remove services from manager list

---

### 🗂️ Remote File Manager

Operate remote files directly from Telegram:

Features:

* Browse directories
* Upload files
* Download files (≤50MB)
* Rename files
* Delete files
* Zip / unzip archives
* Copy / move files
* Bulk selection mode

---

### 🌐 Web Dashboard

Modern status dashboard with:

* Server monitoring
* Live memory / CPU stats
* Disk usage
* Uptime tracking
* Authentication system
* Landing page interface

Runs automatically when the bot starts.

---

### 🧠 MongoDB Storage

Stores:

* Server configurations
* SSH connection metadata
* Server statistics

Uses **Motor (async MongoDB driver)**.

---

## 📦 Requirements

Install dependencies:

```bash
pip install -r requirements.txt
```

Main dependencies:

* aiogram
* motor
* paramiko
* pymongo
* cryptography
* bcrypt
* python-dotenv

---

## ⚙️ Configuration

Edit `config.py`:

```python
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
MONGO_URI = "YOUR_MONGODB_URI"
```

⚠️ Recommended (Production Setup): use environment variables instead:

```python
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
```

Then export variables:

```bash
export BOT_TOKEN=your_token
export MONGO_URI=your_mongo_uri
```

---

## ▶️ Running the Bot

Start the bot:

```bash
python main.py
```

Startup automatically initializes:

* Telegram bot
* SSH session manager
* File manager module
* Service manager module
* Web dashboard server

---

## 🌍 Web Dashboard Access

Runs on:

```
http://0.0.0.0:3000
```

Default credentials:

```
username: admin
password: admin
```

Change using environment variables:

```bash
export WEB_USERNAME=your_user
export WEB_PASSWORD=your_pass
```

---

## ➕ Adding a Server

Inside Telegram:

```
/add_server
```

Then provide:

1. Server name
2. SSH username
3. Server IP address
4. SSH private key file

The bot connects automatically and stores the configuration.

---



## 🐳 Docker Support (Optional)

Build image:

```bash
docker build -t server-manager .
```

Run container:

```bash
docker run -d server-manager
```

---



## 📄 License

MIT License
