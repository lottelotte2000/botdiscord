import discord
from discord.ext import commands
import yt_dlp
from keep_alive import keep_alive
import os
import asyncio
import traceback  # เพิ่ม traceback เพื่อช่วยวิเคราะห์ข้อผิดพลาด

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ปรับปรุงการตั้งค่า yt-dlp
ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'noplaylist': True,
    'extract_flat': True,  # ไม่ต้องดาวน์โหลดวิดีโอก่อนดึงข้อมูลเสียง
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'socket_timeout': 10,  # เพิ่ม timeout ป้องกันการค้าง
}

# ปรับปรุงการตั้งค่า FFMPEG
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -sn -dn -loglevel warning'  # เพิ่ม loglevel warning สำหรับติดตามข้อผิดพลาด
}

# เพิ่มตัวแปรสำหรับเก็บคิวเพลง
class MusicPlayer:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.loop = asyncio.get_event_loop()
        self.next = asyncio.Event()
        self.np = None

    async def player_loop(self, ctx):
        while True:
            self.next.clear()
            try:
                async with asyncio.timeout(180):  # 3 นาทีถ้าไม่มีเพลงใหม่
                    self.current = await self.queue.get()
            except asyncio.TimeoutError:
                return await ctx.voice_client.disconnect()

            voice_client = ctx.voice_client
            if not voice_client:
                return

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await bot.loop.run_in_executor(None, lambda: ydl.extract_info(self.current, download=False))
                    if 'entries' in info:
                        info = info['entries'][0]

                    format_selector = ydl.build_format_selector('bestaudio/best')
                    formats = list(format_selector({**info}))  # แปลง generator เป็น list
                    if not formats:
                        await ctx.send("❌ ไม่พบรูปแบบเสียงที่เหมาะสม")
                        continue

                    url = formats[0]['url']
                    title = info.get('title', 'Unknown')

                    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
                    voice_client.play(source, after=lambda _: bot.loop.call_soon_threadsafe(self.next.set))

                    await ctx.send(f'▶️ กำลังเล่นเพลง: **{title}**')

                    await self.next.wait()
                    try:
                        if source and source._process and source._process.poll() is None:
                            source.cleanup()
                    except Exception as cleanup_error:
                        print(f"Error during cleanup: {cleanup_error}")
                    self.current = None

            except Exception as e:
                await ctx.send(f"❌ เกิดข้อผิดพลาดขณะเล่นเพลง: {str(e)}")
                error_details = traceback.format_exc()  # ดึงข้อมูล traceback ทั้งหมด
                print(f"Detailed error: {error_details}")  # พิมพ์ traceback ทั้งหมดในคอนโซลเพื่อช่วยตรวจสอบ
                continue

players = {}

@bot.event
async def on_ready():
    print(f'Bot พร้อมใช้งานแล้ว: {bot.user.name}')
    await bot.change_presence(activity=discord.Game(name="!commands"))

@bot.command()
async def play(ctx, *, url):  # เพิ่ม * เพื่อรองรับ URL ที่มีช่องว่าง
    if not ctx.author.voice:
        await ctx.send("❌ คุณต้องอยู่ในห้องเสียงก่อน!")
        return

    channel = ctx.author.voice.channel
    voice_client = ctx.voice_client

    try:
        if not voice_client:
            try:
                voice_client = await channel.connect(timeout=10.0)
                await ctx.send("🎵 เข้าร่วมห้องเสียงแล้ว")
            except asyncio.TimeoutError:
                await ctx.send("❌ ไม่สามารถเชื่อมต่อกับห้องเสียงได้ (timeout)")
                return
            except Exception as e:
                await ctx.send(f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อ: {str(e)}")
                return

        if ctx.guild.id not in players:
            players[ctx.guild.id] = MusicPlayer()
            bot.loop.create_task(players[ctx.guild.id].player_loop(ctx))

        await players[ctx.guild.id].queue.put(url)
        await ctx.send("✅ เพิ่มเพลงลงในคิวแล้ว")

    except Exception as e:
        await ctx.send(f"❌ เกิดข้อผิดพลาด: {str(e)}")
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()

@bot.command()
async def stop(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("⏹️ หยุดเล่นเพลงแล้ว")
    else:
        await ctx.send("❌ ไม่มีเพลงที่กำลังเล่นอยู่")

@bot.command()
async def leave(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_connected():
        if voice_client.is_playing():
            voice_client.stop()
        await voice_client.disconnect()
        if ctx.guild.id in players:
            del players[ctx.guild.id]
        await ctx.send("👋 ออกจากห้องเสียงแล้ว")
    else:
        await ctx.send("❌ บอทไม่ได้อยู่ในห้องเสียง")

@bot.command()
async def queue(ctx):
    if ctx.guild.id not in players:
        await ctx.send("❌ ไม่มีคิวเพลงในขณะนี้")
        return

    player = players[ctx.guild.id]
    if player.queue.empty():
        await ctx.send("📋 คิวเพลงว่างอยู่")
        return

    queue_list = "📋 **รายการเพลงในคิว:**\n"
    queue_copy = player.queue._queue.copy()
    for i, url in enumerate(queue_copy, 1):
        queue_list += f"{i}. {url}\n"
    await ctx.send(queue_list)

@bot.command()
async def commands(ctx):
    commands_text = """
📋 **คำสั่งที่ใช้ได้:**
`!play [URL]` - เล่นเพลงจาก YouTube URL
`!stop` - หยุดเล่นเพลงปัจจุบัน
`!queue` - แสดงรายการเพลงในคิว
`!leave` - ให้บอทออกจากห้องเสียง
`!commands` - แสดงคำสั่งที่ใช้ได้
    """
    await ctx.send(commands_text)

keep_alive()
bot.run(os.environ['TOKEN'])
