from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import MediaStream
import aiohttp
import asyncio
from pyrogram.types import Message, CallbackQuery
import isodate
import os
import re
import time
import psutil
from datetime import timedelta
import uuid
import tempfile
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from io import BytesIO
from pyrogram.enums import ChatType, ChatMemberStatus
from typing import Union
from pytgcalls.types import Update
from pytgcalls import filters as fl
from pytgcalls.types import GroupCallParticipant


# Bot and Assistant session strings 
API_ID = 29385418  # Replace with your actual API ID
API_ID = 29385418  # Replace with your actual API ID
API_HASH = "5737577bcb32ea1aac1ac394b96c4b10"  # Replace with your actual API Hash
BOT_TOKEN = "7598576464:AAHTQqNDdgD_DyzOfo_ET2an0OTLtd-S7io"  # Replace with your bot token
ASSISTANT_SESSION = "BQHAYsoAmaja57XTQO0l0e2gHIGEa0K5Nc2h9tG0mm11PB2kLXxnCvyVaskILpPxdjYabtBAxdjvD0PfsFTpZwC_x3hbJpOz89Xna75yG16UHtNm43S0GeGvhtEwsOt73qAnP_7WyTtAR-gciWFQrQw31uqmwrZ_p4R_6JtrQt616sgzZxb8liEADodDBfwMtcNVMfU2RynyxTg7Dba4qN5h4iTnPNjEv5Fo0-KxjBrd6rmzv4ZE47rEawLFUGPKfiIFCKPXqDHxvq1ro60jz2udFPdRaDYxXeTWtljHXIpN3vm-LGXQXpwRWqvzFUoMpFIcGjetc15GPV3bnUXx9MVmyHjHiwAAAAG4QLY7AA"

bot = Client("music_bot1", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)
assistant = Client("assistant_account", session_string=ASSISTANT_SESSION)
call_py = PyTgCalls(assistant)

ASSISTANT_USERNAME = "@Frozensupporter1"
ASSISTANT_CHAT_ID = 7386215995

# API Endpoints
API_URL = "https://odd-block-a945.tenopno.workers.dev/search?title="
DOWNLOAD_API_URL = "https://frozen-youtube-api-search-link-ksog.onrender.com/download?url="

# Containers for song queues per chat/group
chat_containers = {}
playback_tasks = {}  # To manage playback tasks per chat
bot_start_time = time.time()
COOLDOWN = 10
chat_last_command = {}
chat_pending_commands = {}
QUEUE_LIMIT = 5
FILE_AGE_THRESHOLD = 7800 
MAX_DURATION_SECONDS = 2 * 60 * 60 # 2 hours 10 minutes (in seconds)


async def process_pending_command(chat_id, delay):
    await asyncio.sleep(delay)  # Wait for the cooldown period to expire
    if chat_id in chat_pending_commands:
        message, cooldown_reply = chat_pending_commands.pop(chat_id)
        await cooldown_reply.delete()  # Delete the cooldown notification
        await play_handler(bot, message)  # Use `bot` instead of `app`


async def periodic_auto_cleaner():
    """Periodically deletes old downloaded audio files."""
    while True:
        try:
            for chat_id in list(chat_containers.keys()):
                for song in chat_containers[chat_id][:]:  # Copy list to avoid modification errors
                    file_path = song.get('file_path', '')
                    if file_path and os.path.exists(file_path):
                        file_mtime = os.stat(file_path).st_mtime  # Get last modified time
                        if time.time() - file_mtime > FILE_AGE_THRESHOLD:
                            try:
                                os.remove(file_path)
                                print(f"Auto-cleaner: Deleted {file_path}")
                            except Exception as e:
                                print(f"Auto-cleaner: Failed to delete {file_path}: {e}")
                            chat_containers[chat_id].remove(song)  # Remove from queue

                # Remove empty chat queues
                if not chat_containers[chat_id]:
                    chat_containers.pop(chat_id)

        except Exception as e:
            print(f"Auto-cleaner encountered an error: {e}")

        await asyncio.sleep(600)  # Sleep for 10 minutes before checking again

async def extract_invite_link(client, chat_id):
    try:
        chat_info = await client.get_chat(chat_id)
        if chat_info.invite_link:
            return chat_info.invite_link
        else:
            return f"https://t.me/{chat_info.username}" if chat_info.username else None
    except Exception as e:
        print(f"Error extracting invite link: {e}")
        return None

async def is_assistant_in_chat(chat_id):
    try:
        member = await assistant.get_chat_member(chat_id, ASSISTANT_USERNAME)
        return member.status is not None
    except Exception as e:
        error_message = str(e)
        if "USER_BANNED" in error_message or "Banned" in error_message:
            return "banned"
        elif "USER_NOT_PARTICIPANT" in error_message or "Chat not found" in error_message:
            return False
        print(f"Error checking assistant in chat: {e}")
        return False

def iso8601_to_human_readable(iso_duration):
    try:
        duration = isodate.parse_duration(iso_duration)
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}:{minutes:02}:{seconds:02}"
        return f"{minutes}:{seconds:02}"
    except Exception as e:
        return "Unknown duration"

async def fetch_youtube_link(query):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}{query}") as response:
                if response.status == 200:
                    data = await response.json()
                    return (
                        data.get("link"),
                        data.get("title"),
                        data.get("duration"),
                        data.get("thumbnail")  # Add this line to return the thumbnail URL
                    )
                else:
                    raise Exception(f"API returned status code {response.status}")
    except Exception as e:
        raise Exception(f"Failed to fetch YouTube link: {str(e)}")
    


async def add_watermark_to_thumbnail(thumbnail_url, watermark_text="ᴘᴏᴡᴇʀᴇᴅ ʙʏ ғʀᴏᴢᴇɴ ʙᴏᴛs"):
    try:
        # Fetch the thumbnail image
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail_url) as response:
                if response.status != 200:
                    raise Exception("Failed to fetch thumbnail image.")
                image_data = await response.read()

        # Open the image using Pillow
        image = Image.open(BytesIO(image_data)).convert("RGBA")

        # Create a drawing context
        draw = ImageDraw.Draw(image)

        # Load a font (ensure this font file is available or replace it with one that exists on your system)
        font = ImageFont.truetype("arial.ttf", size=28)  # Adjust font size if needed

        # Calculate text size and position
        text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        x = 20  # Padding of 20px from the left
        y = image.height - text_height - 20  # Padding of 20px from the bottom

        # Create a solid black rectangle behind the text for better visibility
        rect_x1 = x - 5
        rect_y1 = y - 5
        rect_x2 = x + text_width + 5
        rect_y2 = y + text_height + 5
        draw.rectangle([rect_x1, rect_y1, rect_x2, rect_y2], fill=(0, 0, 0, 255))  # Solid black

        # Add the neon-colored, bold text watermark
        neon_color = (57, 255, 20)  # Neon green
        draw.text((x, y), watermark_text, font=font, fill=neon_color)

        # Save the watermarked image to an in-memory buffer
        output_buffer = BytesIO()
        image.save(output_buffer, format="PNG")
        output_buffer.seek(0)
        return output_buffer

    except Exception as e:
        raise Exception(f"Error adding watermark: {str(e)}")

async def skip_to_next_song(chat_id, message):
    """Skips to the next song in the queue and starts playback."""
    if chat_id not in chat_containers or not chat_containers[chat_id]:
        await message.edit("❌ No more songs in the queue.")
        await leave_voice_chat(chat_id)
        return


    await message.edit("⏭ Skipping to the next song...")
    await start_playback_task(chat_id, message)
    
async def is_user_admin(obj: Union[Message, CallbackQuery]) -> bool:
    if isinstance(obj, CallbackQuery):
        message = obj.message
        user = obj.from_user
    elif isinstance(obj, Message):
        message = obj
        user = obj.from_user
    else:
        return False

    if not user:
        return False

    if message.chat.type not in [ChatType.SUPERGROUP, ChatType.CHANNEL]:
        return False

    if user.id in [
        777000,  # Telegram Service Notifications
        7856124770,  # GroupwcgbrandedBot
    ]:
        return True

    client = message._client
    chat_id = message.chat.id
    user_id = user.id

    check_status = await client.get_chat_member(chat_id=chat_id, user_id=user_id)
    if check_status.status not in [
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR
    ]:
        return False
    else:
        return True



@bot.on_message(filters.command("start"))
async def start_handler(_, message):
    # Calculate uptime
    current_time = time.time()
    uptime_seconds = int(current_time - bot_start_time)
    uptime_str = str(timedelta(seconds=uptime_seconds))

    # Mention the user
    user_mention = message.from_user.mention

    # Caption with bot info and uptime
    caption = (
        f"👋 нєу {user_mention} 💠, 🥀\n\n"
        "🎶 Wᴇʟᴄᴏᴍᴇ ᴛᴏ Fʀᴏᴢᴇɴ 🥀 ᴍᴜsɪᴄ! 🎵\n\n"
        "➻ 🚀 A Sᴜᴘᴇʀғᴀsᴛ & Pᴏᴡᴇʀғᴜʟ Tᴇʟᴇɢʀᴀᴍ Mᴜsɪᴄ Bᴏᴛ ᴡɪᴛʜ ᴀᴍᴀᴢɪɴɢ ғᴇᴀᴛᴜʀᴇs. ✨\n\n"
        "🎧 Sᴜᴘᴘᴏʀᴛᴇᴅ Pʟᴀᴛғᴏʀᴍs: ʏᴏᴜᴛᴜʙᴇ, sᴘᴏᴛɪғʏ, ʀᴇssᴏ, ᴀᴘᴘʟᴇ ᴍᴜsɪᴄ, sᴏᴜɴᴅᴄʟᴏᴜᴅ.\n\n"
        "🔹 Kᴇʏ Fᴇᴀᴛᴜʀᴇs:\n"
        "🎵 Playlist Support for your favorite tracks.\n"
        "🤖 AI Chat for engaging conversations.\n"
        "🖼️ Image Generation with AI creativity.\n"
        "👥 Group Management tools for admins.\n"
        "💡 And many more exciting features!\n\n"
        f"**Uptime:** `{uptime_str}`\n\n"
        "──────────────────\n"
        "๏ ᴄʟɪᴄᴋ ᴛʜᴇ ʜᴇʟᴘ ʙᴜᴛᴛᴏɴ ғᴏʀ ᴍᴏᴅᴜʟᴇ ᴀɴᴅ ᴄᴏᴍᴍᴀɴᴅ ɪɴғᴏ.."
    )

    # Buttons
    buttons = [
        [InlineKeyboardButton("➕ Add me ", url="https://t.me/vcmusiclubot?startgroup=true"),
         InlineKeyboardButton("💬 Support", url="https://t.me/Frozensupport1")],
        [InlineKeyboardButton("❓ Help", callback_data="show_help")]
    ]

    reply_markup = InlineKeyboardMarkup(buttons)

    # Send the image with the caption and buttons
    await message.reply_photo(
        photo="https://files.catbox.moe/4o3ied.jpg",
        caption=caption,
        reply_markup=reply_markup
    )

@bot.on_callback_query(filters.regex("show_help"))
async def show_help_callback(_, callback_query):
    help_text = (
        "Here are the commands you can use:\n\n"
        "✨/play <song name> - Play a song\n"
        "✨/stop - Stop the music\n"
        "✨/pause - Pause the music\n"
        "✨/resume - Resume the music\n"
        "✨/skip - Skip the current song\n"
        "✨/reboot - Reboot the bot\n"
        "✨/ping - Show bot status and uptime\n"
        "✨/clear - Clear the queue\n"
    )

    # Buttons including the "Back" button
    buttons = [
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴇ 💕", url="https://t.me/vcmusiclubot?startgroup=true"),
         InlineKeyboardButton("💬 ғʀᴏᴢᴇɴ sᴜᴘᴘᴏʀᴛ ❄️", url="https://t.me/Frozensupport1")],
        [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 💕", callback_data="go_back")]
    ]

    reply_markup = InlineKeyboardMarkup(buttons)

    await callback_query.message.edit_text(help_text, reply_markup=reply_markup)

@bot.on_callback_query(filters.regex("go_back"))
async def go_back_callback(_, callback_query):
    # Calculate uptime
    current_time = time.time()
    uptime_seconds = int(current_time - bot_start_time)
    uptime_str = str(timedelta(seconds=uptime_seconds))

    # Mention the user
    user_mention = callback_query.from_user.mention

    # Caption with bot info and uptime
    caption = (
        f"👋 нєу {user_mention} 💠, 🥀\n\n"
        "🎶 Wᴇʟᴄᴏᴍᴇ ᴛᴏ Fʀᴏᴢᴇɴ 🥀 ᴍᴜsɪᴄ! 🎵\n\n"
        "➻ 🚀 A Sᴜᴘᴇʀғᴀsᴛ & Pᴏᴡᴇʀғᴜʟ Tᴇʟᴇɢʀᴀᴍ Mᴜsɪᴄ Bᴏᴛ ᴡɪᴛʜ ᴀᴍᴀᴢɪɴɢ ғᴇᴀᴛᴜʀᴇs. ✨\n\n"
        "🎧 Sᴜᴘᴘᴏʀᴛᴇᴅ Pʟᴀᴛғᴏʀᴍs: ʏᴏᴜᴛᴜʙᴇ, sᴘᴏᴛɪғʏ, ʀᴇssᴏ, ᴀᴘᴘʟᴇ ᴍᴜsɪᴄ, sᴏᴜɴᴅᴄʟᴏᴜᴅ.\n\n"
        "🔹 Kᴇʏ Fᴇᴀᴛᴜʀᴇs:\n"
        "🎵 Playlist Support for your favorite tracks.\n"
        "🤖 AI Chat for engaging conversations.\n"
        "🖼️ Image Generation with AI creativity.\n"
        "👥 Group Management tools for admins.\n"
        "💡 And many more exciting features!\n\n"
        f"**Uptime:** `{uptime_str}`\n\n"
        "──────────────────\n"
        "๏ ᴄʟɪᴄᴋ ᴛʜᴇ ʜᴇʟᴘ ʙᴜᴛᴛᴏɴ ғᴏʀ ᴍᴏᴅᴜʟᴇ ᴀɴᴅ ᴄᴏᴍᴍᴀɴᴅ ɪɴғᴏ.."
    )

    # Buttons
    buttons = [
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴇ 💕", url="https://t.me/vcmusiclubot?startgroup=true"),
         InlineKeyboardButton("💬 ғʀᴏᴢᴇɴ sᴜᴘᴘᴏʀᴛ ❄️", url="https://t.me/Frozensupport1")],
        [InlineKeyboardButton("❓ ʜᴇʟᴘ", callback_data="show_help")]
    ]

    reply_markup = InlineKeyboardMarkup(buttons)

    await callback_query.message.edit_media(
        media=InputMediaPhoto(media="https://files.catbox.moe/4o3ied.jpg", caption=caption),
        reply_markup=reply_markup
    )

@bot.on_message(filters.group & filters.regex(r'^/play(?: (?P<query>.+))?$'))
async def play_handler(_, message):
    chat_id = message.chat.id
    now = time.time()
    
    # Check if this chat is within the cooldown period.
    if chat_id in chat_last_command and (now - chat_last_command[chat_id]) < COOLDOWN:
        remaining = int(COOLDOWN - (now - chat_last_command[chat_id]))
        # If a pending command already exists, just notify the chat.
        if chat_id in chat_pending_commands:
            await message.reply(f"⏳ A command is already queued for this chat. Please wait {remaining} more second(s).")
            return
        else:
            # Send the cooldown reply and store both the user's message and the reply.
            cooldown_reply = await message.reply(f"⏳ This chat is on cooldown. Your command will be processed in {remaining} second(s).")
            chat_pending_commands[chat_id] = (message, cooldown_reply)
            # Schedule the pending command to be processed after the remaining delay.
            asyncio.create_task(process_pending_command(chat_id, remaining))
            return
    else:
        # Update the last command time for this chat.
        chat_last_command[chat_id] = now

    query = message.matches[0]['query']
    if not query:
        await message.reply("❓ Please provide a song name.\nExample: /play Shape of You")
        return

    await process_play_command(message, query)


async def process_play_command(message, query):
    chat_id = message.chat.id

    # Check if the chat already has an active voice chat.
    # We assume call_py.group_call returns a truthy value if a voice chat is active.

    processing_message = await message.reply("❄️")
    
    # --- Convert youtu.be links to full YouTube URLs ---
    if "youtu.be" in query:
        m = re.search(r"youtu\.be/([^?&]+)", query)
        if m:
            video_id = m.group(1)
            query = f"https://www.youtube.com/watch?v={video_id}"
    # --- End URL conversion ---

    # 🔍 Check if the assistant is already in the chat
    is_in_chat = await is_assistant_in_chat(chat_id)
    print(f"Assistant in chat: {is_in_chat}")  # Debugging

    if not is_in_chat:
        invite_link = await extract_invite_link(bot, chat_id)
        if invite_link:
            await bot.send_message(ASSISTANT_CHAT_ID, f"/join {invite_link}")
            await processing_message.edit("⏳ Assistant is joining... Please wait.")
            for _ in range(10):  # Retry for 10 seconds
                await asyncio.sleep(3)
                is_in_chat = await is_assistant_in_chat(chat_id)
                print(f"Retry checking assistant in chat: {is_in_chat}")  # Debugging
                if is_in_chat:
                    await processing_message.edit("✅ Assistant joined! Playing your song...")
                    break
            else:
                await processing_message.edit(
                    "❌ Assistant failed to join. Please unban assistant \n"
                    "assistant username - @Frozensupporter1\n"
                    "assistant id - 7386215995 \n"
                    "support - @frozensupport1"
                )
                return
        else:
            await processing_message.edit(
                "❌ Please give bot invite link permission\n\n support - @frozensupport1"
            )
            return

    try:
        video_url, video_title, video_duration, thumbnail_url = await fetch_youtube_link(query)
        if not video_url:
            await processing_message.edit(
                "❌ Could not find the song. Try another query. \n\n support - @frozensupport1"
            )
            return

        duration_seconds = isodate.parse_duration(video_duration).total_seconds()
        if duration_seconds > MAX_DURATION_SECONDS:
            await processing_message.edit("❌ Streams longer than 2 hours are not allowed on Frozen Music.")
            return

        readable_duration = iso8601_to_human_readable(video_duration)
        try:
            watermarked_thumbnail = await add_watermark_to_thumbnail(thumbnail_url)
        except Exception as e:
            await processing_message.edit(
                f"❌ Error processing thumbnail: {str(e)}\n\n support - @frozensupport1"
            )
            return

        if chat_id in chat_containers and len(chat_containers[chat_id]) >= QUEUE_LIMIT:
            await processing_message.edit("❌ The queue is full (limit 5). Please wait until some songs finish playing or clear the queue.")
            return

        if chat_id not in chat_containers:
            chat_containers[chat_id] = []

        chat_containers[chat_id].append({
            "url": video_url,
            "title": video_title,
            "duration": readable_duration,
            "duration_seconds": duration_seconds,
            "requester": message.from_user.first_name if message.from_user else "Unknown",
            "thumbnail": watermarked_thumbnail
        })

        if len(chat_containers[chat_id]) == 1:
            await start_playback_task(chat_id, processing_message)
        else:
            control_buttons = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("⏭ Skip", callback_data="skip"),
                        InlineKeyboardButton("🗑 Clear", callback_data="clear")
                    ]
                ]
            )
            await message.reply_photo(
                photo=watermarked_thumbnail,
                caption=(
                    f"✨ ᴀᴅᴅᴇᴅ ᴛᴏ ǫᴜᴇᴜᴇ:\n\n"
                    f"✨**Title:** {video_title}\n"
                    f"✨**Duration:** {readable_duration}\n"
                    f"✨**Requested by:** {message.from_user.first_name if message.from_user else 'Unknown'}\n"
                    f"✨**Queue number:** {len(chat_containers[chat_id]) - 1}\n"
                ),
                reply_markup=control_buttons
            )
            await processing_message.delete()
    except Exception as e:
        await processing_message.edit(f"❌ Error: {str(e)}")


async def start_playback_task(chat_id, message):
    """Starts a playback task for the given chat."""
    if chat_id in playback_tasks:
        playback_tasks[chat_id].cancel()  # Cancel the existing task if any

    if chat_id in chat_containers and chat_containers[chat_id]:
        song_info = chat_containers[chat_id][0]  # Get the first song in the queue

        video_url = song_info.get('url')
        if not video_url:
            print(f"Invalid video URL for song: {song_info}")
            chat_containers[chat_id].pop(0)
            return

        try:
            try:
                await message.edit(
                    f"✨ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ... \n\n{song_info['title']}\n\n ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ 💕",
                )
            except Exception as edit_error:
                print(f"Error editing message: {edit_error}")
                message = await bot.send_message(chat_id, f"✨ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ... \n\n{song_info['title']}\n\n ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ 💕")

            media_path = await download_audio(video_url)

            await call_py.play(
                chat_id,
                MediaStream(
                    media_path,
                    video_flags=MediaStream.Flags.IGNORE,
                ),
            )

            control_buttons = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("▶️ Pause", callback_data="pause"),
                        InlineKeyboardButton("⏸ Resume", callback_data="resume"),
                    ],
                    [
                        InlineKeyboardButton("⏭ Skip", callback_data="skip"),
                        InlineKeyboardButton("⏹ Stop", callback_data="stop"),
                    ],
                ]
            )

            await message.reply_photo(
                photo=song_info['thumbnail'],
                caption=(
                    f"✨ **ɴᴏᴡ ᴘʟᴀʏɪɴɢ**\n\n"
                    f"✨**Title:** {song_info['title']}\n\n"
                    f"✨**Duration:** {song_info['duration']}\n\n"
                    f"✨**Requested by:** {song_info['requester']}"
                ),
                reply_markup=control_buttons,
            )
            await message.delete()

        except Exception as playback_error:
            print(f"Error during playback: {playback_error}")
            await message.reply(
                f"❌ Playback error for **{song_info['title']}**. Skipping to the next song...\n\n support - @frozensupport1",
            )
            chat_containers[chat_id].pop(0)
            await start_playback_task(chat_id, message)

@call_py.on_update(fl.stream_end)
async def stream_end_handler(_: PyTgCalls, update: Update):
    chat_id = update.chat_id
    if chat_id in chat_containers and chat_containers[chat_id]:
        skipped_song = chat_containers[chat_id].pop(0)
        await asyncio.sleep(3)  # Delay to ensure the stream has ended
        try:
            os.remove(skipped_song.get('file_path', ''))
        except Exception as e:
            print(f"Error deleting file: {e}")

        if chat_id in chat_containers and chat_containers[chat_id]:
            await start_playback_task(chat_id, None)  # Start the next song
        else:
            await bot.send_message(chat_id, "❌ No more songs in the queue.\n Leaving the voice chat.💕\n\n support - @frozensupport1")
            await leave_voice_chat(chat_id)  # Leave the voice chat

async def leave_voice_chat(chat_id):
    try:
        await call_py.leave_call(chat_id)
    except Exception as e:
        print(f"Error leaving the voice chat: {e}")

    if chat_id in chat_containers:
        for song in chat_containers[chat_id]:
            try:
                os.remove(song.get('file_path', ''))
            except Exception as e:
                print(f"Error deleting file: {e}")
        chat_containers.pop(chat_id)

    if chat_id in playback_tasks:
        playback_tasks[chat_id].cancel()
        del playback_tasks[chat_id]

# Add a callback query handler to handle button presses

@bot.on_callback_query()
async def callback_query_handler(client, callback_query):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id

    # Check if the user is an admin; if not, notify and exit.
    if not await is_user_admin(callback_query):
        await callback_query.answer("❌ You need to be an admin to use this button.", show_alert=True)
        return

    data = callback_query.data

    if data == "pause":
        await call_py.pause_stream(chat_id)
        await callback_query.answer("⏸ Playback paused.")

    elif data == "resume":
        await call_py.resume_stream(chat_id)
        await callback_query.answer("▶️ Playback resumed.")

    elif data == "skip":
        if chat_id in chat_containers and chat_containers[chat_id]:
            skipped_song = chat_containers[chat_id].pop(0)
            await call_py.leave_call(chat_id)
            await asyncio.sleep(3)
            try:
                os.remove(skipped_song.get('file_path', ''))
            except Exception as e:
                print(f"Error deleting file: {e}")

            if chat_id in chat_containers and chat_containers[chat_id]:
                await callback_query.answer("⏩ Skipped! Playing the next song...")
                await skip_to_next_song(chat_id, callback_query.message)
            else:
                await callback_query.answer("⏩ Skipped! No more songs in the queue.")
        else:
            await callback_query.answer("❌ No songs in the queue to skip.")

    elif data == "clear":
        if chat_id in chat_containers:
            # Clear the chat-specific queue by deleting each song's file.
            for song in chat_containers[chat_id]:
                try:
                    os.remove(song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file: {e}")

            # Remove the queue from the container.
            chat_containers.pop(chat_id)
            # Optionally, you can edit the message or send an answer to confirm.
            await callback_query.message.edit("🗑️ Cleared the queue.")
            await callback_query.answer("🗑️ Cleared the queue.")
        else:
            await callback_query.answer("❌ No songs in the queue to clear.", show_alert=True)

    elif data == "stop":
        if chat_id in chat_containers:
            chat_containers[chat_id].clear()
        await call_py.leave_call(chat_id)
        await callback_query.answer("🛑 Playback stopped and queue cleared.")



download_cache = {}  # Global cache dictionary

async def download_audio(url):
    """Downloads the audio from a given URL and returns the file path.
    Uses caching to avoid re-downloading the same file.
    """
    # Return the cached file path if it exists
    if url in download_cache:
        return download_cache[url]

    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        file_name = temp_file.name
        download_url = f"{DOWNLOAD_API_URL}{url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as response:
                if response.status == 200:
                    with open(file_name, 'wb') as f:
                        f.write(await response.read())
                    # Cache the file path for this URL
                    download_cache[url] = file_name
                    return file_name
                else:
                    raise Exception(f"Failed to download audio. HTTP status: {response.status}")
    except Exception as e:
        raise Exception(f"Error downloading audio: {e}")
    


@bot.on_message(filters.group & filters.command(["stop", "end"]))
async def skip_handler(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await is_user_admin(message):
        await message.reply("❌ You need to be an admin to use this command.")
        return

    try:
        await call_py.leave_call(chat_id)
    except Exception as e:
        if "not in a call" in str(e).lower():
            await message.reply("❌ The bot is not currently in a voice chat.")
        else:
            await message.reply(f"❌ An error occurred while leaving the voice chat: {str(e)}\n\n support - @frozensupport1")
        return

    if chat_id in chat_containers:
        for song in chat_containers[chat_id]:
            try:
                os.remove(song.get('file_path', ''))
            except Exception as e:
                print(f"Error deleting file: {e}")
        chat_containers.pop(chat_id)

    if chat_id in playback_tasks:
        playback_tasks[chat_id].cancel()
        del playback_tasks[chat_id]

    await message.reply("⏹ Stopped the music and cleared the queue.")

@bot.on_message(filters.group & filters.command("pause"))
async def skip_handler(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await is_user_admin(message):
        await message.reply("❌ You need to be an admin to use this command.")
        return

    try:
        await call_py.pause_stream(chat_id)
        await message.reply("⏸ Paused the stream.")
    except Exception as e:
        await message.reply(f"❌ Failed to pause the stream. Error: {str(e)}\n\n support - @frozensupport1 ")

@bot.on_message(filters.group & filters.command("resume"))
async def skip_handler(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await is_user_admin(message):
        await message.reply("❌ You need to be an admin to use this command.")
        return

    try:
        await call_py.resume_stream(chat_id)
        await message.reply("▶️ Resumed the stream.")
    except Exception as e:
        await message.reply(f"❌ Failed to resume the stream. Error: {str(e)}\n\n support - @frozensupport1")

@bot.on_message(filters.group & filters.command("skip"))
async def skip_handler(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await is_user_admin(message):
        await message.reply("❌ You need to be an admin to use this command.")
        return

    await_message = await message.reply("⏩ Skipping the current song...")

    if chat_id not in chat_containers or not chat_containers[chat_id]:
        await await_message.edit("❌ No songs in the queue to skip.")
        return

    skipped_song = chat_containers[chat_id].pop(0)
    await call_py.leave_call(chat_id)
    await asyncio.sleep(3)

    try:
        os.remove(skipped_song.get('file_path', ''))
    except Exception as e:
        print(f"Error deleting file: {e}")

    if not chat_containers[chat_id]:
        await await_message.edit(f"⏩ Skipped **{skipped_song['title']}**.\n\n❌ No more songs in the queue.")
    else:
        await await_message.edit(f"⏩ Skipped **{skipped_song['title']}**.\n\n💕 Playing the next song...")
        await skip_to_next_song(chat_id, await_message)


@bot.on_message(filters.command("reboot"))
async def reboot_handler(_, message):
    chat_id = message.chat.id

    try:
        if chat_id in chat_containers:
            for song in chat_containers[chat_id]:
                try:
                    os.remove(song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file: {e}")
            await call_py.leave_call(chat_id)

            # Remove stored audio files for each song in the queue
            for song in chat_containers[chat_id]:
                try:
                    os.remove(song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file: {e}")

            # Clear the queue for this chat
            chat_containers.pop(chat_id, None)

            # Cancel the playback task if it exists
            if chat_id in playback_tasks:
                playback_tasks[chat_id].cancel()
                del playback_tasks[chat_id]

            await message.reply("♻️ Rebooted for this chat and queue is cleared.")
        else:
            await message.reply("❌ No active queue to clear in this chat.")
    except Exception as e:
        await message.reply(f"❌ Failed to reboot. Error: {str(e)}\n\n support - @frozensupport1")

@bot.on_message(filters.command("ping"))
async def ping_handler(_, message):
    try:
        # Calculate uptime
        current_time = time.time()
        uptime_seconds = int(current_time - bot_start_time)
        uptime_str = str(timedelta(seconds=uptime_seconds))

        # Get system stats
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        ram_usage = f"{memory.used // (1024 ** 2)}MB / {memory.total // (1024 ** 2)}MB ({memory.percent}%)"
        disk = psutil.disk_usage('/')
        disk_usage = f"{disk.used // (1024 ** 3)}GB / {disk.total // (1024 ** 3)}GB ({disk.percent}%)"

        # Create response message
        response = (
            f"🏓 **Pong!**\n\n"
            f"**Uptime:** `{uptime_str}`\n"
            f"**CPU Usage:** `{cpu_usage}%`\n"
            f"**RAM Usage:** `{ram_usage}`\n"
            f"**Disk Usage:** `{disk_usage}`\n"
        )

        await message.reply(response)
    except Exception as e:
        await message.reply(f"❌ Failed to execute the command. Error: {str(e)}\n\n support - @frozensupport1")

@bot.on_message(filters.group & filters.command("clear"))
async def clear_handler(_, message):
    chat_id = message.chat.id

    if chat_id in chat_containers:
        # Clear the chat-specific queue
        for song in chat_containers[chat_id]:
            try:
                os.remove(song.get('file_path', ''))
            except Exception as e:
                print(f"Error deleting file: {e}")
        
        chat_containers.pop(chat_id)
        await message.reply("🗑️ Cleared the queue.")
    else:
        await message.reply("❌ No songs in the queue to clear.")

@assistant.on_message(filters.command(["join"], "/"))
async def join(client: Client, message: Message):
    input_text = message.text.split(" ", 1)[1] if len(message.text.split()) > 1 else None
    processing_msg = await message.reply_text("`Processing...`")

    if not input_text:
        await processing_msg.edit("❌ Please provide a valid group/channel link or username.")
        return

    # Validate and process the input
    if re.match(r"https://t\.me/[\w_]+/?", input_text):
        input_text = input_text.split("https://t.me/")[1].strip("/")
    elif input_text.startswith("@"):
        input_text = input_text[1:]

    try:
        # Attempt to join the group/channel
        await client.join_chat(input_text)
        await processing_msg.edit(f"**Successfully Joined Group/Channel:** `{input_text}`")
    except Exception as error:
        error_message = str(error)
        if "USERNAME_INVALID" in error_message:
            await processing_msg.edit("❌ ERROR: Invalid username or link. Please check and try again.")
        elif "INVITE_HASH_INVALID" in error_message:
            await processing_msg.edit("❌ ERROR: Invalid invite link. Please verify and try again.")
        elif "USER_ALREADY_PARTICIPANT" in error_message:
            await processing_msg.edit(f"✅ You are already a member of `{input_text}`.")
        else:
            await processing_msg.edit(f"**ERROR:** \n\n{error_message}")

@bot.on_message(filters.video_chat_ended)
async def clear_queue_on_vc_end(_, message: Message):
    chat_id = message.chat.id

    if chat_id in chat_containers:
        # Clear queue files
        for song in chat_containers[chat_id]:
            try:
                os.remove(song.get('file_path', ''))
            except Exception as e:
                print(f"Error deleting file: {e}")

        chat_containers.pop(chat_id)  # Remove queue data
        await message.reply("**😕ᴠɪᴅᴇᴏ ᴄʜᴀᴛ ᴇɴᴅᴇᴅ💔**\n ✨Queue has been cleared.")
    else:
        await message.reply("**😕ᴠɪᴅᴇᴏ ᴄʜᴀᴛ ᴇɴᴅᴇᴅ💔** \n ❌No active queue to clear.")

@bot.on_message(filters.video_chat_started)
async def brah(_, msg):
    await msg.reply("**😍ᴠɪᴅᴇᴏ ᴄʜᴀᴛ sᴛᴀʀᴛᴇᴅ🥳**")




if __name__ == "__main__":
    try:
        call_py.start()
        bot.start()
        if not assistant.is_connected:
            assistant.start()
            asyncio.create_task(periodic_auto_cleaner())
        idle()
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        bot.stop()
        assistant.stop()
        call_py.stop()

