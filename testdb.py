import sqlite3
import os
import time

DB = "confessions.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            nickname TEXT DEFAULT 'Anonymous',
            telegram_username TEXT,
            emoji TEXT DEFAULT '👤',
            bio TEXT DEFAULT 'No bio set',
            aura_points INTEGER DEFAULT 0,
            star_balance INTEGER DEFAULT 0,
            followers_count INTEGER DEFAULT 0,
            following_count INTEGER DEFAULT 0,
            accepted_policy BOOLEAN DEFAULT 0,
            allow_chats BOOLEAN DEFAULT 1,
            voice_effect TEXT DEFAULT 'Original',
            notify_comment BOOLEAN DEFAULT 1,
            notify_reply BOOLEAN DEFAULT 1,
            notify_like BOOLEAN DEFAULT 1,
            notify_follow BOOLEAN DEFAULT 1,
            notify_activity BOOLEAN DEFAULT 1,
            comments_per_page INTEGER DEFAULT 15,
            warn_count INTEGER DEFAULT 0,
            blocked_until INTEGER DEFAULT 0,
            is_banned BOOLEAN DEFAULT 0,
            last_daily INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS follows (
            follower_id INTEGER,
            followed_id INTEGER,
            PRIMARY KEY (follower_id, followed_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS confessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            media_type TEXT,
            media_file_id TEXT,
            categories TEXT,
            hashtags TEXT,
            approved BOOLEAN DEFAULT 0,
            channel_msg_id INTEGER,
            is_highlighted BOOLEAN DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            confession_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            media_type TEXT,
            media_file_id TEXT,
            voice_effect TEXT DEFAULT 'Original',
            parent_id INTEGER,
            depth INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            is_highlighted BOOLEAN DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS reactions (
            user_id INTEGER,
            comment_id INTEGER,
            reaction TEXT CHECK(reaction IN ('like', 'dislike')),
            PRIMARY KEY (user_id, comment_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER,
            to_user_id INTEGER,
            confession_id INTEGER,
            comment_id INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            target_id INTEGER,
            confession_id INTEGER,
            comment_id INTEGER,
            reason TEXT,
            timestamp INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')

    conn.commit()

    # --- AUTO-MIGRATION FOR EXISTING DATABASES ---
    c.execute("PRAGMA table_info(users)")
    user_cols = [row[1] for row in c.fetchall()]
    if 'last_daily' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN last_daily INTEGER DEFAULT 0")
    if 'notify_activity' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN notify_activity BOOLEAN DEFAULT 1")
        
    c.execute("PRAGMA table_info(confessions)")
    conf_cols = [row[1] for row in c.fetchall()]
    if 'media_type' not in conf_cols:
        c.execute("ALTER TABLE confessions ADD COLUMN media_type TEXT")
    if 'media_file_id' not in conf_cols:
        c.execute("ALTER TABLE confessions ADD COLUMN media_file_id TEXT")
        
    conn.commit()
    conn.close()

def create_user(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_user(user_id, **kwargs):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    cols = ', '.join([f"{k} = ?" for k in kwargs])
    vals = list(kwargs.values()) + [user_id]
    c.execute(f"UPDATE users SET {cols} WHERE user_id = ?", vals)
    conn.commit()
    conn.close()

def accept_privacy_policy(user_id):
    update_user(user_id, accepted_policy=1)

def add_aura_points(user_id, points=1):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("UPDATE users SET aura_points = MAX(0, aura_points + ?) WHERE user_id = ?", (points, user_id))
    c.execute("UPDATE users SET star_balance = star_balance + 1 WHERE user_id = ? AND aura_points % 10 = 0", (user_id,))
    c.execute("SELECT aura_points, star_balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    return row['aura_points'], row['star_balance']

def spend_stars(user_id, amount):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT star_balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    if balance >= amount:
        c.execute("UPDATE users SET star_balance = star_balance - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def claim_daily_reward(user_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row: 
        conn.close()
        return False, "❌ User not found."
    
    last_daily = row['last_daily'] or 0
    current_time = int(time.time())
    
    if current_time - last_daily < 86400:
        remaining = 86400 - (current_time - last_daily)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        conn.close()
        return False, f"⏳ *Daily Reward Already Claimed*\n\nYou can claim your next reward in {hours}h {minutes}m."
    
    c.execute("UPDATE users SET last_daily = ?, aura_points = aura_points + 5, star_balance = star_balance + 1 WHERE user_id = ?", (current_time, user_id))
    conn.commit()
    conn.close()
    return True, "🎁 *Daily Reward Claimed!*\n\nYou received +5 ✨ Aura Points and +1 ⭐️ Star.\n\nSee you tomorrow!"

def highlight_comment(comment_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE comments SET is_highlighted = 1 WHERE id = ?", (comment_id,))
    conn.commit()
    conn.close()

def get_comment_author(comment_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT user_id FROM comments WHERE id = ?", (comment_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_leaderboard(limit=10):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT user_id, nickname, emoji, aura_points, star_balance FROM users WHERE aura_points > 0 ORDER BY aura_points DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_confessions(user_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, text, approved, categories FROM confessions WHERE user_id = ? ORDER BY id DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_user_ids():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def follow_user(follower_id, followed_id):
    if follower_id == followed_id: return False
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO follows (follower_id, followed_id) VALUES (?, ?)", (follower_id, followed_id))
    if c.rowcount > 0:
        c.execute("UPDATE users SET followers_count = followers_count + 1 WHERE user_id = ?", (followed_id,))
        c.execute("UPDATE users SET following_count = following_count + 1 WHERE user_id = ?", (follower_id,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def unfollow_user(follower_id, followed_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM follows WHERE follower_id = ? AND followed_id = ?", (follower_id, followed_id))
    if c.rowcount > 0:
        c.execute("UPDATE users SET followers_count = MAX(0, followers_count - 1) WHERE user_id = ?", (followed_id,))
        c.execute("UPDATE users SET following_count = MAX(0, following_count - 1) WHERE user_id = ?", (follower_id,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def is_following(follower_id, followed_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT 1 FROM follows WHERE follower_id = ? AND followed_id = ?", (follower_id, followed_id))
    res = c.fetchone()
    conn.close()
    return res is not None

# --- NEW: PAGINATED NETWORK QUERIES ---
def get_followers_paginated(user_id, page=0, limit=5):
    offset = page * limit
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT follower_id FROM follows WHERE followed_id = ? LIMIT ? OFFSET ?", (user_id, limit, offset))
    rows = [row[0] for row in c.fetchall()]
    c.execute("SELECT COUNT(*) FROM follows WHERE followed_id = ?", (user_id,))
    total = c.fetchone()[0]
    conn.close()
    return rows, total

def get_following_paginated(user_id, page=0, limit=5):
    offset = page * limit
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT followed_id FROM follows WHERE follower_id = ? LIMIT ? OFFSET ?", (user_id, limit, offset))
    rows = [row[0] for row in c.fetchall()]
    c.execute("SELECT COUNT(*) FROM follows WHERE follower_id = ?", (user_id,))
    total = c.fetchone()[0]
    conn.close()
    return rows, total

def get_followers(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT follower_id FROM follows WHERE followed_id = ?", (user_id,))
    rows = [row[0] for row in c.fetchall()]
    conn.close()
    return rows

def is_user_blocked(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT is_banned, blocked_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row: return False, False
    is_banned, blocked_until = row
    if is_banned: return True, "permanent"
    if blocked_until and blocked_until > int(time.time()): return True, "temporary"
    return False, False

def warn_user(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET warn_count = warn_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def block_user_24h(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET blocked_until = ? WHERE user_id = ?", (int(time.time()) + 86400, user_id))
    conn.commit()
    conn.close()

def ban_user(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_confession(user_id, text, media_type=None, media_file_id=None, categories=""):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO confessions (user_id, text, media_type, media_file_id, categories) VALUES (?, ?, ?, ?, ?)", 
              (user_id, text, media_type, media_file_id, categories))
    conf_id = c.lastrowid
    conn.commit()
    conn.close()
    return conf_id

def approve_confession(conf_id, msg_id, hashtags):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE confessions SET approved=1, channel_msg_id=?, hashtags=? WHERE id=?", (msg_id, hashtags, conf_id))
    conn.commit()
    conn.close()

def get_confession(conf_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM confessions WHERE id = ?", (conf_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_confessions():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM confessions WHERE approved = 1 ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_confession_stats(conf_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM comments WHERE confession_id = ?", (conf_id,))
    comments = c.fetchone()[0]
    conn.close()
    return {"comments": comments}

def add_comment(conf_id, user_id, text, media_type=None, media_file_id=None, voice_effect='Original', parent_id=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    depth = 0
    if parent_id:
        c.execute("SELECT depth FROM comments WHERE id = ?", (parent_id,))
        parent = c.fetchone()
        depth = min((parent[0] + 1) if parent else 1, 2)
    c.execute("""
        INSERT INTO comments (confession_id, user_id, text, media_type, media_file_id, voice_effect, parent_id, depth) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (conf_id, user_id, text, media_type, media_file_id, voice_effect, parent_id, depth))
    comment_id = c.lastrowid
    conn.commit()
    conn.close()
    return comment_id

def get_comments(conf_id, limit=15):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT c.*, u.nickname, u.emoji, u.aura_points, u.star_balance
        FROM comments c
        JOIN users u ON c.user_id = u.user_id
        WHERE c.confession_id = ? AND c.parent_id IS NULL
        ORDER BY c.is_highlighted DESC, c.likes DESC, c.id ASC
        LIMIT ?
    """, (conf_id, limit))
    top = [dict(row) for row in c.fetchall()]
    for comment in top:
        c.execute("""
            SELECT c.*, u.nickname, u.emoji, u.aura_points, u.star_balance
            FROM comments c
            JOIN users u ON c.user_id = u.user_id
            WHERE c.parent_id = ?
            ORDER BY c.is_highlighted DESC, c.likes DESC, c.id ASC
        """, (comment['id'],))
        comment['replies'] = [dict(row) for row in c.fetchall()]
    conn.close()
    return top

def toggle_reaction(user_id, comment_id, reaction_type):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM reactions WHERE user_id = ? AND comment_id = ?", (user_id, comment_id))
    c.execute("INSERT INTO reactions (user_id, comment_id, reaction) VALUES (?, ?, ?)", (user_id, comment_id, reaction_type))
    c.execute("SELECT reaction FROM reactions WHERE comment_id = ?", (comment_id,))
    reactions = c.fetchall()
    likes = sum(1 for r in reactions if r[0] == 'like')
    dislikes = sum(1 for r in reactions if r[0] == 'dislike')
    c.execute("UPDATE comments SET likes = ?, dislikes = ? WHERE id = ?", (likes, dislikes, comment_id))
    conn.commit()
    conn.close()
    return likes, dislikes

def create_chat_request(from_id, to_id, conf_id, comment_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO chat_requests (from_user_id, to_user_id, confession_id, comment_id) VALUES (?, ?, ?, ?)",
              (from_id, to_id, conf_id, comment_id))
    req_id = c.lastrowid
    conn.commit()
    conn.close()
    return req_id

def get_chat_request(req_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM chat_requests WHERE id = ?", (req_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_chat_requests(user_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT cr.*, u1.nickname as from_nick, u2.nickname as to_nick
        FROM chat_requests cr
        JOIN users u1 ON cr.from_user_id = u1.user_id
        JOIN users u2 ON cr.to_user_id = u2.user_id
        WHERE cr.from_user_id = ? OR cr.to_user_id = ?
        ORDER BY cr.id DESC
    """, (user_id, user_id))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_chat_request(req_id, status):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE chat_requests SET status = ? WHERE id = ?", (status, req_id))
    conn.commit()
    conn.close()

def update_confession_text(conf_id, new_text):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE confessions SET text = ? WHERE id = ?", (new_text, conf_id))
    conn.commit()
    conn.close()

def delete_confession_permanently(conf_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM comments WHERE confession_id = ?", (conf_id,))
    c.execute("DELETE FROM confessions WHERE id = ?", (conf_id,))
    conn.commit()
    conn.close()

def add_report(reporter_id, target_id, confession_id, comment_id, reason):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO reports (reporter_id, target_id, confession_id, comment_id, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
              (reporter_id, target_id, confession_id, comment_id, reason, int(time.time())))
    conn.commit()
    conn.close()

def get_user_report_count(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM reports WHERE target_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_user_reports(user_id, limit=5):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM reports WHERE target_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]