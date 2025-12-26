# telegram_assassin_bot.py
# Python 3.10+ | python-telegram-bot==20.6

from __future__ import annotations

import os
import json
import random
import logging
import threading
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer

def start_health_server():
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

from dataclasses import dataclass, asdict
from typing import Dict, Optional, List

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

# --- Windows event loop fix ---
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DATA_FILE = "assassin_bot_data.json"
MIN_PLAYERS = 4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROLE_ICONS = {"killer": "🔪", "detective": "🕵️", "doctor": "💉", "civilian": "🙂"}
ROLE_NAMES = {"killer": "Killer", "detective": "Detective", "doctor": "Doctor", "civilian": "Civilian"}
ROLE_DESCRIPTIONS = {
    "killer": "Pick one victim each night.",
    "detective": "Investigate one player each night (role revealed to you).",
    "doctor": "Save one player each night.",
    "civilian": "No special powers. Vote in the group.",
}

# ---- Callback data ----
CB_G_JOIN = "g:join"
CB_G_LEAVE = "g:leave"
CB_G_START = "g:start"
CB_G_PLAYERS = "g:players"
CB_G_FORCE_VOTE = "g:vote"   # admins only
CB_G_END = "g:end"           # admins only
CB_G_VOTE_PICK = "g:vp"      # g:vp:<chat_id>:<target_id>

CB_DM_KILL_MENU = "dm:killmenu"  # dm:killmenu:<chat_id>
CB_DM_SAVE_MENU = "dm:savemenu"  # dm:savemenu:<chat_id>
CB_DM_INV_MENU  = "dm:invmenu"   # dm:invmenu:<chat_id>

CB_DM_KILL_PICK = "dm:kill"      # dm:kill:<chat_id>:<target_id>
CB_DM_SAVE_PICK = "dm:save"      # dm:save:<chat_id>:<target_id>
CB_DM_INV_PICK  = "dm:inv"       # dm:inv:<chat_id>:<target_id>

CB_NOOP = "noop"

FILE_LOCK = threading.Lock()


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

    # Night actions
    pending_kill_target: Optional[int] = None
    pending_save_target: Optional[int] = None
    pending_investigation_target: Optional[int] = None

    # Day voting
    voting_open: bool = False
    votes: Dict[int, int] = None  # voter_id -> target_id

    def __post_init__(self):
        if self.votes is None:
            self.votes = {}


GAMES: Dict[int, Game] = {}


# ---------------- Persistence ----------------
def save_games() -> None:
    with FILE_LOCK:
        obj = {}
        for cid, g in GAMES.items():
            obj[str(cid)] = {
                "chat_id": g.chat_id,
                "started": g.started,
                "night": g.night,
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


# ---------------- Helpers ----------------
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


def group_keyboard(admin: bool) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton("🔫 Join Game", callback_data=CB_G_JOIN),
        InlineKeyboardButton("🚪 Leave Game", callback_data=CB_G_LEAVE),
    ]]
    if admin:
        rows.append([
            InlineKeyboardButton("🎬 Start Game", callback_data=CB_G_START),
            InlineKeyboardButton("📜 Show Players", callback_data=CB_G_PLAYERS),
        ])
        rows.append([
            InlineKeyboardButton("🗳️ Start Vote", callback_data=CB_G_FORCE_VOTE),
            InlineKeyboardButton("🛑 End Game", callback_data=CB_G_END),
        ])
    return InlineKeyboardMarkup(rows)


def role_dm_menu(role: str, chat_id: int) -> Optional[InlineKeyboardMarkup]:
    if role == "killer":
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔪 Choose victim", callback_data=f"{CB_DM_KILL_MENU}:{chat_id}")]])
    if role == "doctor":
        return InlineKeyboardMarkup([[InlineKeyboardButton("💉 Choose who to save", callback_data=f"{CB_DM_SAVE_MENU}:{chat_id}")]])
    if role == "detective":
        return InlineKeyboardMarkup([[InlineKeyboardButton("🕵️ Choose who to investigate", callback_data=f"{CB_DM_INV_MENU}:{chat_id}")]])
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
        rows = [[InlineKeyboardButton("(No targets)", callback_data=CB_NOOP)]]
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
        rows = [[InlineKeyboardButton("(No players)", callback_data=CB_NOOP)]]
    return InlineKeyboardMarkup(rows)


def majority_needed(game: Game) -> int:
    alive_count = sum(1 for p in game.players.values() if p.alive)
    return (alive_count // 2) + 1


# ---------------- Game Flow ----------------
async def send_role_dms(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    for p in game.players.values():
        role = p.role
        text = (
            f"{ROLE_ICONS[role]} Your role: <b>{ROLE_NAMES[role]}</b>\n"
            f"{ROLE_DESCRIPTIONS[role]}"
            + ("\n\n⚠️ Keep it secret!" if role in ("killer", "doctor", "detective") else "")
        )
        kb = role_dm_menu(role, game.chat_id)
        try:
            await context.bot.send_message(chat_id=p.user_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            await context.bot.send_message(
                chat_id=game.chat_id,
                text=f"⚠️ I couldn't DM {p.name}. They must open a private chat with the bot and press /start once.",
            )


async def start_night(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    game.voting_open = False
    game.votes = {}
    game.pending_kill_target = None
    game.pending_save_target = None
    game.pending_investigation_target = None
    save_games()
    await context.bot.send_message(chat_id=game.chat_id, text=f"🌙 Night {game.night} begins. Roles, check your DMs.")
    await send_role_dms(context, game)


async def start_vote(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    game.voting_open = True
    game.votes = {}
    save_games()
    await context.bot.send_message(
        chat_id=game.chat_id,
        text="🗳️ Day Vote started! Tap a name to vote.",
        reply_markup=vote_keyboard(game),
    )


async def check_win_and_announce(context: ContextTypes.DEFAULT_TYPE, game: Game) -> bool:
    alive = [p for p in game.players.values() if p.alive]
    killers = [p for p in alive if p.role == "killer"]
    others = [p for p in alive if p.role != "killer"]
    if not killers:
        game.started = False
        game.voting_open = False
        save_games()
        await context.bot.send_message(chat_id=game.chat_id, text="✅ Players win! The killer is gone.")
        return True
    if len(killers) >= len(others):
        game.started = False
        game.voting_open = False
        save_games()
        await context.bot.send_message(chat_id=game.chat_id, text="⚠️ Killer wins! Outnumbered the others.")
        return True
    return False


async def resolve_night_if_ready(context: ContextTypes.DEFAULT_TYPE, game: Game) -> None:
    if not game.started:
        return
    if game.pending_kill_target is None or game.pending_save_target is None:
        return

    victim_id = game.pending_kill_target
    saved_id = game.pending_save_target

    # Reset selections
    game.pending_kill_target = None
    game.pending_save_target = None
    game.pending_investigation_target = None

    if victim_id == saved_id:
        await context.bot.send_message(chat_id=game.chat_id, text=f"🌙 Night {game.night} is over. 🛡️ Someone was saved! No one died.")
    else:
        victim = game.players.get(victim_id)
        if victim and victim.alive:
            victim.alive = False
            await context.bot.send_message(chat_id=game.chat_id, text=f"🌙 Night {game.night} is over. 💀 {victim.name} was killed.")
        else:
            await context.bot.send_message(chat_id=game.chat_id, text=f"🌙 Night {game.night} is over. (No valid victim.)")

    save_games()
    if await check_win_and_announce(context, game):
        return

    # After night => vote
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

                await context.bot.send_message(chat_id=game.chat_id, text=f"🪓 Vote result: {target.name} was eliminated ({cnt}/{needed}).")

                if await check_win_and_announce(context, game):
                    return

                game.night += 1
                save_games()
                await start_night(context, game)
            return


# ---------------- Commands ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat or not is_group(chat):
        await update.message.reply_text(
            "Hi! Add me to a group to play.\n"
            "In a group: type /start to get buttons.\n"
            "Players must /start me in private once so I can DM roles."
        )
        return

    # admin check safely
    admin = False
    try:
        member = await chat.get_member(update.effective_user.id)
        admin = member.status in ("administrator", "creator")
    except Exception:
        admin = False

    await update.message.reply_text("🎮 Welcome!\nChoose an option:", reply_markup=group_keyboard(admin))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat or not is_group(chat):
        await update.message.reply_text("Use this in the group.")
        return
    game = GAMES.get(chat.id)
    if not game:
        await update.message.reply_text("No game here yet. Use /start then Join Game.")
        return
    await update.message.reply_text(
        f"Game: {'RUNNING' if game.started else 'NOT STARTED'}\n"
        f"Night: {game.night}\n"
        f"Voting: {'OPEN' if game.voting_open else 'CLOSED'}\n\n"
        f"Players:\n{format_players(game)}"
    )


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Unknown command. Use /start in the group.")


# ---------------- Callbacks ----------------
async def on_group_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    chat = query.message.chat
    user = query.from_user

    if not is_group(chat):
        await query.answer("Use this in a group.", show_alert=True)
        return

    game = get_or_create_game(chat.id)

    # safe admin check
    admin = False
    try:
        member = await chat.get_member(user.id)
        admin = member.status in ("administrator", "creator")
    except Exception:
        admin = False

    if data == CB_G_JOIN:
        if user.id in game.players:
            await query.answer("You are already in the game.", show_alert=True)
            return
        game.players[user.id] = Player(user_id=user.id, name=user.full_name, username=user.username, alive=True)
        save_games()
        await query.answer("✅ Joined!", show_alert=True)

    elif data == CB_G_LEAVE:
        if user.id not in game.players:
            await query.answer("You are not in the game.", show_alert=True)
            return
        del game.players[user.id]
        save_games()
        await query.answer("🚪 Left.", show_alert=True)

    elif data == CB_G_START:
        if not admin:
            await query.answer("Admins only.", show_alert=True)
            return
        if game.started:
            await query.answer("Game already started.", show_alert=True)
            return
        if len(game.players) < MIN_PLAYERS:
            await query.answer(f"Need at least {MIN_PLAYERS} players.", show_alert=True)
            return

        # reset players
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

        await context.bot.send_message(chat_id=chat.id, text="🎬 Game started! Roles sent in DM.")
        await start_night(context, game)
        await query.answer("🎬 Started!", show_alert=True)

    elif data == CB_G_PLAYERS:
        if not admin:
            await query.answer("Admins only.", show_alert=True)
            return
        await query.answer("📜 Players:\n" + format_players(game, limit=180), show_alert=True)

    elif data == CB_G_FORCE_VOTE:
        if not admin:
            await query.answer("Admins only.", show_alert=True)
            return
        if not game.started:
            await query.answer("Start game first.", show_alert=True)
            return
        await query.answer("🗳️ Vote started.", show_alert=True)
        await start_vote(context, game)

    elif data == CB_G_END:
        if not admin:
            await query.answer("Admins only.", show_alert=True)
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
        await context.bot.send_message(chat_id=chat.id, text="🛑 Game ended and reset.")
        await query.answer("🛑 Ended.", show_alert=True)

    # Update keyboard (admin buttons show only to admin who pressed /start message)
    try:
        await query.message.edit_reply_markup(reply_markup=group_keyboard(admin))
    except Exception:
        pass


async def on_vote_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")  # g:vp:<chat_id>:<target_id>
    if len(parts) != 4:
        await query.answer("Invalid.", show_alert=True)
        return

    _, _, chat_id_str, target_id_str = parts
    try:
        chat_id = int(chat_id_str)
        target_id = int(target_id_str)
    except ValueError:
        await query.answer("Invalid.", show_alert=True)
        return

    game = GAMES.get(chat_id)
    if not game or not game.started or not game.voting_open:
        await query.answer("Voting not open.", show_alert=True)
        return

    voter_id = query.from_user.id
    voter = game.players.get(voter_id)
    target = game.players.get(target_id)

    if not voter or not voter.alive:
        await query.answer("You are not an alive player.", show_alert=True)
        return
    if not target or not target.alive:
        await query.answer("Target not alive.", show_alert=True)
        return

    game.votes[voter_id] = target_id
    save_games()
    await query.answer(f"✅ Voted for {target.name}", show_alert=True)
    await apply_vote_if_majority(context, game)


async def on_dm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")  # dm:killmenu:<chat_id>
    if len(parts) != 3:
        await query.answer("Invalid.", show_alert=True)
        return

    _, menu, chat_id_str = parts
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        await query.answer("Invalid game.", show_alert=True)
        return

    game = GAMES.get(chat_id)
    if not game or not game.started:
        await query.answer("No running game.", show_alert=True)
        return

    actor_id = query.from_user.id
    actor = game.players.get(actor_id)
    if not actor or not actor.alive:
        await query.answer("You are not an alive player.", show_alert=True)
        return

    if menu == "killmenu":
        if actor.role != "killer":
            await query.answer("Not your role.", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text("🔪 Choose a victim:", reply_markup=target_list_keyboard(game, CB_DM_KILL_PICK, exclude_ids=[actor_id]))

    elif menu == "savemenu":
        if actor.role != "doctor":
            await query.answer("Not your role.", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text("💉 Choose who to save:", reply_markup=target_list_keyboard(game, CB_DM_SAVE_PICK))

    elif menu == "invmenu":
        if actor.role != "detective":
            await query.answer("Not your role.", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text("🕵️ Choose who to investigate:", reply_markup=target_list_keyboard(game, CB_DM_INV_PICK, exclude_ids=[actor_id]))


async def on_dm_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")  # dm:kill:<chat_id>:<target_id>
    if len(parts) != 4:
        await query.answer("Invalid.", show_alert=True)
        return

    _, action, chat_id_str, target_id_str = parts
    try:
        chat_id = int(chat_id_str)
        target_id = int(target_id_str)
    except ValueError:
        await query.answer("Invalid.", show_alert=True)
        return

    game = GAMES.get(chat_id)
    if not game or not game.started:
        await query.answer("No running game.", show_alert=True)
        return

    actor_id = query.from_user.id
    actor = game.players.get(actor_id)
    target = game.players.get(target_id)

    if not actor or not actor.alive:
        await query.answer("Not alive player.", show_alert=True)
        return
    if not target or not target.alive:
        await query.answer("Target not alive.", show_alert=True)
        return

    if action == "kill":
        if actor.role != "killer":
            await query.answer("Not your role.", show_alert=True)
            return
        if target_id == actor_id:
            await query.answer("Can't pick yourself.", show_alert=True)
            return
        game.pending_kill_target = target_id
        save_games()
        await query.answer(f"🔪 Selected: {target.name}", show_alert=True)
        await query.edit_message_text(f"✅ You selected: {target.name}\nWait for Doctor.")
        await resolve_night_if_ready(context, game)

    elif action == "save":
        if actor.role != "doctor":
            await query.answer("Not your role.", show_alert=True)
            return
        game.pending_save_target = target_id
        save_games()
        await query.answer(f"💉 Selected: {target.name}", show_alert=True)
        await query.edit_message_text(f"✅ You decided to save: {target.name}\nWait for Killer.")
        await resolve_night_if_ready(context, game)

    elif action == "inv":
        if actor.role != "detective":
            await query.answer("Not your role.", show_alert=True)
            return
        if target_id == actor_id:
            await query.answer("Can't investigate yourself.", show_alert=True)
            return
        game.pending_investigation_target = target_id
        save_games()
        role = target.role
        await query.answer(f"🕵️ Investigated: {target.name}", show_alert=True)
        await query.edit_message_text(f"✅ Investigation complete: {target.name}")
        await context.bot.send_message(
            chat_id=actor_id,
            text=f"🕵️ Result: <b>{target.name}</b> is <b>{ROLE_NAMES[role]}</b> {ROLE_ICONS[role]}",
            parse_mode=ParseMode.HTML,
        )


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Update caused error: %s", context.error)


# ---------------- Main ----------------
def main() -> None:
    load_games()

    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN env var")

    # Create and set loop for MainThread (prevents "no current event loop" on Windows)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CallbackQueryHandler(on_group_button, pattern=r"^g:(join|leave|start|players|vote|end)$"))
    app.add_handler(CallbackQueryHandler(on_vote_pick, pattern=r"^g:vp:"))

    app.add_handler(CallbackQueryHandler(on_dm_menu, pattern=r"^dm:(killmenu|savemenu|invmenu):"))
    app.add_handler(CallbackQueryHandler(on_dm_pick, pattern=r"^dm:(kill|save|inv):"))

    app.add_handler(CallbackQueryHandler(noop, pattern=r"^noop$"))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    app.add_error_handler(on_error)

    logger.info("Bot starting...")
    start_health_server()
    app.run_polling()


if __name__ == "__main__":
    main()
