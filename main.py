import discord
from discord.ext import commands
from keep_alive import keep_alive
import yt_dlp
import os
import asyncio
import json
import traceback
import re

# ตั้งค่าต่างๆ สำหรับ Discord Bot
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ฟังก์ชั่นสำหรับโหลดข้อมูลจากไฟล์ JSON
def load_music_channels():
    if not os.path.exists('music_channels.json'):  # ถ้าไฟล์ไม่พบ
        return {}  # ส่งข้อมูลว่างกลับไป

    try:
        with open('music_channels.json', 'r') as f:
            return json.load(f)  # โหลดข้อมูลจากไฟล์ JSON
    except json.JSONDecodeError:  # กรณีที่ข้อมูลในไฟล์ไม่ถูกต้อง
        print("ข้อมูลในไฟล์ไม่ถูกต้อง หรือไฟล์ว่างเปล่า")
        return {}

# ฟังก์ชั่นสำหรับบันทึกข้อมูลกลับไปในไฟล์ JSON
def save_music_channels(data):
    with open('music_channels.json', 'w') as f:
        json.dump(data, f, indent=4)

# เก็บข้อมูลห้องเพลง
MUSIC_CHANNELS = load_music_channels()

# ตั้งค่าต่างๆ สำหรับการเล่นเพลง
ydl_opts = {
    'format': 'bestaudio',
    'quiet': True,
    'no_warnings': True,
    'noplaylist': True,
    'extract_flat': False,
    'socket_timeout': 5,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# สร้างคลาสสำหรับการเล่นเพลง
class MusicPlayer:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.next = asyncio.Event()

    async def player_loop(self, ctx):
        while True:
            self.next.clear()
            try:
                async with asyncio.timeout(180):
                    self.current = await self.queue.get()
            except asyncio.TimeoutError:
                return await ctx.voice_client.disconnect()

            if not ctx.voice_client:
                return

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(self.current, download=False))
                    if 'entries' in info:
                        info = info['entries'][0]

                    url = info['url']
                    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
                    ctx.voice_client.play(source, after=lambda _: self.next.set())  # ใช้ self.next.set() โดยตรง
                    await ctx.send(f'🎵 เปิดเพลง: **{info["title"]}**')
                    await self.next.wait()  # รอให้เพลงเล่นจบ
                    source.cleanup()
                    self.current = None

            except Exception as e:
                print(f"ข้อผิดพลาด: {e}")
                continue

# เก็บตัวผู้เล่นเพลงในแต่ละเซิร์ฟเวอร์
players = {}

# คำสั่งเมื่อบอทพร้อมทำงาน
@bot.event
async def on_ready():
    print(f'บอทพร้อมใช้งาน: {bot.user.name}')
    await bot.change_presence(activity=discord.Game(name="พิมพ์ !สร้างห้อง เพื่อสร้างห้องเพลง"))

# คำสั่งสร้างห้องเพลง
@bot.command(name='สร้างห้อง')
async def createmusic(ctx):
    if ctx.guild.id in MUSIC_CHANNELS:
        return await ctx.send("❌ มีห้องเพลงแล้ว")

    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(
            send_messages=True,
            read_messages=True,
            read_message_history=True
        )
    }

    channel = await ctx.guild.create_text_channel('🎵-ห้องเพลง', overwrites=overwrites)
    MUSIC_CHANNELS[ctx.guild.id] = channel.id
    save_music_channels(MUSIC_CHANNELS)  # บันทึกข้อมูลห้องเพลงใหม่

    await channel.send("""🎵 **ห้องสำหรับใส่ลิงก์เพลง**
วิธีใช้: วางลิงก์ YouTube ในห้องนี้เพื่อเล่นเพลง""")
    await ctx.send(f"✅ สร้างห้อง {channel.mention} แล้ว")

# คำสั่งเล่นเพลงจาก URL
async def play_url(ctx, url):
    if not ctx.author.voice:
        return await ctx.send("❌ เข้าห้องเสียงก่อน")

    try:
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()

        if ctx.guild.id not in players:
            players[ctx.guild.id] = MusicPlayer()
            bot.loop.create_task(players[ctx.guild.id].player_loop(ctx))

        await players[ctx.guild.id].queue.put(url)
        await ctx.send("✅ เพิ่มเพลงแล้ว")

    except Exception as e:
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send(f"❌ ผิดพลาด: {str(e)}")

# ตรวจสอบข้อความเพื่อหาลิงก์ YouTube
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # ตรวจสอบว่าเป็นข้อความในห้องเพลงไหม
    if message.guild.id in MUSIC_CHANNELS and message.channel.id == MUSIC_CHANNELS[message.guild.id]:
        urls = re.findall(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s]+', message.content)
        if urls:
            ctx = await bot.get_context(message)
            for url in urls:
                await play_url(ctx, url)
        elif not message.content.startswith('!'):
            await message.delete()
            temp_msg = await message.channel.send("❌ ใส่ลิงก์ YouTube เท่านั้น")
            await asyncio.sleep(5)
            await temp_msg.delete()

    await bot.process_commands(message)

# คำสั่งหยุดเล่นเพลง
@bot.command(name='หยุด')
async def stop(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏹️ หยุดเล่นแล้ว")

# คำสั่งให้บอทออกจากห้อง
@bot.command(name='ออก')
async def leave(ctx):
    if ctx.voice_client:
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        if ctx.guild.id in players:
            del players[ctx.guild.id]
        await ctx.send("👋 ออกแล้ว")

# คำสั่งดูคิวเพลง
@bot.command(name='คิว')
async def queue(ctx):
    if ctx.guild.id not in players or players[ctx.guild.id].queue.empty():
        return await ctx.send("📋 ไม่มีเพลงในคิว")

    queue_list = "📋 เพลงในคิว:\n"
    for i, url in enumerate(players[ctx.guild.id].queue._queue.copy(), 1):
        queue_list += f"{i}. {url}\n"
    await ctx.send(queue_list)

# คำสั่งแสดงคำสั่งทั้งหมด
@bot.command(name='คำสั่ง')
async def commands(ctx):
    await ctx.send("""📋 คำสั่ง:
!สร้างห้อง - สร้างห้องใส่ลิงก์เพลง
!หยุด - หยุดเล่น
!คิว - ดูคิวเพลง
!ออก - ให้บอทออก
!คำสั่ง - ดูคำสั่ง""")

# การทำให้บอทออนไลน์อยู่ตลอดเวลา
keep_alive()
bot.run(os.environ['TOKEN'])