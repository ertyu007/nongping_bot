import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
from datetime import datetime
import os
from dotenv import load_dotenv
import logging

# โหลด environment variables
load_dotenv()

# ตั้งค่า logging รองรับภาษาไทย
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# โหลดค่าจาก .env
ESP32_IP = os.getenv('ESP32_IP', '10.70.55.222')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 1406180111358885928))
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
HEARTBEAT_INTERVAL = int(os.getenv('HEARTBEAT_INTERVAL', 1))
# ชื่อ role (หรือ 'admin'/'manage_guild' permission) ที่อนุญาตให้สั่งควบคุมระบบได้
CONTROL_ROLE = os.getenv('CONTROL_ROLE', 'Admin')
# Token ที่ใช้ยืนยันตัวตนกับ ESP32 (ฝั่ง firmware ต้องตรวจสอบ header นี้ด้วย)
ESP32_TOKEN = os.getenv('ESP32_TOKEN', '')

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN ไม่พบในไฟล์ .env")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix='/',
    intents=intents,
    help_command=None
)

def esp32_headers():
    """Header สำหรับยืนยันตัวตนกับ ESP32 (ถ้ามีการตั้ง ESP32_TOKEN)."""
    return {'X-Auth-Token': ESP32_TOKEN} if ESP32_TOKEN else {}

def can_control(ctx):
    """อนุญาตเฉพาะเจ้าของบอท / ผู้ที่มี permission ดูแล server / ผู้มี role CONTROL_ROLE."""
    if not isinstance(ctx.author, discord.Member):
        return False
    if ctx.author.id == ctx.bot.owner_id:
        return True
    perms = ctx.author.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True
    return any(role.name.lower() == CONTROL_ROLE.lower() for role in ctx.author.roles)

def require_control():
    """Decorator: ปฏิเสธผู้ใช้ที่ไม่มีสิทธิ์ควบคุมระบบ."""
    async def predicate(ctx):
        if can_control(ctx):
            return True
        await ctx.send(embed=create_embed(
            "⛔ ไม่อนุญาต",
            f"คุณต้องมี role '{CONTROL_ROLE}' หรือสิทธิ์ดูแล server ถึงจะใช้คำสั่งนี้ได้",
            0xFF0000,
        ))
        return False
    return commands.check(predicate)

class ESP32ConnectionError(Exception):
    """Custom exception สำหรับ ESP32"""
    pass

async def get_session():
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

async def check_esp32_connection():
    """ตรวจสอบการเชื่อมต่อ ESP32"""
    async with await get_session() as session:
        try:
            async with session.get(f"http://{ESP32_IP}/ping", headers=esp32_headers()) as response:
                if response.status != 200:
                    text = await response.text()
                    raise ESP32ConnectionError(f"HTTP {response.status}: {text[:100]}")
                return True
        except Exception as e:
            raise ESP32ConnectionError(f"ไม่สามารถเชื่อมต่อ: {type(e).__name__}")

async def get_esp32_status():
    """ดึงสถานะจาก ESP32"""
    async with await get_session() as session:
        try:
            async with session.get(f"http://{ESP32_IP}/status", timeout=10, headers=esp32_headers()) as response:
                if response.status != 200:
                    text = await response.text()
                    raise ESP32ConnectionError(f"HTTP {response.status}: {text[:100]}")
                return await response.json()
        except Exception as e:
            logger.error(f"Error in get_esp32_status: {e}")
            raise ESP32ConnectionError(f"ดึงข้อมูลไม่ได้: {type(e).__name__}")

def create_embed(title: str, description: str, color: int):
    """สร้าง embed พร้อม footer"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now()
    )
    embed.set_footer(text="Smart Farm System")
    return embed

@bot.event
async def on_ready():
    logger.info(f'Bot logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'ESP32 IP: {ESP32_IP}')
    logger.info(f'Monitoring channel ID: {DISCORD_CHANNEL_ID}')
    check_esp32_status.start()

@bot.command()
async def help(ctx):
    """แสดงคำสั่งทั้งหมด"""
    embed = create_embed("🆘 คำสั่งทั้งหมด", "ระบบ Smart Farm บน Discord", 0x7289DA)
    
    commands_list = [
        ("/ping", "ตรวจสอบการเชื่อมต่อ ESP32"),
        ("/on", "เปิดระบบควบคุมอัตโนมัติ"),
        ("/off", "ปิดระบบควบคุมอัตโนมัติ"),
        ("/status", "ดูสถานะปัจจุบัน"),
        ("/pump on/off", "ควบคุมปั๊มด้วยมือ"),
        ("/reboot", "รีสตาร์ท ESP32"),
        ("/help", "แสดงคำสั่งนี้")
    ]
    
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def ping(ctx):
    """ตรวจสอบการเชื่อมต่อ"""
    try:
        await check_esp32_connection()
        status = await get_esp32_status()
        embed = create_embed("✅ ESP32 ออนไลน์", "เชื่อมต่อสำเร็จ", 0x00FF00)
        embed.add_field(name="IP", value=status.get('ip', 'N/A'), inline=True)
        embed.add_field(name="ความชื้น", value=f"{status.get('moisture', 0)}%", inline=True)
        embed.add_field(name="สถานะ", value="เปิด" if status.get('enabled') else "ปิด", inline=True)
    except ESP32ConnectionError as e:
        embed = create_embed("⚠️ ไม่สามารถเชื่อมต่อ", str(e), 0xFF0000)
    await ctx.send(embed=embed)

@bot.command()
@require_control()
async def on(ctx):
    """เปิดระบบควบคุมอัตโนมัติ"""
    try:
        async with await get_session() as session:
            async with session.get(f"http://{ESP32_IP}/command?cmd=on", headers=esp32_headers()) as response:
                if response.status != 200:
                    raise ESP32ConnectionError("ไม่สามารถเปิดระบบได้")
                data = await response.json()
        
        status = await get_esp32_status()
        embed = create_embed("✅ ระบบเปิด", data.get('message', 'ระบบเปิดเรียบร้อย'), 0x00FF00)
        embed.add_field(name="ความชื้น", value=f"{status['moisture']}%", inline=True)
        embed.add_field(name="ปั๊ม", value="เปิด" if status['pump'] else "ปิด", inline=True)
    except ESP32ConnectionError as e:
        embed = create_embed("⚠️ ผิดพลาด", "ไม่สามารถเปิดระบบได้", 0xFF0000)
    await ctx.send(embed=embed)

@bot.command()
@require_control()
async def off(ctx):
    """ปิดระบบควบคุมอัตโนมัติ"""
    try:
        async with await get_session() as session:
            async with session.get(f"http://{ESP32_IP}/command?cmd=off", headers=esp32_headers()) as response:
                if response.status != 200:
                    raise ESP32ConnectionError("ไม่สามารถปิดระบบได้")
                data = await response.json()
        
        status = await get_esp32_status()
        embed = create_embed("🔴 ระบบปิด", data.get('message', 'ระบบปิดเรียบร้อย'), 0xFF0000)
        embed.add_field(name="ความชื้น", value=f"{status['moisture']}%", inline=True)
        embed.add_field(name="ปั๊ม", value="เปิด" if status['pump'] else "ปิด", inline=True)
    except ESP32ConnectionError as e:
        embed = create_embed("⚠️ ผิดพลาด", "ไม่สามารถปิดระบบได้", 0xFF0000)
    await ctx.send(embed=embed)

@bot.command()
async def status(ctx):
    """ตรวจสอบสถานะระบบปัจจุบัน"""
    try:
        status_data = await get_esp32_status()
        embed = create_embed("📊 สถานะระบบ", "ข้อมูลล่าสุด", 0x7289DA)
        embed.add_field(name="เวลา", value=status_data['time'], inline=False)
        embed.add_field(name="ความชื้น", value=f"{status_data['moisture']}%", inline=True)
        embed.add_field(name="ปั๊ม", value="เปิด" if status_data['pump'] else "ปิด", inline=True)
        embed.add_field(name="ระบบ", value="เปิด" if status_data['enabled'] else "ปิด", inline=True)
        embed.add_field(name="WiFi", value="เชื่อมต่อ" if status_data['wifi'] else "ตัดการเชื่อมต่อ", inline=True)
        embed.add_field(name="IP", value=status_data['ip'], inline=True)
        embed.add_field(name="Error", value=status_data.get('last_error', 'None'), inline=False)
    except ESP32ConnectionError as e:
        embed = create_embed("⚠️ ดึงข้อมูลไม่ได้", str(e), 0xFF0000)
    await ctx.send(embed=embed)

@bot.command()
@require_control()
async def pump(ctx, action: str = None):
    """ควบคุมปั๊มด้วยมือ: /pump on หรือ /pump off"""
    if action is None:
        embed = create_embed("❓ วิธีใช้งาน", "ใช้คำสั่ง: `/pump on` หรือ `/pump off`", 0xFFFF00)
        await ctx.send(embed=embed)
        return
    
    if action.lower() not in ['on', 'off']:
        embed = create_embed("⚠️ คำสั่งไม่ถูกต้อง", "ใช้: `/pump on` หรือ `/pump off`", 0xFF0000)
        await ctx.send(embed=embed)
        return
    
    command = f"pump_{action.lower()}"
    try:
        async with await get_session() as session:
            async with session.get(f"http://{ESP32_IP}/command?cmd={command}", headers=esp32_headers()) as response:
                if response.status != 200:
                    raise ESP32ConnectionError("ไม่สามารถควบคุมปั๊มได้")
                data = await response.json()
        
        status = await get_esp32_status()
        embed = create_embed(
            f"{'✅' if action.lower() == 'on' else '🔴'} ปั๊มถูก{action.lower() == 'on' and 'เปิด' or 'ปิด'}",
            data.get('message', f"ปั๊มถูก{action.lower() == 'on' and 'เปิด' or 'ปิด'}แล้ว"),
            0x00FF00 if action.lower() == 'on' else 0xFF0000
        )
        embed.add_field(name="สถานะปั๊ม", value="เปิด" if status['pump'] else "ปิด", inline=True)
        embed.add_field(name="ความชื้น", value=f"{status['moisture']}%", inline=True)
    except ESP32ConnectionError as e:
        embed = create_embed("⚠️ ผิดพลาด", "ไม่สามารถควบคุมปั๊มได้", 0xFF0000)
    await ctx.send(embed=embed)

@bot.command()
@require_control()
async def reboot(ctx):
    """รีสตาร์ท ESP32"""
    try:
        embed = create_embed("🔄 กำลังรีสตาร์ท...", "สั่งรีสตาร์ท ESP32", 0xFFFF00)
        await ctx.send(embed=embed)
        
        async with await get_session() as session:
            async with session.get(f"http://{ESP32_IP}/command?cmd=reboot", timeout=5, headers=esp32_headers()) as response:
                pass  # ไม่ต้องรอ response
        
        await asyncio.sleep(3)
        
        try:
            await asyncio.sleep(30)
            if await check_esp32_connection():
                final_embed = create_embed("✅ กลับมาออนไลน์แล้ว", "ESP32 รีสตาร์ทสำเร็จ", 0x00FF00)
            else:
                final_embed = create_embed("⚠️ ยังไม่ตอบสนอง", "อาจต้องตรวจสอบฮาร์ดแวร์", 0xFF0000)
            await ctx.send(embed=final_embed)
        except:
            pass
            
    except Exception as e:
        embed = create_embed("⚠️ ผิดพลาด", f"ไม่สามารถรีสตาร์ทได้: {str(e)}", 0xFF0000)
        await ctx.send(embed=embed)

@tasks.loop(minutes=HEARTBEAT_INTERVAL)
async def check_esp32_status():
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        logger.error(f"Channel {DISCORD_CHANNEL_ID} ไม่พบ!")
        return

    try:
        status = await get_esp32_status()
        embed = create_embed("💓 สถานะปกติ", "ESP32 ทำงานได้ดี", 0x00FF00)
        embed.add_field(name="ความชื้น", value=f"{status['moisture']}%", inline=True)
        embed.add_field(name="ปั๊ม", value="เปิด" if status['pump'] else "ปิด", inline=True)
        embed.add_field(name="IP", value=status.get('ip', 'N/A'), inline=True)
        embed.add_field(name="Error", value=status.get('last_error', 'None'), inline=False)
        await channel.send(embed=embed)
    except ESP32ConnectionError as e:
        embed = create_embed("⚠️ ESP32 ไม่ตอบสนอง", f"```{str(e)}```", 0xFF0000)
        await channel.send(embed=embed)
        logger.error(f"ESP32 not responding: {e}")

@check_esp32_status.before_loop
async def before_check_status():
    await bot.wait_until_ready()
    logger.info("Heartbeat monitor เริ่มทำงาน")

# เริ่ม Bot
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)