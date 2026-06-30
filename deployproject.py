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
import re
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
ADMIN_ID = 7741344963
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
    """Stop a user's running project"""
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

# --- DEPENDENCY DETECTION ---
def detect_imports_from_file(file_path):
    """Detect all import statements from a Python file"""
    imports = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Patterns for import statements
        patterns = [
            r'^import\s+([a-zA-Z_][a-zA-Z0-9_]*)',  # import module
            r'^from\s+([a-zA-Z_][a-zA-Z0-9_]*)',    # from module import
        ]
        
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            for pattern in patterns:
                matches = re.findall(pattern, line)
                for match in matches:
                    # Filter out Python built-in modules
                    builtins = {'sys', 'os', 're', 'json', 'time', 'datetime', 'math', 
                               'random', 'string', 'collections', 'itertools', 'functools',
                               'typing', 'abc', 'io', 'socket', 'threading', 'multiprocessing',
                               'subprocess', 'signal', 'logging', 'argparse', 'configparser',
                               'csv', 'xml', 'html', 'urllib', 'http', 'email', 'base64',
                               'hashlib', 'hmac', 'tempfile', 'shutil', 'glob', 'fnmatch',
                               'pickle', 'shelve', 'copy', 'pprint', 'traceback', 'warnings',
                               'contextlib', 'dataclasses', 'enum', 'pathlib', 'statistics',
                               'asyncio', 'concurrent', 'queue', 'heapq', 'bisect', 'array',
                               'struct', 'binascii', 'zlib', 'gzip', 'zipfile', 'tarfile',
                               'crypt', 'ssl', 'email', 'mimetypes', 'uuid', 'secrets',
                               'dataclasses', 'abc', 'io', 'types', 'inspect', 'weakref',
                               'copyreg', 'linecache', 'tokenize', 'keyword', 'builtins'}
                    
                    if match not in builtins and not match.startswith('_'):
                        imports.add(match)
    
    except Exception as e:
        logger.error(f"Error detecting imports: {e}")
    
    return imports

def get_package_name(import_name):
    """Map import name to pip package name"""
    mapping = {
        'telebot': 'telebot',
        'pyTelegramBotAPI': 'pyTelegramBotAPI',
        'discord': 'discord.py',
        'requests': 'requests',
        'flask': 'flask',
        'django': 'django',
        'numpy': 'numpy',
        'pandas': 'pandas',
        'matplotlib': 'matplotlib',
        'seaborn': 'seaborn',
        'scipy': 'scipy',
        'sklearn': 'scikit-learn',
        'tensorflow': 'tensorflow',
        'torch': 'torch',
        'keras': 'keras',
        'opencv': 'opencv-python',
        'PIL': 'pillow',
        'Pillow': 'pillow',
        'cv2': 'opencv-python',
        'bs4': 'beautifulsoup4',
        'BeautifulSoup': 'beautifulsoup4',
        'selenium': 'selenium',
        'scrapy': 'scrapy',
        'fastapi': 'fastapi',
        'uvicorn': 'uvicorn',
        'pytest': 'pytest',
        'mysql': 'mysql-connector-python',
        'pymysql': 'pymysql',
        'psycopg2': 'psycopg2-binary',
        'sqlalchemy': 'sqlalchemy',
        'alembic': 'alembic',
        'celery': 'celery',
        'redis': 'redis',
        'pymongo': 'pymongo',
        'motor': 'motor',
        'aiohttp': 'aiohttp',
        'httpx': 'httpx',
        'websockets': 'websockets',
        'python-telegram-bot': 'python-telegram-bot',
        'ptb': 'python-telegram-bot',
        'pyrogram': 'pyrogram',
        'aiogram': 'aiogram',
        'pydantic': 'pydantic',
        'click': 'click',
        'colorama': 'colorama',
        'tqdm': 'tqdm',
        'python-dotenv': 'python-dotenv',
        'dotenv': 'python-dotenv',
        'yaml': 'pyyaml',
        'ruamel': 'ruamel.yaml',
        'jinja2': 'jinja2',
        'markdown': 'markdown',
        'html2text': 'html2text',
        'lxml': 'lxml',
        'xmltodict': 'xmltodict',
    }
    
    base_name = import_name.split(' as ')[0].split('.')[0]
    return mapping.get(base_name, base_name)

async def auto_install_dependencies(file_path, user_id, context):
    """Auto-detect and install dependencies from Python file"""
    await context.bot.send_message(chat_id=user_id, text="🔍 Scanning for dependencies...")
    
    # Detect imports
    imports = detect_imports_from_file(file_path)
    
    if not imports:
        await context.bot.send_message(chat_id=user_id, text="ℹ️ No external dependencies detected.")
        return True
    
    await context.bot.send_message(
        chat_id=user_id, 
        text=f"📦 Found {len(imports)} dependencies:\n`{', '.join(list(imports)[:10])}`",
        parse_mode='Markdown'
    )
    
    # Convert to pip packages
    packages = []
    for imp in imports:
        pkg = get_package_name(imp)
        if pkg and pkg not in packages:
            packages.append(pkg)
    
    if not packages:
        await context.bot.send_message(chat_id=user_id, text="ℹ️ No installable packages found.")
        return True
    
    await context.bot.send_message(
        chat_id=user_id, 
        text=f"📥 Installing {len(packages)} packages... This may take a moment.",
        parse_mode='Markdown'
    )
    
    # Install packages one by one with progress
    installed = 0
    failed = []
    
    for i, pkg in enumerate(packages, 1):
        try:
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"⏳ [{i}/{len(packages)}] Installing `{pkg}`...",
                parse_mode='Markdown'
            )
            
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                installed += 1
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=f"✅ `{pkg}` installed successfully!",
                    parse_mode='Markdown'
                )
            else:
                failed.append(pkg)
                logger.warning(f"Failed to install {pkg}: {result.stderr[:100]}")
                
        except subprocess.TimeoutExpired:
            failed.append(f"{pkg} (timeout)")
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"⏰ `{pkg}` installation timed out.",
                parse_mode='Markdown'
            )
        except Exception as e:
            failed.append(f"{pkg} ({str(e)[:20]})")
    
    # Send summary
    if installed > 0:
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"✅ Installed {installed}/{len(packages)} packages successfully!"
        )
    
    if failed:
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"⚠️ Failed to install: `{', '.join(failed)}`\n\n"
                 f"💡 Try adding these to a `requirements.txt` file in your zip.",
            parse_mode='Markdown'
        )
    
    return True

async def deploy_project(user_id, file_path, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Stop existing project first
        await context.bot.send_message(chat_id=user_id, text="🔄 Stopping previous project (if any)...")
        stop_project(user_id)
        
        user_dir = os.path.join(PROJECTS_DIR, str(user_id))
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir)
        os.makedirs(user_dir, exist_ok=True)
        
        project_name = os.path.basename(file_path)
        target_path = os.path.join(user_dir, project_name)
        shutil.move(file_path, target_path)
        
        main_file = target_path
        
        # Handle zip file
        if project_name.endswith('.zip'):
            await context.bot.send_message(chat_id=user_id, text="📦 Extracting zip file...")
            with zipfile.ZipFile(target_path, 'r') as zip_ref:
                zip_ref.extractall(user_dir)
            
            # Find main file
            files = os.listdir(user_dir)
            priority_files = ['main.py', 'bot.py', 'app.py', 'run.py', 'index.py']
            main_file = None
            for f in priority_files:
                if f in files:
                    main_file = os.path.join(user_dir, f)
                    break
            
            if not main_file:
                py_files = [f for f in files if f.endswith('.py') and f != 'requirements.txt']
                if py_files:
                    main_file = os.path.join(user_dir, py_files[0])
                else:
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text="❌ No Python file found in the zip!"
                    )
                    return
        
        if not main_file or not os.path.exists(main_file):
            await context.bot.send_message(
                chat_id=user_id, 
                text="❌ Main Python file not found!"
            )
            return
        
        # Auto-detect and install dependencies
        await auto_install_dependencies(main_file, user_id, context)
        
        # Also check for requirements.txt if exists
        req_file = os.path.join(user_dir, 'requirements.txt')
        if os.path.exists(req_file):
            await context.bot.send_message(chat_id=user_id, text="📦 Found requirements.txt, installing...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_file], timeout=180)
            await context.bot.send_message(chat_id=user_id, text="✅ Requirements installed!")
        
        # Start the project
        log_file = os.path.join(user_dir, 'output.log')
        
        def preexec():
            os.setsid()
            try:
                import resource
                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_CPU, (3600, 3600))
            except ImportError:
                pass
        
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"🚀 Starting `{os.path.basename(main_file)}`...",
            parse_mode='Markdown'
        )
        
        with open(log_file, 'w') as f:
            process = subprocess.Popen(
                [sys.executable, main_file],
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=user_dir,
                preexec_fn=preexec
            )
        
        # Save to database
        update_project_db(user_id, project_name, "Running", process.pid)
        
        # Wait and check if process is running
        await asyncio.sleep(3)
        
        if psutil.pid_exists(process.pid):
            try:
                proc = psutil.Process(process.pid)
                if proc.is_running():
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ **Project Deployed Successfully!** 🎉\n\n"
                             f"📂 File: `{os.path.basename(main_file)}`\n"
                             f"🆔 PID: `{process.pid}`\n"
                             f"💾 Memory: {proc.memory_info().rss / 1024 / 1024:.2f} MB\n\n"
                             f"📌 `/logs` - View output\n"
                             f"📌 `/stop` - Stop project\n"
                             f"📌 `/status` - Check status\n"
                             f"📌 `/restart` - Restart project",
                        parse_mode='Markdown'
                    )
                    return
            except:
                pass
        
        # If process died, show error
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                error_log = f.read()[-500:]
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ **Project Crashed!** 💥\n\n"
                     f"📋 Error log:\n```\n{error_log}\n```",
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ **Project failed to start!**\nNo logs found."
            )
            
    except Exception as e:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ **Deployment failed:**\n```\n{str(e)[:300]}\n```",
            parse_mode='Markdown'
        )
        logger.error(f"Deployment error for user {user_id}: {e}")

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Python Auto-Deploy Bot**\n\n"
        "Send me a `.py` file or `.zip` archive.\n"
        "I'll automatically detect and install all dependencies! 🚀\n\n"
        "📜 **User Commands:**\n"
        "/status - Check project status\n"
        "/logs - View last 20 lines of logs\n"
        "/stop - Stop your project\n"
        "/restart - Restart your project\n\n"
        "🛠 **Admin Commands:**\n"
        "/list - List all projects\n"
        "/stats - Server health\n"
        "/broadcast <msg> - Broadcast message",
        parse_mode='Markdown'
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not (doc.file_name.endswith('.py') or doc.file_name.endswith('.zip')):
        await update.message.reply_text("❌ Please send a `.py` or `.zip` file only.")
        return
    
    await update.message.reply_text("📥 Downloading your project...")
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
        msg = "".join(logs) if logs else "📭 Logs are empty."
        if len(msg) > 4000:
            msg = msg[-4000:]
        await update.message.reply_text(
            f"📋 **Last 20 lines:**\n\n```\n{msg}\n```",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ No logs found. Is your project running?")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stop_project(user_id)
    await update.message.reply_text("🛑 Project stopped successfully.")

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
        await update.message.reply_text("❌ No active project found.")

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project = get_project_db(user_id)
    if not project:
        await update.message.reply_text("❌ No project found to restart.")
        return
    
    await update.message.reply_text("🔄 Restarting your project...")
    stop_project(user_id)
    
    user_dir = os.path.join(PROJECTS_DIR, str(user_id))
    if os.path.exists(user_dir):
        files = os.listdir(user_dir)
        main_file = None
        priority_files = ['main.py', 'bot.py', 'app.py', 'run.py']
        for f in priority_files:
            if f in files:
                main_file = os.path.join(user_dir, f)
                break
        if not main_file:
            py_files = [f for f in files if f.endswith('.py') and f != 'requirements.txt']
            if py_files:
                main_file = os.path.join(user_dir, py_files[0])
        
        if main_file and os.path.exists(main_file):
            log_file = os.path.join(user_dir, 'output.log')
            def preexec():
                os.setsid()
            with open(log_file, 'a') as f:
                process = subprocess.Popen(
                    [sys.executable, main_file],
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    cwd=user_dir,
                    preexec_fn=preexec
                )
            update_project_db(user_id, project[1], "Running", process.pid)
            await update.message.reply_text(
                f"✅ Project restarted!\n🆔 PID: `{process.pid}`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Main file not found.")
    else:
        await update.message.reply_text("❌ Project directory not found.")

# --- ADMIN COMMANDS ---
async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    projects = get_all_projects_db()
    if not projects:
        await update.message.reply_text("📭 No projects found.")
        return
    msg = "📋 **All Projects:**\n\n"
    for p in projects:
        msg += f"👤 User: `{p[0]}`\n📦 Project: `{p[1]}`\n🚦 Status: `{p[2]}`\n\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    projects = get_all_projects_db()
    count = 0
    for p in projects:
        try:
            await context.bot.send_message(
                chat_id=p[0],
                text=f"📢 **Admin Broadcast:**\n\n{msg}",
                parse_mode='Markdown'
            )
            count += 1
        except:
            pass
    await update.message.reply_text(f"✅ Message sent to {count} users.")

async def admin_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /admin_stop <user_id>")
        return
    target_id = int(context.args[0])
    stop_project(target_id)
    await update.message.reply_text(f"✅ Stopped project for user `{target_id}`", parse_mode='Markdown')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/')
    await update.message.reply_text(
        f"🖥 **Server Stats**\n\n"
        f"💻 CPU: `{cpu}%`\n"
        f"🧠 RAM: `{ram}%`\n"
        f"💾 Disk: `{disk.used / (1024**3):.1f}GB / {disk.total / (1024**3):.1f}GB`",
        parse_mode='Markdown'
    )

# --- AUTO-RESTART ---
async def restart_projects():
    projects = get_all_projects_db()
    for p in projects:
        if p[2] == "Running":
            user_id = p[0]
            user_dir = os.path.join(PROJECTS_DIR, str(user_id))
            if os.path.exists(user_dir):
                files = os.listdir(user_dir)
                main_file = None
                priority_files = ['main.py', 'bot.py', 'app.py', 'run.py']
                for f in priority_files:
                    if f in files:
                        main_file = os.path.join(user_dir, f)
                        break
                if not main_file:
                    py_files = [f for f in files if f.endswith('.py') and f != 'requirements.txt']
                    if py_files:
                        main_file = os.path.join(user_dir, py_files[0])
                
                if main_file and os.path.exists(main_file):
                    log_file = os.path.join(user_dir, 'output.log')
                    def preexec():
                        os.setsid()
                    with open(log_file, 'a') as f:
                        process = subprocess.Popen(
                            [sys.executable, main_file],
                            stdout=f,
                            stderr=subprocess.STDOUT,
                            cwd=user_dir,
                            preexec_fn=preexec
                        )
                    update_project_db(user_id, p[1], "Running", process.pid)
                    logger.info(f"Auto-restarted user {user_id}")

async def run_bot():
    application = Application.builder().token(TOKEN).build()
    
    # User commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("logs", get_logs))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("restart", restart_cmd))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Admin commands
    application.add_handler(CommandHandler("list", admin_list))
    application.add_handler(CommandHandler("admin_stop", admin_stop))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    application.add_handler(CommandHandler("stats", admin_stats))
    
    # Auto-restart projects on boot
    await restart_projects()
    
    logger.info("Bot started...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    while True:
        await asyncio.sleep(1)

# --- MAIN ---
def main():
    if not os.path.exists(PROJECTS_DIR):
        os.makedirs(PROJECTS_DIR)
    init_db()
    
    # Start Flask server for port 5000
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Run the bot
    asyncio.run(run_bot())

if __name__ == '__main__':
    main()
