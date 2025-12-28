# telegram_assassin_bot.py
# Python 3.10+ | python-telegram-bot==20.6
# Bilingual (AR/EN) + Admin language toggle + DM translated too

from __future__ import annotations

import os
import json
import random
import logging
import threading
import asyncio
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, Chat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- Windows event loop policy (safe) ---
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DATA_FILE = "assassin_bot_data.json"
MIN_PLAYERS = 4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- UI TEXT (EN/AR) --------------------
TEXT_EN = {
    "welcome_group": "🎮 Welcome to Assassin Game!\nChoose an option:",
    "join": "🔫 Join Game",
    "leave": "🚪 Leave Game",
    "start_game": "🎬 Start Game",
    "show_players": "📜 Show Players",
    "start_vote": "🗳️ Start Vote",
    "end_game": "🛑 End Game",
    "language_btn": "🌐 Language: EN (tap to switch)",

    "joined": "✅ You joined the game!",
    "left": "🚪 You left the game.",
    "already_joined": "You are already in the game.",
    "not_joined": "You are not in the game.",
    "need_players": f"Need at least {MIN_PLAYERS} players.",
    "admins_only": "Admins only.",
    "start_first": "Start the game first.",
    "game_already_started": "Game already started.",
    "vote_started_ok": "🗳️ Vote started.",
    "game_ended_ok": "🛑 Game ended and reset.",
    "players_popup_title": "📜 Players:",

    "add_to_group": "Hi! Add me to a group to play.\nIn a group, type /start to get buttons.\nPlayers must /start me in private once so I can DM roles.",
    "use_in_group": "Use this in the group.",
    "unknown_cmd": "Unknown command. Use /start in the group.",

    "role_title": "{icon} Your role: <b>{role}</b>",
    "role_killer": "Killer",
    "role_doctor": "Doctor",
    "role_detective": "Detective",
    "role_civilian": "Civilian",

    "role_desc_killer": "Pick one victim each night.",
    "role_desc_doctor": "Save one player each night.",
    "role_desc_detective": "Investigate one player each night (role revealed to you).",
    "role_desc_civilian": "No special powers. Vote in the group.",
    "keep_secret": "⚠️ Keep it secret!",

    "dm_cant": "⚠️ I couldn't DM {name}. They must open a private chat with the bot and press /start once.",

    "night_begins": "🌙 Night {n} begins. Roles, check your DMs.",
    "night_over_saved": "🌙 Night {n} is over. 🛡️ Someone was saved! No one died.",
    "night_over_killed": "🌙 Night {n} is over. 💀 {name} was killed.",
    "night_over_invalid": "🌙 Night {n} is over. (No valid victim.)",

    "vote_started": "🗳️ Day Vote started! Tap a name to vote.",
    "voting_not_open": "Voting is not open.",
    "not_alive_player": "You are not an alive player.",
    "target_not_alive": "Target not alive.",
    "voted_for": "✅ Voted for {name}",
    "vote_result": "🪓 Vote result: {name} was eliminated ({cnt}/{need}).",

    "players_win": "✅ Players win! The killer is gone.",
    "killer_win": "⚠️ Killer wins! Outnumbered the others.",

    "dm_choose_victim": "🔪 Choose a victim:",
    "dm_choose_save": "💉 Choose who to save:",
    "dm_choose_inv": "🕵️ Choose who to investigate:",
    "dm_btn_choose_victim": "🔪 Choose victim",
    "dm_btn_choose_save": "💉 Choose who to save",
    "dm_btn_choose_inv": "🕵️ Choose who to investigate",

    "dm_selected_wait_doctor": "✅ You selected: {name}\nWait for the Doctor.",
    "dm_selected_wait_killer": "✅ You decided to save: {name}\nWait for the Killer.",
    "dm_invest_done": "✅ Investigation complete: {name}",
    "dm_invest_result": "🕵️ Result: <b>{name}</b> is <b>{role}</b> {icon}",

    "noop_targets": "(No targets)",
    "lang_switched": "✅ Language switched.",
}

TEXT_AR = {
    "welcome_group": "🎮 أهلاً بك في لعبة القاتل!\nاختر خياراً:",
    "join": "🔫 انضم للعبة",
    "leave": "🚪 غادر اللعبة",
    "start_game": "🎬 بدء اللعبة",
    "show_players": "📜 عرض اللاعبين",
    "start_vote": "🗳️ بدء التصويت",
    "end_game": "🛑 إنهاء اللعبة",
    "language_btn": "🌐 اللغة: AR (اضغط للتبديل)",

    "joined": "✅ تم انضمامك للعبة!",
    "left": "🚪 غادرت اللعبة.",
    "already_joined": "أنت منضم مسبقًا.",
    "not_joined": "أنت غير منضم.",
    "need_players": f"تحتاج على الأقل {MIN_PLAYERS} لاعبين.",
    "admins_only": "للمشرفين فقط.",
    "start_first": "ابدأ اللعبة أولاً.",
    "game_already_started": "اللعبة بدأت بالفعل.",
    "vote_started_ok": "🗳️ تم بدء التصويت.",
    "game_ended_ok": "🛑 تم إنهاء اللعبة وإعادة ضبطها.",
    "players_popup_title": "📜 اللاعبون:",

    "add_to_group": "مرحباً! أضفني لمجموعة للعب.\nفي المجموعة اكتب /start لإظهار الأزرار.\nلازم كل لاعب يفتح الخاص مع البوت ويكتب /start مرة واحدة حتى أرسل الأدوار.",
    "use_in_group": "استخدم هذا داخل المجموعة.",
    "unknown_cmd": "أمر غير معروف. استخدم /start في المجموعة.",

    "role_title": "{icon} دورك: <b>{role}</b>",
    "role_killer": "القاتل",
    "role_doctor": "الطبيب",
    "role_detective": "المحقق",
    "role_civilian": "مواطن",

    "role_desc_killer": "اختر ضحية كل ليلة.",
    "role_desc_doctor": "اختر شخصاً لإنقاذه كل ليلة.",
    "role_desc_detective": "تحقق من لاعب كل ليلة (يظهر لك دوره).",
    "role_desc_civilian": "بدون صلاحيات خاصة. ناقش وصوّت.",
    "keep_secret": "⚠️ احتفظ به سرّاً!",

    "dm_cant": "⚠️ لم أستطع مراسلة {name}. لازم يفتح الخاص مع البوت ويكتب /start مرة واحدة.",

    "night_begins": "🌙 بدأ الليل {n}. تفقد رسائلك الخاصة.",
    "night_over_saved": "🌙 انتهى الليل {n}. 🛡️ تم إنقاذ شخص! لا أحد مات.",
    "night_over_killed": "🌙 انتهى الليل {n}. 💀 تم قتل {name}.",
    "night_over_invalid": "🌙 انتهى الليل {n}. (لا توجد ضحية صالحة.)",

    "vote_started": "🗳️ بدأ التصويت! اختر لاعبًا.",
    "voting_not_open": "التصويت غير متاح الآن.",
    "not_alive_player": "أنت لست لاعباً حياً.",
    "target_not_alive": "الهدف ليس حيّاً.",
    "voted_for": "✅ تم التصويت لـ {name}",
    "vote_result": "🪓 نتيجة التصويت: تم إقصاء {name} ({cnt}/{need}).",

    "players_win": "✅ فاز اللاعبون! تم التخلص من القاتل.",
    "killer_win": "⚠️ فاز القاتل! أصبحوا أقلية.",

    "dm_choose_victim": "🔪 اختر ضحية:",
    "dm_choose_save": "💉 اختر من تريد إنقاذه:",
    "dm_choose_inv": "🕵️ اختر من تريد التحقق منه:",
    "dm_btn_choose_victim": "🔪 اختر ضحية",
    "dm_btn_choose_save": "💉 اختر إنقاذ",
    "dm_btn_choose_inv": "🕵️ اختر تحقيق",

    "dm_selected_wait_doctor": "✅ اخترت: {name}\nانتظر الطبيب.",
    "dm_selected_wait_killer": "✅ قررت إنقاذ: {name}\nانتظر القاتل.",
    "dm_invest_done": "✅ انتهى التحقيق: {name}",
    "dm_invest_result": "🕵️ النتيجة: <b>{name}</b> هو <b>{role}</b> {icon}",

    "noop_targets": "(لا توجد أهداف)",
    "lang_switched": "✅ تم تبديل اللغة.",
}

def tr(game: "Game", key: str, **kwargs) -> str:
    table = TEXT_AR if (game and game.lang == "ar") else TEXT_EN
    text = table.get(key, key)
    return text.format(**kwargs) if kwargs else text

def role_name(game: "Game", role: str) -> str:
    key = {
        "killer": "role_killer",
        "doctor": "role_doctor",
        "detective": "role_detective",
        "civilian": "role_civilian",
    }[role]
    return tr(game, key)

def role_desc(game: "Game", role: str) -> str:
    key = {
        "killer": "role_desc_killer",
        "doctor": "role_desc_doctor",
        "detective": "role_desc_detective",
        "civilian": "role_desc_civilian",
    }[role]
    return tr(game, key)

# -------------------- Callbacks --------------------
CB_G_JOIN = "g:join"
CB_G_LEAVE = "g:leave"
CB_G_START = "g:start"
CB_G_PLAYERS = "g:players"
CB_G_FORCE_VOTE = "g:vote"
CB_G_END = "g:end"
CB_G_LANG = "g:lang"
CB_G_VOTE_PICK = "g:vp"      # g:vp:<chat_id>:<target_id>

CB_DM_KILL_MENU = "dm:killmenu"  # dm:killmenu:<chat_id>
CB_DM_SAVE_MENU = "dm:savemenu"  # dm:savemenu:<chat_id>
CB_DM_INV_MENU  = "dm:invmenu"   # dm:invmenu:<chat_id>

CB_DM_KILL_PICK = "dm:kill"      # dm:kill:<chat_id>:<target_id>
CB_DM_SAVE_PICK = "dm:save"      # dm:save:<chat_id>:<target_id>
CB_DM_INV_PICK  = "dm:inv"       # dm:inv:<chat_id>:<target_id>

CB_NOOP = "noop"

ROLE_ICONS = {"killer": "🔪", "detective": "🕵️", "doctor": "💉", "civilian": "🙂"}


@dataclass
class Player:
    user_id: int
    name: str
    username: Optional[str] = None
    role: str = "civilian"
    alive: bool = True


@dataclass
class Game:
    chat_id: int
    players: Dict[int, Player]
    started: bool = False
    night: int = 0
    lang: str = "en"  # "en" or "ar"

    # night actions
    pending_kill_target: Optional[int] = None
    pending_save_target: Optional[int] = None
    pending_investigation_target: Optional[int] = None

    # day vote
    voting_open: bool = False
    votes: Dict[int, int] = None  # voter_id -> target_id

    def __post_init__(self):
        if self.votes is None:
            self.votes = {}


GAMES: Dict[int, Game] = {}
FILE_LOCK = threading.Lock()

# -------------------- Render health server (port binding) --------------------
def start_health_server() -> None:
    port = int(os.environ.get("PORT", "10000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, format, *args):
            return

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# -------------------- Persistence --------------------
def save_games() -> None:
    with FILE_LOCK:
        obj = {}
        for cid, g in GAMES.items():
            obj[str(cid)] = {
                "chat_id": g.chat_id,
                "started": g.started,
                "night": g.night,
                "lang": g.lang,
                "pending_kill_target": g.pending_kill_target,
                "pending_save_target": g.pending_save_target,
                "pending_investigation_target": g.pending_investigation_target,
                "voting_open": g.voting_open,
                "votes": {str(k): v for k, v in (g.votes or {}).items()},
                "players": {str(uid): asdict(p) for uid, p in g.players.items()},
            }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

def load_games() -> None:
    global GAMES
    if not os.path.exists(DATA_FILE):
        return
    with FILE_LOCK:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            games: Dict[int, Game] = {}
            for cid_str, data in raw.items():
                cid = int(cid_str)
                players = {int(uid): Player(**pdata) for uid, pdata in data.get("players", {}).items()}
                g = Game(
                    chat_id=cid,
                    players=players,
                    started=bool(data.get("started", False)),
                    night=int(data.get("night", 0)),
                    lang=str(data.get("lang", "en")),
                    pending_kill_target=data.get("pending_kill_target"),
                    pending_save_target=data.get("pending_save_target"),
                    pending_investigation_target=data.get("pending_investigation_target"),
                    voting_open=bool(data.get("voting_open", False)),
                    votes={int(k): v for k, v in (data.get("votes") or {}).items()},
                )
                games[cid] = g
            GAMES = games
        except Exception:
            logger.exception("Failed to load games. Starting fresh.")
            GAMES = {}

# -------------------- Helpers --------------------
def is_group(chat: Chat) -> bool:
    return chat.type in (Chat.GROUP, Chat.SUPERGROUP)

def get_or_create_game(chat_id: int) -> Game:
    g = GAMES.get(chat_id)
    if not g:
        g = Game(chat_id=chat_id, players={})
        GAMES[chat_id] = g
        save_games()
    return g

def format_players(game: Game, limit: Optional[int] = None) -> str:
    lines = []
    for p in game.players.values():
        status = "🟢 alive" if p.alive else "⚰️ dead"
        uname = f"@{p.username}" if p.username else ""
        lines.append(f"• {p.name} {uname} — {status}")
    text = "\n".join(lines) if lines else "(no players)"
    if limit and len(text) > limit:
        return text[:limit] + "…"
    return text

def group_keyboard(game: Game, admin: bool) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(tr(game, "join"), callback_data=CB_G_JOIN),
        InlineKeyboardButton(tr(game, "leave"), callback_data=CB_G_LEAVE),
    ]]
    if admin:
        rows.append([
            InlineKeyboardButton(tr(game, "start_game"), callback_data=CB_G_START),
            InlineKeyboardButton(tr(game, "show_players"), callback_data=CB_G_PLAYERS),
        ])
        rows.append([
            InlineKeyboardButton(tr(game, "start_vote"), callback_data=CB_G_FORCE_VOTE),
            InlineKeyboardButton(tr(game, "end_game"), callback_data=CB_G_END),
        ])
        rows.append([InlineKeyboardButton(tr(game, "language_btn"), callback_data=CB_G_LANG)])
    return InlineKeyboardMarkup(rows)

def role_dm_menu(game: Game, role: str) -> Optional[InlineKeyboardMarkup]:
    if role == "killer":
        return InlineKeyboardMarkup([[InlineKeyboardButton(tr(game, "dm_btn_choose_victim"), callback_data=f"{CB_DM_KILL_MENU}:{game.chat_id}")]])
    if role == "doctor":
        return InlineKeyboardMarkup([[InlineKeyboardButton(tr(game, "dm_btn_choose_save"), callback_data=f"{CB_DM_SAVE_MENU}:{game.chat_id}")]])
    if role == "detective":
        return InlineKeyboardMarkup([[InlineKeyboardButton(tr(game, "dm_btn_choose_inv"), callback_data=f"{CB_DM_INV_MENU}:{game.chat_id}")]])
    return None

def target_list_keyboard(game: Game, prefix: str, exclude_ids: Optional[List[int]] = None) -> InlineKeyboardMarkup:
    exclude_ids = exclude_ids or []
    alive = [p for p in game.players.values() if p.alive and p.user_id not in exclude_ids]
    rows: List[List[InlineKeyboardButton]] = []
    for i in range(0, len(alive), 2):
        row = []
        for p in alive[i:i+2]:
            row.append(InlineKeyboardButton(p.name, callback_data=f"{prefix}:{game.chat_id}:{p.user_id}"))
        rows.append(row)
    if not rows:
        rows = [[InlineKeyboardButton(tr(game, "noop_targets"), callback_data=CB_NOOP)]]
    return InlineKeyboardMarkup(rows)

def vote_keyboard(game: Game) -> InlineKeyboardMarkup:
    alive = [p for p in game.players.values() if p.alive]
    rows: List[List[InlineKeyboardButton]] = []
    for i in range(0, len(alive), 2):
        row = []
        for p in alive[i:i+2]:
            row.append(InlineKeyboardButton(p.name, callback_data=f"{CB_G_VOTE_PICK}:{game.chat_id}:{p.user_id}"))
        rows.append(row)
    if not rows:
        rows = [[InlineKeyboardButton(tr(game, "noop_targets"), callback_data=CB_NOOP)]]
    return InlineKeyboardMarkup(rows)

def majority_needed(game: Game) -> int:
    alive_count = sum(1 for p in game.players.values() if p.alive)
    return (alive_count // 2) + 1

# -------------------- Game Flow --------------------
async def send_role_dms(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    for p in game.players.values():
        role = p.role
        title = tr(game, "role_title", icon=ROLE_ICONS[role], role=role_name(game, role))
        desc = role_desc(game, role)
        extra = f"\n\n{tr(game, 'keep_secret')}" if role in ("killer", "doctor", "detective") else ""
        text = f"{title}\n{desc}{extra}"
        kb = role_dm_menu(game, role)
        try:
            await context.bot.send_message(chat_id=p.user_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "dm_cant", name=p.name))

async def start_night(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    game.voting_open = False
    game.votes = {}
    game.pending_kill_target = None
    game.pending_save_target = None
    game.pending_investigation_target = None
    save_games()
    await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "night_begins", n=game.night))
    await send_role_dms(context, game)

async def start_vote(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    game.voting_open = True
    game.votes = {}
    save_games()
    await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "vote_started"), reply_markup=vote_keyboard(game))

async def check_win_and_announce(context: ContextTypes.DEFAULT_TYPE, game: Game) -> bool:
    alive = [p for p in game.players.values() if p.alive]
    killers = [p for p in alive if p.role == "killer"]
    others = [p for p in alive if p.role != "killer"]
    if not killers:
        game.started = False
        game.voting_open = False
        save_games()
        await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "players_win"))
        return True
    if len(killers) >= len(others):
        game.started = False
        game.voting_open = False
        save_games()
        await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "killer_win"))
        return True
    return False

async def resolve_night_if_ready(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    if not game.started:
        return
    if game.pending_kill_target is None or game.pending_save_target is None:
        return

    victim_id = game.pending_kill_target
    saved_id = game.pending_save_target

    game.pending_kill_target = None
    game.pending_save_target = None
    game.pending_investigation_target = None

    if victim_id == saved_id:
        await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "night_over_saved", n=game.night))
    else:
        victim = game.players.get(victim_id)
        if victim and victim.alive:
            victim.alive = False
            await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "night_over_killed", n=game.night, name=victim.name))
        else:
            await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "night_over_invalid", n=game.night))

    save_games()
    if await check_win_and_announce(context, game):
        return

    # after night -> vote
    await start_vote(context, game)

async def apply_vote_if_majority(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    if not game.started or not game.voting_open:
        return

    counts: Dict[int, int] = {}
    for voter_id, target_id in (game.votes or {}).items():
        voter = game.players.get(voter_id)
        if voter and voter.alive:
            counts[target_id] = counts.get(target_id, 0) + 1

    needed = majority_needed(game)
    for target_id, cnt in counts.items():
        if cnt >= needed:
            target = game.players.get(target_id)
            if target and target.alive:
                target.alive = False
                game.voting_open = False
                game.votes = {}
                save_games()

                await context.bot.send_message(chat_id=game.chat_id, text=tr(game, "vote_result", name=target.name, cnt=cnt, need=needed))

                if await check_win_and_announce(context, game):
                    return

                game.night += 1
                save_games()
                await start_night(context, game)
            return

# -------------------- Commands --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat or not is_group(chat):
        # Private chat
        await update.message.reply_text(TEXT_AR["add_to_group"] + "\n\n---\n\n" + TEXT_EN["add_to_group"])
        return

    game = get_or_create_game(chat.id)

    admin = False
    try:
        member = await chat.get_member(update.effective_user.id)
        admin = member.status in ("administrator", "creator")
    except Exception:
        admin = False

    await update.message.reply_text(tr(game, "welcome_group"), reply_markup=group_keyboard(game, admin))

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat or not is_group(chat):
        await update.message.reply_text(TEXT_AR["use_in_group"] + "\n" + TEXT_EN["use_in_group"])
        return

    game = GAMES.get(chat.id)
    if not game:
        await update.message.reply_text("—")
        return

    await update.message.reply_text(
        f"{'RUNNING' if game.started else 'NOT STARTED'} | Night: {game.night} | Voting: {'OPEN' if game.voting_open else 'CLOSED'}\n\n"
        + format_players(game)
    )

async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat and is_group(chat) and chat.id in GAMES:
        game = GAMES[chat.id]
        await update.message.reply_text(tr(game, "unknown_cmd"))
    else:
        await update.message.reply_text(TEXT_AR["unknown_cmd"] + "\n" + TEXT_EN["unknown_cmd"])

# -------------------- Callbacks --------------------
async def on_group_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    chat = query.message.chat
    user = query.from_user

    if not is_group(chat):
        await query.answer("—", show_alert=True)
        return

    game = get_or_create_game(chat.id)

    admin = False
    try:
        member = await chat.get_member(user.id)
        admin = member.status in ("administrator", "creator")
    except Exception:
        admin = False

    if data == CB_G_JOIN:
        if user.id in game.players:
            await query.answer(tr(game, "already_joined"), show_alert=True)
            return
        game.players[user.id] = Player(user_id=user.id, name=user.full_name, username=user.username, alive=True)
        save_games()
        await query.answer(tr(game, "joined"), show_alert=True)

    elif data == CB_G_LEAVE:
        if user.id not in game.players:
            await query.answer(tr(game, "not_joined"), show_alert=True)
            return
        del game.players[user.id]
        save_games()
        await query.answer(tr(game, "left"), show_alert=True)

    elif data == CB_G_LANG:
        if not admin:
            await query.answer(tr(game, "admins_only"), show_alert=True)
            return
        game.lang = "ar" if game.lang == "en" else "en"
        save_games()
        await query.answer(tr(game, "lang_switched"), show_alert=True)

    elif data == CB_G_START:
        if not admin:
            await query.answer(tr(game, "admins_only"), show_alert=True)
            return
        if game.started:
            await query.answer(tr(game, "game_already_started"), show_alert=True)
            return
        if len(game.players) < MIN_PLAYERS:
            await query.answer(tr(game, "need_players"), show_alert=True)
            return

        for p in game.players.values():
            p.alive = True
            p.role = "civilian"

        uids = list(game.players.keys())
        random.shuffle(uids)
        game.players[uids[0]].role = "killer"
        game.players[uids[1]].role = "detective"
        game.players[uids[2]].role = "doctor"

        game.started = True
        game.night = 1
        game.voting_open = False
        game.votes = {}
        game.pending_kill_target = None
        game.pending_save_target = None
        game.pending_investigation_target = None
        save_games()

        await context.bot.send_message(chat_id=chat.id, text=tr(game, "game_started"))
        await start_night(context, game)
        await query.answer("✅", show_alert=False)

    elif data == CB_G_PLAYERS:
        if not admin:
            await query.answer(tr(game, "admins_only"), show_alert=True)
            return
        short = format_players(game, limit=180)
        await query.answer(f"{tr(game,'players_popup_title')}\n{short}", show_alert=True)

    elif data == CB_G_FORCE_VOTE:
        if not admin:
            await query.answer(tr(game, "admins_only"), show_alert=True)
            return
        if not game.started:
            await query.answer(tr(game, "start_first"), show_alert=True)
            return
        await query.answer(tr(game, "vote_started_ok"), show_alert=True)
        await start_vote(context, game)

    elif data == CB_G_END:
        if not admin:
            await query.answer(tr(game, "admins_only"), show_alert=True)
            return
        game.started = False
        game.night = 0
        game.voting_open = False
        game.votes = {}
        game.pending_kill_target = None
        game.pending_save_target = None
        game.pending_investigation_target = None
        for p in game.players.values():
            p.alive = True
            p.role = "civilian"
        save_games()
        await context.bot.send_message(chat_id=chat.id, text=tr(game, "game_ended_ok"))
        await query.answer("✅", show_alert=False)

    # keep keyboard updated
    try:
        await query.message.edit_reply_markup(reply_markup=group_keyboard(game, admin))
    except Exception:
        pass

async def on_vote_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")  # g:vp:<chat_id>:<target_id>
    if len(parts) != 4:
        await query.answer("—", show_alert=True)
        return

    _, _, chat_id_str, target_id_str = parts
    try:
        chat_id = int(chat_id_str)
        target_id = int(target_id_str)
    except ValueError:
        await query.answer("—", show_alert=True)
        return

    game = GAMES.get(chat_id)
    if not game or not game.started or not game.voting_open:
        await query.answer(tr(game or Game(chat_id, {}), "voting_not_open"), show_alert=True)
        return

    voter_id = query.from_user.id
    voter = game.players.get(voter_id)
    target = game.players.get(target_id)

    if not voter or not voter.alive:
        await query.answer(tr(game, "not_alive_player"), show_alert=True)
        return
    if not target or not target.alive:
        await query.answer(tr(game, "target_not_alive"), show_alert=True)
        return

    game.votes[voter_id] = target_id
    save_games()
    await query.answer(tr(game, "voted_for", name=target.name), show_alert=True)
    await apply_vote_if_majority(context, game)

async def on_dm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")  # dm:killmenu:<chat_id>
    if len(parts) != 3:
        await query.answer("—", show_alert=True)
        return

    _, menu, chat_id_str = parts
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        await query.answer("—", show_alert=True)
        return

    game = GAMES.get(chat_id)
    if not game or not game.started:
        await query.answer("—", show_alert=True)
        return

    actor_id = query.from_user.id
    actor = game.players.get(actor_id)
    if not actor or not actor.alive:
        await query.answer(tr(game, "not_alive_player"), show_alert=True)
        return

    if menu == "killmenu":
        if actor.role != "killer":
            await query.answer("—", show_alert=True)
            return
        await query.edit_message_text(tr(game, "dm_choose_victim"), reply_markup=target_list_keyboard(game, CB_DM_KILL_PICK, exclude_ids=[actor_id]))

    elif menu == "savemenu":
        if actor.role != "doctor":
            await query.answer("—", show_alert=True)
            return
        await query.edit_message_text(tr(game, "dm_choose_save"), reply_markup=target_list_keyboard(game, CB_DM_SAVE_PICK))

    elif menu == "invmenu":
        if actor.role != "detective":
            await query.answer("—", show_alert=True)
            return
        await query.edit_message_text(tr(game, "dm_choose_inv"), reply_markup=target_list_keyboard(game, CB_DM_INV_PICK, exclude_ids=[actor_id]))

async def on_dm_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")  # dm:kill:<chat_id>:<target_id>
    if len(parts) != 4:
        await query.answer("—", show_alert=True)
        return

    _, action, chat_id_str, target_id_str = parts
    try:
        chat_id = int(chat_id_str)
        target_id = int(target_id_str)
    except ValueError:
        await query.answer("—", show_alert=True)
        return

    game = GAMES.get(chat_id)
    if not game or not game.started:
        await query.answer("—", show_alert=True)
        return

    actor_id = query.from_user.id
    actor = game.players.get(actor_id)
    target = game.players.get(target_id)

    if not actor or not actor.alive:
        await query.answer(tr(game, "not_alive_player"), show_alert=True)
        return
    if not target or not target.alive:
        await query.answer(tr(game, "target_not_alive"), show_alert=True)
        return

    if action == "kill":
        if actor.role != "killer" or target_id == actor_id:
            await query.answer("—", show_alert=True)
            return
        game.pending_kill_target = target_id
        save_games()
        await query.answer("✅", show_alert=False)
        await query.edit_message_text(tr(game, "dm_selected_wait_doctor", name=target.name))
        await resolve_night_if_ready(context, game)

    elif action == "save":
        if actor.role != "doctor":
            await query.answer("—", show_alert=True)
            return
        game.pending_save_target = target_id
        save_games()
        await query.answer("✅", show_alert=False)
        await query.edit_message_text(tr(game, "dm_selected_wait_killer", name=target.name))
        await resolve_night_if_ready(context, game)

    elif action == "inv":
        if actor.role != "detective" or target_id == actor_id:
            await query.answer("—", show_alert=True)
            return
        game.pending_investigation_target = target_id
        save_games()
        await query.answer("✅", show_alert=False)
        await query.edit_message_text(tr(game, "dm_invest_done", name=target.name))

        rname = role_name(game, target.role)
        await context.bot.send_message(
            chat_id=actor_id,
            text=tr(game, "dm_invest_result", name=target.name, role=rname, icon=ROLE_ICONS[target.role]),
            parse_mode=ParseMode.HTML,
        )

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Update caused error: %s", context.error)

# -------------------- Main --------------------
def main() -> None:
    load_games()

    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN env var")

    # Health server for Render port binding
    start_health_server()

    # Create and set loop for MainThread (prevents event loop issues)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CallbackQueryHandler(on_group_button, pattern=r"^g:(join|leave|start|players|vote|end|lang)$"))
    app.add_handler(CallbackQueryHandler(on_vote_pick, pattern=r"^g:vp:"))

    app.add_handler(CallbackQueryHandler(on_dm_menu, pattern=r"^dm:(killmenu|savemenu|invmenu):"))
    app.add_handler(CallbackQueryHandler(on_dm_pick, pattern=r"^dm:(kill|save|inv):"))

    app.add_handler(CallbackQueryHandler(noop, pattern=r"^noop$"))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    app.add_error_handler(on_error)

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
