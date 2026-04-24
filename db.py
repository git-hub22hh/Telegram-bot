# Version: 1.1.0 | Location: /db.py
import aiosqlite
import logging

DB_PATH = "database.db"
logger = logging.getLogger(__name__)

async def init_db():
    """Initializes the database schemas if they do not exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Users Table: Tracks balance, referrals, and reward state
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0.0,
                referrer_id INTEGER,
                reward_claimed BOOLEAN DEFAULT FALSE
            )
        """)
        
        # Withdrawals Table: Tracks all transactions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                phone TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
        logger.info("Database initialized successfully.")

async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, referrer_id, reward_claimed FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def create_user(user_id, referrer_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, referrer_id) VALUES (?, ?)", (user_id, referrer_id))
        await db.commit()

async def update_balance(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def mark_reward_claimed(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET reward_claimed = TRUE WHERE user_id = ?", (user_id,))
        await db.commit()

async def create_withdrawal(user_id, amount, method, phone):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO withdrawals (user_id, amount, method, phone) VALUES (?, ?, ?, ?)",
            (user_id, amount, method, phone)
        )
        await db.commit()

async def update_withdrawal_status(withdrawal_id, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (status, withdrawal_id))
        await db.commit()
        
async def get_withdrawal(withdrawal_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (withdrawal_id,)) as cursor:
            return await cursor.fetchone()
