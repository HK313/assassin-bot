# telegram_assassin_bot.py
# Final Stable Version – Arabic Default + Moving Control Panel
# python-telegram-bot==20.6 | Python 3.10+

from __future__ import annotations
import os, json, random, asyncio, threading, logging
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, Chat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ---------- Windows fix ----------
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = "assassin_bot_data.json"
MIN_PLAYERS = 4

# ---------- Health server (Render) ----------
def start_health_server():
    port = int(os.environ.get("PORT", "10000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *args): pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# ---------- Text (Arabic default) ----------
TEXT_AR = {
    "panel": "🎮 لوحة التحكم – لعبة القاتل",
    "join": "🔫 انضم",
    "leave": "🚪 غادر",
    "start": "🎬 بدء اللعبة",
    "players": "📜 اللاعبون",
    "vote": "🗳️ بدء التصويت",
    "end": "🛑 إنهاء اللعبة",
    "lang": "🌐 اللغة: عربي",
    "joined": "✅ انضممت للعبة",
    "left": "🚪 غادرت اللعبة",
    "need": f"❗ تحتاج {MIN_PLAYERS} لاعبين على الأقل",
    "admins": "للمشرفين فقط",
    "started": "🎬 بدأت اللعبة وتم إرسال الأدوار بالخاص",
    "night": "🌙 بدأ الليل {n}",
    "vote_start": "🗳️ بدأ التصويت",
    "vote_done": "🪓 تم إقصاء {name}",
    "players_win": "✅ فاز اللاعبون",
    "killer_win": "⚠️ فاز القاتل",
    "dm_killer": "🔪 دورك: القاتل\nاختر ضحية",
    "dm_doctor": "💉 دورك: الطبيب\nاختر من تنقذه",
    "dm_detective": "🕵️ دورك: المحقق\nاختر من تحقق منه",
    "dm_civilian": "🙂 دورك: مواطن\nناقش وصوّت",
    "choose": "اختر لاعبًا:",
}

# ---------- Callbacks ----------
CB_JOIN="g:join"; CB_LEAVE="g:leave"; CB_START="g:start"
CB_PLAYERS="g:players"; CB_VOTE="g:vote"; CB_END="g:end"; CB_LANG="g:lang"
CB_KILL="n:kill"; CB_SAVE="n:save"; CB_INV="n:inv"
CB_PICK_K="p:k"; CB_PICK_S="p:s"; CB_PICK_I="p:i"

ROLE_ICONS={"killer":"🔪","doctor":"💉","detective":"🕵️","civilian":"🙂"}

@dataclass
class Player:
    uid:int
    name:str
    role:str="civilian"
    alive:bool=True

@dataclass
class Game:
    chat_id:int
    players:Dict[int,Player]
    started:bool=False
    night:int=0
    panel_id:Optional[int]=None
    kill:Optional[int]=None
    save:Optional[int]=None

GAMES:Dict[int,Game]={}
LOCK=threading.Lock()

# ---------- Persistence ----------
def save():
    with LOCK:
        with open(DATA_FILE,"w",encoding="utf8") as f:
            json.dump({cid:asdict(g) for cid,g in GAMES.items()},f,ensure_ascii=False,indent=2)

def load():
    if not os.path.exists(DATA_FILE):
        return

    with open(DATA_FILE, "r", encoding="utf8") as f:
        raw = json.load(f)

    for cid, data in raw.items():
        cid_int = int(cid)

        # دعم البيانات القديمة والجديدة
        players_raw = data.get("players", {})
        players_new: Dict[int, Player] = {}

        for k, v in players_raw.items():
            if isinstance(v, dict):
                uid = v.get("uid", v.get("user_id", v.get("id")))
                name = v.get("name", v.get("full_name", "Player"))
                role = v.get("role", "civilian")
                alive = v.get("alive", True)
            else:
                uid = int(k)
                name = "Player"
                role = "civilian"
                alive = True

            if uid is None:
                try:
                    uid = int(k)
                except Exception:
                    continue

            players_new[int(uid)] = Player(
                uid=int(uid),
                name=name,
                role=role,
                alive=bool(alive)
            )

        GAMES[cid_int] = Game(
            chat_id=cid_int,
            players=players_new,
            started=bool(data.get("started", False)),
            night=int(data.get("night", 0)),
            panel_id=data.get("panel_id"),
            kill=data.get("kill"),
            save=data.get("save"),
        )


# ---------- Helpers ----------
def is_group(chat): return chat.type in (Chat.GROUP,Chat.SUPERGROUP)

async def delete_panel(ctx,game):
    if game.panel_id:
        try: await ctx.bot.delete_message(game.chat_id,game.panel_id)
        except: pass

async def post_panel(ctx,game):
    await delete_panel(ctx,game)
    kb=[
        [InlineKeyboardButton(TEXT_AR["join"],callback_data=CB_JOIN),
         InlineKeyboardButton(TEXT_AR["leave"],callback_data=CB_LEAVE)],
        [InlineKeyboardButton(TEXT_AR["start"],callback_data=CB_START),
         InlineKeyboardButton(TEXT_AR["players"],callback_data=CB_PLAYERS)],
        [InlineKeyboardButton(TEXT_AR["vote"],callback_data=CB_VOTE),
         InlineKeyboardButton(TEXT_AR["end"],callback_data=CB_END)]
    ]
    msg=await ctx.bot.send_message(game.chat_id,TEXT_AR["panel"],reply_markup=InlineKeyboardMarkup(kb))
    game.panel_id=msg.message_id
    save()

# ---------- Commands ----------
async def start_cmd(upd,ctx):
    if not is_group(upd.effective_chat):
        await upd.message.reply_text("أضفني إلى مجموعة للعب 🎮")
        return
    game=GAMES.get(upd.effective_chat.id) or Game(upd.effective_chat.id,{})
    GAMES[upd.effective_chat.id]=game
    await post_panel(ctx,game)

# ---------- Buttons ----------
async def on_group_btn(upd,ctx):
    q = upd.callback_query
    await q.answer()

    chat_id = q.message.chat.id
    game = GAMES.get(chat_id)
    if not game:
        game = Game(chat_id, {})
        GAMES[chat_id] = game
        save()

    uid = q.from_user.id

    if q.data==CB_JOIN:
        if uid not in game.players:
            game.players[uid]=Player(uid,q.from_user.full_name)
            save(); await post_panel(ctx,game)

    elif q.data==CB_LEAVE:
        game.players.pop(uid,None)
        save(); await post_panel(ctx,game)

    elif q.data==CB_START:
        if len(game.players)<MIN_PLAYERS:
            await q.answer(TEXT_AR["need"],True); return
        ids=list(game.players.keys()); random.shuffle(ids)
        roles=["killer","doctor","detective"]+["civilian"]*(len(ids)-3)
        for i,uid in enumerate(ids):
            game.players[uid].role=roles[i]
            await ctx.bot.send_message(uid,TEXT_AR["dm_"+roles[i]])
        game.started=True; game.night=1
        save()
        await ctx.bot.send_message(game.chat_id,TEXT_AR["started"])
        await post_panel(ctx,game)

# ---------- Main ----------
async def on_error(update, context):
    logger.exception("Update caused error: %s", context.error)

def main():
    load()
    start_health_server()
    token=os.environ.get("BOT_TOKEN")
    if not token: raise RuntimeError("BOT_TOKEN missing")

    loop=asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app=ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CallbackQueryHandler(on_group_btn,pattern="^g:"))
    logger.info("Bot started")
    app.add_error_handler(on_error)

    app.run_polling()

if __name__=="__main__":
    main()
