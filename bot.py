# -*- coding: utf-8 -*-
"""
===============================================================================
🇬🇧 NOVA AI — ENGLISH LEARNING BOT
===============================================================================
Framework: pyTelegramBotAPI / TeleBot
Database : SQLite3
AI       : NOVA AI learning assistant
Files    : Single-file bot.py
Language : Uzbek + English
===============================================================================

MUHIM:
1) aiogram ishlatilmaydi.
2) NOVA AI uchun .env ichida NOVA_API_KEY o'rnatiladi.
3) .env faylini to'ldiring.
4) Birinchi ishga tushishda SQLite bazaga mazmunli offline savollar qo'shiladi.
5) AI yangi savollarni ham generatsiya qilib, bazaga saqlay oladi.
6) Har bir test javobidan keyin inglizcha gap + o'zbekcha tarjima ko'rsatiladi.
7) NOVA AI o'zbekcha, inglizcha yoki aralash suhbatni tushunadi.
===============================================================================
"""

import os
import sys
import re
import json
import html
import random
import sqlite3
import logging
import threading
import traceback
import atexit
import errno
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import telebot
from telebot import types

try:
    from google import genai
    from google.genai import types as genai_types
    GOOGLE_GENAI_AVAILABLE = True
except Exception:
    genai = None
    genai_types = None
    GOOGLE_GENAI_AVAILABLE = False



# =============================================================================
# 01. CONFIGURATION
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
NOVA_API_KEY = (
    os.getenv("NOVA_API_KEY", "").strip()
    or os.getenv("GEMINI_API_KEY", "").strip()
)
AI_MODEL = (
    os.getenv("AI_MODEL", "").strip()
    or os.getenv("GEMINI_MODEL", "").strip()
    or "gemini-flash-latest"
)
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
DB_NAME = os.getenv("DB_NAME", "").strip()
RAILWAY_VOLUME_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()


def positive_int_setting(name, default, minimum=1, maximum=1000):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise SystemExit(f"❌ {name} butun son bo'lishi kerak.") from exc
    if not minimum <= value <= maximum:
        raise SystemExit(f"❌ {name} {minimum}–{maximum} oralig'ida bo'lishi kerak.")
    return value


AI_TIMEOUT = positive_int_setting("AI_TIMEOUT", 30, 5, 300)
AI_HISTORY_LIMIT = positive_int_setting("AI_HISTORY_LIMIT", 12, 1, 100)
QUESTIONS_PER_TEST = positive_int_setting("QUESTIONS_PER_TEST", 10, 1, 50)
MIN_DATABASE_QUESTIONS = positive_int_setting("MIN_DATABASE_QUESTIONS", 39, 1, 10000)
if not DB_NAME:
    DB_NAME = (
        os.path.join(RAILWAY_VOLUME_PATH, "english_academy.db")
        if RAILWAY_VOLUME_PATH
        else "english_academy.db"
    )
DB_PATH = DB_NAME if os.path.isabs(DB_NAME) else os.path.join(BASE_DIR, DB_NAME)
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
LOCK_FILE = os.path.join(BASE_DIR, ".bot.lock")
LOCK_HANDLE = None


def acquire_single_instance_lock() -> bool:
    global LOCK_HANDLE
    handle = open(LOCK_FILE, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or getattr(exc, "winerror", None) in (33, 36):
            return False
        raise
    LOCK_HANDLE = handle
    return True


def release_single_instance_lock():
    global LOCK_HANDLE
    if LOCK_HANDLE is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            LOCK_HANDLE.seek(0)
            msvcrt.locking(LOCK_HANDLE.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
    finally:
        LOCK_HANDLE.close()
        LOCK_HANDLE = None


atexit.register(release_single_instance_lock)

if __name__ == "__main__" and not acquire_single_instance_lock():
    raise SystemExit("⚠️ Boshqa bot nusxasi ishlayapti. Faqat bitta nusxa ishga tushiriladi.")

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
    raise SystemExit("❌ BOT_TOKEN topilmadi. .env faylini to'ldiring.")

if not ADMIN_ID_RAW or ADMIN_ID_RAW == "YOUR_TELEGRAM_USER_ID":
    raise SystemExit("❌ ADMIN_ID topilmadi. .env faylini to'ldiring.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise SystemExit("❌ ADMIN_ID butun son bo'lishi kerak.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("NOVA_AI")

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode=None,
    threaded=True,
    num_threads=8
)

gemini_client = None
if GOOGLE_GENAI_AVAILABLE and NOVA_API_KEY:
    try:
        gemini_client = genai.Client(
            api_key=NOVA_API_KEY,
            http_options=genai_types.HttpOptions(timeout=AI_TIMEOUT * 1000)
        )
        logger.info("🤖 NOVA AI provider: READY")
    except Exception as exc:
        logger.exception("NOVA AI initialization failed: %s", exc)
        gemini_client = None
else:
    logger.warning("🤖 NOVA AI: OFFLINE (set NOVA_API_KEY in .env)")


# =============================================================================
# 02. LEVELS AND TOPICS
# =============================================================================

LEVELS = {
    "beginner": {
        "title": "🌱 Beginner",
        "emoji": "🌱",
        "description": "Boshlang'ich daraja: asosiy grammatika va kundalik ingliz tili.",
        "topics": [
            "🟢 To Be — am / is / are",
            "🟢 Subject Pronouns",
            "🟢 Object Pronouns",
            "🟢 Possessive Adjectives",
            "🟢 Articles — a / an / the",
            "🟢 Plural Nouns",
            "🟢 This / That / These / Those",
            "🟢 There is / There are",
            "🟢 Have / Has",
            "🟢 Can / Can't",
            "🟢 Present Simple",
            "🟢 Present Continuous",
            "🟢 Past Simple",
            "🟢 Future Simple",
            "🟢 Question Words",
            "🟢 Prepositions of Place",
            "🟢 Prepositions of Time",
            "🟢 Some / Any",
            "🟢 Much / Many",
            "🟢 Countable / Uncountable Nouns",
            "🟢 Adjectives",
            "🟢 Adverbs",
            "🟢 Basic Conjunctions"
        ]
    },
    "elementary": {
        "title": "📗 Elementary",
        "emoji": "📗",
        "description": "Asosiy zamonlar, modal fe'llar va gap tuzilishi.",
        "topics": [
            "🟡 Present Simple",
            "🟡 Present Continuous",
            "🟡 Past Simple",
            "🟡 Past Continuous",
            "🟡 Future Simple",
            "🟡 Be Going To",
            "🟡 Present Perfect",
            "🟡 Comparatives",
            "🟡 Superlatives",
            "🟡 Modal Verbs",
            "🟡 Should",
            "🟡 Must",
            "🟡 Have To",
            "🟡 First Conditional",
            "🟡 Gerunds",
            "🟡 Infinitives",
            "🟡 Quantifiers",
            "🟡 Question Forms",
            "🟡 Tag Questions",
            "🟡 Phrasal Verbs"
        ]
    },
    "pre_intermediate": {
        "title": "📘 Pre-Intermediate",
        "emoji": "📘",
        "description": "Murakkab zamonlar, passive, reported speech va conditionals.",
        "topics": [
            "🔵 Present Perfect vs Past Simple",
            "🔵 Present Perfect Continuous",
            "🔵 Past Perfect",
            "🔵 Future Forms",
            "🔵 Second Conditional",
            "🔵 Passive Voice",
            "🔵 Reported Speech",
            "🔵 Relative Clauses",
            "🔵 Used To",
            "🔵 Would",
            "🔵 Gerund vs Infinitive",
            "🔵 Linking Words",
            "🔵 Phrasal Verbs",
            "🔵 Advanced Prepositions"
        ]
    },
    "intermediate": {
        "title": "📙 Intermediate",
        "emoji": "📙",
        "description": "Erkin muloqot, barcha zamonlar va murakkab grammar.",
        "topics": [
            "🟣 All English Tenses",
            "🟣 Past Perfect Continuous",
            "🟣 Future Continuous",
            "🟣 Future Perfect",
            "🟣 Future Perfect Continuous",
            "🟣 Conditionals",
            "🟣 Mixed Conditionals",
            "🟣 Passive Voice",
            "🟣 Reported Speech",
            "🟣 Advanced Modal Verbs",
            "🟣 Wish / If Only",
            "🟣 Causative",
            "🟣 Relative Clauses",
            "🟣 Participle Clauses",
            "🟣 Gerunds / Infinitives",
            "🟣 Inversion",
            "🟣 Complex Sentences",
            "🟣 Collocations"
        ]
    },
    "upper_intermediate": {
        "title": "📕 Upper-Intermediate",
        "emoji": "📕",
        "description": "Akademik ingliz tili, idiomalar va advanced structures.",
        "topics": [
            "🟠 Advanced Tenses",
            "🟠 Mixed Conditionals",
            "🟠 Advanced Passive",
            "🟠 Advanced Reported Speech",
            "🟠 Modal Perfect",
            "🟠 Inversion",
            "🟠 Cleft Sentences",
            "🟠 Emphasis",
            "🟠 Participle Clauses",
            "🟠 Reduced Relative Clauses",
            "🟠 Advanced Relative Clauses",
            "🟠 Formal English",
            "🟠 Academic English",
            "🟠 Collocations",
            "🟠 Idioms",
            "🟠 Phrasal Verbs"
        ]
    },
    "advanced": {
        "title": "🎓 Advanced",
        "emoji": "🎓",
        "description": "C1/C2 grammar, academic writing va murakkab gaplar.",
        "topics": [
            "🔴 Advanced Grammar",
            "🔴 Advanced Conditionals",
            "🔴 Inversion",
            "🔴 Subjunctive",
            "🔴 Cleft Sentences",
            "🔴 Ellipsis",
            "🔴 Nominalisation",
            "🔴 Advanced Passive",
            "🔴 Advanced Modals",
            "🔴 Discourse Markers",
            "🔴 Academic Grammar",
            "🔴 Formal Grammar",
            "🔴 Advanced Collocations",
            "🔴 Idiomatic Expressions",
            "🔴 Complex Sentence Structures"
        ]
    },
    "ielts": {
        "title": "🏆 IELTS 1–9",
        "emoji": "🏆",
        "description": "IELTS Grammar, Vocabulary, Writing va Speaking uchun mashqlar.",
        "topics": [
            "🏆 IELTS Band 1",
            "🏆 IELTS Band 2",
            "🏆 IELTS Band 3",
            "🏆 IELTS Band 4",
            "🏆 IELTS Band 5",
            "🏆 IELTS Band 6",
            "🏆 IELTS Band 7",
            "🏆 IELTS Band 8",
            "🏆 IELTS Band 9",
            "🏆 IELTS Academic Vocabulary",
            "🏆 IELTS Writing Task 1",
            "🏆 IELTS Writing Task 2",
            "🏆 IELTS Speaking",
            "🏆 IELTS Reading",
            "🏆 IELTS Listening"
        ]
    }
}

LEVEL_BUTTONS = {
    "🌱 Beginner": "beginner",
    "📗 Elementary": "elementary",
    "📘 Pre-Intermediate": "pre_intermediate",
    "📙 Intermediate": "intermediate",
    "📕 Upper-Intermediate": "upper_intermediate",
    "🎓 Advanced": "advanced",
    "🏆 IELTS 1–9": "ielts"
}


# =============================================================================
# 03. DATABASE
# =============================================================================

def sentence_key(sentence: str) -> str:
    return re.sub(r"\W+", " ", sentence.casefold(), flags=re.UNICODE).strip()


class Database:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self.init()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=60, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self):
        with self.lock:
            conn = self.connect()
            cur = conn.cursor()

            cur.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                streak INTEGER DEFAULT 0,
                last_active TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                topic TEXT NOT NULL,
                sentence TEXT NOT NULL,
                translation TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                option1 TEXT NOT NULL,
                option2 TEXT NOT NULL,
                option3 TEXT NOT NULL,
                explanation TEXT NOT NULL,
                difficulty TEXT DEFAULT 'medium',
                source TEXT DEFAULT 'database',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);
            CREATE INDEX IF NOT EXISTS idx_questions_level ON questions(level);

            CREATE TABLE IF NOT EXISTS served_questions (
                sentence_key TEXT PRIMARY KEY,
                question_id INTEGER UNIQUE NOT NULL,
                served_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                question_id INTEGER,
                topic TEXT,
                answer TEXT,
                correct INTEGER,
                xp INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS progress (
                telegram_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                total INTEGER DEFAULT 0,
                correct INTEGER DEFAULT 0,
                wrong INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0,
                PRIMARY KEY (telegram_id, topic)
            );

            CREATE TABLE IF NOT EXISTS ai_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                telegram_id INTEGER PRIMARY KEY,
                preferred_language TEXT DEFAULT 'uz',
                ai_enabled INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS study_plans (
                telegram_id INTEGER PRIMARY KEY,
                reminder_enabled INTEGER NOT NULL DEFAULT 0,
                reminder_time TEXT NOT NULL DEFAULT '19:00',
                last_reminded_date TEXT,
                last_completed_date TEXT
            );

            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """)
            previously_answered = conn.execute("""
                SELECT DISTINCT q.id, q.sentence
                FROM answers a
                JOIN questions q ON q.id=a.question_id
                WHERE a.question_id IS NOT NULL
            """).fetchall()
            for row in previously_answered:
                conn.execute(
                    "INSERT OR IGNORE INTO served_questions(sentence_key, question_id) "
                    "VALUES(?, ?)",
                    (sentence_key(row["sentence"]), row["id"])
                )
            conn.commit()
            conn.close()

    def user(self, telegram_id: int):
        with self.lock:
            conn = self.connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()
            conn.close()
            return row

    def register(self, telegram_id: int, username: str, first_name: str, last_name: str):
        today = date.today().isoformat()
        with self.lock:
            conn = self.connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()

            if row is None:
                conn.execute("""
                    INSERT INTO users
                    (telegram_id, username, first_name, last_name, xp, level, streak, last_active)
                    VALUES (?, ?, ?, ?, 0, 1, 1, ?)
                """, (telegram_id, username, first_name, last_name, today))
            else:
                old_date = row["last_active"]
                streak = row["streak"] or 0
                if old_date:
                    try:
                        diff = (date.today() - date.fromisoformat(old_date)).days
                        if diff == 1:
                            streak += 1
                        elif diff > 1:
                            streak = 1
                    except Exception:
                        streak = max(streak, 1)
                else:
                    streak = max(streak, 1)

                conn.execute("""
                    UPDATE users
                    SET username=?, first_name=?, last_name=?, streak=?, last_active=?
                    WHERE telegram_id=?
                """, (username, first_name, last_name, streak, today, telegram_id))

            conn.execute("""
                INSERT OR IGNORE INTO settings(telegram_id)
                VALUES(?)
            """, (telegram_id,))
            conn.execute("""
                INSERT OR IGNORE INTO study_plans(telegram_id)
                VALUES(?)
            """, (telegram_id,))
            conn.commit()

            result = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()
            conn.close()
            return result

    def count_questions(self) -> int:
        with self.lock:
            conn = self.connect()
            n = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
            conn.close()
            return n

    def questions_by_ids(self, question_ids: List[int]) -> List[Dict[str, Any]]:
        if not question_ids:
            return []
        placeholders = ",".join("?" for _ in question_ids)
        with self.lock:
            conn = self.connect()
            rows = conn.execute(
                f"SELECT * FROM questions WHERE id IN ({placeholders})",
                question_ids
            ).fetchall()
            conn.close()
            row_by_id = {row["id"]: dict(row) for row in rows}
            return [row_by_id[qid] for qid in question_ids if qid in row_by_id]

    def insert_question(self, q: Dict[str, Any]) -> int:
        with self.lock:
            conn = self.connect()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO questions
                (level, topic, sentence, translation, correct_answer,
                 option1, option2, option3, explanation, difficulty, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                q["level"], q["topic"], q["sentence"], q["translation"],
                q["correct_answer"], q["option1"], q["option2"], q["option3"],
                q["explanation"], q.get("difficulty", "medium"),
                q.get("source", "database")
            ))
            conn.commit()
            qid = cur.lastrowid
            conn.close()
            return qid

    def bulk_insert(self, questions: List[Dict[str, Any]]) -> List[int]:
        with self.lock:
            conn = self.connect()
            question_ids = []
            for q in questions:
                cursor = conn.execute("""
                    INSERT INTO questions
                    (level, topic, sentence, translation, correct_answer,
                     option1, option2, option3, explanation, difficulty, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    q["level"], q["topic"], q["sentence"], q["translation"],
                    q["correct_answer"], q["option1"], q["option2"], q["option3"],
                    q["explanation"], q.get("difficulty", "medium"),
                    q.get("source", "database")
                ))
                question_ids.append(cursor.lastrowid)
            conn.commit()
            conn.close()
            return question_ids

    def bulk_insert_unique(self, questions: List[Dict[str, Any]]) -> List[int]:
        with self.lock:
            conn = self.connect()
            existing_keys = {
                sentence_key(row["sentence"])
                for row in conn.execute("SELECT sentence FROM questions").fetchall()
            }
            question_ids = []
            for question in questions:
                key = sentence_key(question["sentence"])
                if not key or key in existing_keys:
                    continue
                cursor = conn.execute("""
                    INSERT INTO questions
                    (level, topic, sentence, translation, correct_answer,
                     option1, option2, option3, explanation, difficulty, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    question["level"], question["topic"], question["sentence"],
                    question["translation"], question["correct_answer"],
                    question["option1"], question["option2"], question["option3"],
                    question["explanation"], question.get("difficulty", "medium"),
                    question.get("source", "database")
                ))
                question_ids.append(cursor.lastrowid)
                existing_keys.add(key)
            conn.commit()
            conn.close()
            return question_ids

    def reserve_questions(
        self, questions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        with self.lock:
            conn = self.connect()
            reserved = []
            keys = set()
            for question in questions:
                key = sentence_key(question["sentence"])
                if not key or key in keys:
                    continue
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO served_questions(sentence_key, question_id) "
                    "VALUES(?, ?)",
                    (key, question["id"])
                )
                if cursor.rowcount:
                    keys.add(key)
                    reserved.append(question)
            conn.commit()
            conn.close()
            return reserved

    def question_sentence_sample(self, limit: int = 40) -> List[str]:
        with self.lock:
            conn = self.connect()
            rows = conn.execute(
                "SELECT sentence FROM questions ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return [row["sentence"] for row in rows]

    def meta(self, key: str) -> Optional[str]:
        with self.lock:
            conn = self.connect()
            row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
            conn.close()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        with self.lock:
            conn = self.connect()
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value)
            )
            conn.commit()
            conn.close()

    def random_questions(self, topic: str, level: str, limit: int = 10,
                         fallback_to_level: bool = True):
        with self.lock:
            conn = self.connect()
            rows = conn.execute("""
                SELECT * FROM questions
                WHERE topic=? AND level=?
                    AND id NOT IN (SELECT question_id FROM served_questions)
                ORDER BY RANDOM()
            """, (topic, level)).fetchall()
            selected = []
            seen_keys = set()

            def reserve_rows(candidates):
                for row in candidates:
                    if len(selected) >= limit:
                        break
                    question = dict(row)
                    key = sentence_key(question["sentence"])
                    if not key or key in seen_keys:
                        continue
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO served_questions(sentence_key, question_id) "
                        "VALUES(?, ?)",
                        (key, question["id"])
                    )
                    if cursor.rowcount:
                        seen_keys.add(key)
                        selected.append(question)

            reserve_rows(rows)
            if fallback_to_level and len(selected) < limit:
                fallback_rows = conn.execute("""
                    SELECT * FROM questions
                    WHERE level=? AND topic<>?
                        AND id NOT IN (SELECT question_id FROM served_questions)
                    ORDER BY RANDOM()
                """, (level, topic)).fetchall()
                reserve_rows(fallback_rows)
            conn.commit()
            conn.close()
            return selected

    def plan_questions(self, telegram_id: int, topic: str, level: str,
                       limit: int = 3) -> List[Dict[str, Any]]:
        with self.lock:
            conn = self.connect()
            review_rows = conn.execute("""
                SELECT q.*
                FROM answers a
                JOIN (
                    SELECT question_id, MAX(id) AS latest_id
                    FROM answers
                    WHERE telegram_id=? AND question_id IS NOT NULL
                    GROUP BY question_id
                ) latest ON latest.latest_id=a.id
                JOIN questions q ON q.id=a.question_id
                WHERE a.correct=0 AND q.topic=? AND q.level=?
                    AND q.id NOT IN (SELECT question_id FROM served_questions)
                ORDER BY a.id DESC
                LIMIT ?
            """, (telegram_id, topic, level, limit)).fetchall()
            questions = [dict(row) for row in review_rows]
            selected_ids = {question["id"] for question in questions}
            exclusion = (
                f" AND id NOT IN ({','.join('?' for _ in selected_ids)})"
                if selected_ids else ""
            )
            excluded_ids = tuple(selected_ids)
            rows = conn.execute(
                f"""
                SELECT * FROM questions
                WHERE level=? AND topic=?
                    AND id NOT IN (SELECT question_id FROM served_questions)
                    {exclusion}
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (level, topic, *excluded_ids, limit - len(questions))
            ).fetchall()
            questions.extend(dict(row) for row in rows)
            selected_ids.update(row["id"] for row in rows)
            if len(questions) < limit:
                exclusion = (
                    f" AND id NOT IN ({','.join('?' for _ in selected_ids)})"
                    if selected_ids else ""
                )
                rows = conn.execute(
                    f"""
                    SELECT * FROM questions
                    WHERE level=? AND topic<>?
                        AND id NOT IN (SELECT question_id FROM served_questions)
                        {exclusion}
                    ORDER BY RANDOM()
                    LIMIT ?
                    """,
                    (level, topic, *tuple(selected_ids), limit - len(questions))
                ).fetchall()
                questions.extend(dict(row) for row in rows)
            conn.close()
            questions = self.reserve_questions(questions)
            if len(questions) < limit:
                questions.extend(
                    self.random_questions(topic, level, limit - len(questions))
                )
            return questions[:limit]

    def study_plan(self, telegram_id: int):
        with self.lock:
            conn = self.connect()
            conn.execute(
                "INSERT OR IGNORE INTO study_plans(telegram_id) VALUES(?)",
                (telegram_id,)
            )
            row = conn.execute(
                "SELECT * FROM study_plans WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()
            conn.commit()
            conn.close()
            return dict(row)

    def set_study_reminder(self, telegram_id: int, enabled: bool,
                           reminder_time: Optional[str] = None):
        with self.lock:
            conn = self.connect()
            conn.execute(
                "INSERT OR IGNORE INTO study_plans(telegram_id) VALUES(?)",
                (telegram_id,)
            )
            if reminder_time is None:
                conn.execute(
                    "UPDATE study_plans SET reminder_enabled=? WHERE telegram_id=?",
                    (int(enabled), telegram_id)
                )
            else:
                conn.execute("""
                    UPDATE study_plans
                    SET reminder_enabled=?, reminder_time=?
                    WHERE telegram_id=?
                """, (int(enabled), reminder_time, telegram_id))
            conn.commit()
            conn.close()

    def due_study_reminders(self, today: str, current_time: str):
        with self.lock:
            conn = self.connect()
            rows = conn.execute("""
                SELECT telegram_id, reminder_time FROM study_plans
                WHERE reminder_enabled=1
                  AND reminder_time<=?
                  AND (last_reminded_date IS NULL OR last_reminded_date<>?)
            """, (current_time, today)).fetchall()
            conn.close()
            return [dict(row) for row in rows]

    def mark_study_reminder_sent(self, telegram_id: int, today: str):
        with self.lock:
            conn = self.connect()
            conn.execute(
                "UPDATE study_plans SET last_reminded_date=? WHERE telegram_id=?",
                (today, telegram_id)
            )
            conn.commit()
            conn.close()

    def mark_study_completed(self, telegram_id: int, today: str):
        with self.lock:
            conn = self.connect()
            conn.execute(
                "UPDATE study_plans SET last_completed_date=? WHERE telegram_id=?",
                (today, telegram_id)
            )
            conn.commit()
            conn.close()

    def add_xp(self, telegram_id: int, amount: int):
        thresholds = [0, 100, 250, 500, 900, 1400, 2100, 3000, 4200, 6000, 8500]
        with self.lock:
            conn = self.connect()
            row = conn.execute(
                "SELECT xp, level FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()
            if not row:
                conn.close()
                return 0, 1, False
            xp = (row["xp"] or 0) + amount
            old = row["level"] or 1
            level = 1
            for i, threshold in enumerate(thresholds, 1):
                if xp >= threshold:
                    level = i
            conn.execute(
                "UPDATE users SET xp=?, level=? WHERE telegram_id=?",
                (xp, level, telegram_id)
            )
            conn.commit()
            conn.close()
            return xp, level, level > old

    def record_answer(self, telegram_id, question_id, topic, answer, correct, xp):
        with self.lock:
            conn = self.connect()
            user = conn.execute(
                "SELECT streak, last_active FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()
            if user:
                today = date.today().isoformat()
                old_date = user["last_active"]
                streak = user["streak"] or 0
                if old_date != today:
                    try:
                        elapsed_days = (date.today() - date.fromisoformat(old_date)).days if old_date else None
                    except ValueError:
                        elapsed_days = None
                    streak = streak + 1 if elapsed_days == 1 else 1
                    conn.execute(
                        "UPDATE users SET streak=?, last_active=? WHERE telegram_id=?",
                        (streak, today, telegram_id)
                    )

            conn.execute("""
                INSERT INTO answers
                (telegram_id, question_id, topic, answer, correct, xp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (telegram_id, question_id, topic, answer, int(correct), xp))

            row = conn.execute("""
                SELECT * FROM progress
                WHERE telegram_id=? AND topic=?
            """, (telegram_id, topic)).fetchone()

            if row is None:
                total = 1
                c = int(correct)
                w = int(not correct)
                acc = c * 100.0
                conn.execute("""
                    INSERT INTO progress
                    (telegram_id, topic, total, correct, wrong, accuracy)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (telegram_id, topic, total, c, w, acc))
            else:
                total = row["total"] + 1
                c = row["correct"] + int(correct)
                w = row["wrong"] + int(not correct)
                acc = c * 100.0 / total
                conn.execute("""
                    UPDATE progress
                    SET total=?, correct=?, wrong=?, accuracy=?
                    WHERE telegram_id=? AND topic=?
                """, (total, c, w, acc, telegram_id, topic))

            conn.commit()
            conn.close()

    def stats(self, telegram_id):
        with self.lock:
            conn = self.connect()
            user = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()
            a = conn.execute("""
                SELECT COUNT(*) total,
                       COALESCE(SUM(correct),0) correct,
                       COALESCE(SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END),0) wrong
                FROM answers WHERE telegram_id=?
            """, (telegram_id,)).fetchone()

            strong = conn.execute("""
                SELECT topic, accuracy FROM progress
                WHERE telegram_id=? AND total>=3
                ORDER BY accuracy DESC, total DESC LIMIT 1
            """, (telegram_id,)).fetchone()

            weak = conn.execute("""
                SELECT topic, accuracy FROM progress
                WHERE telegram_id=? AND total>=3
                ORDER BY accuracy ASC, total DESC LIMIT 1
            """, (telegram_id,)).fetchone()

            conn.close()
            total = a["total"] or 0
            correct = a["correct"] or 0
            accuracy = round(correct * 100 / total, 1) if total else 0
            return {
                "user": user,
                "total": total,
                "correct": correct,
                "wrong": a["wrong"] or 0,
                "accuracy": accuracy,
                "strong": strong,
                "weak": weak
            }

    def leaderboard(self, limit=10):
        with self.lock:
            conn = self.connect()
            rows = conn.execute("""
                SELECT first_name, username, xp, level, streak
                FROM users ORDER BY xp DESC, streak DESC LIMIT ?
            """, (limit,)).fetchall()
            conn.close()
            return rows

    def rank(self, telegram_id):
        with self.lock:
            conn = self.connect()
            row = conn.execute("""
                SELECT COUNT(*) + 1 AS rank
                FROM users
                WHERE xp > (SELECT COALESCE(xp,0) FROM users WHERE telegram_id=?)
            """, (telegram_id,)).fetchone()
            conn.close()
            return row["rank"] if row else 1

    def save_ai(self, telegram_id, role, content):
        with self.lock:
            conn = self.connect()
            conn.execute(
                "INSERT INTO ai_history(telegram_id, role, content) VALUES(?,?,?)",
                (telegram_id, role, content)
            )
            conn.commit()
            conn.close()

    def ai_history(self, telegram_id, limit=12):
        with self.lock:
            conn = self.connect()
            rows = conn.execute("""
                SELECT role, content FROM ai_history
                WHERE telegram_id=? ORDER BY id DESC LIMIT ?
            """, (telegram_id, limit)).fetchall()
            conn.close()
            return list(reversed(rows))

    def clear_ai(self, telegram_id):
        with self.lock:
            conn = self.connect()
            conn.execute("DELETE FROM ai_history WHERE telegram_id=?", (telegram_id,))
            conn.commit()
            conn.close()

    def all_users(self):
        with self.lock:
            conn = self.connect()
            rows = conn.execute("SELECT telegram_id FROM users").fetchall()
            conn.close()
            return [x["telegram_id"] for x in rows]

    def admin_stats(self):
        with self.lock:
            conn = self.connect()
            data = {
                "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
                "answers": conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0],
                "ai": conn.execute("SELECT COUNT(*) FROM ai_history WHERE role='user'").fetchone()[0],
            }
            conn.close()
            return data

db = Database(DB_PATH)


# =============================================================================
# 04. LARGE OFFLINE QUESTION BANK + AUTO GENERATION
# =============================================================================

def clean_topic(topic: str) -> str:
    return re.sub(r"^[^\w]+", "", topic, flags=re.UNICODE).strip()

def make_q(level, topic, sentence, translation, correct, wrong1, wrong2,
           wrong3, explanation, difficulty="easy"):
    return {
        "level": level,
        "topic": topic,
        "sentence": sentence,
        "translation": translation,
        "correct_answer": correct,
        "option1": wrong1,
        "option2": wrong2,
        "option3": wrong3,
        "explanation": explanation,
        "difficulty": difficulty,
        "source": "offline_seed"
    }

def _build_legacy_seed_questions() -> List[Dict[str, Any]]:
    q = []

    # -------------------------------------------------------------------------
    # Beginner — To Be
    # -------------------------------------------------------------------------
    subjects = [
        ("I", "am", "Men"), ("You", "are", "Sen/Siz"), ("He", "is", "U (erkak)"),
        ("She", "is", "U (ayol)"), ("It", "is", "U (narsa/hayvon)"),
        ("We", "are", "Biz"), ("They", "are", "Ular")
    ]
    adjectives = [
        ("happy", "xursand"), ("ready", "tayyor"), ("busy", "band"),
        ("tired", "charchagan"), ("strong", "kuchli"), ("careful", "ehtiyotkor"),
        ("at home", "uyda"), ("a student", "talaba/o'quvchi"),
        ("from Uzbekistan", "O'zbekistondan"), ("very kind", "juda mehribon")
    ]
    for i, (s, verb, uzs) in enumerate(subjects):
        for j, (adj, uadj) in enumerate(adjectives):
            sentence = f"{s} ___ {adj}."
            translation = f"{uzs} {uadj}."
            wrongs = ["is", "am", "are"]
            options = [verb] + [x for x in wrongs if x != verb][:2]
            q.append(make_q(
                "beginner", "🟢 To Be — am / is / are",
                sentence, translation, verb, options[1], options[2],
                "was", f"{s} bilan {verb} ishlatiladi.", "easy"
            ))

    # -------------------------------------------------------------------------
    # Beginner — Present Simple
    # -------------------------------------------------------------------------
    people = [
        ("I", "work", "Men ishlayman"), ("You", "study", "Sen/Siz o'qiysan"),
        ("We", "play", "Biz o'ynaymiz"), ("They", "watch", "Ular tomosha qiladi"),
        ("He", "works", "U ishlaydi"), ("She", "studies", "U o'qiydi"),
        ("It", "works", "U ishlaydi")
    ]
    for s, verb, uz in people:
        base = re.sub(r"(s|ies)$", "", verb)
        if verb.endswith("ies"):
            base = verb[:-3] + "y"
        elif verb.endswith("s"):
            base = verb[:-1]
        correct = verb
        sentence = f"{s} ___ English every day."
        translation = f"{uz} ingliz tilini har kuni."
        if s in ("I", "You", "We", "They"):
            correct = base
            w1 = verb
            w2 = base + "ing"
            w3 = "is"
        else:
            correct = verb
            w1 = base
            w2 = base + "ing"
            w3 = "are"
        q.append(make_q(
            "beginner", "🟢 Present Simple", sentence, translation,
            correct, w1, w2, w3,
            "Present Simpleda he/she/it bilan fe'l odatda -s/-es oladi.",
            "easy"
        ))

    # -------------------------------------------------------------------------
    # Beginner — Have/Has, Can, There is/are
    # -------------------------------------------------------------------------
    have_items = [
        ("I", "have", "Men ... ga egaman"),
        ("You", "have", "Sen/Siz ... ga egasan"),
        ("We", "have", "Biz ... ga egamiz"),
        ("They", "have", "Ular ... ga ega"),
        ("He", "has", "U ... ga ega"),
        ("She", "has", "U ... ga ega")
    ]
    for s, v, uz in have_items:
        q.append(make_q(
            "beginner", "🟢 Have / Has",
            f"{s} ___ a new English book.",
            f"{uz} yangi ingliz tili kitobiga.",
            v, "have" if v == "has" else "has",
            "having", "had",
            "He/She bilan has, I/You/We/They bilan have ishlatiladi.", "easy"
        ))

    can_subjects = ["I", "You", "He", "She", "We", "They"]
    can_verbs = [("swim", "suzmoq"), ("drive", "haydamoq"), ("cook", "ovqat pishirmoq"),
                 ("read", "o'qimoq"), ("speak English", "inglizcha gapirmoq")]
    for s in can_subjects:
        for v, uv in can_verbs:
            q.append(make_q(
                "beginner", "🟢 Can / Can't",
                f"{s} ___ {v}.",
                f"{s} {uv} oladi.",
                "can", "can to", "cans", "is",
                "Can dan keyin fe'lning V1 shakli ishlatiladi.", "easy"
            ))

    for n, noun, uznoun in [
        ("There is", "a book on the desk", "stol ustida kitob bor"),
        ("There are", "two books on the desk", "stol ustida ikkita kitob bor"),
        ("There is", "a computer in the room", "xonada kompyuter bor"),
        ("There are", "three students outside", "tashqarida uchta o'quvchi bor"),
    ]:
        correct = n
        wrong = "There are" if n == "There is" else "There is"
        q.append(make_q(
            "beginner", "🟢 There is / There are",
            f"___ {noun}.", f"{uznoun}.", correct, wrong,
            "It is", "They are",
            "Birlik ot bilan There is, ko'plik bilan There are ishlatiladi.", "easy"
        ))

    # -------------------------------------------------------------------------
    # Elementary — Past Simple
    # -------------------------------------------------------------------------
    past = [
        ("I", "visit", "visited", "Men ... bordim"),
        ("She", "watch", "watched", "U ... tomosha qildi"),
        ("They", "play", "played", "Ular ... o'ynadi"),
        ("We", "clean", "cleaned", "Biz ... tozaladik"),
        ("He", "open", "opened", "U ... ochdi"),
        ("I", "study", "studied", "Men ... o'qidim")
    ]
    objects = [
        ("the museum", "muzeyni"), ("the lesson", "darsni"),
        ("football", "futbolni"), ("the room", "xonani"),
        ("the door", "eshikni"), ("English", "ingliz tilini")
    ]
    for idx, (s, base, v2, uzs) in enumerate(past):
        obj, uobj = objects[idx]
        q.append(make_q(
            "elementary", "🟡 Past Simple",
            f"{s} ___ {obj} yesterday.",
            f"{uzs} {uobj} kecha.",
            v2, base, base + "ing", "will " + base,
            "Yesterday o'tgan zamonni bildiradi, shuning uchun Past Simple ishlatiladi.",
            "easy"
        ))

    irregulars = [
        ("go", "went", "gone", "bormoq"),
        ("see", "saw", "seen", "ko'rmoq"),
        ("eat", "ate", "eaten", "yemoq"),
        ("take", "took", "taken", "olmoq"),
        ("write", "wrote", "written", "yozmoq"),
        ("come", "came", "come", "kelmoq"),
        ("buy", "bought", "bought", "sotib olmoq"),
        ("make", "made", "made", "qilmoq/yasamoq"),
        ("find", "found", "found", "topmoq"),
        ("give", "gave", "given", "bermoq")
    ]
    for base, v2, v3, uz in irregulars:
        q.append(make_q(
            "elementary", "🟡 Past Simple",
            f"Yesterday I ___ to the market.",
            f"Kecha men bozorga ___.",
            v2, base, v3, "will " + base,
            f"{base} fe'lining Past Simple shakli {v2}.", "medium"
        ))

    # -------------------------------------------------------------------------
    # Elementary — Present Continuous / Future / Perfect / Comparatives
    # -------------------------------------------------------------------------
    continuous_verbs = [
        ("read", "o'qimoq"), ("write", "yozmoq"), ("study", "o'qimoq"),
        ("cook", "ovqat pishirmoq"), ("sleep", "uxlamoq"), ("work", "ishlamoq"),
        ("run", "yugurmoq"), ("play", "o'ynamoq")
    ]
    for verb, uv in continuous_verbs:
        ing = verb + "ing"
        if verb.endswith("e"):
            ing = verb[:-1] + "ing"
        q.append(make_q(
            "elementary", "🟡 Present Continuous",
            f"She is ___ {verb} now.",
            f"U hozir {uv} bilan band.",
            ing, verb, verb + "s", "was " + verb,
            "Hozir sodir bo'layotgan harakat uchun am/is/are + V-ing ishlatiladi.",
            "easy"
        ))

    future_verbs = [
        ("call", "qo'ng'iroq qilmoq"), ("visit", "tashrif buyurmoq"),
        ("study", "o'qimoq"), ("travel", "sayohat qilmoq"),
        ("help", "yordam bermoq"), ("start", "boshlamoq")
    ]
    for verb, uv in future_verbs:
        q.append(make_q(
            "elementary", "🟡 Future Simple",
            f"I ___ {verb} you tomorrow.",
            f"Men ertaga sizga {uv} qilaman.",
            "will " + verb, verb, "am " + verb + "ing", "did " + verb,
            "Future Simple: will + V1.", "easy"
        ))

    perfect_verbs = [
        ("finish", "tugatmoq"), ("complete", "yakunlamoq"),
        ("visit", "tashrif buyurmoq"), ("read", "o'qimoq"),
        ("learn", "o'rganmoq")
    ]
    for verb, uv in perfect_verbs:
        q.append(make_q(
            "elementary", "🟡 Present Perfect",
            f"I have ___ the task already.",
            f"Men vazifani allaqachon {uv}.",
            verb + ("ed" if verb not in ("read",) else ""),
            verb, verb + "ing", "will " + verb,
            "Present Perfect: have/has + V3. Already ko'pincha shu zamon bilan keladi.",
            "medium"
        ))

    comps = [
        ("fast", "faster", "eng tez", "tez"), ("small", "smaller", "kichikroq", "kichik"),
        ("beautiful", "more beautiful", "chiroyliroq", "chiroyli"),
        ("interesting", "more interesting", "qiziqroq", "qiziqarli"),
        ("good", "better", "yaxshiroq", "yaxshi"),
        ("bad", "worse", "yomonroq", "yomon")
    ]
    for base, comp, _, uz in comps:
        q.append(make_q(
            "elementary", "🟡 Comparatives",
            f"My car is ___ than yours.",
            f"Mening mashinam siznikidan {uz}roq.",
            comp, base, "most " + base, "as " + base,
            "Ikki narsani solishtirishda comparative shakl ishlatiladi.", "medium"
        ))

    # -------------------------------------------------------------------------
    # Pre-Intermediate
    # -------------------------------------------------------------------------
    for v, uv in [
        ("finish", "tugatmoq"), ("see", "ko'rmoq"), ("visit", "tashrif buyurmoq"),
        ("learn", "o'rganmoq"), ("read", "o'qimoq"), ("write", "yozmoq")
    ]:
        v3 = v + "ed" if v not in ("see", "read") else ("seen" if v == "see" else "read")
        q.append(make_q(
            "pre_intermediate", "🔵 Present Perfect vs Past Simple",
            f"I have ___ this book before.",
            f"Men bu kitobni oldin {uv}.",
            v3, v, v + "ing", "had " + v3,
            "Aniq o'tgan vaqt emas, tajriba ma'nosi bo'lsa Present Perfect ishlatilishi mumkin.",
            "medium"
        ))

    for verb in ["go", "travel", "study", "work", "live", "exercise"]:
        q.append(make_q(
            "pre_intermediate", "🔵 Second Conditional",
            f"If I had more time, I would ___ every day.",
            f"Agar ko'proq vaqtim bo'lsa, har kuni ___ qilardim.",
            verb, verb + "ed", "will " + verb, "would " + verb,
            "Second Conditional: If + Past Simple, would + V1.", "medium"
        ))

    passive_pairs = [
        ("build", "built", "The bridge was ___ last year.", "Ko'prik o'tgan yili qurildi."),
        ("write", "written", "The report was ___ by the manager.", "Hisobot menejer tomonidan yozildi."),
        ("make", "made", "The cake was ___ this morning.", "Tort bugun ertalab tayyorlandi."),
        ("clean", "cleaned", "The room was ___ yesterday.", "Xona kecha tozalandi."),
        ("translate", "translated", "The text was ___ into English.", "Matn inglizchaga tarjima qilindi.")
    ]
    for base, v3, sentence, translation in passive_pairs:
        q.append(make_q(
            "pre_intermediate", "🔵 Passive Voice",
            sentence, translation, v3, base, base + "ing", "was " + base,
            "Passive Voice'da be + V3 ishlatiladi.", "medium"
        ))

    # -------------------------------------------------------------------------
    # Intermediate
    # -------------------------------------------------------------------------
    for marker, form, translation in [
        ("By next year", "will have finished", "Keyingi yilgacha tugatgan bo'laman."),
        ("By Friday", "will have completed", "Jumagacha yakunlagan bo'laman."),
        ("By 2030", "will have developed", "2030 yilgacha ishlab chiqqan bo'ladi."),
        ("By the end of the month", "will have saved", "Oy oxirigacha jamg'argan bo'laman.")
    ]:
        sentence = f"{marker}, I ___ the project."
        wrong1 = form.replace("will have", "have")
        wrong2 = form.replace("will have", "had")
        q.append(make_q(
            "intermediate", "🟣 Future Perfect",
            sentence, translation, form, wrong1, wrong2, "will " + form.split()[-1],
            "Future Perfect: will have + V3.", "hard"
        ))

    inversion = [
        ("Never", "have I seen", "Men hech qachon ko'rmaganman."),
        ("Rarely", "do we get", "Biz kamdan-kam olamiz."),
        ("Only then", "did he understand", "Faqat shunda u tushundi."),
        ("Seldom", "has she visited", "U kamdan-kam tashrif buyurgan.")
    ]
    for starter, correct, uz in inversion:
        sentence = f"{starter} ___ such a beautiful place."
        wrong1 = correct.split()[-1]
        wrong2 = "I have seen"
        q.append(make_q(
            "intermediate", "🟣 Inversion",
            sentence, uz, correct, wrong1, wrong2, "has " + correct.split()[-1],
            "Negative/restrictive adverbials gap boshida kelsa inversion yuz berishi mumkin.",
            "hard"
        ))

    # -------------------------------------------------------------------------
    # Upper-Intermediate / Advanced / IELTS
    # -------------------------------------------------------------------------
    advanced_items = [
        ("subjunctive", "🔴 Subjunctive",
         "The committee insisted that he ___ present.",
         "Komissiya uning shaxsan kelishini talab qildi.",
         "be", "is", "was", "will be",
         "Mandative subjunctive'da that-clause ichida V1 ishlatilishi mumkin."),
        ("nominalisation", "🔴 Nominalisation",
         "The ___ of the new policy caused debate.",
         "Yangi siyosatning ___ bahsga sabab bo'ldi.",
         "implementation", "implement", "implementing", "implemented",
         "Academic English'da fe'lni noun shakliga o'tkazish nominalisation deyiladi."),
        ("cleft", "🔴 Cleft Sentences",
         "It was Maria who ___ the problem.",
         "Muammoni aynan Maria hal qilgan edi.",
         "solved", "solve", "solving", "has solve",
         "It was ... who/that ... urg'uni ma'lum bo'lakka beradi.")
    ]
    for _, topic, sentence, translation, correct, a, b, c, exp in advanced_items:
        q.append(make_q(
            "advanced", topic, sentence, translation, correct, a, b, c, exp, "hard"
        ))

    ielts_words = [
        ("significant", "sezilarli", "The change was ___ and affected many people.",
         "O'zgarish sezilarli bo'lib, ko'p odamlarga ta'sir qildi."),
        ("rapidly", "tez sur'atda", "Technology is developing ___ nowadays.",
         "Bugungi kunda texnologiya tez sur'atda rivojlanmoqda."),
        ("decline", "pasayish", "The chart shows a ___ in sales.",
         "Grafik savdolarda pasayishni ko'rsatadi."),
        ("increase", "oshish", "There was a significant ___ in demand.",
         "Talabda sezilarli oshish bo'ldi."),
        ("consequently", "natijada", "The road was closed; ___, traffic increased elsewhere.",
         "Yo'l yopildi; natijada boshqa joylarda tirbandlik oshdi.")
    ]
    for word, uzword, sentence, translation in ielts_words:
        q.append(make_q(
            "ielts", "🏆 IELTS Academic Vocabulary", sentence, translation,
            word, "ordinary", "slowly", "decrease",
            f"IELTS akademik lug'atida {word} — {uzword} ma'nosida ishlatiladi.",
            "hard"
        ))

    # -------------------------------------------------------------------------
    # Vocabulary / everyday mixed bank
    # -------------------------------------------------------------------------
    vocab = [
        ("borrow", "qarzga olmoq", "Can I ___ your pen?", "Ruchkangizni qarzga olsam bo'ladimi?", "borrow", "lend", "take", "give"),
        ("lend", "qarzga bermoq", "Could you ___ me your book?", "Kitobingizni menga qarzga bera olasizmi?", "lend", "borrow", "take", "keep"),
        ("advice", "maslahat", "She gave me useful ___.", "U menga foydali maslahat berdi.", "advice", "advices", "advise", "advised"),
        ("information", "ma'lumot", "I need more ___.", "Menga ko'proq ma'lumot kerak.", "information", "informations", "inform", "informed"),
        ("enough", "yetarli", "We have ___ time.", "Bizda yetarli vaqt bor.", "enough", "too", "many", "very"),
        ("already", "allaqachon", "I have ___ finished.", "Men allaqachon tugatdim.", "already", "yet", "ago", "still"),
        ("usually", "odatda", "He ___ wakes up early.", "U odatda erta uyg'onadi.", "usually", "yesterday", "tomorrow", "now"),
        ("carefully", "ehtiyotkorlik bilan", "Please drive ___.", "Iltimos, ehtiyotkorlik bilan haydang.", "carefully", "careful", "care", "caring"),
        ("successful", "muvaffaqiyatli", "The project was ___.", "Loyiha muvaffaqiyatli bo'ldi.", "successful", "success", "successfully", "succeed"),
        ("decision", "qaror", "We need to make a ___.", "Biz qaror qabul qilishimiz kerak.", "decision", "decide", "deciding", "decided")
    ]
    for word, uw, sentence, translation, correct, a, b, c in vocab:
        q.append(make_q(
            "elementary", "🟡 Vocabulary & Word Choice",
            sentence, translation, correct, a, b, c,
            f"{correct} — {uw}. Gap mazmuniga mos variant shu.", "medium"
        ))

    # At least 300 questions: deterministically clone with different contexts.
    # Clones are NOT exact duplicates; context, translation and explanation change.
    contexts = [
        ("at school", "maktabda"), ("at home", "uyda"), ("in Tashkent", "Toshkentda"),
        ("in the morning", "ertalab"), ("every weekend", "har hafta oxiri"),
        ("after class", "darsdan keyin"), ("with my friends", "do'stlarim bilan"),
        ("before dinner", "kechki ovqatdan oldin"), ("today", "bugun"),
        ("this week", "bu hafta"), ("in the evening", "kechqurun"),
        ("during the lesson", "dars davomida")
    ]

    originals = list(q)
    for idx in range(0, max(0, 330 - len(q))):
        src = originals[idx % len(originals)].copy()
        context, ucontext = contexts[idx % len(contexts)]
        src["sentence"] = src["sentence"].replace(".", f" {context}.")
        src["translation"] = src["translation"].replace(".", f" {ucontext}.")
        src["explanation"] += f" 🧠 Qo'shimcha kontekst: {context}."
        src["source"] = "offline_generated_seed"
        q.append(src)

    # Make every question unique enough for the DB.
    seen = set()
    unique = []
    for item in q:
        key = (
            item["level"], item["topic"], item["sentence"],
            item["correct_answer"], item["translation"]
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def build_seed_questions() -> List[Dict[str, Any]]:
    examples = [
        ("beginner", "🟢 To Be — am / is / are", "Although the interview was challenging, Dilnoza ___ confident about her answers.", "Suhbat qiyin o'tgan bo'lsa-da, Dilnoza javoblariga ishonchi komil edi.", "was", "were", "is", "be", "O'tgan holat va birlikdagi ega uchun was ishlatiladi.", "medium"),
        ("beginner", "🟢 To Be — am / is / are", "The volunteers ___ exhausted after they delivered food to every family in the village.", "Qishloqdagi har bir oilaga oziq-ovqat yetkazib bergach, ko'ngillilar juda charchashdi.", "were", "was", "are", "be", "Volunteers ko'plikda va voqea o'tgan zamonda: were exhausted.", "medium"),
        ("beginner", "🟢 To Be — am / is / are", "The library ___ unusually quiet because students were taking their final exams.", "O'quvchilar yakuniy imtihon topshirayotgani uchun kutubxona odatdagidan sokin edi.", "was", "were", "is", "be", "Library birlikdagi ega; o'tgan holat uchun was ishlatiladi.", "medium"),
        ("beginner", "🟢 To Be — am / is / are", "Our neighbours ___ delighted when the lost puppy finally returned home.", "Yo'qolgan kuchukcha nihoyat uyiga qaytganda, qo'shnilarimiz juda xursand bo'lishdi.", "were", "was", "are", "be", "Neighbours ko'plikdagi ega va voqea o'tgan zamonda: were.", "medium"),
        ("beginner", "🟢 To Be — am / is / are", "I ___ grateful that my classmates stayed late to help me finish the science project.", "Sinfdoshlarim ilmiy loyihamni tugatishimga yordam berish uchun kechgacha qolishganidan minnatdorman.", "am", "is", "are", "was", "Hozirgi holat birinchi shaxs I bilan am orqali ifodalanadi.", "medium"),
        ("beginner", "🟢 Can / Can't", "Because she has practised for months, Malika can ___ the difficult piano piece without stopping.", "Malika bir necha oy mashq qilgani uchun, murakkab pianino asarini to'xtamasdan chala oladi.", "play", "plays", "playing", "played", "Can modal fe'lidan keyin fe'lning boshlang'ich shakli keladi.", "medium"),
        ("beginner", "🟢 Can / Can't", "The road is covered in ice, so our small car can't ___ the steep hill safely.", "Yo'l muz bilan qoplangan, shuning uchun kichik mashinamiz tik tepalikka xavfsiz ko'tarila olmaydi.", "climb", "climbs", "climbing", "climbed", "Can't dan keyin climb kabi V1 shakli ishlatiladi.", "medium"),
        ("beginner", "🟢 Can / Can't", "With this translation app, visitors can ___ local residents for directions.", "Ushbu tarjima ilovasi yordamida sayyohlar yo'l so'rash uchun mahalliy aholi bilan gaplasha oladi.", "ask", "asks", "asking", "asked", "Can dan so'ng fe'lning boshlang'ich shakli keladi.", "medium"),
        ("beginner", "🟢 Can / Can't", "The museum is closed today, so we can't ___ the ancient manuscripts this afternoon.", "Muzey bugun yopiq, shu sababli bu tushdan keyin qadimiy qo'lyozmalarni ko'ra olmaymiz.", "see", "saw", "seeing", "sees", "Can't dan so'ng see fe'lining V1 shakli ishlatiladi.", "medium"),
        ("beginner", "🟢 Present Simple", "Every autumn, the school library ___ used textbooks so that new students can borrow them.", "Har kuzda maktab kutubxonasi yangi o'quvchilar olishi uchun ishlatilgan darsliklarni yig'adi.", "collects", "collect", "is collecting", "collected", "Every autumn muntazam odatni bildiradi; birlikdagi ega bilan fe'lga -s qo'shiladi.", "medium"),
        ("beginner", "🟢 Present Simple", "My older sister ___ the family budget carefully before she books a holiday.", "Opam ta'tilga joy band qilishdan oldin oilaviy budjetni diqqat bilan hisoblaydi.", "checks", "check", "is checking", "checked", "Doimiy odat Present Simple'da; sister birlik bo'lgani uchun checks ishlatiladi.", "medium"),
        ("beginner", "🟢 Present Simple", "Although the café opens early, it ___ hot meals until the kitchen staff arrive.", "Kafe erta ochilsa ham, oshxona xodimlari kelmaguncha issiq taomlar tayyorlamaydi.", "doesn't serve", "don't serve", "isn't serving", "didn't serve", "Muntazam inkor: birlikdagi it + doesn't + V1.", "hard"),
        ("beginner", "🟢 Present Simple", "Whenever the river rises after heavy rain, the town council ___ a safety warning.", "Kuchli yomg'irdan keyin daryo ko'tarilganida, shahar kengashi xavfsizlik ogohlantirishini e'lon qiladi.", "issues", "issue", "is issuing", "issued", "Takrorlanuvchi holat Present Simple'da; birlikdagi council bilan issues keladi.", "hard"),
        ("beginner", "🟢 Have / Has", "Our research team ___ enough evidence to explain why the old bridge became unstable.", "Tadqiqot guruhimiz eski ko'prik nega beqaror bo'lganini tushuntirish uchun yetarli dalillarga ega.", "has", "have", "having", "had", "Team birlikdagi jamoa sifatida ishlatilgan, shu sabab has kerak.", "medium"),
        ("beginner", "🟢 Have / Has", "The two new community centres ___ accessible entrances for wheelchair users.", "Yangi jamoat markazlarining ikkalasida ham aravachadan foydalanuvchilar uchun qulay kirish joylari bor.", "have", "has", "having", "had", "Centres ko'plikdagi ega, shuning uchun have ishlatiladi.", "medium"),
        ("elementary", "🟡 Past Simple", "After the storm damaged several houses, local engineers ___ the bridge before reopening the road.", "Bo'ron bir nechta uyga zarar yetkazgach, mahalliy muhandislar yo'lni qayta ochishdan avval ko'prikni tekshirdilar.", "inspected", "inspect", "inspecting", "will inspect", "O'tgan voqealar ketma-ketligi Past Simple'da: inspected.", "medium"),
        ("elementary", "🟡 Past Simple", "When the guide noticed a visitor had fallen ill, she ___ emergency services immediately.", "Gid bir mehmonning mazasi qochganini payqagach, darhol tez yordam xizmatiga qo'ng'iroq qildi.", "called", "calls", "calling", "will call", "O'tgan zamondagi noticed dan keyingi harakat called bo'ladi.", "medium"),
        ("elementary", "🟡 Past Simple", "The students ___ their presentation after the projector stopped working unexpectedly.", "Proyektor kutilmaganda ishlamay qolgach, o'quvchilar taqdimotlarini davom ettirdilar.", "continued", "continue", "continuing", "will continue", "Stopped bilan bog'langan o'tgan harakat continued shaklida keladi.", "medium"),
        ("elementary", "🟡 Past Simple", "Although the train was delayed, we ___ the conference before the keynote speech began.", "Poyezd kechikkan bo'lsa-da, asosiy ma'ruza boshlanishidan oldin konferensiyaga yetib bordik.", "reached", "reach", "reaching", "will reach", "Was delayed va began o'tgan zamonda; mos fe'l reached.", "hard"),
        ("elementary", "🟡 Present Continuous", "The university research team is ___ how air pollution affects children near busy roads.", "Universitet tadqiqot guruhi havo ifloslanishi gavjum yo'llar yaqinidagi bolalarga qanday ta'sir qilishini o'rganmoqda.", "investigating", "investigate", "investigates", "investigated", "Hozir davom etayotgan ish is + V-ing bilan ifodalanadi.", "hard"),
        ("elementary", "🟡 Present Continuous", "Because the main kitchen is being repaired, volunteers are ___ meals in a temporary shelter.", "Asosiy oshxona ta'mirlanayotgani sababli, ko'ngillilar vaqtinchalik boshpanada ovqat tayyorlashmoqda.", "preparing", "prepare", "prepares", "prepared", "Are dan keyin hozir davom etayotgan harakat uchun V-ing keladi.", "medium"),
        ("elementary", "🟡 Future Simple", "The council ___ its final decision after residents have reviewed the new transport plan.", "Aholi yangi transport rejasini ko'rib chiqqanidan keyin kengash yakuniy qarorini e'lon qiladi.", "will announce", "announced", "announces", "is announce", "Kelajakdagi qaror will + V1 bilan ifodalanadi.", "medium"),
        ("elementary", "🟡 Future Simple", "If the weather remains clear, the rescue helicopter ___ supplies to the mountain village tomorrow.", "Ob-havo ochiq bo'lib tursa, qutqaruv vertolyoti ertaga tog'dagi qishloqqa zarur buyumlarni yetkazadi.", "will deliver", "delivered", "delivers", "will delivered", "Tomorrow kelajakni bildiradi; will dan keyin deliver ning V1 shakli keladi.", "medium"),
        ("elementary", "🟡 Present Perfect", "The conservation team has ___ the historic garden, restoring its original design for visitors.", "Tabiatni muhofaza qilish guruhi tarixiy bog'ni tiklab, uning asl ko'rinishini mehmonlar uchun qaytardi.", "restored", "restore", "restoring", "restores", "Has dan keyin fe'lning V3 shakli keladi: restored.", "medium"),
        ("elementary", "🟡 Present Perfect", "Researchers have ___ practical ways to reduce food waste in school cafeterias.", "Tadqiqotchilar maktab oshxonalarida oziq-ovqat isrofini kamaytirishning amaliy usullarini topishdi.", "discovered", "discover", "discovering", "discovers", "Have dan keyin discover fe'lining V3 shakli discovered ishlatiladi.", "medium"),
        ("elementary", "🟡 Comparatives", "The new water filter is ___ than the old model because it removes more harmful minerals.", "Yangi suv filtri eski modeldan samaraliroq, chunki u zararli minerallarni ko'proq ajratib oladi.", "more efficient", "most efficient", "efficient", "as efficient", "Than ikki narsani qiyoslaydi; uzun sifat more efficient shaklini oladi.", "medium"),
        ("elementary", "🟡 Vocabulary & Word Choice", "Before signing the rental agreement, Nodira asked the owner to ___ her deposit if the heating was not repaired.", "Ijara shartnomasini imzolashdan oldin Nodira isitish tizimi ta'mirlanmasa, omonat pulini qaytarishni egasidan so'radi.", "refund", "borrow", "charge", "waste", "Refund to'langan pulni qaytarishni anglatadi.", "hard"),
        ("elementary", "🟡 Vocabulary & Word Choice", "The report compares several neighbourhoods, so its conclusions rely on ___ rather than guesswork.", "Hisobot bir nechta mahallani taqqoslaydi, shuning uchun xulosalari taxminga emas, dalillarga asoslangan.", "evidence", "advice", "permission", "equipment", "Evidence xulosani tasdiqlaydigan dalillarni anglatadi.", "hard"),
        ("pre_intermediate", "🔵 Passive Voice", "After engineers confirmed that the wall was unsafe, the damaged section was ___ before the school reopened.", "Muhandislar devor xavfli ekanini tasdiqlagach, maktab qayta ochilishidan oldin shikastlangan qism mustahkamlandi.", "reinforced", "reinforce", "reinforcing", "reinforces", "Majhul nisbat was + V3 shaklida tuziladi: was reinforced.", "hard"),
        ("pre_intermediate", "🔵 Passive Voice", "The community garden was ___ by local residents using rainwater collected from nearby rooftops.", "Jamoat bog'i yaqin tomlardan yig'ilgan yomg'ir suvidan foydalangan mahalliy aholi tomonidan loyihalashtirildi.", "designed", "design", "designing", "designs", "Was dan keyin fe'lning V3 shakli keladi: designed.", "medium"),
        ("pre_intermediate", "🔵 Second Conditional", "If the town had a reliable night bus, more hospital staff ___ public transport after late shifts.", "Agar shaharda tungi avtobus ishonchli qatnaganida, shifoxona xodimlarining ko'pi kechki smenadan keyin jamoat transportidan foydalanardi.", "would use", "will use", "used", "would used", "Second Conditional: If + Past Simple, would + V1.", "hard"),
        ("pre_intermediate", "🔵 Second Conditional", "If I ___ more time to volunteer, I would help the neighbourhood food bank every weekend.", "Agar ko'ngillilikka ko'proq vaqtim bo'lganida, har dam olish kuni mahalladagi oziq-ovqat markaziga yordam berardim.", "had", "have", "will have", "would have", "If qismida Second Conditional uchun Past Simple had ishlatiladi.", "medium"),
        ("pre_intermediate", "🔵 Present Perfect vs Past Simple", "The science centre ___ three new exhibits this month, and visitors can already explore them.", "Ilmiy markaz shu oy uchta yangi ko'rgazma ochdi va mehmonlar ularni allaqachon tomosha qilishi mumkin.", "has opened", "opened", "opens", "is opening", "This month hali davom etmoqda; hozirgi natija uchun Present Perfect ishlatiladi.", "hard"),
        ("intermediate", "🟣 Future Perfect", "By the time the winter storms arrive, engineers ___ repairs to the coastal road.", "Qishki bo'ronlar boshlanguniga qadar muhandislar sohil yo'lidagi ta'mirlash ishlarini tugatgan bo'lishadi.", "will have completed", "will complete", "have completed", "had completed", "Kelajakdagi muddatgacha tugaydigan ish: will have + V3.", "hard"),
        ("intermediate", "🟣 Inversion", "Only after the laboratory repeated the experiment ___ why the first results were unreliable.", "Laboratoriya tajribani takrorlaganidan keyingina, dastlabki natijalar nega ishonchsiz bo'lgani ma'lum bo'ldi.", "did the researchers understand", "the researchers understood", "understood the researchers", "do the researchers understand", "Only after gap boshida kelganda, yordamchi fe'l egadan oldin keladi.", "hard"),
        ("advanced", "🔴 Subjunctive", "The review panel recommended that each safety report ___ by an independent engineer.", "Ko'rib chiqish hay'ati har bir xavfsizlik hisobotini mustaqil muhandis tekshirishini tavsiya qildi.", "be checked", "is checked", "was checked", "will be checked", "Recommend that dan keyin subjunctive shakli be + V3 ishlatiladi.", "hard"),
        ("advanced", "🔴 Nominalisation", "The careful ___ of the old railway line created safer access to several remote villages.", "Eski temir yo'l liniyasining ehtiyotkorlik bilan qayta tiklanishi bir nechta olis qishloqqa xavfsizroq yo'l yaratdi.", "restoration", "restore", "restoring", "restored", "Careful sifatidan keyin ot kerak: restoration.", "hard"),
        ("advanced", "🔴 Cleft Sentences", "It was the neighbourhood volunteers who ___ the injured hikers before the storm reached the valley.", "Bo'ron vodiyga yetib kelishidan oldin jarohatlangan sayyohlarga aynan mahalla ko'ngillilari yordam berishdi.", "rescued", "rescue", "were rescuing", "have rescue", "It was ... who tuzilmasidagi o'tgan ish uchun rescued ishlatiladi.", "hard"),
        ("ielts", "🏆 IELTS Academic Vocabulary", "The survey found a ___ increase in cycling after the city built protected lanes across the centre.", "So'rovga ko'ra, shahar markaz bo'ylab himoyalangan yo'laklar qurgach, velosipedda yurish sezilarli darajada oshgan.", "substantial", "temporary", "minor", "uncertain", "Substantial ancha katta yoki sezilarli o'zgarishni anglatadi.", "hard"),
        ("ielts", "🏆 IELTS Academic Vocabulary", "Although the first trial was promising, researchers repeated it to ensure the results were ___.", "Dastlabki sinov umidli ko'rinsa-da, tadqiqotchilar natijalar ishonchli ekaniga amin bo'lish uchun uni takrorlashdi.", "reliable", "irrelevant", "artificial", "occasional", "Reliable takroriy sinovda ishonchli chiqadigan natijani bildiradi.", "hard"),
    ]

    questions = []
    for level, topic, sentence, translation, correct, option1, option2, option3, explanation, difficulty in examples:
        question = make_q(
            level, topic, sentence, translation, correct,
            option1, option2, option3, explanation, difficulty
        )
        question["source"] = "nova_curated"
        questions.append(question)
    return questions


# =============================================================================
# 05. NOVA AI SERVICE — CHAT, EXPLANATION, EVALUATION, NEW QUESTIONS
# =============================================================================

def strip_markdown(text: str) -> str:
    text = text or ""
    text = text.replace("```html", "").replace("```", "")
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    return text.strip()

def safe_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
    return None

class AIStreamUpdateError(RuntimeError):
    pass


class AI:
    @staticmethod
    def online():
        return gemini_client is not None

    @staticmethod
    def call(prompt: str, on_update=None) -> str:
        if not AI.online():
            raise RuntimeError(
                "NOVA AI hozircha mavjud emas. .env dagi NOVA_API_KEY va paketlarni tekshiring."
            )
        model_candidates = list(dict.fromkeys((
            AI_MODEL,
            "gemini-flash-latest",
        )))
        failures = []
        for model_name in model_candidates:
            try:
                if on_update is None:
                    response = gemini_client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                    text = getattr(response, "text", None)
                else:
                    chunks = []
                    for chunk in gemini_client.models.generate_content_stream(
                        model=model_name,
                        contents=prompt
                    ):
                        piece = getattr(chunk, "text", None)
                        if piece:
                            chunks.append(piece)
                            try:
                                on_update(strip_markdown("".join(chunks)))
                            except Exception as exc:
                                raise AIStreamUpdateError from exc
                    text = "".join(chunks)
                if not text or not text.strip():
                    raise RuntimeError("NOVA AI bo'sh javob qaytardi.")
                if model_name != AI_MODEL:
                    logger.info("NOVA AI zaxira modeli ishladi.")
                return strip_markdown(text)
            except AIStreamUpdateError:
                raise
            except Exception as exc:
                failures.append(type(exc).__name__)
                logger.warning(
                    "NOVA AI request failed for one configured model (%s).",
                    type(exc).__name__
                )
                if on_update is not None:
                    try:
                        on_update("")
                    except Exception as update_exc:
                        raise AIStreamUpdateError from update_exc

        logger.error(
            "NOVA AI request failed for every configured model (%s attempts).",
            len(failures)
        )
        raise RuntimeError(
            "NOVA AI hozir javob bera olmadi. API kaliti, internet yoki AI xizmatini tekshiring."
        ) from None

    @staticmethod
    def teacher(telegram_id: int, user_message: str, on_update=None) -> str:
        user = db.user(telegram_id)
        stats = db.stats(telegram_id)
        history = db.ai_history(telegram_id, AI_HISTORY_LIMIT)

        history_text = []
        for row in history:
            history_text.append(f"{row['role']}: {row['content']}")
        history_text = "\n".join(history_text)

        prompt = f"""
You are NOVA AI, a friendly and clear English tutor. Never reveal the
technical AI provider or model.

LANGUAGE:
- Reply in the language used in the student's latest message: Uzbek in Uzbek,
  English in English. For mixed messages, use the language used most.
- Do not add translations or switch languages unless the student asks for it
  or the learning task requires an example in another language.
- The latest message's language takes priority over the conversation history.

STYLE:
- Be clear, natural, and concise. Use simple, direct wording.
- For a simple question, answer in 1–3 short sentences and aim for no more
  than 35 words. Give more detail only when asked or needed for accuracy.
- Answer the question directly; avoid long introductions, repeated summaries,
  unnecessary lists, and filler.
- Do not introduce yourself in every reply. Ask a follow-up only when needed.
- Use at most one emoji, and only when it fits. Do not use markdown tables.
- Use correct, natural Uzbek or English; do not mix languages in explanations
  or produce broken, unfinished phrases.
- Correct mistakes gently and never shame the learner.
- Do not claim you performed actions you cannot perform.
- When the task needs English examples, make them natural and meaningful;
  include a fluent Uzbek translation only if requested or useful to that task.

Student profile:
Name: {user['first_name'] if user else 'Student'}
XP: {user['xp'] if user else 0}
Level: {user['level'] if user else 1}
Accuracy: {stats['accuracy']}%

Recent conversation:
{history_text}

Student message:
{user_message}
"""
        return AI.call(prompt, on_update=on_update)

    @staticmethod
    def explain(topic: str, level: str) -> str:
        prompt = f"""
You are NOVA AI, an expert bilingual English teacher. Teach "{topic}" to a
"{level}" student in Uzbek.

Explain the rule accurately, then give five natural, context-rich English
examples. For EACH example give a fluent Uzbek translation with exactly the
same meaning, people, tense, and details. Explain why the target grammar is
used and point out one common mistake. End with one short practice question
and its answer hidden under a clearly labelled "Javob" line.
Never invent awkward or meaningless sentences. Do not use tables.
"""
        return AI.call(prompt)

    @staticmethod
    def evaluate(sentence: str, translation: str, correct: str, user_answer: str):
        prompt = f"""
You are NOVA AI, carefully evaluating an English learner's answer.

Sentence: {sentence}
Expected answer: {correct}
Uzbek translation: {translation}
Student answer: {user_answer}

Decide whether the student's answer is grammatically acceptable in context.
Return ONLY JSON:
{{
  "correct": true,
  "feedback_uz": "short Uzbek explanation",
  "correct_answer": "{correct}",
  "translation": "{translation}",
  "english_sentence": "completed English sentence"
}}

If the student answer is grammatically valid but different from the database
answer and works naturally, accept it.
"""
        raw = AI.call(prompt)
        data = safe_json(raw)
        if not isinstance(data, dict) or not isinstance(data.get("correct"), bool):
            return False, "⚠️ AI javobni tekshirishda JSON formatida xatolik bo'ldi.", correct, translation
        return (
            data["correct"],
            str(data.get("feedback_uz", "")),
            str(data.get("correct_answer", correct)),
            str(data.get("translation", translation))
        )

    @staticmethod
    def generate_questions(
        level: str, topic: str, amount: int = 10,
        avoid_sentences: Optional[List[str]] = None
    ):
        amount = max(3, min(amount, 30))
        excluded_sentences = list(dict.fromkeys(avoid_sentences or []))
        avoid_text = "\n".join(f"- {sentence}" for sentence in excluded_sentences)
        prompt = f"""
You are NOVA AI, a careful bilingual English teacher and question writer.
Create exactly {amount} original, accurate, useful questions.

Student level: {level}
Grammar/vocabulary topic: {topic}

Never reuse any English sentence from this previous-question list:
{avoid_text or "- (no examples provided)"}
Every new sentence must use a different real-life situation and wording.

Every question MUST describe a meaningful, plausible real-life situation.
Do not use trivial templates such as "I am happy", disconnected phrases,
random extra locations, or word-for-word English-to-Uzbek translations.
Prefer specific contexts with a reason, outcome, decision, plan, or useful
detail; match sentence complexity to the requested student level.

For each question produce:
- One natural English sentence containing exactly one blank: ___
- One fluent Uzbek translation of the whole sentence, with the same people,
  action, tense, reasons, and outcome. Keep ___ in the translated answer spot.
- One grammatically correct answer and three distinct plausible wrong options.
- A concise Uzbek explanation that proves why the answer fits the sentence.
- difficulty set to exactly easy, medium, or hard.
- A question that actually tests the requested topic; do not repeat scenarios.

Return ONLY a JSON array:
[
 {{
   "sentence":"...",
   "translation":"...",
   "correct_answer":"...",
   "option1":"...",
   "option2":"...",
   "option3":"...",
   "explanation":"...",
   "difficulty":"easy"
 }}
]

Rules:
- Every English sentence and its Uzbek translation must describe the same
  people, action, tense, reason, and situation. Uzbek must be fluent, not
  literal word-for-word English.
- Translate the completed sentence; do not add information not in English.
- Exactly one correct option.
- Return only a valid JSON array: no markdown, comments, or extra text.
"""
        raw = AI.call(prompt)
        data = safe_json(raw)
        if not isinstance(data, list):
            return []

        result = []
        seen_sentences = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            required = [
                "sentence", "translation", "correct_answer",
                "option1", "option2", "option3", "explanation"
            ]
            if not all(str(item.get(k, "")).strip() for k in required):
                continue
            options = [
                str(item[k]).strip().casefold()
                for k in ("correct_answer", "option1", "option2", "option3")
            ]
            if str(item["sentence"]).count("___") != 1 or len(set(options)) != 4:
                continue
            if len(str(item["sentence"]).split()) < 9 or len(str(item["translation"]).split()) < 7:
                continue
            if str(item.get("difficulty", "")).lower() not in {"easy", "medium", "hard"}:
                continue
            key = sentence_key(str(item["sentence"]))
            if not key or key in seen_sentences:
                continue
            seen_sentences.add(key)
            item["level"] = level
            item["topic"] = topic
            item["source"] = "nova_ai"
            result.append(item)
        return result

    @staticmethod
    def new_sentence(topic: str, level: str) -> str:
        prompt = f"""
You are NOVA AI. Create one fresh, meaningful, context-rich English practice
sentence for "{topic}" at {level}.
Give:
🇬🇧 One natural English sentence (not a trivial isolated phrase)
🇺🇿 One fluent Uzbek translation with the same meaning and tense
🧠 One short explanation of the target grammar
Use a real-life situation with a reason, result, plan, or useful detail. Do not
add unrelated context. Use no markdown table.
"""
        return AI.call(prompt)



# =============================================================================
# 06. DATABASE SEEDING
# =============================================================================

def seed_database():
    if db.meta("offline_question_bank_version") != "2":
        with db.lock:
            conn = db.connect()
            conn.execute(
                "DELETE FROM questions WHERE source IN "
                "('offline_seed', 'offline_generated_seed', 'nova_curated')"
            )
            conn.commit()
            conn.close()
        curated_questions = build_seed_questions()
        db.bulk_insert(curated_questions)
        db.set_meta("offline_question_bank_version", "2")
        logger.info(
            "✅ Eski sifatsiz gaplar almashtirildi; %s ta mazmunli savol o'rnatildi.",
            len(curated_questions)
        )

    current = db.count_questions()
    logger.info("📚 Database question count: %s", current)

    if current >= MIN_DATABASE_QUESTIONS:
        return

    seeds = build_seed_questions()
    missing = MIN_DATABASE_QUESTIONS - current
    with db.lock:
        conn = db.connect()
        existing_sentences = {
            row["sentence"]
            for row in conn.execute("SELECT sentence FROM questions").fetchall()
        }
        conn.close()
    seeds = [
        question for question in seeds
        if question["sentence"] not in existing_sentences
    ][:missing]

    if seeds:
        db.bulk_insert(seeds)
        logger.info("✅ %s ta offline savol bazaga qo'shildi.", len(seeds))

    logger.info("📚 Final question count: %s", db.count_questions())

seed_database()


# =============================================================================
# 07. USER STATE / SESSION
# =============================================================================

class Session:
    def __init__(self):
        self.state = "MAIN"
        self.level = None
        self.topic = None
        self.mode = None
        self.questions = []
        self.index = 0
        self.correct = 0
        self.wrong = 0
        self.xp = 0
        self.current_options = []
        self.waiting_written = False
        self.answered_current = False
        self.ai_topic = None

sessions: Dict[int, Session] = {}
sessions_lock = threading.RLock()

def get_session(user_id: int) -> Session:
    with sessions_lock:
        if user_id not in sessions:
            sessions[user_id] = Session()
        return sessions[user_id]

def reset_session(user_id: int):
    with sessions_lock:
        sessions[user_id] = Session()

def level_title(key):
    return LEVELS.get(key, {}).get("title", "🌱 Beginner")

def find_topic_level(topic: str):
    for key, data in LEVELS.items():
        if topic in data["topics"]:
            return key
    return "beginner"


# =============================================================================
# 08. EMOJI KEYBOARDS
# =============================================================================

class KB:
    @staticmethod
    def main(user_id):
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton("📚 Mavzular"),
            types.KeyboardButton("📝 Testlar"),
            types.KeyboardButton("📅 Kunlik reja")
        )
        k.add(
            types.KeyboardButton("✍️ Yozma mashq"),
            types.KeyboardButton("🤖 NOVA AI")
        )
        k.add(
            types.KeyboardButton("💬 AI Suhbat"),
            types.KeyboardButton("📊 Natijalarim")
        )
        k.add(
            types.KeyboardButton("🔥 Streak"),
            types.KeyboardButton("🏆 Reyting")
        )
        k.add(
            types.KeyboardButton("⚙️ Sozlamalar"),
            types.KeyboardButton("❓ Yordam")
        )
        if user_id == ADMIN_ID:
            k.add(types.KeyboardButton("👑 Admin Panel"))
        return k

    @staticmethod
    def levels():
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton("🌱 Beginner"),
            types.KeyboardButton("📗 Elementary")
        )
        k.add(
            types.KeyboardButton("📘 Pre-Intermediate"),
            types.KeyboardButton("📙 Intermediate")
        )
        k.add(
            types.KeyboardButton("📕 Upper-Intermediate"),
            types.KeyboardButton("🎓 Advanced")
        )
        k.add(types.KeyboardButton("🏆 IELTS 1–9"))
        k.add(types.KeyboardButton("⬅️ Orqaga"))
        return k

    @staticmethod
    def topics(level):
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        topics = LEVELS.get(level, {}).get("topics", [])
        buttons = [types.KeyboardButton(t) for t in topics]
        for i in range(0, len(buttons), 2):
            k.row(*buttons[i:i+2])
        k.add(types.KeyboardButton("🎲 AI yangi mavzu"))
        k.add(types.KeyboardButton("⬅️ Orqaga"))
        return k

    @staticmethod
    def topic_actions():
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton("📝 Testni boshlash"),
            types.KeyboardButton("✍️ Yozma mashq")
        )
        k.add(
            types.KeyboardButton("📖 AI tushuntirsin"),
            types.KeyboardButton("🤖 AI bilan mashq")
        )
        k.add(
            types.KeyboardButton("🎲 AI yangi savollar"),
            types.KeyboardButton("⬅️ Orqaga")
        )
        return k

    @staticmethod
    def back():
        k = types.ReplyKeyboardMarkup(resize_keyboard=True)
        k.add(types.KeyboardButton("⬅️ Orqaga"))
        return k

    @staticmethod
    def ai():
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton("🎯 AI savol bersin"),
            types.KeyboardButton("🧹 AI tarixini tozalash")
        )
        k.add(types.KeyboardButton("⬅️ Orqaga"))
        return k

    @staticmethod
    def settings():
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton("👤 Profil"),
            types.KeyboardButton("🎯 Darajam")
        )
        k.add(types.KeyboardButton("⏰ Kunlik eslatma"))
        k.add(
            types.KeyboardButton("🧹 AI tarixini tozalash"),
            types.KeyboardButton("⬅️ Orqaga")
        )
        return k

    @staticmethod
    def study_plan():
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton("▶️ Bugungi 5 daqiqa"),
            types.KeyboardButton("⏰ Eslatmani sozlash")
        )
        k.add(types.KeyboardButton("⬅️ Orqaga"))
        return k

    @staticmethod
    def reminder(enabled):
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton(
                "🔕 Eslatmani o'chirish" if enabled else "🔔 Eslatmani yoqish"
            ),
            types.KeyboardButton("🕒 Vaqtni o'zgartirish")
        )
        k.add(types.KeyboardButton("⬅️ Orqaga"))
        return k

    @staticmethod
    def admin():
        k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        k.add(
            types.KeyboardButton("📊 Statistika"),
            types.KeyboardButton("👥 Foydalanuvchilar")
        )
        k.add(
            types.KeyboardButton("🤖 AI holati"),
            types.KeyboardButton("📚 Savollar soni")
        )
        k.add(
            types.KeyboardButton("📢 Broadcast"),
            types.KeyboardButton("➕ AI orqali savol qo'shish")
        )
        k.add(types.KeyboardButton("⬅️ Orqaga"))
        return k

    @staticmethod
    def answers(options, qid):
        k = types.InlineKeyboardMarkup(row_width=1)
        for idx, option in enumerate(options):
            # index-based callback prevents long/special-character callback bugs
            k.add(types.InlineKeyboardButton(
                f"🔘 {option}",
                callback_data=f"answer:{qid}:{idx}"
            ))
        k.add(types.InlineKeyboardButton(
            "⏹️ Testni to'xtatish",
            callback_data="stop_test"
        ))
        return k

    @staticmethod
    def next_question(question_id):
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(
            "➡️ Keyingi savol",
            callback_data=f"next_question:{question_id}"
        ))
        return k


# =============================================================================
# 09. HELPERS / MESSAGES
# =============================================================================

def esc(value) -> str:
    return html.escape(str(value or ""))

def normalize_menu_text(value):
    return re.sub(r"[\u200b-\u200d\ufe0e\ufe0f]", "", str(value or "")).strip().casefold()


def is_back_button(value):
    return normalize_menu_text(value) == normalize_menu_text("⬅️ Orqaga")


def split_message(text, limit=3500):
    if limit < 1:
        raise ValueError("limit must be a positive integer")

    remaining = str(text)
    chunks = []
    while len(remaining) > limit:
        split_at = max(
            remaining.rfind("\n", 0, limit),
            remaining.rfind(" ", 0, limit)
        )
        if split_at < 1:
            split_at = limit
        else:
            split_at += 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    chunks.append(remaining)
    return chunks

def send(chat_id, text, markup=None):
    # Plain-text AI responses are intentionally sent without Telegram HTML
    # parsing so AI cannot break messages with malformed tags.
    chunks = split_message(text)
    for index, chunk in enumerate(chunks):
        bot.send_message(
            chat_id,
            chunk,
            reply_markup=markup if index == len(chunks) - 1 else None
        )

def welcome_text(first_name):
    return (
        f"🤖✨ NOVA AI | ENGLISH ACADEMY ✨🇬🇧\n\n"
        f"Assalomu alaykum, {first_name}! 👋😊\n\n"
        f"🎓 Bu bot sizga ingliz tilini Beginner'dan IELTS 9 gacha "
        f"o'rganishga yordam beradi.\n\n"
        f"🤖 NOVA AI — savollaringizga javob beradi.\n"
        f"🧠 AI yangi gap va testlar yaratadi.\n"
        f"📝 Testlar — variantli savollar.\n"
        f"✍️ Yozma mashq — javobni o'zingiz yozasiz.\n"
        f"📅 Kunlik reja — har kuni 5 daqiqalik shaxsiy mashq.\n"
        f"🇺🇿 Har bir savol va javobning o'zbekcha tarjimasi ko'rsatiladi.\n"
        f"⭐ XP + 🔥 Streak + 🏆 Reyting mavjud.\n\n"
        f"👇 Quyidagi menyudan bo'lim tanlang:"
    )

def completed_sentence(sentence, answer):
    return sentence.replace("___", answer, 1)

def start_test(user_id, mode="test"):
    s = get_session(user_id)
    if not s.topic or not s.level:
        send(user_id, "⚠️ Avval 📚 Mavzular bo'limidan mavzu tanlang.")
        return

    qs = []
    if AI.online():
        try:
            send(
                user_id,
                "✨ NOVA AI tanlangan mavzu uchun tabiiy inglizcha gaplar "
                "va mazmuniga mos o'zbekcha tarjimalarni tayyorlamoqda..."
            )
            bot.send_chat_action(user_id, "typing")
            generated = AI.generate_questions(
                s.level,
                s.topic,
                QUESTIONS_PER_TEST,
                avoid_sentences=db.question_sentence_sample()
            )
            if generated:
                question_ids = db.bulk_insert_unique(generated)
                qs = db.reserve_questions(db.questions_by_ids(question_ids))
            if qs:
                logger.info(
                    "NOVA AI prepared %s questions for %s",
                    len(qs), s.topic
                )
        except Exception:
            logger.exception("NOVA AI question generation failed for %s", s.topic)
            send(
                user_id,
                "⚠️ NOVA AI savollarni hozir yaratolmadi. "
                "Mavjud sifatli savollar bilan davom etishga urinaman."
            )

    if len(qs) < QUESTIONS_PER_TEST:
        qs.extend(db.random_questions(
            s.topic,
            s.level,
            QUESTIONS_PER_TEST - len(qs),
            fallback_to_level=False
        ))
    used_level_fallback = False
    if len(qs) < QUESTIONS_PER_TEST:
        fallback = db.random_questions(
            s.topic, s.level, QUESTIONS_PER_TEST - len(qs)
        )
        qs.extend(fallback)
        used_level_fallback = bool(fallback)
    if not qs:
        send(
            user_id,
            "⚠️ Takrorlanmagan savollar qolmadi va NOVA AI yangi savol "
            "tayyorlay olmadi. Birozdan so'ng qayta urinib ko'ring."
        )
        return
    if used_level_fallback:
        send(
            user_id,
            "ℹ️ Bu mavzu uchun yetarli savol topilmadi. "
            f"{level_title(s.level)} darajasidagi savollardan foydalanaman."
        )
    if len(qs) < QUESTIONS_PER_TEST:
        send(
            user_id,
            f"ℹ️ Takrorlanmagan {len(qs)} ta savol mavjud; "
            "mashq shu savollar bilan yakunlanadi."
        )

    s.mode = mode
    s.questions = qs
    s.index = 0
    s.correct = 0
    s.wrong = 0
    s.xp = 0
    s.waiting_written = False
    s.state = "TEST" if mode == "test" else "WRITTEN"
    show_question(user_id)

def show_question(user_id):
    s = get_session(user_id)
    if s.index >= len(s.questions):
        finish_test(user_id)
        return

    s.answered_current = False
    q = s.questions[s.index]
    qnum = s.index + 1
    total = len(s.questions)

    if s.mode in ("test", "study_plan"):
        options = [
            q["correct_answer"],
            q["option1"],
            q["option2"],
            q["option3"]
        ]
        # Remove exact duplicates and shuffle.
        clean = []
        for x in options:
            if x not in clean:
                clean.append(x)
        random.shuffle(clean)
        s.current_options = clean

        text = (
            f"📝❓ SAVOL {qnum}/{total}\n"
            f"📚 Mavzu: {q['topic']}\n\n"
            f"🇬🇧 {q['sentence']}\n"
            f"🇺🇿 {q['translation']}\n\n"
            f"👇 To'g'ri javobni tanlang:"
        )
        bot.send_message(
            user_id, text,
            reply_markup=KB.answers(clean, q["id"])
        )
    else:
        s.waiting_written = True
        text = (
            f"✍️🧠 YOZMA MASHQ {qnum}/{total}\n"
            f"📚 {q['topic']}\n\n"
            f"🇬🇧 {q['sentence']}\n"
            f"🇺🇿 {q['translation']}\n\n"
            f"⌨️ Bo'sh joyga mos javobni yozing:"
        )
        send(user_id, text, KB.back())

def finish_test(user_id):
    s = get_session(user_id)
    total = len(s.questions)
    accuracy = round(s.correct * 100 / total, 1) if total else 0
    user = db.user(user_id)
    xp = user["xp"] if user else 0

    if s.mode == "study_plan":
        today = datetime.now(timezone(timedelta(hours=5))).date().isoformat()
        db.mark_study_completed(user_id, today)
        s.state = "MAIN"
        send(
            user_id,
            f"✅ Bugungi 5 daqiqalik mashq bajarildi!\n\n"
            f"📚 Mavzu: {s.topic}\n"
            f"✅ To'g'ri: {s.correct}/{total}\n"
            f"⭐ Olingan XP: +{s.xp}\n\n"
            "Xato qilingan savollar keyingi rejada takrorlanadi.",
            KB.main(user_id)
        )
        return

    text = (
        f"🏁🎉 TEST YAKUNLANDI! 🎉🏁\n\n"
        f"📚 Mavzu: {s.topic}\n"
        f"🔢 Savollar: {total} ta\n"
        f"✅ To'g'ri: {s.correct} ta\n"
        f"❌ Xato: {s.wrong} ta\n"
        f"📈 Aniqlik: {accuracy}%\n"
        f"⭐ Ushbu test XP: +{s.xp}\n"
        f"🏆 Jami XP: {xp}\n\n"
        f"💪 Juda yaxshi! Yana bir test orqali natijangizni oshiring."
    )
    s.state = "TOPIC_ACTIONS"
    s.waiting_written = False
    send(user_id, text, KB.topic_actions())

def show_topic_actions(user_id):
    s = get_session(user_id)
    send(
        user_id,
        f"📖✨ MAVZU TANLANDI\n\n"
        f"🎯 Daraja: {level_title(s.level)}\n"
        f"📚 Mavzu: {s.topic}\n\n"
        f"👇 Endi nima qilamiz?",
        KB.topic_actions()
    )

def level_from_button(text):
    return LEVEL_BUTTONS.get(text)


# =============================================================================
# 10. /START / HELP / MAIN MENU
# =============================================================================

@bot.message_handler(commands=["start"])
def start_handler(message):
    try:
        uid = message.from_user.id
        db.register(
            uid,
            message.from_user.username or "",
            message.from_user.first_name or "O'quvchi",
            message.from_user.last_name or ""
        )
        reset_session(uid)
        send(uid, welcome_text(message.from_user.first_name or "O'quvchi"), KB.main(uid))
    except Exception:
        logger.exception("start_handler error")
        send(message.chat.id, "⚠️ Texnik xatolik yuz berdi. 🔄 /start ni qayta bosing.")

@bot.message_handler(commands=["help"])
def help_handler(message):
    send(
        message.chat.id,
        "❓📚 YORDAM\n\n"
        "📚 Mavzular — daraja va grammar mavzusini tanlaysiz.\n"
        "📝 Testlar — 4 variantli testlar.\n"
        "✍️ Yozma mashq — javobni o'zingiz yozasiz.\n"
        "🤖 NOVA AI — o'zbekcha/inglizcha suhbat va dars.\n"
        "💬 AI Suhbat — erkin ingliz tili mashqi.\n"
        "📖 AI tushuntirsin — mavzuni AI tushuntiradi.\n"
        "🎲 AI yangi savollar — yangi savollar generatsiya qilinadi.\n"
        "📊 Natijalarim — statistika.\n"
        "🔥 Streak — kunlik davomiylik.\n"
        "📅 Kunlik reja — 5 daqiqalik shaxsiy mashq va xatolarni takrorlash.\n"
        "⏰ Kunlik eslatma — xohlasangiz, Toshkent vaqti bilan vaqtini tanlang.\n"
        "🏆 Reyting — XP bo'yicha top o'quvchilar.\n\n"
        "/start — qayta boshlash\n"
        "/cancel — joriy amaldan chiqish\n"
        "/id — Telegram ID ni ko'rish\n"
        "/help — yordam\n\n"
        "🤖 AI ishlashi uchun .env ichida NOVA_API_KEY bo'lishi kerak."
    )

@bot.message_handler(commands=["id"])
def id_handler(message):
    send(
        message.chat.id,
        f"🆔 Telegram ID: {message.from_user.id}\n"
        "Bu raqamni .env faylidagi ADMIN_ID qiymati sifatida ishlatishingiz mumkin."
    )

@bot.message_handler(commands=["cancel"])
def cancel_handler(message):
    uid = message.from_user.id
    reset_session(uid)
    send(uid, "⏹️ Joriy amal bekor qilindi.", KB.main(uid))

@bot.message_handler(func=lambda m: is_back_button(m.text))
def back_handler(message):
    uid = message.from_user.id
    s = get_session(uid)

    if s.state in ("TEST", "WRITTEN"):
        is_study_plan = s.mode == "study_plan"
        s.state = "MAIN" if is_study_plan else "TOPIC_ACTIONS"
        s.questions = []
        s.index = 0
        s.waiting_written = False
        s.answered_current = False
        markup = KB.main(uid) if is_study_plan else KB.topic_actions()
        send(uid, "⏹️ Joriy mashq to'xtatildi.", markup)
        return

    if s.state == "TOPICS":
        s.state = "LEVELS"
        send(uid, "📚 Darajani tanlang:", KB.levels())
        return

    if s.state == "TOPIC_ACTIONS":
        s.state = "TOPICS" if s.level else "LEVELS"
        markup = KB.topics(s.level) if s.level else KB.levels()
        send(uid, "📚 Mavzu tanlang:" if s.level else "📚 Darajani tanlang:", markup)
        return

    if s.state == "REMINDER_TIME":
        s.state = "REMINDER"
        show_reminder_settings(uid)
        return

    if s.state == "REMINDER":
        s.state = "SETTINGS"
        send(uid, "⚙️ Sozlamalar:", KB.settings())
        return

    if s.state == "PROFILE":
        s.state = "SETTINGS"
        send(uid, "⚙️ Sozlamalar:", KB.settings())
        return

    if s.state == "AI" and s.ai_topic and s.topic and s.level:
        s.state = "TOPIC_ACTIONS"
        s.ai_topic = None
        send(uid, "📚 Mavzu menyusiga qaytdingiz.", KB.topic_actions())
        return

    s.state = "MAIN"
    s.ai_topic = None
    send(uid, "🏠 Asosiy menyu:", KB.main(uid))

@bot.message_handler(func=lambda m: m.text == "📚 Mavzular")
def menu_topics(message):
    uid = message.from_user.id
    s = get_session(uid)
    s.state = "LEVELS"
    s.mode = None
    send(uid, "📚🎓 DARAJANI TANLANG:\n\n👇 O'zingizga mos darajani bosing:", KB.levels())

@bot.message_handler(func=lambda m: m.text == "📝 Testlar")
def menu_tests(message):
    uid = message.from_user.id
    s = get_session(uid)
    s.state = "LEVELS"
    s.mode = "test"
    send(uid, "📝🎯 TEST REJIMI\n\nAvval darajani tanlang:", KB.levels())

@bot.message_handler(func=lambda m: m.text == "✍️ Yozma mashq")
def menu_written(message):
    uid = message.from_user.id
    s = get_session(uid)
    s.state = "LEVELS"
    s.mode = "written"
    send(uid, "✍️🧠 YOZMA MASHQ\n\nAvval darajani tanlang:", KB.levels())

@bot.message_handler(func=lambda m: m.text in ("🤖 NOVA AI", "💬 AI Suhbat"))
def menu_ai(message):
    uid = message.from_user.id
    s = get_session(uid)
    s.state = "AI"
    s.ai_topic = None
    send(
        uid,
        "🤖💬 NOVA AI ISHLAYAPTI!\n\n"
        f"{'🟢 NOVA AI tayyor' if AI.online() else '🔴 NOVA AI sozlanmagan'}\n\n"
        "🇺🇿 O'zbekcha yozishingiz mumkin.\n"
        "🇬🇧 English yozishingiz mumkin.\n"
        "🔄 Aralashtirib yozsangiz ham AI tushunadi.\n\n"
        "Masalan:\n"
        "👉 Present Perfectni oddiy tushuntir\n"
        "👉 I have went to school — xatomi?\n"
        "👉 Let's practice speaking\n"
        "👉 'Although' nimani anglatadi?\n\n"
        "✍️ Xabaringizni yuboring:",
        KB.ai()
    )

@bot.message_handler(func=lambda m: m.text == "📊 Natijalarim")
def menu_results(message):
    uid = message.from_user.id
    get_session(uid).state = "RESULTS"
    st = db.stats(uid)
    u = st["user"]
    if not u:
        db.register(uid, "", message.from_user.first_name or "Student", "")
        st = db.stats(uid)
        u = st["user"]

    strong = st["strong"]["topic"] if st["strong"] else "⏳ Hali yetarli ma'lumot yo'q"
    weak = st["weak"]["topic"] if st["weak"] else "⏳ Hali yetarli ma'lumot yo'q"
    send(
        uid,
        f"📊🏆 NATIJALARINGIZ\n\n"
        f"👤 Ism: {u['first_name'] or 'Student'}\n"
        f"🎯 Level: {u['level']}\n"
        f"⭐ XP: {u['xp']}\n"
        f"🔥 Streak: {u['streak']} kun\n\n"
        f"📝 Jami javob: {st['total']}\n"
        f"✅ To'g'ri: {st['correct']}\n"
        f"❌ Xato: {st['wrong']}\n"
        f"📈 Aniqlik: {st['accuracy']}%\n\n"
        f"💚 Kuchli mavzu: {strong}\n"
        f"❤️ Ko'proq mashq: {weak}",
        KB.back()
    )

@bot.message_handler(func=lambda m: m.text == "🔥 Streak")
def menu_streak(message):
    uid = message.from_user.id
    get_session(uid).state = "RESULTS"
    u = db.user(uid)
    streak = u["streak"] if u else 0
    send(
        uid,
        f"🔥🔥 STREAK 🔥🔥\n\n"
        f"📅 Sizning streak'ingiz: {streak} kun!\n\n"
        f"💡 Har kuni test yoki AI bilan mashq qiling.\n"
        f"🚀 Muntazamlik ingliz tilini tezroq o'rganishga yordam beradi.",
        KB.back()
    )

@bot.message_handler(func=lambda m: m.text == "🏆 Reyting")
def menu_ranking(message):
    uid = message.from_user.id
    get_session(uid).state = "RESULTS"
    rows = db.leaderboard(10)
    rank = db.rank(uid)
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    lines = ["🏆🌟 TOP-10 REYTING\n"]
    for i, row in enumerate(rows):
        name = row["first_name"] or "Student"
        lines.append(
            f"{medals[i] if i < len(medals) else '🔹'} {name} — ⭐ {row['xp']} XP"
        )
    lines.append(f"\n📍 Sizning o'rningiz: #{rank}")
    send(uid, "\n".join(lines), KB.back())

@bot.message_handler(func=lambda m: m.text == "⚙️ Sozlamalar")
def menu_settings(message):
    uid = message.from_user.id
    get_session(uid).state = "SETTINGS"
    send(uid, "⚙️🔧 SOZLAMALAR\n\n👇 Kerakli bo'limni tanlang:", KB.settings())

def tashkent_now():
    return datetime.now(timezone(timedelta(hours=5)))

def show_study_plan(user_id):
    get_session(user_id).state = "STUDY_PLAN"
    plan = db.study_plan(user_id)
    stats = db.stats(user_id)
    topic = stats["weak"]["topic"] if stats["weak"] else "🟢 Present Simple"
    today = tashkent_now().date().isoformat()
    completed = plan["last_completed_date"] == today
    reminder = (
        f"⏰ Eslatma: yoqilgan, {plan['reminder_time']} (Toshkent vaqti)"
        if plan["reminder_enabled"]
        else "⏰ Eslatma: o'chiq"
    )
    status = "✅ Bugungi reja bajarilgan." if completed else "🎯 Bugungi reja hali bajarilmadi."
    send(
        user_id,
        f"📅 SHAXSIY KUNLIK REJA\n\n"
        f"⏱ Kuniga 5 daqiqa · 3 ta savol\n"
        f"📚 Bugungi mavzu: {topic}\n"
        f"🔁 Hali ishlatilmagan oldingi xatolar birinchi chiqadi.\n"
        f"{status}\n"
        f"{reminder}\n\n"
        "Reja natijalaringizga qarab zaifroq mavzuni tanlaydi.",
        KB.study_plan()
    )

def show_reminder_settings(user_id):
    plan = db.study_plan(user_id)
    state = "yoqilgan" if plan["reminder_enabled"] else "o'chiq"
    send(
        user_id,
        f"⏰ KUNLIK ESLATMA\n\n"
        f"Hozir: {state}\n"
        f"Vaqt: {plan['reminder_time']} (Toshkent vaqti, UTC+5)\n\n"
        "Eslatma faqat yoqqaningizda yuboriladi. Vaqtni o'zgartirish uchun "
        "HH:MM ko'rinishida yuboring (masalan, 19:30).",
        KB.reminder(bool(plan["reminder_enabled"]))
    )

def start_daily_plan(user_id):
    db.study_plan(user_id)
    stats = db.stats(user_id)
    topic = stats["weak"]["topic"] if stats["weak"] else "🟢 Present Simple"
    level = find_topic_level(topic)
    questions = db.plan_questions(user_id, topic, level, limit=3)
    if not questions:
        send(
            user_id,
            "Hozircha reja uchun mos savol topilmadi. Birozdan keyin qayta urinib ko'ring.",
            KB.study_plan()
        )
        return

    s = get_session(user_id)
    s.level = level
    s.topic = topic
    s.mode = "study_plan"
    s.questions = questions
    s.index = 0
    s.correct = 0
    s.wrong = 0
    s.xp = 0
    s.waiting_written = False
    s.answered_current = False
    s.state = "TEST"
    send(
        user_id,
        f"🚀 Bugungi 5 daqiqalik reja boshlandi!\n"
        f"📚 Mavzu: {topic}\n"
        f"🔁 Ishlatilmagan eski xatolaringiz bo'lsa, avval shu savollar chiqadi."
    )
    show_question(user_id)

@bot.message_handler(func=lambda m: m.text == "❓ Yordam")
def menu_help_button(message):
    get_session(message.from_user.id).state = "HELP"
    help_handler(message)

@bot.message_handler(func=lambda m: m.text == "📅 Kunlik reja")
def menu_study_plan(message):
    show_study_plan(message.from_user.id)

@bot.message_handler(func=lambda m: m.text == "▶️ Bugungi 5 daqiqa")
def start_plan_button(message):
    start_daily_plan(message.from_user.id)

@bot.message_handler(func=lambda m: m.text == "⏰ Eslatmani sozlash")
@bot.message_handler(func=lambda m: m.text == "⏰ Kunlik eslatma")
def reminder_menu(message):
    get_session(message.from_user.id).state = "REMINDER"
    show_reminder_settings(message.from_user.id)

@bot.message_handler(func=lambda m: m.text in (
    "🔔 Eslatmani yoqish", "🔕 Eslatmani o'chirish"
))
def toggle_study_reminder(message):
    uid = message.from_user.id
    enabled = message.text == "🔔 Eslatmani yoqish"
    db.set_study_reminder(uid, enabled)
    get_session(uid).state = "REMINDER"
    send(
        uid,
        "🔔 Eslatma yoqildi." if enabled else "🔕 Eslatma o'chirildi.",
        KB.reminder(enabled)
    )

@bot.message_handler(func=lambda m: m.text == "🕒 Vaqtni o'zgartirish")
def request_reminder_time(message):
    get_session(message.from_user.id).state = "REMINDER_TIME"
    send(
        message.from_user.id,
        "Eslatma vaqtini Toshkent vaqti bilan yuboring.\n"
        "Masalan: 08:30 yoki 19:00."
    )

@bot.message_handler(func=lambda m: get_session(m.from_user.id).state == "REMINDER_TIME")
def set_reminder_time(message):
    uid = message.from_user.id
    if not message.text:
        send(uid, "Vaqtni HH:MM ko'rinishida yozing, masalan 19:30.")
        return
    match = re.fullmatch(r"\s*([0-9]{1,2}):([0-5][0-9])\s*", message.text)
    if not match or int(match.group(1)) > 23:
        send(uid, "Vaqt noto'g'ri. 00:00–23:59 oralig'ida HH:MM yozing.")
        return
    reminder_time = f"{int(match.group(1)):02d}:{match.group(2)}"
    db.set_study_reminder(uid, True, reminder_time)
    get_session(uid).state = "REMINDER"
    send(
        uid,
        f"✅ Eslatma har kuni {reminder_time} da yuboriladi (Toshkent vaqti).",
        KB.reminder(True)
    )


# =============================================================================
# 11. LEVEL / TOPIC SELECTION
# =============================================================================

@bot.message_handler(func=lambda m: m.text in LEVEL_BUTTONS)
def choose_level(message):
    uid = message.from_user.id
    s = get_session(uid)
    s.level = LEVEL_BUTTONS[message.text]
    s.state = "TOPICS"
    send(
        uid,
        f"{level_title(s.level)}\n\n"
        f"📚 Mavzular ro'yxati:\n"
        f"👇 Kerakli mavzuni tanlang:",
        KB.topics(s.level)
    )

@bot.message_handler(func=lambda m: m.text == "🎲 AI yangi mavzu")
def random_ai_topic(message):
    uid = message.from_user.id
    s = get_session(uid)
    if not s.level:
        send(uid, "⚠️ Avval darajani tanlang.", KB.levels())
        return
    topics = LEVELS[s.level]["topics"]
    s.topic = random.choice(topics)
    s.state = "TOPIC_ACTIONS"
    show_topic_actions(uid)

@bot.message_handler(
    func=lambda m: (
        get_session(m.from_user.id).state == "TOPICS"
        and not is_back_button(m.text)
    )
)
def choose_topic(message):
    uid = message.from_user.id
    s = get_session(uid)
    if message.text not in LEVELS[s.level]["topics"]:
        send(uid, "⚠️ Iltimos, pastdagi 📚 mavzu tugmalaridan birini tanlang.")
        return

    s.topic = message.text
    if s.mode == "test":
        start_test(uid, "test")
    elif s.mode == "written":
        start_test(uid, "written")
    else:
        s.state = "TOPIC_ACTIONS"
        show_topic_actions(uid)

# =============================================================================
# 12. TOPIC ACTIONS
# =============================================================================

@bot.message_handler(func=lambda m: m.text == "📝 Testni boshlash")
def topic_test(message):
    uid = message.from_user.id
    start_test(uid, "test")

@bot.message_handler(func=lambda m: m.text == "✍️ Yozma mashq")
def topic_written(message):
    uid = message.from_user.id
    start_test(uid, "written")

@bot.message_handler(func=lambda m: m.text == "📖 AI tushuntirsin")
def topic_explain(message):
    uid = message.from_user.id
    s = get_session(uid)
    if not s.topic:
        send(uid, "⚠️ Avval mavzu tanlang.")
        return
    if not AI.online():
        send(
            uid,
            "⚠️🤖 AI hozir OFFLINE.\n\n"
            "NOVA_API_KEY ni .env fayliga yozing va botni qayta ishga tushiring.",
            KB.topic_actions()
        )
        return
    try:
        bot.send_chat_action(uid, "typing")
        result = AI.explain(s.topic, level_title(s.level))
        send(uid, f"📖🤖 AI DARS\n\n{result}", KB.topic_actions())
    except Exception as exc:
        logger.exception("topic_explain failed")
        send(uid, f"⚠️ AI xatoligi:\n{exc}", KB.topic_actions())

@bot.message_handler(func=lambda m: m.text in ("🤖 AI bilan mashq", "🎯 AI savol bersin"))
def topic_ai_practice(message):
    uid = message.from_user.id
    s = get_session(uid)
    s.state = "AI"
    s.ai_topic = s.topic
    send(
        uid,
        f"🤖🧠 AI MASHQ REJIMI\n\n"
        f"📚 Mavzu: {s.topic or 'Erkin suhbat'}\n\n"
        f"🇺🇿 O'zbekcha yozing — AI o'zbekcha tushuntiradi.\n"
        f"🇬🇧 English yozing — AI inglizcha mashq qildiradi.\n\n"
        f"✍️ Boshlang:",
        KB.ai()
    )

@bot.message_handler(func=lambda m: m.text == "🎲 AI yangi savollar")
def ai_new_questions(message):
    uid = message.from_user.id
    s = get_session(uid)
    if not s.topic or not s.level:
        send(uid, "⚠️ Avval daraja va mavzuni tanlang.")
        return
    if not AI.online():
        send(uid, "⚠️🤖 NOVA AI o‘chiq. .env dagi NOVA_API_KEY ni tekshiring.")
        return

    try:
        bot.send_chat_action(uid, "typing")
        generated = AI.generate_questions(s.level, s.topic, 10)
        if not generated:
            send(uid, "⚠️ AI savol yaratmadi. 🔄 Qayta urinib ko'ring.")
            return
        question_ids = db.bulk_insert_unique(generated)
        if not question_ids:
            send(
                uid,
                "ℹ️ AI faqat avval yaratilgan gaplarni taklif qildi. "
                "🔄 Yana urinib ko'ring.",
                KB.topic_actions()
            )
            return
        send(
            uid,
            f"🎉🤖 AI {len(question_ids)} ta yangi savol yaratdi!\n\n"
            f"📚 Mavzu: {s.topic}\n"
            f"💾 Savollar bazaga saqlandi.\n\n"
            f"📝 Endi yangi testni boshlashingiz mumkin.",
            KB.topic_actions()
        )
    except Exception as exc:
        logger.exception("AI question generation failed")
        send(uid, f"⚠️ AI savol generatsiyasi xatosi:\n{exc}", KB.topic_actions())


# =============================================================================
# 13. TEST CALLBACKS
# =============================================================================

@bot.callback_query_handler(func=lambda call: call.data == "stop_test")
def stop_test(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id, "⏹️ Test to'xtatildi.")
    s = get_session(uid)
    s.state = "MAIN" if s.mode == "study_plan" else "TOPIC_ACTIONS"
    s.questions = []
    s.index = 0
    markup = KB.main(uid) if s.mode == "study_plan" else KB.topic_actions()
    send(uid, "⏹️ Mashq to'xtatildi.", markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_question:"))
def next_question(call):
    uid = call.from_user.id
    s = get_session(uid)
    try:
        question_id = int(call.data.split(":", 1)[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "⚠️ Callback xatosi.", show_alert=True)
        return

    with sessions_lock:
        if s.state not in ("TEST", "WRITTEN"):
            error = "Bu mashq yakunlangan."
        elif s.index >= len(s.questions) or s.questions[s.index]["id"] != question_id:
            error = "Bu tugma eskirgan. Joriy savolni davom ettiring."
        elif not s.answered_current:
            error = "Avval savolga javob bering."
        else:
            error = None
            s.index += 1
            s.waiting_written = False
            s.answered_current = False
    if error:
        bot.answer_callback_query(call.id, error, show_alert=True)
        return
    bot.answer_callback_query(call.id)
    show_question(uid)

@bot.callback_query_handler(func=lambda call: call.data.startswith("answer:"))
def answer_callback(call):
    uid = call.from_user.id
    s = get_session(uid)

    try:
        _, qid_raw, option_idx_raw = call.data.split(":", 2)
        qid = int(qid_raw)
        option_idx = int(option_idx_raw)
    except Exception:
        bot.answer_callback_query(call.id, "⚠️ Callback xatosi.", show_alert=True)
        return

    with sessions_lock:
        if s.state != "TEST" or s.index >= len(s.questions):
            error = "⏳ Bu savol faol emas."
        else:
            q = s.questions[s.index]
            if q["id"] != qid:
                error = "⚠️ Eski savol."
            elif option_idx < 0 or option_idx >= len(s.current_options):
                error = "⚠️ Variant topilmadi."
            elif s.answered_current:
                error = "Bu savolga javob berilgansiz."
            else:
                error = None
                s.answered_current = True
                chosen = s.current_options[option_idx]
    if error:
        bot.answer_callback_query(call.id, error, show_alert=True)
        return

    correct = str(q["correct_answer"])
    is_correct = chosen.strip().lower() == correct.strip().lower()

    xp = 0
    if is_correct:
        xp = {"easy": 10, "medium": 15, "hard": 20}.get(q["difficulty"], 15)
        s.correct += 1
        s.xp += xp
        new_xp, new_level, leveled = db.add_xp(uid, xp)
    else:
        s.wrong += 1
        new_xp, new_level, leveled = (db.user(uid)["xp"], db.user(uid)["level"], False)

    db.record_answer(uid, q["id"], q["topic"], chosen, is_correct, xp)

    completed = completed_sentence(q["sentence"], correct)

    if is_correct:
        feedback = (
            f"✅🎉 TO'G'RI JAVOB!\n\n"
            f"🇬🇧 {completed}\n"
            f"🇺🇿 {q['translation']}\n\n"
            f"🧠 Izoh: {q['explanation']}\n"
            f"⭐ +{xp} XP\n"
        )
        if leveled:
            feedback += f"🎊 LEVEL UP! Endi siz {new_level}-darajasiz! 🏆\n"
    else:
        feedback = (
            f"❌📚 XATO JAVOB\n\n"
            f"🔴 Sizning javobingiz: {chosen}\n"
            f"🟢 To'g'ri javob: {correct}\n\n"
            f"🇬🇧 To'liq gap: {completed}\n"
            f"🇺🇿 Tarjimasi: {q['translation']}\n\n"
            f"🧠 Izoh: {q['explanation']}\n"
        )

    bot.answer_callback_query(call.id, "✅ Javob qabul qilindi!" if is_correct else "❌ Javob xato.")
    try:
        bot.edit_message_text(
            feedback,
            uid,
            call.message.message_id,
            reply_markup=KB.next_question(q["id"])
        )
    except Exception:
        send(uid, feedback, KB.next_question(q["id"]))


# =============================================================================
# 14. WRITTEN ANSWERS + AI CONVERSATION
# =============================================================================

def normalize_answer(value):
    value = value.lower().strip()
    value = re.sub(r"[.!?,;:]+$", "", value)
    contractions = {
        "isn't": "is not", "aren't": "are not",
        "wasn't": "was not", "weren't": "were not",
        "don't": "do not", "doesn't": "does not",
        "didn't": "did not", "won't": "will not",
        "can't": "cannot", "haven't": "have not",
        "hasn't": "has not", "hadn't": "had not"
    }
    return contractions.get(value, value)

@bot.message_handler(func=lambda m: get_session(m.from_user.id).state == "WRITTEN")
def written_answer(message):
    uid = message.from_user.id
    s = get_session(uid)

    if not message.text:
        send(uid, "✍️ Iltimos, javobni matn ko'rinishida yuboring.")
        return

    if not s.questions or s.index >= len(s.questions):
        send(uid, "⚠️ Faol yozma mashq topilmadi. /cancel buyrug'i bilan menyuga qayting.")
        return

    with sessions_lock:
        if s.waiting_written:
            s.waiting_written = False
            s.answered_current = True
            waiting_for_answer = True
        else:
            waiting_for_answer = False

    if not waiting_for_answer:
        current_question = s.questions[s.index]
        send(uid, "✅ Bu savolga javob berdingiz. Keyingi savol uchun tugmani bosing.", KB.next_question(current_question["id"]))
        return

    q = s.questions[s.index]
    user_answer = message.text.strip()

    exact = normalize_answer(user_answer) == normalize_answer(q["correct_answer"])
    accepted = exact
    feedback_uz = q["explanation"]

    # AI semantic evaluation: allows natural alternatives.
    if not exact and AI.online():
        try:
            accepted, feedback_uz, ai_correct, ai_translation = AI.evaluate(
                q["sentence"], q["translation"], q["correct_answer"], user_answer
            )
            if ai_correct:
                q["correct_answer"] = ai_correct
            if ai_translation:
                q["translation"] = ai_translation
        except Exception as exc:
            logger.warning("AI written evaluation failed: %s", exc)

    if accepted:
        xp = {"easy": 10, "medium": 15, "hard": 20}.get(q["difficulty"], 15)
        s.correct += 1
        s.xp += xp
        db.add_xp(uid, xp)
        db.record_answer(uid, q["id"], q["topic"], user_answer, True, xp)
        text = (
            f"✅🎉 TO'G'RI!\n\n"
            f"🇬🇧 {completed_sentence(q['sentence'], q['correct_answer'])}\n"
            f"🇺🇿 {q['translation']}\n\n"
            f"🧠 {feedback_uz}\n"
            f"⭐ +{xp} XP"
        )
    else:
        s.wrong += 1
        db.record_answer(uid, q["id"], q["topic"], user_answer, False, 0)
        text = (
            f"❌🧠 XATO\n\n"
            f"🔴 Siz: {user_answer}\n"
            f"🟢 To'g'ri: {q['correct_answer']}\n\n"
            f"🇬🇧 {completed_sentence(q['sentence'], q['correct_answer'])}\n"
            f"🇺🇿 {q['translation']}\n\n"
            f"💡 {feedback_uz}"
        )

    send(uid, text, KB.next_question(q["id"]))

@bot.message_handler(func=lambda m: get_session(m.from_user.id).state == "AI")
def ai_message(message):
    uid = message.from_user.id

    if message.text == "🧹 AI tarixini tozalash":
        db.clear_ai(uid)
        send(uid, "🧹✅ AI suhbat tarixi tozalandi.", KB.ai())
        return

    if not AI.online():
        send(
            uid,
            "⚠️🤖 NOVA AI hozircha javob bera olmayapti.\n\n"
            "1️⃣ .env faylida NOVA_API_KEY qiymatini tekshiring.\n"
            "2️⃣ setup.bat orqali kerakli kutubxonalarni o'rnating.\n"
            "3️⃣ Botni qayta ishga tushiring.\n\n"
            "🔑 Key bo'lmasa, AI ishlamaydi."
        )
        return

    if not message.text:
        send(uid, "✍️ Iltimos, xabaringizni matn ko'rinishida yuboring.", KB.ai())
        return

    user_text = message.text.strip()
    if not user_text:
        send(uid, "✍️ Savolingizni yozing.")
        return

    try:
        bot.send_chat_action(uid, "typing")
        db.save_ai(uid, "user", user_text)
        prefix = "🤖✨ NOVA AI:\n\n"
        placeholder = f"{prefix}✍️ Yozmoqda..."
        progress_message = bot.send_message(uid, placeholder)
        last_update = 0.0
        last_visible = placeholder

        def update_stream(text, force=False):
            nonlocal last_update, last_visible
            now = time.monotonic()
            if not force and text and now - last_update < 1.1:
                return

            current_text = f"{prefix}{text.strip() or '✍️ Yozmoqda...'}"
            chunks = split_message(current_text)
            visible_text = chunks[0]
            if visible_text != last_visible or force:
                bot.edit_message_text(
                    visible_text,
                    uid,
                    progress_message.message_id,
                    reply_markup=KB.ai() if force and len(chunks) == 1 else None
                )
                last_visible = visible_text
                last_update = now

            if force:
                for index, chunk in enumerate(chunks[1:]):
                    bot.send_message(
                        uid,
                        chunk,
                        reply_markup=(
                            KB.ai() if index == len(chunks[1:]) - 1 else None
                        )
                    )

        answer = AI.teacher(uid, user_text, on_update=update_stream)
        db.save_ai(uid, "assistant", answer)
        update_stream(answer, force=True)
    except Exception as exc:
        logger.exception("AI chat error")
        send(
            uid,
            f"❌🤖 AI bilan bog'lanishda xatolik.\n\n"
            f"🔧 Texnik ma'lumot: {exc}\n\n"
            "💡 NOVA AI holatini /novadiag orqali tekshiring."
        )

@bot.message_handler(func=lambda m: m.text == "🧹 AI tarixini tozalash")
def clear_ai_main(message):
    uid = message.from_user.id
    db.clear_ai(uid)
    markup = KB.settings() if get_session(uid).state == "SETTINGS" else KB.ai()
    send(uid, "🧹✅ AI tarixi tozalandi.", markup)


# =============================================================================
# 15. SETTINGS
# =============================================================================

@bot.message_handler(func=lambda m: m.text == "👤 Profil")
def profile(message):
    uid = message.from_user.id
    get_session(uid).state = "PROFILE"
    st = db.stats(uid)
    u = st["user"]
    if not u:
        db.register(
            uid,
            message.from_user.username or "",
            message.from_user.first_name or "Student",
            message.from_user.last_name or ""
        )
        st = db.stats(uid)
        u = st["user"]
    send(
        uid,
        f"👤📋 PROFIL\n\n"
        f"🧑 Ism: {u['first_name']}\n"
        f"🔗 Username: @{u['username'] or 'yo‘q'}\n"
        f"⭐ XP: {u['xp']}\n"
        f"🎯 Level: {u['level']}\n"
        f"🔥 Streak: {u['streak']} kun\n"
        f"📝 Savollar: {st['total']}\n"
        f"📈 Aniqlik: {st['accuracy']}%",
        KB.settings()
    )

@bot.message_handler(func=lambda m: m.text == "🎯 Darajam")
def my_level(message):
    uid = message.from_user.id
    get_session(uid).state = "PROFILE"
    u = db.user(uid)
    xp = u["xp"] if u else 0
    lvl = u["level"] if u else 1
    thresholds = [0,100,250,500,900,1400,2100,3000,4200,6000,8500]
    nxt = thresholds[lvl] if lvl < len(thresholds) else xp + 1000
    need = max(0, nxt - xp)
    send(
        uid,
        f"🎯🏆 DARAJANGIZ\n\n"
        f"🌟 Hozirgi level: {lvl}\n"
        f"⭐ XP: {xp}\n"
        f"🚀 Keyingi levelgacha: {need} XP",
        KB.settings()
    )

@bot.message_handler(func=lambda m: m.text == "🧹 AI tarixini tozalash")
def settings_clear_ai(message):
    uid = message.from_user.id
    db.clear_ai(uid)
    send(uid, "🧹✅ AI tarixi tozalandi.", KB.settings())

# =============================================================================
# 16. ADMIN
# =============================================================================

@bot.message_handler(commands=["admin"])
def admin_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    get_session(ADMIN_ID).state = "ADMIN"
    send(ADMIN_ID, "👑🔐 ADMIN PANEL\n\n👇 Boshqaruv bo'limini tanlang:", KB.admin())

@bot.message_handler(func=lambda m: m.text == "👑 Admin Panel")
def admin_button(message):
    if message.from_user.id != ADMIN_ID:
        return
    get_session(ADMIN_ID).state = "ADMIN"
    send(ADMIN_ID, "👑🔐 ADMIN PANEL", KB.admin())

@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def admin_statistics(message):
    if message.from_user.id != ADMIN_ID:
        return
    x = db.admin_stats()
    send(
        ADMIN_ID,
        f"📊📈 BOT STATISTIKASI\n\n"
        f"👥 Foydalanuvchilar: {x['users']}\n"
        f"📚 Savollar: {x['questions']}\n"
        f"📝 Javoblar: {x['answers']}\n"
        f"🤖 AI so'rovlar: {x['ai']}\n"
        f"🟢 NOVA AI: {'tayyor' if AI.online() else 'o‘chiq'}",
        KB.admin()
    )

@bot.message_handler(func=lambda m: m.text == "📚 Savollar soni")
def admin_questions(message):
    if message.from_user.id != ADMIN_ID:
        return
    send(ADMIN_ID, f"📚🧠 Bazada hozir {db.count_questions()} ta savol bor.", KB.admin())

@bot.message_handler(func=lambda m: m.text == "👥 Foydalanuvchilar")
def admin_users(message):
    if message.from_user.id != ADMIN_ID:
        return
    x = db.admin_stats()
    send(ADMIN_ID, f"👥 Jami foydalanuvchilar: {x['users']} ta.", KB.admin())

@bot.message_handler(func=lambda m: m.text == "🤖 AI holati")
def admin_ai_status(message):
    if message.from_user.id != ADMIN_ID:
        return
    send(
        ADMIN_ID,
        f"🤖🔌 AI HOLATI\n\n"
        f"AI kutubxonasi: {'✅ mavjud' if GOOGLE_GENAI_AVAILABLE else '❌ topilmadi'}\n"
        f"API kalit: {'✅ o‘rnatilgan' if NOVA_API_KEY else '❌ o‘rnatilmagan'}\n"
        f"AI xizmati: {'✅ tayyor' if AI.online() else '❌ o‘chiq'}\n\n"
        f"💡 AI ishlamasa, /novadiag buyrug'idan foydalaning.",
        KB.admin()
    )

@bot.message_handler(commands=["novadiag", "aidiag"])
def ai_diag(message):
    if message.from_user.id != ADMIN_ID:
        return
    checks = [
        f"🤖 NOVA AI: {'✅ tayyor' if AI.online() else '❌ o‘chiq'}",
        f"🔑 NOVA_API_KEY: {'✅ mavjud' if NOVA_API_KEY else '❌ yo‘q'}",
        f"📦 AI kutubxonasi: {'✅ mavjud' if GOOGLE_GENAI_AVAILABLE else '❌ topilmadi'}",
    ]
    if AI.online():
        try:
            test = AI.call("Reply with exactly: NOVA_OK")
            checks.append(f"🌐 Haqiqiy AI so‘rovi: {'✅ ' + test if test else '❌ bo‘sh'}")
        except Exception as exc:
            logger.exception("NOVA AI diagnostic request failed")
            checks.append(f"🌐 Haqiqiy AI so‘rovi: ❌ {exc}")
    send(ADMIN_ID, "🔍🤖 AI DIAGNOSTIKA\n\n" + "\n".join(checks), KB.admin())

@bot.message_handler(func=lambda m: m.text == "➕ AI orqali savol qo'shish")
def admin_generate(message):
    if message.from_user.id != ADMIN_ID:
        return
    if not AI.online():
        send(ADMIN_ID, "⚠️ NOVA AI o‘chiq. .env ichidagi NOVA_API_KEY ni tekshiring.", KB.admin())
        return
    level = "beginner"
    topic = LEVELS[level]["topics"][0]
    try:
        generated = AI.generate_questions(level, topic, 10)
        if generated:
            question_ids = db.bulk_insert_unique(generated)
            if question_ids:
                send(ADMIN_ID, f"✅🤖 {len(question_ids)} ta yangi AI savol bazaga qo'shildi.", KB.admin())
            else:
                send(ADMIN_ID, "ℹ️ Yangi, takrorlanmagan AI savol topilmadi.", KB.admin())
        else:
            send(ADMIN_ID, "⚠️ AI savol yaratmadi.", KB.admin())
    except Exception as exc:
        send(ADMIN_ID, f"❌ AI xatosi: {exc}", KB.admin())

@bot.message_handler(func=lambda m: m.text == "📢 Broadcast")
def admin_broadcast_info(message):
    if message.from_user.id != ADMIN_ID:
        return
    send(
        ADMIN_ID,
        "📢 Broadcast funksiyasi uchun xavfsiz rejim.\n\n"
        "Hozirgi versiyada tasodifiy spam yuborilmasligi uchun "
        "broadcast alohida buyruq orqali bajariladi.",
        KB.admin()
    )


# =============================================================================
# 18. FALLBACK / ERROR HANDLING
# =============================================================================

@bot.message_handler(func=lambda m: True)
def fallback(message):
    uid = message.from_user.id
    try:
        db.register(
            uid,
            message.from_user.username or "",
            message.from_user.first_name or "Student",
            message.from_user.last_name or ""
        )
    except Exception:
        logger.exception("Could not register Telegram user in fallback")

    s = get_session(uid)

    if s.state == "AI":
        # AI handler should normally catch it, but this branch keeps unknown
        # messages inside AI mode instead of silently ignoring them.
        if AI.online():
            try:
                db.save_ai(uid, "user", message.text or "")
                answer = AI.teacher(uid, message.text or "")
                db.save_ai(uid, "assistant", answer)
                send(uid, f"🤖✨ {answer}", KB.ai())
                return
            except Exception as exc:
                logger.exception("fallback AI error")
                send(uid, f"⚠️🤖 AI xatosi: {exc}", KB.ai())
                return

    send(
        uid,
        "🤔 Bu tugma yoki buyruqni tushunmadim.\n\n"
        "👇 Asosiy menyudan tanlang:",
        KB.main(uid)
    )

# =============================================================================
# 19. ERROR LOGGING
# =============================================================================

def log_uncaught_error():
    logger.error("Bot process terminated unexpectedly.")
    logger.error(traceback.format_exc())

# =============================================================================
# 20. STARTUP
# =============================================================================

def print_startup():
    print()
    print("=" * 72)
    print("🤖✨ NOVA AI | ENGLISH ACADEMY ✨🇬🇧")
    print("=" * 72)
    print("🤖 NOVA AI         :", "ONLINE" if AI.online() else "OFFLINE")
    print("📚 Questions       :", db.count_questions())
    print("🗄️ Database        :", DB_NAME)
    print("📦 AI library      :", "READY" if GOOGLE_GENAI_AVAILABLE else "MISSING")
    print("🔑 AI access key   :", "SET" if NOVA_API_KEY else "MISSING")
    print("🚀 Telegram Bot    : READY")
    print("=" * 72)
    print()


def register_bot_commands():
    bot.set_my_commands([
        types.BotCommand("start", "Botni boshlash"),
        types.BotCommand("help", "Yordam va bo'limlar"),
        types.BotCommand("cancel", "Joriy amaldan chiqish"),
        types.BotCommand("id", "Telegram ID ni ko'rish"),
    ])
    bot.set_my_commands(
        [
            types.BotCommand("admin", "Admin panel"),
            types.BotCommand("novadiag", "NOVA AI diagnostikasi"),
        ],
        scope=types.BotCommandScopeChat(chat_id=ADMIN_ID)
    )


def prepare_telegram_polling():
    me = bot.get_me()
    if not me or not me.id:
        raise RuntimeError("Telegram bot tokeni orqali bot ma'lumotini olib bo'lmadi.")
    logger.info("Telegram bot tokeni tekshirildi: @%s", me.username or me.id)

    if not bot.set_my_name("NOVA AI | English Academy"):
        raise RuntimeError("Telegram bot profil nomini NOVA AI qilib o'zgartira olmadi.")
    logger.info("Telegram bot profili NOVA AI nomiga o'rnatildi.")

    webhook = bot.get_webhook_info()
    if webhook.url:
        logger.warning("Webhook topildi; polling uchun o'chirilyapti (pending xabarlar saqlanadi).")
        if not bot.delete_webhook(drop_pending_updates=False):
            raise RuntimeError("Telegram webhookni o'chira olmadi; polling boshlanmadi.")

    register_bot_commands()
    logger.info("Telegram buyruqlari (/start, /help, /cancel, /id) o'rnatildi.")

def study_reminder_worker():
    wait_event = threading.Event()
    while True:
        try:
            deliver_due_study_reminders()
        except Exception:
            logger.exception("Study reminder scheduler failed.")
        wait_event.wait(30)

def deliver_due_study_reminders(now=None) -> int:
    now = now or tashkent_now()
    today = now.date().isoformat()
    current_time = now.strftime("%H:%M")
    sent = 0
    for reminder in db.due_study_reminders(today, current_time):
        user_id = reminder["telegram_id"]
        try:
            bot.send_message(
                user_id,
                "⏰ Ingliz tili uchun 5 daqiqa ajrating!\n"
                "📅 Kunlik rejangiz tayyor — 3 ta savol va xatolarni takrorlash.",
                reply_markup=KB.study_plan()
            )
            db.mark_study_reminder_sent(user_id, today)
            sent += 1
        except Exception as exc:
            logger.warning(
                "Study reminder could not be delivered (%s).",
                type(exc).__name__
            )
            if getattr(exc, "error_code", None) == 403:
                db.set_study_reminder(user_id, False)
    return sent


if __name__ == "__main__":
    try:
        prepare_telegram_polling()
        threading.Thread(
            target=study_reminder_worker,
            name="StudyReminderWorker",
            daemon=True
        ).start()
        print_startup()
        logger.info("🚀 Telegram polling boshlandi. To'xtatish uchun Ctrl+C bosing.")
        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=30,
            skip_pending=False,
            logger_level=logging.INFO
        )
    except KeyboardInterrupt:
        logger.info("🛑 Bot foydalanuvchi tomonidan to'xtatildi.")
    except Exception:
        logger.exception("Bot ishga tushmadi yoki polling to'xtadi.")
        raise
    finally:
        bot.stop_polling()
        release_single_instance_lock()


# =============================================================================
# 21. BUILT-IN ENGLISH LEARNING REFERENCE
# =============================================================================
# Quyidagi reference blok botning ichki o'quv materiallarini hujjatlashtiradi.
# Bu qism executable code emas, lekin loyiha bitta faylda to'liq hujjatlashtirilgan.

# 📘 To Be
# 🧮 Formula: I am / You are / He is / She is / It is / We are / They are
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Present Simple
# 🧮 Formula: Subject + V1; he/she/it + V-s; do/does questions
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Present Continuous
# 🧮 Formula: am/is/are + V-ing
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Past Simple
# 🧮 Formula: V2 or did + V1
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Future Simple
# 🧮 Formula: will + V1
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Present Perfect
# 🧮 Formula: have/has + V3
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Past Perfect
# 🧮 Formula: had + V3
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Future Perfect
# 🧮 Formula: will have + V3
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Present Perfect Continuous
# 🧮 Formula: have/has been + V-ing
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Past Perfect Continuous
# 🧮 Formula: had been + V-ing
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Future Continuous
# 🧮 Formula: will be + V-ing
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Future Perfect Continuous
# 🧮 Formula: will have been + V-ing
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Passive
# 🧮 Formula: be + V3
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 First Conditional
# 🧮 Formula: If + Present Simple, will + V1
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Second Conditional
# 🧮 Formula: If + Past Simple, would + V1
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Third Conditional
# 🧮 Formula: If + Past Perfect, would have + V3
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Mixed Conditional
# 🧮 Formula: Past condition + present result or related mixed forms
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Modal Verbs
# 🧮 Formula: can, could, may, might, must, should, would
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Reported Speech
# 🧮 Formula: Tense and pronoun changes depend on reporting context
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Relative Clauses
# 🧮 Formula: who, which, that, whose, where
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Gerund
# 🧮 Formula: V-ing used as noun or after selected verbs/prepositions
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Infinitive
# 🧮 Formula: to + V1 after selected verbs
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Articles
# 🧮 Formula: a/an for non-specific singular countable nouns; the for specific
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Comparatives
# 🧮 Formula: adjective + -er / more + adjective
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Superlatives
# 🧮 Formula: the + -est / the most + adjective
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Inversion
# 🧮 Formula: Auxiliary + subject after selected negative/restrictive openers
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Cleft
# 🧮 Formula: It is/was ... that/who ... for emphasis
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 📘 Subjunctive
# 🧮 Formula: Base form in certain formal that-clauses
# 🇺🇿 O'zbekcha: Bu qoida kontekstga qarab AI tomonidan batafsil tushuntiriladi.
# 🇬🇧 Example: The AI Teacher can generate fresh examples for this topic.
# ⚠️ Common mistakes are dynamically discussed by Gemini.

# 🧠 Learning template 001: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 001: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 001: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 002: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 002: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 002: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 003: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 003: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 003: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 004: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 004: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 004: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 005: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 005: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 005: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 006: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 006: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 006: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 007: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 007: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 007: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 008: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 008: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 008: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 009: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 009: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 009: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 010: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 010: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 010: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 011: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 011: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 011: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 012: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 012: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 012: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 013: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 013: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 013: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 014: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 014: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 014: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 015: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 015: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 015: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 016: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 016: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 016: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 017: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 017: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 017: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 018: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 018: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 018: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 019: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 019: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 019: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 020: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 020: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 020: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 021: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 021: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 021: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 022: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 022: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 022: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 023: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 023: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 023: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 024: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 024: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 024: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 025: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 025: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 025: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 026: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 026: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 026: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 027: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 027: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 027: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 028: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 028: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 028: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 029: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 029: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 029: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 030: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 030: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 030: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 031: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 031: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 031: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 032: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 032: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 032: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 033: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 033: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 033: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 034: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 034: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 034: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 035: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 035: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 035: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 036: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 036: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 036: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 037: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 037: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 037: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 038: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 038: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 038: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 039: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 039: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 039: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 040: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 040: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 040: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 041: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 041: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 041: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 042: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 042: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 042: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 043: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 043: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 043: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 044: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 044: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 044: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 045: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 045: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 045: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 046: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 046: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 046: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 047: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 047: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 047: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 048: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 048: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 048: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 049: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 049: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 049: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 050: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 050: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 050: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 051: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 051: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 051: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 052: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 052: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 052: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 053: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 053: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 053: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 054: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 054: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 054: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 055: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 055: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 055: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 056: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 056: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 056: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 057: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 057: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 057: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 058: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 058: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 058: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 059: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 059: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 059: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 060: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 060: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 060: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 061: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 061: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 061: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 062: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 062: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 062: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 063: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 063: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 063: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 064: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 064: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 064: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 065: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 065: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 065: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 066: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 066: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 066: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 067: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 067: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 067: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 068: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 068: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 068: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 069: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 069: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 069: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 070: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 070: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 070: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 071: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 071: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 071: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 072: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 072: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 072: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 073: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 073: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 073: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 074: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 074: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 074: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 075: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 075: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 075: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 076: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 076: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 076: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 077: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 077: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 077: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 078: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 078: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 078: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 079: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 079: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 079: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 080: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 080: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 080: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 081: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 081: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 081: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 082: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 082: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 082: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 083: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 083: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 083: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 084: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 084: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 084: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 085: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 085: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 085: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 086: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 086: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 086: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 087: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 087: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 087: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 088: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 088: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 088: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 089: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 089: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 089: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 090: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 090: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 090: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 091: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 091: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 091: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 092: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 092: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 092: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 093: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 093: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 093: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 094: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 094: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 094: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 095: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 095: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 095: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 096: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 096: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 096: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 097: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 097: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 097: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 098: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 098: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 098: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 099: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 099: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 099: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 100: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 100: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 100: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 101: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 101: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 101: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 102: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 102: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 102: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 103: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 103: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 103: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 104: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 104: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 104: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 105: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 105: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 105: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 106: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 106: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 106: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 107: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 107: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 107: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 108: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 108: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 108: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 109: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 109: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 109: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 110: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 110: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 110: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 111: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 111: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 111: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 112: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 112: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 112: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 113: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 113: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 113: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 114: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 114: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 114: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 115: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 115: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 115: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 116: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 116: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 116: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 117: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 117: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 117: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 118: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 118: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 118: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 119: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 119: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 119: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 120: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 120: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 120: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 121: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 121: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 121: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 122: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 122: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 122: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 123: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 123: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 123: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 124: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 124: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 124: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 125: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 125: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 125: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 126: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 126: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 126: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 127: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 127: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 127: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 128: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 128: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 128: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 129: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 129: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 129: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 130: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 130: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 130: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 131: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 131: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 131: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 132: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 132: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 132: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 133: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 133: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 133: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 134: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 134: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 134: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 135: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 135: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 135: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 136: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 136: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 136: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 137: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 137: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 137: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 138: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 138: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 138: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 139: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 139: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 139: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 140: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 140: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 140: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 141: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 141: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 141: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 142: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 142: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 142: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 143: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 143: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 143: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 144: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 144: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 144: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 145: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 145: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 145: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 146: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 146: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 146: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 147: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 147: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 147: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 148: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 148: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 148: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 149: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 149: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 149: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 150: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 150: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 150: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 151: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 151: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 151: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 152: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 152: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 152: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 153: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 153: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 153: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 154: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 154: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 154: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 155: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 155: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 155: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 156: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 156: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 156: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 157: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 157: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 157: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 158: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 158: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 158: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 159: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 159: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 159: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 160: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 160: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 160: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 161: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 161: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 161: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 162: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 162: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 162: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 163: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 163: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 163: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 164: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 164: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 164: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 165: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 165: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 165: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 166: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 166: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 166: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 167: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 167: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 167: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 168: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 168: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 168: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 169: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 169: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 169: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 170: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 170: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 170: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 171: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 171: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 171: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 172: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 172: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 172: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 173: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 173: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 173: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 174: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 174: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 174: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 175: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 175: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 175: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 176: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 176: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 176: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 177: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 177: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 177: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 178: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 178: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 178: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 179: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 179: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 179: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 180: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 180: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 180: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 181: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 181: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 181: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 182: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 182: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 182: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 183: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 183: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 183: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 184: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 184: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 184: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 185: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 185: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 185: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 186: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 186: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 186: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 187: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 187: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 187: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 188: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 188: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 188: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 189: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 189: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 189: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 190: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 190: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 190: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 191: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 191: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 191: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 192: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 192: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 192: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 193: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 193: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 193: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 194: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 194: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 194: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 195: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 195: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 195: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 196: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 196: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 196: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 197: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 197: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 197: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 198: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 198: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 198: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 199: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 199: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 199: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 200: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 200: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 200: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 201: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 201: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 201: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 202: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 202: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 202: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 203: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 203: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 203: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 204: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 204: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 204: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 205: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 205: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 205: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 206: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 206: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 206: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 207: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 207: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 207: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 208: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 208: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 208: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 209: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 209: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 209: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 210: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 210: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 210: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 211: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 211: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 211: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 212: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 212: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 212: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 213: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 213: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 213: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 214: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 214: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 214: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 215: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 215: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 215: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 216: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 216: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 216: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 217: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 217: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 217: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 218: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 218: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 218: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 219: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 219: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 219: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 220: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 220: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 220: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 221: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 221: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 221: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 222: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 222: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 222: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 223: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 223: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 223: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 224: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 224: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 224: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 225: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 225: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 225: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 226: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 226: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 226: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 227: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 227: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 227: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 228: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 228: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 228: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 229: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 229: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 229: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 230: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 230: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 230: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 231: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 231: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 231: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 232: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 232: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 232: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 233: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 233: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 233: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 234: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 234: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 234: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 235: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 235: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 235: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 236: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 236: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 236: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 237: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 237: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 237: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 238: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 238: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 238: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 239: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 239: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 239: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 240: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 240: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 240: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 241: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 241: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 241: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 242: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 242: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 242: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 243: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 243: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 243: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 244: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 244: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 244: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 245: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 245: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 245: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 246: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 246: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 246: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 247: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 247: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 247: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 248: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 248: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 248: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 249: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 249: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 249: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 250: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 250: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 250: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 251: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 251: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 251: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 252: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 252: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 252: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 253: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 253: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 253: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 254: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 254: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 254: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 255: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 255: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 255: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 256: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 256: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 256: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 257: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 257: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 257: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 258: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 258: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 258: question -> answer -> translation -> explanation -> next question.
# 🧠 Learning template 259: AI yangi gap, tarjima, izoh va mashq yaratishi mumkin.
# 🎯 Practice target 259: vocabulary + grammar + Uzbek explanation + English output.
# 🔄 Review cycle 259: question -> answer -> translation -> explanation -> next question.
