import discord
from discord.ext import commands, tasks
import requests
import asyncio
from datetime import datetime
import os
from dotenv import load_dotenv
import logging

# ตั้งค่า logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()  # โหลด environment variables จากไฟล์ .env

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix='/',
    intents=intents,
    help_command=None
)

# ข้อมูลการตั้งค่า
ESP32_IP = os.getenv('ESP32_IP', "10.70.55.222")  # ใช้จาก environment variable หรือค่าเริ่มต้น
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 1406180111358885928))
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # ต้องตั้งค่าใน .env
HEARTBEAT_INTERVAL = int(os.getenv('HEARTBEAT_INTERVAL', 1))  # นาที

class ESP32ConnectionError(Exception):
    pass

async def check_esp32_connection():
    try:
        response = requests.get(f"http://{ESP32_IP}/ping", timeout=5)
        if response.status_code != 200:
            raise ESP32ConnectionError(f"HTTP Status: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        raise ESP32ConnectionError(f"Connection failed: {str(e)}")

async def send_command_to_esp32(ctx, command):
    try:
        response = requests.get(f"http://{ESP32_IP}/command?cmd={command}", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending command {command}: {str(e)}")
        raise ESP32ConnectionError(f"ไม่สามารถเชื่อมต่อกับ ESP32 ได้: {str(e)}")
    except ValueError as e:
        logger.error(f"JSON decode error for command {command}: {str(e)}")
        raise ESP32ConnectionError("การตอบสนองจาก ESP32 ไม่ถูกต้อง")

async def get_esp32_status():
    try:
        response = requests.get(f"http://{ESP32_IP}/status", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting status: {str(e)}")
        raise ESP32ConnectionError(f"ไม่สามารถดึงสถานะจาก ESP32 ได้: {str(e)}")
    except ValueError as e:
        logger.error(f"JSON decode error for status: {str(e)}")
        raise ESP32ConnectionError("การตอบสนองสถานะจาก ESP32 ไม่ถูกต้อง")

def create_embed(title, description, color):
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
    logger.info(f'Connected to ESP32 at {ESP32_IP}')
    logger.info(f'Monitoring channel ID: {CHANNEL_ID}')
    check_esp32_status.start()

@bot.command()
async def help(ctx):
    """แสดงคำสั่งทั้งหมดที่ใช้งานได้"""
    embed = create_embed("🆘 คำสั่งทั้งหมด", "รายการคำสั่งสำหรับระบบ Smart Farm", 0x7289DA)
    
    commands_list = [
        ("/ping", "ตรวจสอบการเชื่อมต่อกับ ESP32"),
        ("/on", "เปิดระบบควบคุมอัตโนมัติ"),
        ("/off", "ปิดระบบควบคุมอัตโนมัติ"),
        ("/status", "ตรวจสอบสถานะระบบปัจจุบัน"),
        ("/pump on/off", "ควบคุมปั๊มด้วยมือ"),
        ("/setmin [ค่า]", "ตั้งค่าความชื้นขั้นต่ำ"),
        ("/reboot", "รีสตาร์ทระบบ ESP32"),
        ("/test", "ทดสอบระบบพื้นฐาน"),
        ("/help", "แสดงคำสั่งทั้งหมด")
    ]
    
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def ping(ctx):
    """ตรวจสอบการเชื่อมต่อ ESP32"""
    try:
        await check_esp32_connection()
        status_data = await get_esp32_status()
        
        embed = create_embed(
            "✅ ESP32 ตอบสนอง",
            "ระบบ ESP32 เชื่อมต่อปกติและทำงานได้ดี",
            0x00FF00
        )
        
        embed.add_field(name="IP Address", value=status_data.get('ip', 'N/A'), inline=False)
        embed.add_field(name="สถานะ WiFi", value="เชื่อมต่อ" if status_data.get('wifi', False) else "ตัดการเชื่อมต่อ", inline=True)
        embed.add_field(name="ความชื้นดิน", value=f"{status_data.get('moisture', 0)}%", inline=True)
        embed.add_field(name="สถานะระบบ", value="เปิด" if status_data.get('enabled', False) else "ปิด", inline=True)
        
        await ctx.send(embed=embed)
        
    except ESP32ConnectionError as e:
        embed = create_embed(
            "⚠️ ไม่สามารถเชื่อมต่อ ESP32",
            str(e),
            0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def on(ctx):
    """เปิดระบบควบคุมอัตโนมัติ"""
    try:
        data = await send_command_to_esp32(ctx, "on")
        status_data = await get_esp32_status()
        
        embed = create_embed(
            "✅ ระบบถูกเปิดใช้งาน",
            data['message'],
            0x00FF00
        )
        
        embed.add_field(name="ความชื้นดิน", value=f"{status_data['moisture']}%", inline=True)
        embed.add_field(name="สถานะปั๊ม", value="เปิด" if status_data['pump'] else "ปิด", inline=True)
        
        await ctx.send(embed=embed)
        
    except ESP32ConnectionError as e:
        embed = create_embed(
            "⚠️ เกิดข้อผิดพลาด",
            str(e),
            0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def off(ctx):
    """ปิดระบบควบคุมอัตโนมัติ"""
    try:
        data = await send_command_to_esp32(ctx, "off")
        status_data = await get_esp32_status()
        
        embed = create_embed(
            "🔴 ระบบถูกปิดใช้งาน",
            data['message'],
            0xFF0000
        )
        
        embed.add_field(name="ความชื้นดิน", value=f"{status_data['moisture']}%", inline=True)
        embed.add_field(name="สถานะปั๊ม", value="เปิด" if status_data['pump'] else "ปิด", inline=True)
        
        await ctx.send(embed=embed)
        
    except ESP32ConnectionError as e:
        embed = create_embed(
            "⚠️ เกิดข้อผิดพลาด",
            str(e),
            0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def status(ctx):
    """ตรวจสอบสถานะระบบปัจจุบัน"""
    try:
        status_data = await get_esp32_status()
        
        embed = create_embed(
            "📊 สถานะระบบ ESP32",
            "ข้อมูลสถานะปัจจุบันจากระบบ Smart Farm",
            0x7289DA
        )
        
        embed.add_field(name="เวลา", value=status_data['time'], inline=False)
        embed.add_field(name="ความชื้นดิน", value=f"{status_data['moisture']}% ({status_data['moisture_status']})", inline=True)
        embed.add_field(name="สถานะปั๊ม", value="เปิด" if status_data['pump'] else "ปิด", inline=True)
        embed.add_field(name="สถานะระบบ", value="เปิด" if status_data['enabled'] else "ปิด", inline=True)
        embed.add_field(name="WiFi", value="เชื่อมต่อ" if status_data['wifi'] else "ตัดการเชื่อมต่อ", inline=True)
        embed.add_field(name="IP Address", value=status_data['ip'], inline=True)
        embed.add_field(name="Last Error", value=status_data.get('last_error', 'None'), inline=False)
        
        await ctx.send(embed=embed)
        
    except ESP32ConnectionError as e:
        embed = create_embed(
            "⚠️ เกิดข้อผิดพลาด",
            str(e),
            0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def pump(ctx, action: str = None):
    """ควบคุมปั๊มด้วยมือ: /pump on หรือ /pump off"""
    if action is None:
        embed = create_embed(
            "❓ วิธีใช้งาน",
            "ใช้คำสั่ง: `/pump on` หรือ `/pump off`",
            0xFFFF00
        )
        await ctx.send(embed=embed)
        return
    
    if action.lower() not in ['on', 'off']:
        embed = create_embed(
            "⚠️ คำสั่งไม่ถูกต้อง",
            "ใช้คำสั่ง: `/pump on` หรือ `/pump off`",
            0xFF0000
        )
        await ctx.send(embed=embed)
        return
    
    try:
        old_status = await get_esp32_status()
        old_pump_status = old_status.get('pump', False)
        
        command = f"pump_{action.lower()}"
        data = await send_command_to_esp32(ctx, command)
        
        await asyncio.sleep(2)
        
        new_status = await get_esp32_status()
        new_pump_status = new_status.get('pump', False)
        
        if (action.lower() == 'on' and new_pump_status) or (action.lower() == 'off' and not new_pump_status):
            embed = create_embed(
                f"{'✅' if action.lower() == 'on' else '🔴'} ปั๊มถูก{'เปิด' if action.lower() == 'on' else 'ปิด'}",
                data.get('message', f"ปั๊มถูก{action.lower() == 'on' and 'เปิด' or 'ปิด'}ด้วยมือ"),
                0x00FF00 if action.lower() == 'on' else 0xFF0000
            )
        else:
            embed = create_embed(
                "⚠️ คำสั่งไม่สำเร็จ",
                f"ไม่สามารถ{'เปิด' if action.lower() == 'on' else 'ปิด'}ปั๊มได้ โปรดลองใหม่อีกครั้ง",
                0xFF0000
            )
        
        embed.add_field(name="สถานะปั๊ม (ก่อน)", value="เปิด" if old_pump_status else "ปิด", inline=True)
        embed.add_field(name="สถานะปั๊ม (หลัง)", value="เปิด" if new_pump_status else "ปิด", inline=True)
        embed.add_field(name="ความชื้นดิน", value=f"{new_status.get('moisture', 0)}%", inline=True)
        
        await ctx.send(embed=embed)
        
    except ESP32ConnectionError as e:
        embed = create_embed(
            "⚠️ เกิดข้อผิดพลาด",
            str(e),
            0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def setmin(ctx, min_moisture: int = None):
    """ตั้งค่าความชื้นขั้นต่ำ: /setmin 30"""
    if min_moisture is None:
        embed = create_embed(
            "❓ วิธีใช้งาน",
            "ใช้คำสั่ง: `/setmin [ค่าความชื้น]` (เช่น `/setmin 30`)",
            0xFFFF00
        )
        await ctx.send(embed=embed)
        return
    
    if min_moisture < 0 or min_moisture > 100:
        embed = create_embed(
            "⚠️ ค่าไม่ถูกต้อง",
            "ค่าความชื้นต้องอยู่ระหว่าง 0-100%",
            0xFF0000
        )
        await ctx.send(embed=embed)
        return
    
    try:
        command = f"set_min_moisture_{min_moisture}"
        data = await send_command_to_esp32(ctx, command)
        
        embed = create_embed(
            "✅ ตั้งค่าความชื้นขั้นต่ำ",
            f"ตั้งค่าความชื้นขั้นต่ำเป็น {min_moisture}%",
            0x00FF00
        )
        
        embed.add_field(name="ข้อความ", value=data.get('message', 'ตั้งค่าสำเร็จ'), inline=False)
        
        await ctx.send(embed=embed)
        
    except ESP32ConnectionError as e:
        embed = create_embed(
            "⚠️ เกิดข้อผิดพลาด",
            str(e),
            0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def test(ctx):
    """ทดสอบการเชื่อมต่อและฟังก์ชันพื้นฐาน"""
    try:
        embed = create_embed(
            "🧪 กำลังทดสอบระบบ...",
            "กำลังตรวจสอบการเชื่อมต่อและฟังก์ชันต่างๆ",
            0xFFFF00
        )
        test_message = await ctx.send(embed=embed)
        
        connection_test = await check_esp32_connection()
        connection_status = "✅ เชื่อมต่อได้" if connection_test else "❌ ไม่สามารถเชื่อมต่อ"
        
        try:
            status_data = await get_esp32_status()
            status_status = "✅ ดึงข้อมูลได้"
            moisture_value = status_data.get('moisture', 'N/A')
            pump_status = "เปิด" if status_data.get('pump', False) else "ปิด"
        except:
            status_status = "❌ ดึงข้อมูลไม่ได้"
            moisture_value = "N/A"
            pump_status = "N/A"
        
        try:
            response = requests.get(f"http://{ESP32_IP}/ping", timeout=5)
            ping_status = "✅ ตอบสนอง ping" if response.status_code == 200 else f"❌ HTTP {response.status_code}"
        except:
            ping_status = "❌ ไม่ตอบสนอง ping"
        
        final_embed = create_embed(
            "✅ ทดสอบระบบเสร็จสิ้น",
            "ผลการทดสอบระบบ Smart Farm",
            0x00FF00 if connection_test else 0xFF0000
        )
        
        final_embed.add_field(name="การเชื่อมต่อ", value=connection_status, inline=False)
        final_embed.add_field(name="การดึงสถานะ", value=status_status, inline=False)
        final_embed.add_field(name="Ping Test", value=ping_status, inline=False)
        final_embed.add_field(name="ความชื้นปัจจุบัน", value=f"{moisture_value}%", inline=True)
        final_embed.add_field(name="สถานะปั๊ม", value=pump_status, inline=True)
        
        await test_message.edit(embed=final_embed)
        
    except Exception as e:
        embed = create_embed(
            "⚠️ เกิดข้อผิดพลาดในการทดสอบ",
            str(e),
            0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def reboot(ctx):
    """รีสตาร์ทระบบ ESP32"""
    try:
        embed = create_embed(
            "🔄 กำลังรีสตาร์ทระบบ...",
            "กำลังสั่งรีสตาร์ท ESP32 ระบบจะกลับมาใช้งานในอีก 30-60 วินาที",
            0xFFFF00
        )
        await ctx.send(embed=embed)
        
        requests.get(f"http://{ESP32_IP}/command?cmd=reboot", timeout=5)
        await asyncio.sleep(45)
        
        if await check_esp32_connection():
            final_embed = create_embed(
                "✅ ระบบกลับมาทำงานแล้ว",
                "ESP32 รีสตาร์ทสำเร็จและกลับมาใช้งานได้แล้ว",
                0x00FF00
            )
        else:
            final_embed = create_embed(
                "⚠️ ระบบยังไม่ตอบสนอง",
                "ESP32 ยังไม่ตอบสนองหลังจากรีสตาร์ท อาจต้องตรวจสอบฮาร์ดแวร์",
                0xFF0000
            )
        
        await ctx.send(embed=final_embed)
        
    except Exception as e:
        embed = create_embed(
            "⚠️ เกิดข้อผิดพลาด",
            f"ไม่สามารถรีสตาร์ทระบบได้: {str(e)}",
            0xFF0000
        )
        await ctx.send(embed=embed)

@tasks.loop(minutes=HEARTBEAT_INTERVAL)
async def check_esp32_status():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        logger.error(f"Channel {CHANNEL_ID} not found!")
        return
    
    try:
        status_data = await get_esp32_status()
        
        embed = create_embed(
            "💓 ระบบทำงานปกติ",
            "ESP32 ยังคงทำงานตามปกติ",
            0x00FF00
        )
        
        embed.add_field(name="ความชื้นดิน", value=f"{status_data['moisture']}%", inline=True)
        embed.add_field(name="สถานะปั๊ม", value="เปิด" if status_data['pump'] else "ปิด", inline=True)
        embed.add_field(name="IP Address", value=status_data.get('ip', 'N/A'), inline=True)
        embed.add_field(name="Last Error", value=status_data.get('last_error', 'None'), inline=False)
        
        await channel.send(embed=embed)
        
    except ESP32ConnectionError as e:
        embed = create_embed(
            "⚠️ ระบบไม่ตอบสนอง",
            f"ESP32 ไม่ตอบสนองต่อการตรวจสอบ\n{str(e)}",
            0xFF0000
        )
        await channel.send(embed=embed)
        
        try:
            requests.get(f"http://{ESP32_IP}/command?cmd=reboot", timeout=5)
        except:
            pass

@check_esp32_status.before_loop
async def before_check_status():
    await bot.wait_until_ready()
    logger.info("Heartbeat monitor is ready")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("Error: DISCORD_TOKEN not found in environment variables!")
    else:
        bot.run(DISCORD_TOKEN)