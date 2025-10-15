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

def load_scores():
    if os.path.exists(SCORE_FILE):
        with open(SCORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_scores():
    with open(SCORE_FILE, "w", encoding="utf-8") as f:
        json.dump(player_scores, f, ensure_ascii=False, indent=4)


# ======================
# Khởi tạo bot
# ======================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ======================
# Lưu điểm người chơi
# ======================
player_scores = load_scores()

# ======================
# Danh sách câu hỏi đã hỏi
# ======================
asked_questions = set()
is_quiz_running = False
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
        self.answered_users = {}  # {user_id: {"user": user, "answer": "A", "time": 1.23}}
        self.start_time = time.time()

    async def on_timeout(self):
        """Khi hết thời gian"""
        for child in self.children:
            child.disabled = True
        await self.question_message.edit(view=self)
        await self.show_results(timeout=True)
        global is_quiz_running
        is_quiz_running = False


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

        # Nếu đã trả lời -> không cho chọn lại
        if interaction.user.id in self.answered_users:
            await interaction.response.send_message("⚠️ Bạn đã trả lời rồi, không thể chọn lại!", ephemeral=True)
            return

        # Ghi nhận thời gian bấm
        elapsed = round(time.time() - self.start_time, 2)
        self.answered_users[interaction.user.id] = {
            "user": interaction.user,
            "answer": answer,
            "time": elapsed
        }

        # Nếu có người đã đúng rồi, ngăn không cho ai khác chọn đúng
        if self.winner:
            await interaction.response.send_message("❗ Đã có người trả lời đúng rồi!", ephemeral=True)
            return

        # Kiểm tra đúng/sai
        if answer == self.correct_answer:
            self.winner = interaction.user
            player_scores[self.winner.id] = player_scores.get(self.winner.id, 0) + 1
            save_scores()  # 🧠 Lưu ngay khi có thay đổi
            score = player_scores[self.winner.id]

            # Tải avatar
            async with aiohttp.ClientSession() as session:
                async with session.get(self.winner.display_avatar.url) as resp:
                    avatar_bytes = await resp.read()

            # Ghép avatar với khung
            png_bytes = merge_avatar_with_frame_on_top(
                avatar_bytes,
                frame_path='frame.png',
                avatar_size=(177,177),
                final_size=(256,256),
                y_offset=-7
            )
            file = discord.File(fp=png_bytes, filename="winner.png")

            # Khóa nút
            for child in self.children:
                child.disabled = True
            await self.question_message.edit(view=self)

            await self.show_results(timeout=False, file=file, winner_score=score)
            global is_quiz_running
            is_quiz_running = False

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
        # Hiển thị đáp án đầy đủ (ví dụ: "B) Sông Hồng")
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

        
        # 🪄 Thêm một field trống để tạo khoảng cách trước footer
        embed.add_field(name="\u200b", value="\n\u200b", inline=False)

        # 👇 Thêm dòng footer nhỏ ở cuối embed
        embed.set_footer(text="Crate: 🌸 Boizzzz 🗡")

        if self.winner and not timeout:
            embed.description = f"🎉 **{self.winner.mention}** đã trả lời đúng và nhanh nhất!"
            embed.color = discord.Color.green()
            embed.set_image(url="attachment://winner.png")
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
    global asked_questions, is_quiz_running

    # ✅ Nếu quiz đang chạy, ngăn không cho tạo thêm
    if is_quiz_running:
        await ctx.send("⚠️ Đang có câu hỏi diễn ra rồi! Vui lòng đợi câu hỏi này kết thúc.")
        return

    is_quiz_running = True  # 🔒 Đánh dấu đang chạy

    # Lọc những câu chưa hỏi
    remaining_questions = [q for q in quiz_questions if q["question"] not in asked_questions]

    if not remaining_questions:
        await ctx.send("🎯 Hết câu hỏi rồi! Hãy reset bot hoặc thêm câu hỏi mới nhé.")
        return

    quiz = random.choice(remaining_questions)
    asked_questions.add(quiz["question"])  # Đánh dấu đã hỏi

    embed = discord.Embed(
        title="🧠 Câu hỏi kiến thức",
        description=quiz["question"],
        color=random.randint(0, 0xFFFFFF)
    )
    embed.add_field(name="Các lựa chọn", value="\n".join(quiz["options"]), inline=False)
    embed.set_footer(text="⏰ Bạn có 20 giây để trả lời!")

    msg = await ctx.send(embed=embed)
    view = QuizView(quiz, ctx, msg)
    await msg.edit(view=view)
    # Chờ câu hỏi kết thúc
    await view.wait()

    
    global no_answer_streak
    if not view.answered_users:
        no_answer_streak += 1
    else:
        no_answer_streak = 0
    
    if no_answer_streak >= 4:
        await ctx.send("🚫 Không ai trả lời trong 4 câu liên tiếp — kết thúc trò chơi!")
        is_quiz_running = False
        no_answer_streak = 0
        return

    await quiz(ctx)



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
    mid = max(1, total_players // 2)  # ít nhất 1 người ở nhóm thông minh

    smart_players = sorted_scores[:mid]
    dumb_players = sorted_scores[mid:]

    smart_list = ""
    for i, (user_id, points) in enumerate(smart_players, start=1):
        user = await bot.fetch_user(user_id)
        smart_list += f"{i}. 🧠 **{user.name}** — {points} điểm\n"

    dumb_list = ""
    if dumb_players:
        for i, (user_id, points) in enumerate(dumb_players, start=mid + 1):
            user = await bot.fetch_user(user_id)
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
import os
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
#add keep_alive for Render








