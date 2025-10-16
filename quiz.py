import discord
from discord.ext import commands
import random
from PIL import Image, ImageDraw
import io
import aiohttp
import asyncio
from quiz_questions import quiz_questions
import json, os

from flask import Flask
import threading

app = Flask('')

@app.route('/')
def home():
    return "Bot is awake!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()


SCORE_FILE = "scores.json"
INVENTORY_FILE = "inventory.json"

def load_scores():
    if os.path.exists(SCORE_FILE):
        with open(SCORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_scores():
    with open(SCORE_FILE, "w", encoding="utf-8") as f:
        json.dump(player_scores, f, ensure_ascii=False, indent=4)

def load_inventory():
    if os.path.exists(INVENTORY_FILE):
        with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_inventory():
    with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(player_inventory, f, ensure_ascii=False, indent=4)


# ======================
# Khởi tạo bot
# ======================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="bz", intents=intents)

# ======================
# Lưu điểm người chơi
# ======================
player_scores = load_scores()
player_inventory = load_inventory()

# ======================
# Danh sách khung
# ======================
FRAMES = {
    0: {"name": "Khung Mặc Định", "price": 0, "file": "frame.png", "emoji": "🖼️"},
    1: {"name": "Khung Đồng", "price": 10, "file": "frame1.png", "emoji": "🥉"},
    2: {"name": "Khung Bạc", "price": 20, "file": "frame2.png", "emoji": "🥈"},
    3: {"name": "Khung Vàng", "price": 50, "file": "frame3.png", "emoji": "🥇"},
    4: {"name": "Khung Kim Cương", "price": 100, "file": "frame4.png", "emoji": "💎"}
}

# ======================
# Danh sách câu hỏi đã hỏi
# ======================
asked_questions = set()
is_quiz_running = False
quiz_lock = asyncio.Lock()
no_answer_streak = 0


# ======================
# Hàm tạo avatar hình tròn
# ======================
def make_circle_avatar(avatar_img, size=(128,128)):
    avatar_img = avatar_img.resize(size).convert("RGBA")
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size[0], size[1]), fill=255)
    avatar_img.putalpha(mask)
    return avatar_img

# ======================
# Hàm ghép avatar dưới khung PNG
# ======================
def merge_avatar_with_frame_on_top(
    avatar_bytes,
    frame_path='frame.png',
    avatar_size=(158,158),
    final_size=(256,256),
    y_offset=-10
):
    avatar_img = Image.open(io.BytesIO(avatar_bytes))
    avatar_img = make_circle_avatar(avatar_img, size=avatar_size)
    
    # Kiểm tra file khung có tồn tại không, nếu không dùng frame.png
    if not os.path.exists(frame_path):
        frame_path = 'frame.png'
    
    frame = Image.open(frame_path).convert("RGBA").resize(final_size)

    pos_x = (final_size[0] - avatar_size[0]) // 2
    pos_y = (final_size[1] - avatar_size[1]) // 2 + y_offset

    canvas = Image.new("RGBA", final_size, (0,0,0,0))
    canvas.paste(avatar_img, (pos_x, pos_y), avatar_img)
    canvas.paste(frame, (0,0), frame)

    output_bytes = io.BytesIO()
    canvas.save(output_bytes, format="PNG")
    output_bytes.seek(0)
    return output_bytes

def get_user_frame(user_id):
    """Lấy khung đang trang bị của người chơi"""
    user_id = str(user_id)
    if user_id not in player_inventory:
        return "frame.png"
    
    equipped = player_inventory[user_id].get("equipped", 0)
    return FRAMES[equipped]["file"]

# ======================
# Giao diện trả lời (button)
# ======================
import time

class QuizView(discord.ui.View):
    def __init__(self, quiz, ctx, question_message):
        super().__init__(timeout=20)
        self.quiz = quiz
        self.correct_answer = quiz["answer"]
        self.ctx = ctx
        self.winner = None
        self.question_message = question_message
        self.answered_users = {}
        self.start_time = time.time()

    async def on_timeout(self):
        """Khi hết thời gian"""
        for child in self.children:
            child.disabled = True
        await self.question_message.edit(view=self)
        await self.show_results(timeout=True)

    @discord.ui.button(label="A", style=discord.ButtonStyle.primary)
    async def a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, "A")

    @discord.ui.button(label="B", style=discord.ButtonStyle.primary)
    async def b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, "B")

    @discord.ui.button(label="C", style=discord.ButtonStyle.primary)
    async def c(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, "C")

    @discord.ui.button(label="D", style=discord.ButtonStyle.primary)
    async def d(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.check_answer(interaction, "D")

    async def check_answer(self, interaction, answer):
        global player_scores

        if interaction.user.id in self.answered_users:
            await interaction.response.send_message("⚠️ Bạn đã trả lời rồi, không thể chọn lại!", ephemeral=True)
            return

        elapsed = round(time.time() - self.start_time, 2)
        self.answered_users[interaction.user.id] = {
            "user": interaction.user,
            "answer": answer,
            "time": elapsed
        }

        if self.winner:
            await interaction.response.send_message("❗ Đã có người trả lời đúng rồi!", ephemeral=True)
            return

        if answer == self.correct_answer:
            self.winner = interaction.user
            player_scores[str(self.winner.id)] = player_scores.get(str(self.winner.id), 0) + 1
            save_scores()
            score = player_scores[str(self.winner.id)]

            # Tải avatar
            async with aiohttp.ClientSession() as session:
                async with session.get(self.winner.display_avatar.url) as resp:
                    avatar_bytes = await resp.read()

            # Lấy khung đang trang bị
            frame_path = get_user_frame(self.winner.id)

            # Ghép avatar với khung (nhỏ hơn để làm thumbnail)
            png_bytes = merge_avatar_with_frame_on_top(
                avatar_bytes,
                frame_path=frame_path,
                avatar_size=(110,110),
                final_size=(150,150),
                y_offset=-5
            )
            file = discord.File(fp=png_bytes, filename="winner.png")

            for child in self.children:
                child.disabled = True
            await self.question_message.edit(view=self)

            await self.show_results(timeout=False, file=file, winner_score=score)

            self.stop()
        else:
            await interaction.response.send_message("❌ Sai rồi, bạn không thể chọn lại!", ephemeral=True)

    async def show_results(self, timeout=False, file=None, winner_score=None):
        """Hiển thị kết quả bằng embed"""
        correct_list = []
        wrong_list = []

        for data in self.answered_users.values():
            user = data["user"]
            ans = data["answer"]
            t = data["time"]

            if ans == self.correct_answer:
                correct_list.append(f"✅ {user.mention} — {ans} ({t}s)")
            else:
                wrong_list.append(f"❌ {user.mention} — {ans} ({t}s)")

        if not correct_list:
            correct_list = ["(Không ai chọn đúng)"]
        if not wrong_list:
            wrong_list = ["(Không ai chọn sai)"]

        embed = discord.Embed(
            title="📋 Kết quả câu hỏi",
            color=discord.Color.blurple()
        )
        embed.add_field(name="----- TRẢ LỜI ĐÚNG ✅ -----", value="\n".join(correct_list), inline=False)
        embed.add_field(name="----- TRẢ LỜI SAI ❌ -----", value="\n".join(wrong_list), inline=False)
        embed.add_field(name="🕓 Thời gian tối đa", value="20 giây", inline=True)
        
        options = self.quiz["options"]
        full_answer = next(
            (opt for opt in options if opt.startswith(self.correct_answer + ")")),
            self.correct_answer
        )

        embed.add_field(
            name="----- 📖 ĐÁP ÁN CHÍNH XÁC -----",
            value=full_answer,
            inline=False
        )

        embed.add_field(name="\u200b", value="\n\u200b", inline=False)
        embed.set_footer(text="Crate: 🌸 Boizzzz 🗡")

        if self.winner and not timeout:
            embed.description = f"🎉 **{self.winner.mention}** đã trả lời đúng và nhanh nhất!"
            embed.color = discord.Color.green()
            embed.set_thumbnail(url="attachment://winner.png")  # Dùng thumbnail thay vì image
            embed.add_field(name="🏅 Điểm hiện tại", value=f"{winner_score} điểm", inline=False)
            await self.ctx.send(embed=embed, file=file)
        else:
            embed.description = "⏰ Hết thời gian hoặc không ai trả lời đúng!"
            await self.ctx.send(embed=embed)

# ======================
# Lệnh quiz
# ======================
@bot.command()
async def quiz(ctx):
    global asked_questions, is_quiz_running, no_answer_streak

    async with quiz_lock:
        if is_quiz_running:
            await ctx.send("⚠️ Đang có câu hỏi diễn ra rồi! Vui lòng đợi câu hỏi này kết thúc.")
            return

        is_quiz_running = True
        no_answer_streak = 0

    while True:
        remaining_questions = [q for q in quiz_questions if q["question"] not in asked_questions]

        if not remaining_questions:
            await ctx.send("🎯 Hết câu hỏi rồi! Hãy reset bot hoặc thêm câu hỏi mới nhé.")
            is_quiz_running = False
            break

        question_data = random.choice(remaining_questions)
        asked_questions.add(question_data["question"])

        embed = discord.Embed(
            title="🧠 Câu hỏi kiến thức",
            description=question_data["question"],
            color=random.randint(0, 0xFFFFFF)
        )
                        embed.add_field(name="Các lựa chọn", value="\n".join(question_data["options"]), inline=False)
        embed.set_footer(text="⏰ Bạn có 20 giây để trả lời!")

        msg = await ctx.send(embed=embed)
        view = QuizView(question_data, ctx, msg)
        await msg.edit(view=view)

        await view.wait()

        if not view.answered_users:
            no_answer_streak += 1
        else:
            no_answer_streak = 0

        if no_answer_streak >= 4:
            await ctx.send("🚫 Không ai trả lời trong 4 câu liên tiếp — kết thúc trò chơi!")
            break

        await asyncio.sleep(1)

    is_quiz_running = False

# ======================
# Lệnh xem bảng điểm
# ======================
@bot.command()
async def score(ctx):
    if not player_scores:
        await ctx.send("📊 Chưa có ai có điểm cả.")
        return

    sorted_scores = sorted(player_scores.items(), key=lambda x: x[1], reverse=True)
    total_players = len(sorted_scores)
    mid = max(1, total_players // 2)

    smart_players = sorted_scores[:mid]
    dumb_players = sorted_scores[mid:]

    smart_list = ""
    for i, (user_id, points) in enumerate(smart_players, start=1):
        user = await bot.fetch_user(int(user_id))
        smart_list += f"{i}. 🧠 **{user.name}** — {points} điểm\n"

    dumb_list = ""
    if dumb_players:
        for i, (user_id, points) in enumerate(dumb_players, start=mid + 1):
            user = await bot.fetch_user(int(user_id))
            dumb_list += f"{i}. 😅 **{user.name}** — {points} điểm\n"
    else:
        dumb_list = "(Không có ai ở nhóm này 🎉)"

    embed = discord.Embed(
        title="🏆 Xếp độ THÔNG MINH nào ",
        color=discord.Color.gold()
    )
    embed.add_field(name="🧠 Những người Thông Minh", value=smart_list, inline=False)
    embed.add_field(name="💩 Những người NGỜ U", value=dumb_list, inline=False)
    embed.set_footer(text="Crate : 🌸 Boizzzz 🗡")

    await ctx.send(embed=embed)

# ======================
# Lệnh shop
# ======================
@bot.command()
async def shop(ctx):
    embed = discord.Embed(
        title="🛒 SHOP KHUNG AVATAR",
        description="Dùng điểm của bạn để mua khung đẹp hơn!",
        color=discord.Color.blue()
    )
    
    for frame_id, frame_data in FRAMES.items():
        status = "🎁 MIỄN PHÍ" if frame_data["price"] == 0 else f"💰 {frame_data['price']} điểm"
        embed.add_field(
            name=f"{frame_data['emoji']} {frame_data['name']} (ID: {frame_id})",
            value=f"Giá: {status}",
            inline=False
        )
    
    user_points = player_scores.get(str(ctx.author.id), 0)
    embed.set_footer(text=f"💵 Điểm của bạn: {user_points} | Dùng !buy <ID> để mua")
    
    await ctx.send(embed=embed)

# ======================
# Lệnh mua khung
# ======================
@bot.command()
async def buy(ctx, frame_id: int):
    user_id = str(ctx.author.id)
    
    # Kiểm tra khung có tồn tại không
    if frame_id not in FRAMES:
        await ctx.send("❌ ID khung không hợp lệ! Dùng `bzshop` để xem danh sách.")
        return
    
    frame = FRAMES[frame_id]
    
    # Khởi tạo inventory nếu chưa có
    if user_id not in player_inventory:
        player_inventory[user_id] = {"owned": [0], "equipped": 0}
    
    # Kiểm tra đã sở hữu chưa
    if frame_id in player_inventory[user_id]["owned"]:
        await ctx.send(f"⚠️ Bạn đã sở hữu **{frame['name']}** rồi!")
        return
    
    # Kiểm tra đủ điểm không
    user_points = player_scores.get(user_id, 0)
    if user_points < frame["price"]:
        await ctx.send(f"❌ Không đủ điểm! Bạn cần **{frame['price']}** điểm nhưng chỉ có **{user_points}** điểm.")
        return
    
    # Trừ điểm và thêm khung
    player_scores[user_id] = user_points - frame["price"]
    player_inventory[user_id]["owned"].append(frame_id)
    
    save_scores()
    save_inventory()
    
    embed = discord.Embed(
        title="✅ MUA THÀNH CÔNG!",
        description=f"Bạn đã mua **{frame['emoji']} {frame['name']}**!",
        color=discord.Color.green()
    )
    embed.add_field(name="💰 Giá", value=f"{frame['price']} điểm", inline=True)
    embed.add_field(name="💵 Điểm còn lại", value=f"{player_scores[user_id]} điểm", inline=True)
    embed.set_footer(text="Dùng !equip <ID> để trang bị khung này")
    
    await ctx.send(embed=embed)

# ======================
# Lệnh trang bị khung
# ======================
@bot.command()
async def equip(ctx, frame_id: int):
    user_id = str(ctx.author.id)
    
    # Kiểm tra khung có tồn tại không
    if frame_id not in FRAMES:
        await ctx.send("❌ ID khung không hợp lệ!")
        return
    
    # Kiểm tra đã sở hữu chưa
    if user_id not in player_inventory or frame_id not in player_inventory[user_id]["owned"]:
        await ctx.send(f"❌ Bạn chưa sở hữu khung này! Dùng `bzbuy {frame_id}` để mua.")
        return
    
    # Trang bị khung
    player_inventory[user_id]["equipped"] = frame_id
    save_inventory()
    
    frame = FRAMES[frame_id]
    embed = discord.Embed(
        title="✅ TRANG BỊ THÀNH CÔNG!",
        description=f"Bạn đã trang bị **{frame['emoji']} {frame['name']}**!",
        color=discord.Color.green()
    )
    embed.set_footer(text="Khung này sẽ hiển thị khi bạn trả lời đúng câu hỏi!")
    
    await ctx.send(embed=embed)

# ======================
# Lệnh xem inventory
# ======================
@bot.command(aliases=["inv"])
async def inventory(ctx):
    user_id = str(ctx.author.id)
    
    if user_id not in player_inventory or not player_inventory[user_id]["owned"]:
        await ctx.send("📦 Bạn chưa có khung nào! Dùng `bzshop` để xem và mua khung.")
        return
    
    owned = player_inventory[user_id]["owned"]
    equipped = player_inventory[user_id]["equipped"]
    
    embed = discord.Embed(
        title="🎒 TỦ ĐỒ CỦA BẠN",
        description="Các khung bạn đang sở hữu:",
        color=discord.Color.purple()
    )
    
    for frame_id in owned:
        frame = FRAMES[frame_id]
        status = "✅ ĐANG TRANG BỊ" if frame_id == equipped else "⚪ Chưa trang bị"
        embed.add_field(
            name=f"{frame['emoji']} {frame['name']} (ID: {frame_id})",
            value=status,
            inline=False
        )
    
    embed.set_footer(text="Dùng !equip <ID> để thay đổi khung")
    
    await ctx.send(embed=embed)

import os
keep_alive()

# ======================
# Lệnh help tùy chỉnh
# ======================
bot.remove_command('help')  # Xóa lệnh help mặc định

@bot.command()
async def help(ctx):
    """Hiển thị danh sách lệnh"""
    embed = discord.Embed(
        title="📚 HƯỚNG DẪN SỬ DỤNG BOT",
        description="Danh sách các lệnh bạn có thể sử dụng:",
        color=discord.Color.blue()
    )
    
    # Game Commands
    embed.add_field(
        name="🎮 LỆNH CHƠI GAME",
        value=(
            "`bzquiz` - Bắt đầu trò chơi câu hỏi\n"
            "`bzscore` - Xem bảng xếp hạng điểm\n"
        ),
        inline=False
    )
    
    # Shop Commands
    embed.add_field(
        name="🛒 LỆNH SHOP KHUNG",
        value=(
            "`bzshop` - Xem danh sách khung có thể mua\n"
            "`bzbuy <ID>` - Mua khung (VD: `bzbuy 1`)\n"
            "`bzequip <ID>` - Trang bị khung đã mua\n"
            "`bzinventory` hoặc `bzinv` - Xem khung đã sở hữu\n"
        ),
        inline=False
    )
    
    # Info
    embed.add_field(
        name="💡 THÔNG TIN",
        value=(
            "• Trả lời đúng câu hỏi để nhận **1 điểm**\n"
            "• Dùng điểm để mua khung đẹp trong shop\n"
            "• Khung sẽ hiển thị khi bạn trả lời đúng\n"
        ),
        inline=False
    )
    
    embed.set_footer(text="Crate: 🌸 Boizzzz 🗡 | Chúc bạn chơi vui vẻ!")
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    
    await ctx.send(embed=embed)

import os
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
#add keep_alive for Render

















