import os
import discor
import random
import time
from discord.ext import commands

TOKEN = os.getenv("BOT_TOKEN")
GUILD_ID = 1406418646237974608  # 서버 ID

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
user_points = {}
last_play_time = {}
COOLDOWN = 300  # 30분 쿨타임 (초 단위)


class MinesButton(discord.ui.Button):
    def __init__(self, x, y):
        super().__init__(label="\u200b", style=discord.ButtonStyle.secondary, row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        # 본인만 클릭 가능
        if interaction.user != self.view.player:
            await interaction.response.send_message("**이 게임은 당신 것이 아닙니다**", ephemeral=True)
            return

        cell = self.view.board[self.y][self.x]

        # 보석 클릭
        if cell == "💎":
            self.label = "💎"
            self.style = discord.ButtonStyle.success
            self.disabled = True
            self.view.found_gems += 1

            # 모든 보석 찾음 → 게임 종료
            if self.view.found_gems == self.view.gems_to_find:
                user_points[interaction.user.id] = user_points.get(interaction.user.id, 0) + 1
                for item in self.view.children:
                    item.disabled = True
                await interaction.response.send_message(
                    f"🎉 축하합니다! 보석 {self.view.gems_to_find}개 모두 찾았습니다! "
                    f"(+1점, 총 {user_points[interaction.user.id]}점)",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"💎 보석 발견! ({self.view.found_gems}/{self.view.gems_to_find})",
                    ephemeral=True
                )

            await interaction.message.edit(view=self.view)

        # 폭탄 클릭
        else:
            self.label = "💣"
            self.style = discord.ButtonStyle.danger
            self.disabled = True

            # 전체 보드 공개
            for item in self.view.children:
                if isinstance(item, MinesButton) and not item.disabled:
                    if self.view.board[item.y][item.x] == "💣":
                        item.label = "💣"
                        item.style = discord.ButtonStyle.secondary
                    elif self.view.board[item.y][item.x] == "💎":
                        item.label = "💎"
                        item.style = discord.ButtonStyle.secondary
                    item.disabled = True

            await interaction.response.send_message(
                f"💥 아쉽습니다! 폭탄을 뽑아 탈락했습니다.",
                ephemeral=True
            )
            await interaction.message.edit(view=self.view)


class MinesGame(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)  # 무제한 유지
        self.player = player
        self.gems_to_find = 3
        self.total_gems = 7
        self.found_gems = 0

        # 기본 보드 생성
        self.board = [["💣" for _ in range(5)] for _ in range(5)]
        positions = random.sample([(x, y) for y in range(5) for x in range(5)], self.total_gems)
        for x, y in positions:
            self.board[y][x] = "💎"

        # 버튼 생성
        for y in range(5):
            for x in range(5):
                self.add_item(MinesButton(x, y))


@bot.tree.command(name="미니게임", description="5x5 보석 맞추기 게임 (30분 쿨타임)", guild=discord.Object(id=GUILD_ID))
async def minigame(interaction: discord.Interaction):
    now = time.time()
    last_time = last_play_time.get(interaction.user.id, 0)

    if now - last_time < COOLDOWN:
        remaining = int(COOLDOWN - (now - last_time))
        minutes = remaining // 60
        seconds = remaining % 60
        await interaction.response.send_message(
            f"**{minutes}분 {seconds}초 후에 다시 시도하세요**",
            ephemeral=True
        )
        return

    last_play_time[interaction.user.id] = now
    view = MinesGame(interaction.user)

    await interaction.response.send_message(
        f"**{interaction.user.mention} 님이 미니게임을 시작했습니다**"
    )
    await interaction.channel.send(
        f"**보석 {view.gems_to_find}개를 찾으면 포인트 하나 드립니다**\n"
        f"**총 {view.total_gems}개의 보석이 숨겨져 있습니다**",
        view=view
    )


@bot.tree.command(name="포인트", description="내 포인트 확인", guild=discord.Object(id=GUILD_ID))
async def check_points(interaction: discord.Interaction):
    points = user_points.get(interaction.user.id, 0)
    await interaction.response.send_message(f"**💰 현재 포인트: {points}점**", ephemeral=True)


@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"✅ 로그인됨: {bot.user} | 명령어 동기화 완료!")


bot.run(TOKEN)
