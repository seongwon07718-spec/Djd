# -*- coding: utf-8 -*-
import os
import re
import asyncio
from typing import Optional, Union

import discord
from discord.ext import commands
from discord import app_commands, ui, Embed, ButtonStyle
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")  # 사용하지 않아도 무방
GUILD_ID = os.getenv("GUILD_ID")

if not TOKEN or not CLIENT_ID or not GUILD_ID:
    print("ENV 설정을 확인하세요: DISCORD_TOKEN, CLIENT_ID, GUILD_ID")
    raise SystemExit(1)

try:
    GUILD_ID_INT = int(GUILD_ID)
except ValueError:
    print("GUILD_ID는 숫자여야 합니다.")
    raise SystemExit(1)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== 경매 상태 =====
class AuctionState:
    def __init__(
        self,
        channel: Union[discord.TextChannel, discord.Thread, discord.DMChannel],
        message: discord.Message,
        item: str,
        start_price: int,
        duration_sec: int,
        owner: discord.Member
    ):
        self.channel = channel
        self.message = message
        self.item = item
        self.start_price = start_price
        self.highest_bid = start_price
        self.highest_bidder: Optional[discord.Member] = None
        self.ends_at = discord.utils.utcnow().timestamp() + duration_sec
        self.owner = owner
        self.lock = asyncio.Lock()
        self.task = asyncio.create_task(self._run_countdown())

    def money_fmt(self, n: int) -> str:
        return f"{n:,}₩"

    def make_embed(self) -> Embed:
        remaining = max(0, int(self.ends_at - discord.utils.utcnow().timestamp()))
        ends_at_ts = int(self.ends_at)
        highest_line = (
            f"**{self.money_fmt(self.highest_bid)}** (<@{self.highest_bidder.id}>)"
            if self.highest_bidder else
            f"아직 없음 (시작가: **{self.money_fmt(self.start_price)}**)"
        )
        embed = Embed(
            title="⚡️경매 진행 중⚡️",
            description=f"**아이템:** {self.item}",
            color=0x000000
        )
        embed.add_field(name="최고 입찰가", value=highest_line, inline=True)
        embed.add_field(
            name="남은 시간",
            value=f"{remaining}초 (<t:{ends_at_ts}:R>)",
            inline=True
        )
        embed.set_footer(text="버튼을 눌러 입찰하고, 모달에 금액을 입력하세요.")
        return embed

    def buttons(self, disabled: bool = False) -> ui.View:
        view = ui.View(timeout=None)
        view.add_item(ui.Button(label="💰입찰하기", custom_id="bid_open",
                                style=ButtonStyle.primary, disabled=disabled))
        view.add_item(ui.Button(label="✖️조기 종료", custom_id="auction_end",
                                style=ButtonStyle.secondary, disabled=disabled))
        return view

    async def _run_countdown(self):
        try:
            while True:
                await asyncio.sleep(5)
                remaining = self.ends_at - discord.utils.utcnow().timestamp()
                if remaining <= 0:
                    await end_auction(self, "시간 종료")
                    break
                try:
                    await self.message.edit(embed=self.make_embed(),
                                            view=self.buttons(False))
                except Exception as e:
                    print("주기 업데이트 실패(무시):", repr(e))
        except asyncio.CancelledError:
            pass

# 채널별 경매상태 저장
auctions = {}  # key: channel.id, value: AuctionState

# ===== 모달(입찰) =====
class BidModal(ui.Modal, title="입찰하기"):
    def __init__(self, state: AuctionState):
        super().__init__(timeout=60)
        self.state = state
        self.bid_value = ui.TextInput(
            label="입찰 금액(정수)",
            placeholder=f"현재가 이상을 입력 (현재: {state.money_fmt(state.highest_bid)})",
            required=True
        )
        self.add_item(self.bid_value)

    async def on_submit(self, interaction: discord.Interaction):
        state = self.state
        if not state:
            await interaction.response.send_message("이미 종료된 경매입니다.", ephemeral=True)
            return

        async with state.lock:
            now_ts = discord.utils.utcnow().timestamp()
            if now_ts >= state.ends_at:
                state.task.cancel()
                await end_auction(state, "시간 종료")
                await interaction.response.send_message("이미 시간이 종료되었습니다.", ephemeral=True)
                return

            raw = (self.bid_value.value or "").strip()
            digits = re.sub(r"\D", "", raw)  # 숫자만 추출
            if not digits:
                await interaction.response.send_message("정수를 입력해주세요.", ephemeral=True)
                return

            bid = int(digits)
            if bid <= state.highest_bid or bid < state.start_price:
                await interaction.response.send_message(
                    f"현재가(**{state.money_fmt(state.highest_bid)}**)보다 높은 금액을 입력하세요.",
                    ephemeral=True
                )
                return

            # 업데이트
            state.highest_bid = bid
            state.highest_bidder = interaction.user
            try:
                await state.message.edit(embed=state.make_embed(), view=state.buttons(False))
            except Exception as e:
                print("즉시 업데이트 실패(무시):", repr(e))

            await interaction.response.send_message(
                f"입찰 성공! 현재 최고가는 **{state.money_fmt(bid)}**입니다.",
                ephemeral=True
            )

# ===== 봇 이벤트/커맨드 =====
@bot.event
async def on_ready():
    print(f"✅ 로그인: {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID_INT))
        print(f"✅ 슬래시 커맨드 동기화 완료: {len(synced)}개")
    except Exception:
        import traceback
        print("❌ 슬래시 동기화 실패:")
        traceback.print_exc()

@bot.tree.command(
    name="경매",
    description="경매를 시작합니다.",
    guild=discord.Object(id=GUILD_ID_INT)
)
@app_commands.describe(아이템="원하는 템 이름/설명",
                       시작금액="시작 금액 (정수)",
                       진행초="몇 초 동안 진행할지")
async def auction(
    interaction: discord.Interaction,
    아이템: str,
    시작금액: int,
    진행초: int
):
    channel = interaction.channel
    if channel.id in auctions:
        await interaction.response.send_message(
            "❗️이 채널에서는 이미 경매가 진행 중입니다. 종료 후 다시 시도해주세요❗️",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    # 우선 '준비중' 메시지 전송
    msg = await interaction.followup.send(embed=Embed(title="경매 준비중..."))

    # 상태 생성 및 등록
    state = AuctionState(channel, msg, 아이템, 시작금액, 진행초, interaction.user)
    auctions[channel.id] = state

    # 본문으로 교체
    await msg.edit(embed=state.make_embed(), view=state.buttons(False))

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # 버튼 클릭만 처리
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id")
    channel_id = interaction.channel.id
    state: Optional[AuctionState] = auctions.get(channel_id)

    if custom_id == "bid_open":
        if not state:
            await interaction.response.send_message("이미 종료된 경매입니다.", ephemeral=True)
            return
        await interaction.response.send_modal(BidModal(state))

    elif custom_id == "auction_end":
        if not state:
            await interaction.response.send_message("이미 종료된 경매입니다.", ephemeral=True)
            return
        is_owner = interaction.user.id == state.owner.id
        is_mod = interaction.user.guild_permissions.manage_messages
        if not (is_owner or is_mod):
            await interaction.response.send_message(
                "❗️개설자 또는 관리자만 조기 종료할 수 있어요❗️",
                ephemeral=True
            )
            return
        state.task.cancel()
        await interaction.response.send_message("경매를 종료했어요.", ephemeral=True)
        await end_auction(state, "조기 종료")

# ===== 종료 처리 =====
async def end_auction(state: AuctionState, reason: str):
    winner_text = (
        f"🏆 우승자: <@{state.highest_bidder.id}> — **{state.money_fmt(state.highest_bid)}**"
        if state.highest_bidder else "입찰자가 없어 낙찰 실패"
    )
    embed = Embed(title="🔔 경매 종료", description=f"**아이템:** {state.item}", color=0xDD2E44)
    embed.add_field(name="결과", value=winner_text, inline=False)
    embed.add_field(name="종료 사유", value=reason, inline=False)
    embed.set_footer(text=None)
    embed.timestamp = discord.utils.utcnow()

    try:
        await state.message.edit(embed=embed, view=state.buttons(True))
        await state.channel.send(winner_text)
    except Exception as e:
        print("종료 업데이트 실패(무시):", repr(e))
    finally:
        auctions.pop(getattr(state.channel, "id", None), None)

bot.run(TOKEN)
