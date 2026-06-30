import os
import sys
import logging
import sqlite3
import subprocess
import signal
import zipfile
import shutil
import psutil
import asyncio
from datetime import datetime
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- FLASK APP FOR PORT 500 ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=5000)

# --- CONFIGURATION ---
TOKEN = '8635537345:AAFRhzpRhV1MU6It2a_1MDU2pPNfEgtVwr4'
ADMIN_ID = 7741344963  # ✅ Fixed: Your chat ID
DB_FILE = 'bot_database.db'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, 'user_projects')

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE MANAGEMENT ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS projects
                 (user_id INTEGER PRIMARY KEY, 
                  project_name TEXT, 
                  status TEXT, 
                  pid INTEGER, 
                  start_time TEXT)''')
    conn.commit()
    conn.close()

def update_project_db(user_id, project_name, status, pid):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR REPLACE INTO projects (user_id, project_name, status, pid, start_time) VALUES (?, ?, ?, ?, ?)",
              (user_id, project_name, status, pid, start_time))
    conn.commit()
    conn.close()

def get_project_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_all_projects_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM projects")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_project_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM projects WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# --- PROCESS MANAGEMENT ---
def stop_project(user_id):
    project = get_project_db(user_id)
    if project and project[3]:  # project[3] is pid
        try:
            parent = psutil.Process(project[3])
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            logger.info(f"Stopped project for user {user_id}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            logger.warning(f"Process {project[3]} already stopped or inaccessible.")
    
    update_project_db(user_id, project[1] if project else "None", "Stopped", None)

async def install_dependencies(user_dir, user_id, context):
    """Install all dependencies that user projects might need"""
    try:
        # First check if requirements.txt exists
        req_file = os.path.join(user_dir, 'requirements.txt')
        if os.path.exists(req_file):
            await context.bot.send_message(chat_id=user_id, text="📦 Installing dependencies from requirements.txt...")
            result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_file], 
                                  capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                await context.bot.send_message(chat_id=user_id, text="✅ Requirements installed successfully!")
            else:
                await context.bot.send_message(chat_id=user_id, text=f"⚠️ Some requirements failed:\n{result.stderr[:200]}")
        
        # Install telebot specifically (most common for Telegram bots)
        await context.bot.send_message(chat_id=user_id, text="📦 Installing telebot...")
        result = subprocess.run([sys.executable, "-m", "pip", "install", "telebot"], 
                              capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            await context.bot.send_message(chat_id=user_id, text="✅ telebot installed!")
        else:
            # Try pyTelegramBotAPI as alternative
            await context.bot.send_message(chat_id=user_id, text="📦 Installing pyTelegramBotAPI...")
            subprocess.run([sys.executable, "-m", "pip", "install", "pyTelegramBotAPI"], 
                         capture_output=True, text=True, timeout=60)
        
        # Install other common dependencies
        common_deps = ['requests', 'psutil']
        for dep in common_deps:
            subprocess.run([sys.executable, "-m", "pip", "install", dep], 
                         capture_output=True, text=True, timeout=30)
        
        await context.bot.send_message(chat_id=user_id, text="✅ All dependencies installed!")
        return True
    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Error installing dependencies: {str(e)[:200]}")
        return False

async def deploy_project(user_id, file_path, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Stop existing project first
        stop_project(user_id)
        
        user_dir = os.path.join(PROJECTS_DIR, str(user_id))
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir)
        os.makedirs(user_dir, exist_ok=True)
        
        project_name = os.path.basename(file_path)
        target_path = os.path.join(user_dir, project_name)
        shutil.move(file_path, target_path)
        
        main_file = target_path
        if project_name.endswith('.zip'):
            await context.bot.send_message(chat_id=user_id, text="📦 Extracting zip file...")
            with zipfile.ZipFile(target_path, 'r') as zip_ref:
                zip_ref.extractall(user_dir)
            # Look for main file
            files = os.listdir(user_dir)
            if 'main.py' in files:
                main_file = os.path.join(user_dir, 'main.py')
            elif 'bot.py' in files:
                main_file = os.path.join(user_dir, 'bot.py')
            else:
                py_files = [f for f in files if f.endswith('.py')]
                if py_files:
                    main_file = os.path.join(user_dir, py_files[0])
                else:
                    await context.bot.send_message(chat_id=user_id, text="❌ No .py file found in zip!")
                    return
        
        # Install dependencies
        install_success = await install_dependencies(user_dir, user_id, context)
        if not install_success:
            await context.bot.send_message(chat_id=user_id, text="⚠️ Continuing despite dependency issues...")
        
        # Start project
        log_file = os.path.join(user_dir, 'output.log')
        
        def preexec():
            os.setsid()
            try:
                import resource
                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_CPU, (3600, 3600))
            except ImportError:
                pass
        
        await context.bot.send_message(chat_id=user_id, text=f"🚀 Starting project: {os.path.basename(main_file)}...")
        
        with open(log_file, 'w') as f:
            process = subprocess.Popen([sys.executable, main_file], 
                                     stdout=f, stderr=subprocess.STDOUT, 
                                     cwd=user_dir, preexec_fn=preexec)
        
        update_project_db(user_id, project_name, "Running", process.pid)
        
        # Wait a moment to check if process is still running
        await asyncio.sleep(2)
        if psutil.pid_exists(process.pid):
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"✅ **Project {project_name} deployed successfully!**\n"
                     f"📂 File: {os.path.basename(main_file)}\n"
                     f"🆔 PID: `{process.pid}`\n"
                     f"📊 Status: Running\n\n"
                     f"Use /logs to see the output.",
                parse_mode='Markdown'
            )
        else:
            # Process died immediately, check logs
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    error_log = f.read()[-500:]
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=f"❌ **Project crashed on startup!**\n\n"
                         f"📋 Error log:\n```\n{error_log}\n```",
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id, 
                    text="❌ **Project failed to start!**\n"
                         "Check your code for errors.",
                    parse_mode='Markdown'
                )
    except Exception as e:
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"❌ **Deployment failed:**\n`{str(e)[:300]}`",
            parse_mode='Markdown'
        )
        logger.error(f"Deployment error for user {user_id}: {e}")

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Python Auto-Deploy Bot!\n\n"
        "Send me a .py file or a .zip archive to deploy your project.\n\n"
        "📜 **User Commands:**\n"
        "/status - Check your project status\n"
        "/logs - View last 20 lines of logs\n"
        "/stop - Stop your project\n"
        "/restart - Restart your project\n\n"
        "🛠 **Admin Commands:**\n"
        "/list - List all projects\n"
        "/admin_stop <user_id> - Stop a user's project\n"
        "/broadcast <message> - Message all users\n"
        "/stats - Server health (CPU/RAM)"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not (doc.file_name.endswith('.py') or doc.file_name.endswith('.zip')):
        await update.message.reply_text("❌ Please send a .py or .zip file only.")
        return
    
    await update.message.reply_text("📥 Downloading and deploying your project...")
    file = await context.bot.get_file(doc.file_id)
    file_path = os.path.join(BASE_DIR, doc.file_name)
    await file.download_to_drive(file_path)
    
    await deploy_project(update.effective_user.id, file_path, context)

async def get_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log_file = os.path.join(PROJECTS_DIR, str(user_id), 'output.log')
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            logs = f.readlines()[-20:]
        msg = "".join(logs) if logs else "Logs are empty."
        if len(msg) > 4000: msg = msg[-4000:]
        await update.message.reply_text(f"📋 **Last 20 lines of logs:**\n\n`{msg}`", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No logs found. Is your project running?")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stop_project(user_id)
    await update.message.reply_text("🛑 Project stopped.")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project = get_project_db(user_id)
    if project:
        status_text = f"📊 **Project Status**\n\n"
        status_text += f"📦 Name: `{project[1]}`\n"
        status_text += f"🚦 Status: `{project[2]}`\n"
        status_text += f"🆔 PID: `{project[3] if project[3] else 'N/A'}`\n"
        status_text += f"⏰ Started: `{project[4]}`\n"
        await update.message.reply_text(status_text, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active project.")

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project = get_project_db(user_id)
    if not project:
        await update.message.reply_text("❌ No project found to restart.")
        return
    
    await update.message.reply_text("🔄 Restarting your project...")
    stop_project(user_id)
    
    # Find main file
    user_dir = os.path.join(PROJECTS_DIR, str(user_id))
    if os.path.exists(user_dir):
        files = os.listdir(user_dir)
        main_file = None
        for f in files:
            if f.endswith('.py') and f not in ['requirements.txt']:
                main_file = os.path.join(user_dir, f)
                break
        
        if main_file:
            log_file = os.path.join(user_dir, 'output.log')
            def preexec():
                os.setsid()
            with open(log_file, 'a') as f:
                process = subprocess.Popen([sys.executable, main_file], 
                                         stdout=f, stderr=subprocess.STDOUT, 
                                         cwd=user_dir, preexec_fn=preexec)
            update_project_db(user_id, project[1], "Running", process.pid)
            await update.message.reply_text(f"✅ Project restarted! PID: `{process.pid}`", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Main file not found.")

# --- ADMIN COMMANDS ---
async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    projects = get_all_projects_db()
    msg = "📋 **All Projects:**\n\n"
    for p in projects:
        msg += f"👤 User: `{p[0]}`\n📦 Project: `{p[1]}`\n🚦 Status: `{p[2]}`\n\n"
    await update.message.reply_text(msg if projects else "No projects found.", parse_mode='Markdown')

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    projects = get_all_projects_db()
    count = 0
    for p in projects:
        try:
            await context.bot.send_message(chat_id=p[0], text=f"📢 **Broadcast from Admin:**\n\n{msg}", parse_mode='Markdown')
            count += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Message sent to {count} users.")

async def admin_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /admin_stop <user_id>")
        return
    target_id = int(context.args[0])
    stop_project(target_id)
    await update.message.reply_text(f"Stopped project for {target_id}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    await update.message.reply_text(f"🖥 Server Stats:\nCPU: {cpu}%\nRAM: {ram}%")

# --- AUTO-RESTART ON BOOT ---
async def restart_projects():
    projects = get_all_projects_db()
    for p in projects:
        if p[2] == "Running":
            user_id = p[0]
            user_dir = os.path.join(PROJECTS_DIR, str(user_id))
            if os.path.exists(user_dir):
                files = os.listdir(user_dir)
                main_file = None
                for f in files:
                    if f.endswith('.py') and f not in ['requirements.txt']:
                        main_file = os.path.join(user_dir, f)
                        break
                
                if main_file:
                    log_file = os.path.join(user_dir, 'output.log')
                    def preexec():
                        os.setsid()
                    with open(log_file, 'a') as f:
                        process = subprocess.Popen([sys.executable, main_file], 
                                                   stdout=f, stderr=subprocess.STDOUT, 
                                                   cwd=user_dir, preexec_fn=preexec)
                    update_project_db(user_id, p[1], "Running", process.pid)
                    logger.info(f"Auto-restarted project for {user_id}")

async def run_bot():
    application = Application.builder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("logs", get_logs))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("restart", restart_cmd))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Admin Handlers
    application.add_handler(CommandHandler("list", admin_list))
    application.add_handler(CommandHandler("admin_stop", admin_stop))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    application.add_handler(CommandHandler("stats", admin_stats))
    
    # Auto-restart projects on startup
    await restart_projects()
    
    logger.info("Bot started...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep the bot running
    while True:
        await asyncio.sleep(1)

# --- MAIN ENTRY POINT ---
def main():
    if not os.path.exists(PROJECTS_DIR):
        os.makedirs(PROJECTS_DIR)
    init_db()
    
    # Start Flask server in a separate thread for port 5000
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Run the bot
    asyncio.run(run_bot())

if __name__ == '__main__':
    main()
