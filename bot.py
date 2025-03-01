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
from io import BytesIO
from pyrogram.enums import ChatType, ChatMemberStatus
from typing import Union
from pytgcalls.types import Update
from pytgcalls import filters as fl
from pytgcalls.types import GroupCallParticipant
import requests
import urllib.parse
from flask import Flask
from flask import request
from threading import Thread
from dotenv import load_dotenv
import json    # Required for persisting the download cache
import sys 
from http.server import HTTPServer, BaseHTTPRequestHandler 
import threading
import subprocess
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()


API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ASSISTANT_SESSION = os.environ.get("ASSISTANT_SESSION")
OWNER_ID = 5268762773

session_name = os.environ.get("SESSION_NAME", "music_bot1")
bot = Client(session_name, bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)
assistant = Client("assistant_account", session_string=ASSISTANT_SESSION)
call_py = PyTgCalls(assistant)

ASSISTANT_USERNAME = "@Frozensupporter1"
ASSISTANT_CHAT_ID = 7386215995
API_ASSISTANT_USERNAME = "@Frozensupporter1"

# API Endpoints
API_URL = os.environ.get("API_URL")
DOWNLOAD_API_URL = os.environ.get("DOWNLOAD_API_URL")



# Use an environment variable for the MongoDB URI
mongo_uri = os.environ.get("MONGO_URI", "mongodb+srv://frozenbotss:frozenbots@cluster0.s0tak.mongodb.net/?retryWrites=true&w=majority")
mongo_client = MongoClient(mongo_uri)
db = mongo_client["music_bot"]
playlist_collection = db["playlists"]
bots_collection = db["bots"]


# Containers for song queues per chat/group
chat_containers = {}
playback_tasks = {}  # To manage playback tasks per chat
bot_start_time = time.time()
COOLDOWN = 10
chat_last_command = {}
chat_pending_commands = {}
QUEUE_LIMIT = 5
MAX_DURATION_SECONDS = 2 * 60 * 60 # 2 hours 10 minutes (in seconds)
LOCAL_VC_LIMIT = 3
api_playback_records = []
playback_mode = {}
# Global dictionaries for the new feature
last_played_song = {}    # Maps chat_id to the info of the last played song
last_suggestions = {}    # Maps chat_id to the list of suggestion objects

# Stores "local" or "api" for each chat


async def process_pending_command(chat_id, delay):
    await asyncio.sleep(delay)  # Wait for the cooldown period to expire
    if chat_id in chat_pending_commands:
        message, cooldown_reply = chat_pending_commands.pop(chat_id)
        await cooldown_reply.delete()  # Delete the cooldown notification
        await play_handler(bot, message) # Use `bot` instead of `app`


async def show_suggestions(chat_id, last_song_url, status_message=None):
    try:
        suggestions_api = f"https://odd-block-a945.tenopno.workers.dev/related?input={urllib.parse.quote(last_song_url)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(suggestions_api) as resp:
                if resp.status != 200:
                    error_text = f"Suggestions API returned status {resp.status} for chat {chat_id} using URL: {last_song_url}"
                    print(error_text)
                    await bot.send_message(5268762773, error_text)
                    if status_message:
                        try:
                            await status_message.edit("❌ Failed to fetch suggestions from the API.")
                        except Exception as e:
                            print("Error editing status message:", e)
                            await bot.send_message(chat_id, "❌ Failed to fetch suggestions from the API.")
                    else:
                        await bot.send_message(chat_id, "❌ Failed to fetch suggestions from the API.")
                    return
                data = await resp.json()
                suggestions = data.get("suggestions", [])
                if not suggestions:
                    error_text = "No suggestions returned from API."
                    print(error_text)
                    await bot.send_message(5268762773, f"Suggestions API error in chat {chat_id}: {error_text}")
                    if status_message:
                        try:
                            await status_message.edit("❌ No suggestions available from the API.")
                        except Exception as e:
                            print("Error editing status message:", e)
                            await bot.send_message(chat_id, "❌ No suggestions available from the API.")
                    else:
                        await bot.send_message(chat_id, "❌ No suggestions available from the API.")
                    return
                # Save suggestions for later use in callback queries.
                last_suggestions[chat_id] = suggestions
                # Build inline buttons with callback data "suggestion|<index>"
                buttons = [
                    [InlineKeyboardButton(text=suggestion.get("title", "Suggestion"), callback_data=f"suggestion|{i}")]
                    for i, suggestion in enumerate(suggestions)
                ]
                markup = InlineKeyboardMarkup(buttons)
                new_text = "✨ No more songs in the queue. Here are some suggestions based on the last played song: ✨"
                if status_message:
                    try:
                        await status_message.edit(new_text, reply_markup=markup)
                    except Exception as e:
                        print("Error editing status message in show_suggestions:", e)
                        await bot.send_message(chat_id, new_text, reply_markup=markup)
                else:
                    await bot.send_message(chat_id, new_text, reply_markup=markup)
    except Exception as e:
        error_text = f"Error fetching suggestions: {str(e)}"
        print(error_text)
        await bot.send_message(5268762773, f"Suggestions API error in chat {chat_id}: {error_text}")
        if status_message:
            try:
                await status_message.edit(f"❌ Error fetching suggestions: {str(e)}")
            except Exception as ex:
                print("Error editing status message:", ex)
                await bot.send_message(chat_id, f"❌ Error fetching suggestions: {str(e)}")
        else:
            await bot.send_message(chat_id, f"❌ Error fetching suggestions: {str(e)}")
        await leave_voice_chat(chat_id)




def safe_handler(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # Attempt to extract a chat ID (if available)
            chat_id = "Unknown"
            try:
                # If your function is a message handler, the second argument is typically the Message object.
                if len(args) >= 2:
                    chat_id = args[1].chat.id
                elif "message" in kwargs:
                    chat_id = kwargs["message"].chat.id
            except Exception:
                chat_id = "Unknown"
            error_text = (
                f"Error in handler `{func.__name__}` (chat id: {chat_id}):\n\n{str(e)}"
            )
            print(error_text)
            # Log the error to support
            await bot.send_message(5268762773, error_text)
    return wrapper


async def extract_invite_link(client, chat_id):
    try:
        chat_info = await client.get_chat(chat_id)
        if chat_info.invite_link:
            return chat_info.invite_link
        elif chat_info.username:
            return f"https://t.me/{chat_info.username}"
        return None
    except ValueError as e:
        if "Peer id invalid" in str(e):
            print(f"Invalid peer ID for chat {chat_id}. Skipping invite link extraction.")
            return None
        else:
            raise e  # re-raise if it's another ValueError
    except Exception as e:
        print(f"Error extracting invite link for chat {chat_id}: {e}")
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

async def is_api_assistant_in_chat(chat_id):
    try:
        member = await bot.get_chat_member(chat_id, API_ASSISTANT_USERNAME)
        return member.status is not None
    except Exception as e:
        print(f"Error checking API assistant in chat: {e}")
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
    

async def skip_to_next_song(chat_id, message):
    """Skips to the next song in the queue and starts playback."""
    if chat_id not in chat_containers or not chat_containers[chat_id]:
        # Update playback records since the voice chat is ending
        record = {
            "chat_id": chat_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "event": "vc_ended",
            "mode": playback_mode.get(chat_id, "unknown")
        }
        api_playback_records.append(record)
        playback_mode.pop(chat_id, None)
        
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
        777000,  
        5268762773, 
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
    
async def stop_playback(chat_id):
    """
    Stops playback in the given chat using the external API.
    """
    api_stop_url = f"https://py-tgcalls-api1.onrender.com/stop?chatid={chat_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_stop_url) as resp:
                data = await resp.json()
        # Record the API stop event
        record = {
            "chat_id": chat_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "event": "stop",
            "api_response": data,
            "mode": playback_mode.get(chat_id, "unknown")
        }
        api_playback_records.append(record)
        playback_mode.pop(chat_id, None)  # Clear playback mode for the chat
        await bot.send_message(chat_id, f"API Stop: {data['message']}")
    except Exception as e:
        await bot.send_message(chat_id, f"❌ API Stop Error: {str(e)}")

async def invite_assistant(chat_id, invite_link, processing_message):
    """
    Internally invite the assistant to the chat by using the assistant client to join the chat.
    If an error occurs, it returns False and displays the exact error.
    """
    try:
        # Use the assistant client to join the chat via the invite link.
        await assistant.join_chat(invite_link)
        return True
    except Exception as e:
        error_message = f"❌ Error while inviting assistant: {str(e)}"
        await processing_message.edit(error_message)
        return False


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

    # Buttons on the start screen
    buttons = [
        [InlineKeyboardButton("➕ Add me", url="https://t.me/vcmusiclubot?startgroup=true"),
         InlineKeyboardButton("💬 Support", url="https://t.me/Frozensupport1")],
        [InlineKeyboardButton("❓ Help", callback_data="show_help")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    # Send the image with caption and buttons
    await message.reply_photo(
        photo="https://files.catbox.moe/kao3ip.jpeg",
        caption=caption,
        reply_markup=reply_markup
    )

@bot.on_callback_query(filters.regex("show_help"))
async def show_help_callback(_, callback_query):
    # Main help menu with category options
    help_text = "Choose a category to see available commands:"
    buttons = [
        [InlineKeyboardButton("🎵 Music Commands", callback_data="music_commands")],
        [InlineKeyboardButton("👥 Group Commands", callback_data="group_commands")],
        [InlineKeyboardButton("🏠 Home", callback_data="go_back")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await callback_query.message.edit_text(help_text, reply_markup=reply_markup)

@bot.on_callback_query(filters.regex("music_commands"))
async def music_commands_callback(_, callback_query):
    # Music-related commands help text
    music_help_text = (
        "Here are the music commands:\n\n"
        "✨ /play <song name> - Play a song\n"
        "✨ /stop - Stop the music\n"
        "✨ /pause - Pause the music\n"
        "✨ /resume - Resume the music\n"
        "✨ /skip - Skip the current song\n"
        "✨ /reboot - Reboot the bot\n"
        "✨ /ping - Show bot status and uptime\n"
        "✨ /clear - Clear the queue\n"
    )
    buttons = [
        [InlineKeyboardButton("🔙 Back", callback_data="show_help")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await callback_query.message.edit_text(music_help_text, reply_markup=reply_markup)

@bot.on_callback_query(filters.regex("group_commands"))
async def group_commands_callback(_, callback_query):
    # Group-related commands help text (plain text, no Markdown)
    group_help_text = (
        "Welcome to the bot!\n\n"
        "Here's what I can do for you in groups:\n"
        "- /id: Get your Telegram ID (in DM) or the group ID (in a group).\n"
        "- /kick, /ban, /unban, /mute, /unmute: Manage users in the group.\n"
        "- /promote, /demote: Promote or demote users.\n"
        "- /purge: Remove messages in bulk. Reply to a message to start purging from.\n"
        "- /report: Report a message to group admins.\n"
        "- /bcast: Broadcast a message to all registered chats.\n\n"
        "Enjoy using the bot! For more info or support, visit: https://t.me/Frozensupport1"
    )
    buttons = [
        [InlineKeyboardButton("🔙 Back", callback_data="show_help")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await callback_query.message.edit_text(group_help_text, reply_markup=reply_markup)


@bot.on_callback_query(filters.regex("go_back"))
async def go_back_callback(_, callback_query):
    # Re-create the start screen (with image, caption, and buttons)
    current_time = time.time()
    uptime_seconds = int(current_time - bot_start_time)
    uptime_str = str(timedelta(seconds=uptime_seconds))
    user_mention = callback_query.from_user.mention
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
    buttons = [
        [InlineKeyboardButton("➕ Add me", url="https://t.me/vcmusiclubot?startgroup=true"),
         InlineKeyboardButton("💬 Support", url="https://t.me/Frozensupport1")],
        [InlineKeyboardButton("❓ Help", callback_data="show_help")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await callback_query.message.edit_media(
        media=InputMediaPhoto(media="https://files.catbox.moe/kao3ip.jpeg", caption=caption),
        reply_markup=reply_markup
    )



# Modify the /play handler so that an empty query shows a button to play the playlist.
@bot.on_message(filters.group & filters.regex(r'^/play(?:\s+(?:@\S+))?(?:\s+(?P<query>.+))?$'))
async def play_handler(_, message):
    chat_id = message.chat.id
    # Extract the query before deleting the message.
    query = message.matches[0]['query']

    # Try to delete the command message; if it fails, log the error and continue.
    try:
        await message.delete()
    except Exception as e:
        print(f"Failed to delete command message: {e}")

    now = time.time()
    
    # Check if this chat is within the cooldown period.
    if chat_id in chat_last_command and (now - chat_last_command[chat_id]) < COOLDOWN:
        remaining = int(COOLDOWN - (now - chat_last_command[chat_id]))
        if chat_id in chat_pending_commands:
            await _.send_message(chat_id, f"⏳ A command is already queued for this chat. Please wait {remaining} more second(s).")
            return
        else:
            cooldown_reply = await _.send_message(chat_id, f"⏳ This chat is on cooldown. Your command will be processed in {remaining} second(s).")
            chat_pending_commands[chat_id] = (message, cooldown_reply)
            asyncio.create_task(process_pending_command(chat_id, remaining))
            return
    else:
        chat_last_command[chat_id] = now

    if not query:
        # If no song name is provided, prompt the user with two buttons:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎵 Play Your Playlist", callback_data="play_playlist"),
                InlineKeyboardButton("🔥 Play Trending Songs", callback_data="play_trending")
            ]
        ])
        await _.send_message(
            chat_id,
            "You did not specify a song. Would you like to play your playlist or trending songs instead?\n\n"
            "Correct usage: /play <song name>\nExample: /play shape of you",
            reply_markup=keyboard
        )
        return

    await process_play_command(message, query)

async def process_play_command(message, query):
    chat_id = message.chat.id
    processing_message = await message.reply("❄️")
    
    # --- Convert youtu.be links to full YouTube URLs ---
    if "youtu.be" in query:
        m = re.search(r"youtu\.be/([^?&]+)", query)
        if m:
            video_id = m.group(1)
            query = f"https://www.youtube.com/watch?v={video_id}"
    # --- End URL conversion ---

    # 🔍 Check if the assistant is already in the chat.
    is_in_chat = await is_assistant_in_chat(chat_id)
    print(f"Assistant in chat: {is_in_chat}")  # Debugging

    if not is_in_chat:
        invite_link = await extract_invite_link(bot, chat_id)
        if invite_link:
            # Internally invite the assistant without sending a public command.
            joined = await invite_assistant(chat_id, invite_link, processing_message)
            if not joined:
                return  # If joining fails, exit.
            await processing_message.edit("⏳ Assistant is joining... Please wait.")
            for _ in range(10):  # Retry for 10 seconds.
                await asyncio.sleep(3)
                is_in_chat = await is_assistant_in_chat(chat_id)
                print(f"Retry checking assistant in chat: {is_in_chat}")  # Debugging
                if is_in_chat:
                    await processing_message.edit("✅ Assistant joined! Playing your song...")
                    break
            else:
                await processing_message.edit(
                    "❌ Assistant failed to join. Please unban the assistant.\n"
                    "Assistant username: @Frozensupporter1\n"
                    "Assistant ID: 7386215995\n"
                    "Support: @frozensupport1"
                )
                record = {
                    "chat_id": chat_id,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "event": "assistant_join_failed",
                    "mode": playback_mode.get(chat_id, "unknown")
                }
                api_playback_records.append(record)
                playback_mode.pop(chat_id, None)
                return
        else:
            await processing_message.edit(
                "❌ Please give bot invite link permission.\n\nSupport: @frozensupport1"
            )
            record = {
                "chat_id": chat_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "event": "invite_link_missing",
                "mode": playback_mode.get(chat_id, "unknown")
            }
            api_playback_records.append(record)
            playback_mode.pop(chat_id, None)
            return

    try:
        # Call your API, which may return either a single video or a playlist.
        result = await fetch_youtube_link(query)
        # If the API returns a playlist:
        if isinstance(result, dict) and "playlist" in result:
            playlist_items = result["playlist"]
            if not playlist_items:
                await processing_message.edit("❌ No videos found in the playlist.")
                return
            if chat_id not in chat_containers:
                chat_containers[chat_id] = []
            for item in playlist_items:
                duration_seconds = isodate.parse_duration(item["duration"]).total_seconds()
                readable_duration = iso8601_to_human_readable(item["duration"])
                chat_containers[chat_id].append({
                    "url": item["link"],
                    "title": item["title"],
                    "duration": readable_duration,
                    "duration_seconds": duration_seconds,
                    "requester": message.from_user.first_name if message.from_user else "Unknown",
                    "thumbnail": item["thumbnail"]
                })
            # If the queue was empty before adding the playlist, start playback immediately.
            if len(chat_containers[chat_id]) == len(playlist_items):
                await start_playback_task(chat_id, processing_message)
            else:
                queue_buttons = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(text="⏭ Skip", callback_data="skip"),
                            InlineKeyboardButton(text="🗑 Clear", callback_data="clear")
                        ]
                    ]
                )
                await message.reply(
                    f"✨ Playlist added to queue. Total {len(chat_containers[chat_id])} songs.",
                    reply_markup=queue_buttons
                )
                await processing_message.delete()
        else:
            # Else, assume a single video response.
            video_url, video_title, video_duration, thumbnail_url = result
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
            
            # Use the thumbnail URL directly (no watermark processing)
            watermarked_thumbnail = thumbnail_url

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
                queue_buttons = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(text="⏭ Skip", callback_data="skip"),
                            InlineKeyboardButton(text="🗑 Clear", callback_data="clear")
                        ]
                    ]
                )
                await message.reply(
                    f"✨ Added to queue:\n\n"
                    f"✨**Title:** {video_title}\n"
                    f"✨**Duration:** {readable_duration}\n"
                    f"✨**Requested by:** {message.from_user.first_name if message.from_user else 'Unknown'}\n"
                    f"✨**Queue number:** {len(chat_containers[chat_id]) - 1}\n",
                    reply_markup=queue_buttons
                )
                await processing_message.delete()
    except Exception as e:
        await processing_message.edit(f"❌ Error: {str(e)}")


async def fallback_local_playback(chat_id, message, song_info):
    # Set playback mode to local
    playback_mode[chat_id] = "local"
    try:
        if chat_id in playback_tasks:
            playback_tasks[chat_id].cancel()

        video_url = song_info.get('url')
        if not video_url:
            print(f"Invalid video URL for song: {song_info}")
            chat_containers[chat_id].pop(0)
            return

        # Inform the user about fallback to local playback
        try:
            await message.edit(f"⏳ Falling back to local playback for {song_info['title']}...")
        except Exception as edit_error:
            message = await bot.send_message(chat_id, f"⏳ Falling back to local playback for {song_info['title']}...")

        # Proceed with downloading and playing locally
        media_path = await download_audio(video_url)

        await call_py.play(
            chat_id,
            MediaStream(
                media_path,
                video_flags=MediaStream.Flags.IGNORE
            )
        )

        playback_tasks[chat_id] = asyncio.current_task()

        # Updated inline keyboard without the "Download Songs" button:
        control_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(text="▶️", callback_data="pause"),
                InlineKeyboardButton(text="⏸", callback_data="resume"),
                InlineKeyboardButton(text="⏭", callback_data="skip"),
                InlineKeyboardButton(text="⏹", callback_data="stop")
            ],
            [InlineKeyboardButton(text="➕ Add to Playlist", callback_data="add_to_playlist")],
            [
                InlineKeyboardButton(text="✨ Updates ✨", url="https://t.me/vibeshiftbots"),
                InlineKeyboardButton(text="💕 Support 💕", url="https://t.me/Frozensupport1")
            ]
        ])

        await message.reply_photo(
            photo=song_info['thumbnail'],
            caption=(
                f"✨ **NOW PLAYING (Local Playback)**\n\n"
                f"✨**Title:** {song_info['title']}\n\n"
                f"✨**Duration:** {song_info['duration']}\n\n"
                f"✨**Requested by:** {song_info['requester']}"
            ),
            reply_markup=control_buttons
        )
        await message.delete()
    except Exception as fallback_error:
        print(f"Error during fallback local playback: {fallback_error}")


async def start_playback_task(chat_id, message):
    print(f"Current local VC count: {len(playback_tasks)}; Current chat: {chat_id}")

    # Use the external API if local VC limit has been reached.
    if chat_id not in playback_tasks and len(playback_tasks) >= LOCAL_VC_LIMIT:
        # External API branch
        if not await is_api_assistant_in_chat(chat_id):
            invite_link = await extract_invite_link(bot, chat_id)
            if invite_link:
                join_api_url = f"https://py-tgcalls-api1.onrender.com/join?input={urllib.parse.quote(invite_link)}"
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(join_api_url, timeout=20) as join_resp:
                            if join_resp.status != 200:
                                raise Exception(f"Join API responded with status {join_resp.status}")
                except Exception as e:
                    error_text = f"❌ API Assistant join error: {str(e)}. Please check the API endpoint."
                    if message:
                        await message.edit(error_text)
                    else:
                        await bot.send_message(chat_id, error_text)
                    return

                if message:
                    await message.edit("⏳ API Assistant is joining via API endpoint...")
                else:
                    await bot.send_message(chat_id, "⏳ API Assistant is joining via API endpoint...")

                for _ in range(10):
                    await asyncio.sleep(3)
                    if await is_api_assistant_in_chat(chat_id):
                        if message:
                            await message.edit("✅ API Assistant joined!")
                        else:
                            await bot.send_message(chat_id, "✅ API Assistant joined!")
                        break
                else:
                    if message:
                        await message.edit("❌ API Assistant failed to join. Please check the API endpoint.")
                    else:
                        await bot.send_message(chat_id, "❌ API Assistant failed to join. Please check the API endpoint.")
                    return

        if message:
            await message.edit("⏳ Calling Frozen Play API...")
        else:
            await bot.send_message(chat_id, "⏳ Calling Frozen Play API...")

        # Fetch the current song from the queue.
        song_info = chat_containers[chat_id][0]
        last_played_song[chat_id] = song_info  # Save the current song as last played
        video_title = song_info.get('title', 'Unknown')
        encoded_title = urllib.parse.quote(video_title)
        api_url = f"https://py-tgcalls-api1.onrender.com/play?chatid={chat_id}&title={encoded_title}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=30) as resp:
                    if resp.status != 200:
                        raise Exception(f"API responded with status {resp.status}")
                    data = await resp.json()
        except Exception as e:
            error_text = f"❌ Frozen Play API Error: {str(e)}\nFalling back to local playback..."
            if message:
                await message.edit(error_text)
            else:
                await bot.send_message(chat_id, error_text)
            await fallback_local_playback(chat_id, message, song_info)
            return

        record = {
            "chat_id": chat_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "song_title": video_title,
            "api_response": data
        }
        api_playback_records.append(record)
        playback_mode[chat_id] = "api"

        # External API branch inline keyboard without "Download Songs":
        control_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(text="▶️", callback_data="pause"),
                InlineKeyboardButton(text="⏸", callback_data="resume"),
                InlineKeyboardButton(text="⏭", callback_data="skip"),
                InlineKeyboardButton(text="⏹", callback_data="stop")
            ],
            [InlineKeyboardButton(text="➕ Add to Playlist", callback_data="add_to_playlist")],
            [
                InlineKeyboardButton(text="✨ Updates ✨", url="https://t.me/vibeshiftbots"),
                InlineKeyboardButton(text="💕 Support 💕", url="https://t.me/Frozensupport1")
            ]
        ])

        external_notice = (
            "Note: Bot is using Frozen Play API to play (beta). "
            "If any issues occur, fallback to local playback will be initiated."
        )
        caption = (
            f"{external_notice}\n\n"
            f"✨ **NOW PLAYING**\n\n"
            f"✨**Title:** {song_info['title']}\n\n"
            f"✨**Duration:** {song_info['duration']}\n\n"
            f"✨**Requested by:** {song_info['requester']}"
        )

        await bot.send_photo(
            chat_id,
            photo=song_info['thumbnail'],
            caption=caption,
            reply_markup=control_buttons
        )
        return  # Exit the external API branch.

    # --- Local Playback Branch (if external API branch is not used) ---
       # --- Local Playback Branch (if external API branch is not used) ---
    playback_mode[chat_id] = "local"
    try:
        if chat_id in playback_tasks:
            playback_tasks[chat_id].cancel()

        if chat_id in chat_containers and chat_containers[chat_id]:
            song_info = chat_containers[chat_id][0]
            last_played_song[chat_id] = song_info  # Save the current song as last played
            video_url = song_info.get('url')
            if not video_url:
                print(f"Invalid video URL for song: {song_info}")
                chat_containers[chat_id].pop(0)
                return

            try:
                await message.edit(
                    f"✨ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ... \n\n{song_info['title']}\n\nᴘʟᴇᴀsᴇ ᴡᴀɪᴛ 💕"
                )
            except Exception as edit_error:
                print(f"Error editing message: {edit_error}")
                message = await bot.send_message(
                    chat_id,
                    f"✨ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ... \n\n{song_info['title']}\n\nᴘʟᴇᴀsᴇ ᴡᴀɪᴛ 💕"
                )

            media_path = await download_audio(video_url)

            await call_py.play(
                chat_id,
                MediaStream(
                    media_path,
                    video_flags=MediaStream.Flags.IGNORE
                )
            )

            playback_tasks[chat_id] = asyncio.current_task()

            # Local branch inline keyboard without "Download Songs":
            control_buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(text="▶️", callback_data="pause"),
                    InlineKeyboardButton(text="⏸", callback_data="resume"),
                    InlineKeyboardButton(text="⏭", callback_data="skip"),
                    InlineKeyboardButton(text="⏹", callback_data="stop")
                ],
                [InlineKeyboardButton(text="➕ Add to Playlist", callback_data="add_to_playlist")],
                [
                    InlineKeyboardButton(text="✨ Updates ✨", url="https://t.me/vibeshiftbots"),
                    InlineKeyboardButton(text="💕 Support 💕", url="https://t.me/Frozensupport1")
                ]
            ])

            await message.reply_photo(
                photo=song_info['thumbnail'],
                caption=(
                    f"✨ **NOW PLAYING**\n\n"
                    f"✨**Title:** {song_info['title']}\n\n"
                    f"✨**Duration:** {song_info['duration']}\n\n"
                    f"✨**Requested by:** {song_info['requester']}"
                ),
                reply_markup=control_buttons
            )
            await message.delete()
    except Exception as playback_error:
        print(f"Error during playback: {playback_error}")
        time_of_error = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        try:
            chat_invite_link = await bot.export_chat_invite_link(chat_id)
        except Exception as link_error:
            chat_invite_link = "Could not retrieve invite link"
        error_message = (
            f"Error in chat id: {chat_id}\n\n"
            f"Error: {playback_error}\n\n"
            f"Chat Link: {chat_invite_link}\n\n"
            f"Time of error: {time_of_error}\n\n"
            f"Song title: {song_info['title']}"
        )
        await bot.send_message(5268762773, error_message)
        await message.reply(
            f"❌ Playback error for **{song_info['title']}**. Skipping to the next song...\n\nSupport has been notified."
        )
        chat_containers[chat_id].pop(0)
        await start_playback_task(chat_id, message)

 # Ensure this import is present

@bot.on_callback_query()
async def callback_query_handler(client, callback_query):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    data = callback_query.data
    mode = playback_mode.get(chat_id, "local")  # Default mode is local
    user = callback_query.from_user  # For later use

    # Skip admin check for playlist and trending actions, as well as suggestions and certain playlist commands.
    if not (data.startswith("suggestion|") or data.startswith("playlist_") or data in ["add_to_playlist", "play_playlist", "play_trending"]):
        if not await is_user_admin(callback_query):
            await callback_query.answer("❌ You need to be an admin to use this button.", show_alert=True)
            return

    # Playback control branches:
    if data == "pause":
        if mode == "local":
            try:
                await call_py.pause_stream(chat_id)
                await callback_query.answer("⏸ Playback paused.")
                await client.send_message(chat_id, f"⏸ Playback paused by {user.first_name}.")
            except Exception as e:
                await callback_query.answer("❌ Error pausing playback.", show_alert=True)
        else:
            await callback_query.answer("❌ Pause not supported in API mode.", show_alert=True)

    elif data == "resume":
        if mode == "local":
            try:
                await call_py.resume_stream(chat_id)
                await callback_query.answer("▶️ Playback resumed.")
                await client.send_message(chat_id, f"▶️ Playback resumed by {user.first_name}.")
            except Exception as e:
                await callback_query.answer("❌ Error resuming playback.", show_alert=True)
        else:
            await callback_query.answer("❌ Resume not supported in API mode.", show_alert=True)

    elif data == "skip":
        if chat_id in chat_containers and chat_containers[chat_id]:
            record = {
                "chat_id": chat_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "event": "skip",
                "mode": mode
            }
            api_playback_records.append(record)
            playback_mode.pop(chat_id, None)
            skipped_song = chat_containers[chat_id].pop(0)
            if mode == "local":
                try:
                    await call_py.leave_call(chat_id)
                except Exception as e:
                    print("Local leave_call error:", e)
                await asyncio.sleep(3)
                try:
                    os.remove(skipped_song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file: {e}")
            else:
                try:
                    await stop_playback(chat_id)
                except Exception as e:
                    print("API stop error:", e)
                await asyncio.sleep(3)
                try:
                    if skipped_song.get('file_path'):
                        os.remove(skipped_song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file: {e}")
            await client.send_message(chat_id, f"⏩ {user.first_name} skipped **{skipped_song['title']}**.")
            if chat_id in chat_containers and chat_containers[chat_id]:
                await callback_query.answer("⏩ Skipped! Playing the next song...")
                await start_playback_task(chat_id, callback_query.message)
            else:
                await callback_query.answer("⏩ Skipped! No more songs in the queue. Fetching suggestions...")
                last_song = last_played_song.get(chat_id)
                if last_song and last_song.get('url'):
                    try:
                        await callback_query.message.edit(
                            f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue. Fetching song suggestions..."
                        )
                    except Exception as e:
                        print("Error editing callback message:", e)
                        await bot.send_message(
                            chat_id,
                            f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue. Fetching song suggestions..."
                        )
                    await show_suggestions(chat_id, last_song.get('url'), status_message=callback_query.message)
                else:
                    try:
                        await callback_query.message.edit(
                            f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue and no last played song available. ❌"
                        )
                    except Exception as e:
                        print("Error editing callback message:", e)
                        await bot.send_message(
                            chat_id,
                            f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue and no last played song available. ❌"
                        )
        else:
            await callback_query.answer("❌ No songs in the queue to skip.")

    elif data == "clear":
        if chat_id in chat_containers:
            for song in chat_containers[chat_id]:
                try:
                    os.remove(song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file: {e}")
            chat_containers.pop(chat_id)
            await callback_query.message.edit("🗑️ Cleared the queue.")
            await callback_query.answer("🗑️ Cleared the queue.")
        else:
            await callback_query.answer("❌ No songs in the queue to clear.", show_alert=True)

    elif data == "stop":
        if chat_id in chat_containers:
            chat_containers[chat_id].clear()
        if mode == "local":
            record = {
                "chat_id": chat_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "event": "stop",
                "mode": mode
            }
            api_playback_records.append(record)
            playback_mode.pop(chat_id, None)
        try:
            if mode == "local":
                await call_py.leave_call(chat_id)
            else:
                await stop_playback(chat_id)
            await callback_query.answer("🛑 Playback stopped and queue cleared.")
            await client.send_message(chat_id, f"🛑 Playback stopped and queue cleared by {user.first_name}.")
        except Exception as e:
            print("Stop error:", e)
            await callback_query.answer("❌ Error stopping playback.", show_alert=True)

    elif data.startswith("suggestion|"):
        try:
            parts = data.split("|")
            index = int(parts[1])
        except Exception:
            await callback_query.answer("Invalid selection.", show_alert=True)
            return
        suggestions = last_suggestions.get(chat_id, [])
        if index < 0 or index >= len(suggestions):
            await callback_query.answer("Invalid suggestion selection.", show_alert=True)
            return
        suggestion = suggestions[index]
        duration_iso = suggestion.get("duration")
        readable_duration = iso8601_to_human_readable(duration_iso) if duration_iso else "Unknown"
        song_data = {
            "url": suggestion.get("link"),
            "title": suggestion.get("title"),
            "duration": readable_duration,
            "duration_seconds": isodate.parse_duration(duration_iso).total_seconds() if duration_iso else 0,
            "requester": "Suggestion",
            "thumbnail": suggestion.get("thumbnail")
        }
        if chat_id not in chat_containers:
            chat_containers[chat_id] = []
        chat_containers[chat_id].append(song_data)
        await callback_query.answer("Song added from suggestions. Starting playback...")
        if len(chat_containers[chat_id]) == 1:
            await start_playback_task(chat_id, callback_query.message)
        else:
            await client.send_message(chat_id, f"Added **{song_data['title']}** to the queue from suggestions.")

    elif data == "add_to_playlist":
        if chat_id in chat_containers and chat_containers[chat_id]:
            song_info = chat_containers[chat_id][0]
            existing_song = playlist_collection.find_one({
                "chat_id": chat_id,
                "user_id": user_id,
                "song_title": song_info.get("title")
            })
            if existing_song:
                await callback_query.answer("❌ Song already in your playlist.", show_alert=True)
                return
            playlist_entry = {
                "chat_id": chat_id,
                "user_id": user_id,
                "song_title": song_info.get("title"),
                "url": song_info.get("url"),
                "duration": song_info.get("duration"),
                "thumbnail": song_info.get("thumbnail"),
                "timestamp": time.time()
            }
            playlist_collection.insert_one(playlist_entry)
            await callback_query.answer("✅ Added to your playlist!")
        else:
            await callback_query.answer("❌ No song currently playing.", show_alert=True)

    elif data.startswith("playlist_page|"):
        try:
            _, page_str = data.split("|", 1)
            page = int(page_str)
        except Exception:
            page = 1
        per_page = 10
        user_playlist = list(playlist_collection.find({"user_id": user_id}))
        total = len(user_playlist)
        if total == 0:
            await callback_query.message.edit("Your playlist is empty.")
            return
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        page_items = user_playlist[start_index:end_index]
        buttons = []
        for idx, song in enumerate(page_items, start=start_index+1):
            song_id = str(song.get('_id'))
            song_title = song.get('song_title', 'Unknown')
            buttons.append([InlineKeyboardButton(text=f"{idx}. {song_title}", callback_data=f"playlist_detail|{song_id}")])
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"playlist_page|{page-1}"))
        if end_index < total:
            nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"playlist_page|{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        await callback_query.message.edit("🎶 **Your Playlist:**", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("playlist_detail|"):
        _, song_id = data.split("|", 1)
        try:
            song = playlist_collection.find_one({"_id": ObjectId(song_id)})
        except Exception as e:
            await callback_query.answer("Error fetching song details.", show_alert=True)
            return
        if not song:
            await callback_query.answer("Song not found in your playlist.", show_alert=True)
            return
        title = song.get("song_title", "Unknown")
        duration = song.get("duration", "Unknown")
        url = song.get("url", "Unknown")
        details_text = f"**Title:** {title}\n**Duration:** {duration}\n**URL:** {url}"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(text="▶️ Play This Song", callback_data=f"play_song|{song_id}"),
                InlineKeyboardButton(text="🗑 Remove from Playlist", callback_data=f"remove_from_playlist|{song_id}")
            ],
            [InlineKeyboardButton(text="⬅️ Back to Playlist", callback_data="playlist_back")]
        ])
        await callback_query.message.edit(details_text, reply_markup=keyboard)

    elif data.startswith("play_song|"):
        _, song_id = data.split("|", 1)
        try:
            song = playlist_collection.find_one({"_id": ObjectId(song_id)})
        except Exception as e:
            await callback_query.answer("Error fetching song.", show_alert=True)
            return
        if not song:
            await callback_query.answer("Song not found.", show_alert=True)
            return

        song_data = {
            "url": song.get("url"),
            "title": song.get("song_title"),
            "duration": song.get("duration"),
            "duration_seconds": 0,  # Convert if needed
            "requester": user.first_name,
            "thumbnail": song.get("thumbnail")
        }

        # Check if there’s an existing queue (and playback) for this chat.
        existing_queue = chat_containers.get(chat_id)
        if not existing_queue:
            chat_containers[chat_id] = []
            queue_already_running = False
        else:
            queue_already_running = len(chat_containers[chat_id]) > 0

        chat_containers[chat_id].append(song_data)
        if not queue_already_running:
            await callback_query.answer("Song added to queue. Starting playback...", show_alert=False)
            await start_playback_task(chat_id, callback_query.message)
        else:
            await callback_query.answer("Song added to queue.", show_alert=False)

    elif data.startswith("remove_from_playlist|"):
        _, song_id = data.split("|", 1)
        try:
            result = playlist_collection.delete_one({"_id": ObjectId(song_id)})
        except Exception as e:
            await callback_query.answer("Error removing song.", show_alert=True)
            return
        if result.deleted_count:
            await callback_query.answer("Song removed from your playlist.")
        else:
            await callback_query.answer("Failed to remove song or song not found.", show_alert=True)
        # Refresh the playlist display (default to page 1).
        user_playlist = list(playlist_collection.find({"user_id": user_id}))
        if not user_playlist:
            await callback_query.message.edit("Your playlist is now empty.")
            return
        page = 1
        per_page = 10
        total = len(user_playlist)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        page_items = user_playlist[start_index:end_index]
        buttons = []
        for idx, song in enumerate(page_items, start=start_index+1):
            song_id = str(song.get('_id'))
            song_title = song.get('song_title', 'Unknown')
            buttons.append([InlineKeyboardButton(text=f"{idx}. {song_title}", callback_data=f"playlist_detail|{song_id}")])
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"playlist_page|{page-1}"))
        if end_index < total:
            nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"playlist_page|{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        await callback_query.message.edit("🎶 **Your Playlist:**", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "playlist_back":
        user_playlist = list(playlist_collection.find({"user_id": user_id}))
        if not user_playlist:
            await callback_query.message.edit("Your playlist is empty.")
            return
        page = 1
        per_page = 10
        total = len(user_playlist)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        page_items = user_playlist[start_index:end_index]
        buttons = []
        for idx, song in enumerate(page_items, start=start_index+1):
            song_id = str(song.get('_id'))
            song_title = song.get('song_title', 'Unknown')
            buttons.append([InlineKeyboardButton(text=f"{idx}. {song_title}", callback_data=f"playlist_detail|{song_id}")])
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"playlist_page|{page-1}"))
        if end_index < total:
            nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"playlist_page|{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        await callback_query.message.edit("🎶 **Your Playlist:**", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "play_playlist":
        # Retrieve the entire playlist for this user from MongoDB.
        user_playlist = list(playlist_collection.find({"user_id": user_id}))
        if not user_playlist:
            await callback_query.answer("❌ You don't have any songs in your playlist.", show_alert=True)
            return
        if chat_id not in chat_containers:
            chat_containers[chat_id] = []
        count_added = 0
        for song in user_playlist:
            song_data = {
                "url": song.get("url"),
                "title": song.get("song_title"),
                "duration": song.get("duration"),
                "duration_seconds": 0,
                "requester": user.first_name,
                "thumbnail": song.get("thumbnail")
            }
            chat_containers[chat_id].append(song_data)
            count_added += 1
        await callback_query.answer(f"✅ Added {count_added} songs from your playlist to the queue!")
        if len(chat_containers[chat_id]) > 0:
            await start_playback_task(chat_id, callback_query.message)

    elif data == "play_trending":
        # Call the trending songs API endpoint.
        trending_query = "/search?title=trending"
        try:
            result = await fetch_youtube_link(trending_query)
            if isinstance(result, dict) and "playlist" in result:
                playlist_items = result["playlist"]
                if not playlist_items:
                    await callback_query.answer("❌ No trending songs found.", show_alert=True)
                    return
                if chat_id not in chat_containers:
                    chat_containers[chat_id] = []
                count_added = 0
                for item in playlist_items:
                    duration_seconds = isodate.parse_duration(item["duration"]).total_seconds()
                    readable_duration = iso8601_to_human_readable(item["duration"])
                    chat_containers[chat_id].append({
                        "url": item["link"],
                        "title": item["title"],
                        "duration": readable_duration,
                        "duration_seconds": duration_seconds,
                        "requester": user.first_name,
                        "thumbnail": item["thumbnail"]
                    })
                    count_added += 1
                await callback_query.answer(f"✅ Added {count_added} trending songs to the queue!")
                if len(chat_containers[chat_id]) > 0:
                    await start_playback_task(chat_id, callback_query.message)
            else:
                video_url, video_title, video_duration, thumbnail_url = result
                if not video_url:
                    await callback_query.answer("❌ Could not fetch trending songs.", show_alert=True)
                    return
                duration_seconds = isodate.parse_duration(video_duration).total_seconds()
                readable_duration = iso8601_to_human_readable(video_duration)
                if chat_id not in chat_containers:
                    chat_containers[chat_id] = []
                chat_containers[chat_id].append({
                    "url": video_url,
                    "title": video_title,
                    "duration": readable_duration,
                    "duration_seconds": duration_seconds,
                    "requester": user.first_name,
                    "thumbnail": thumbnail_url
                })
                await callback_query.answer("✅ Added trending song to the queue!")
                if len(chat_containers[chat_id]) == 1:
                    await start_playback_task(chat_id, callback_query.message)
        except Exception as e:
            await callback_query.answer(f"❌ Error fetching trending songs: {str(e)}", show_alert=True)

    else:
        await callback_query.answer("Unknown action.", show_alert=True)



@call_py.on_update(fl.stream_end)
async def stream_end_handler(_: PyTgCalls, update: Update):
    chat_id = update.chat_id

    # Update playback records for a natural end event
    record = {
        "chat_id": chat_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "event": "natural_end",
        "mode": playback_mode.get(chat_id, "unknown")
    }
    api_playback_records.append(record)
    playback_mode.pop(chat_id, None)

    if chat_id in chat_containers and chat_containers[chat_id]:
        # Remove the finished song from the queue.
        skipped_song = chat_containers[chat_id].pop(0)
        await asyncio.sleep(3)  # Delay to ensure the stream has fully ended
        try:
            os.remove(skipped_song.get('file_path', ''))
        except Exception as e:
            print(f"Error deleting file: {e}")

        if chat_id in chat_containers and chat_containers[chat_id]:
            # If there are more songs, start the next one.
            await start_playback_task(chat_id, None)
        else:
            # Queue is empty; try to leave the voice chat first.
            await leave_voice_chat(chat_id)
            # Then fetch suggestions if a last played song is available.
            last_song = last_played_song.get(chat_id)
            if last_song and last_song.get('url'):
                status_msg = await bot.send_message(chat_id, "😔 No more songs in the queue. Fetching song suggestions...")
                await show_suggestions(chat_id, last_song.get('url'), status_message=status_msg)
            else:
                await bot.send_message(
                    chat_id,
                    "❌ No more songs in the queue.\nSupport: @frozensupport1"
                )
    else:
        # No songs in the queue.
        await leave_voice_chat(chat_id)
        last_song = last_played_song.get(chat_id)
        if last_song and last_song.get('url'):
            status_msg = await bot.send_message(chat_id, "😔 No more songs in the queue. Fetching song suggestions...")
            await show_suggestions(chat_id, last_song.get('url'), status_message=status_msg)
        else:
            await bot.send_message(
                chat_id,
                "❌ No more songs in the queue.\nSupport: @frozensupport1"
            )

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


@bot.on_message(filters.command("playlist"))
async def my_playlist_handler(_, message):
    user_id = message.from_user.id
    # Retrieve the user's playlist from MongoDB
    user_playlist = list(playlist_collection.find({"user_id": user_id}))
    if not user_playlist:
        await message.reply("You don't have any songs in your playlist yet.")
        return

    # Default to page 1
    page = 1
    per_page = 10
    total = len(user_playlist)
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    page_items = user_playlist[start_index:end_index]

    buttons = []
    for idx, song in enumerate(page_items, start=start_index+1):
        song_id = str(song.get('_id'))
        song_title = song.get('song_title', 'Unknown')
        # Each button triggers the detail menu for that song.
        buttons.append([InlineKeyboardButton(text=f"{idx}. {song_title}", callback_data=f"playlist_detail|{song_id}")])

    # Add pagination buttons if needed.
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"playlist_page|{page-1}"))
    if end_index < total:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"playlist_page|{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    await message.reply("🎶 **Your Playlist:**", reply_markup=InlineKeyboardMarkup(buttons))




download_cache = {}  # Global cache dictionary

async def download_audio(url):
    """Downloads the audio from a given URL and returns the file path.
    Uses caching to avoid re-downloading the same file.
    """
    if url in download_cache:
        return download_cache[url]  # Return cached file path if available

    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        file_name = temp_file.name
        download_url = f"{DOWNLOAD_API_URL}{url}"

        async with aiohttp.ClientSession() as session:
            async with session.get(download_url, timeout=35) as response:  # Increased timeout to 35 seconds
                if response.status == 200:
                    with open(file_name, 'wb') as f:
                        f.write(await response.read())

                    download_cache[url] = file_name  # Cache the file path
                    return file_name
                else:
                    raise Exception(f"Failed to download audio. HTTP status: {response.status}")
    except asyncio.TimeoutError:
        raise Exception("❌ Download API took too long to respond. Please try again.")
    except Exception as e:
        raise Exception(f"Error downloading audio: {e}")


@bot.on_message(filters.command("clone"))
async def clone_handler(client, message):
    """
    Clones a bot using the provided token.
    Usage: /clone <bot_token>
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: /clone <bot_token>")
        return

    new_bot_token = args[1].strip()

    # Validate the bot token format
    token_pattern = r'^\d+:[A-Za-z0-9_-]+$'
    if not re.match(token_pattern, new_bot_token):
        await message.reply("Invalid bot token format. Please provide a valid bot token.")
        return

    # Inform the user and wait 10 seconds
    await message.reply("⏳ Please wait, cloning your own music bot...")
    await asyncio.sleep(10)

    try:
        # Create a unique session name for the clone bot to avoid conflicts
        clone_session_name = f"clone_{int(time.time())}"
        
        # Prepare a new environment for the clone bot
        new_env = os.environ.copy()
        new_env["BOT_TOKEN"] = new_bot_token
        new_env["SESSION_NAME"] = clone_session_name  # if used in your Client initialization

        # Launch a new process running the same script (this assumes the script handles the new bot)
        subprocess.Popen([sys.executable, sys.argv[0]], env=new_env)
        
        # Store the bot token and details in MongoDB
        bot_data = {
            "user_id": message.from_user.id,
            "bot_token": new_bot_token,
            "clone_session_name": clone_session_name,
            "timestamp": int(time.time())
        }
        bots_collection.insert_one(bot_data)
        
        await message.reply("✅ Clone bot deployed successfully!")
    except Exception as e:
        await message.reply(f"Error deploying clone bot: {e}")

@bot.on_message(filters.command("bots"))
async def bots_handler(client, message):
    """
    Returns a list of all cloned bots along with who cloned them.
    Only the authorized user (OWNER_ID) can access this command.
    """
    if message.from_user.id != OWNER_ID:
        await message.reply("Access Denied!")
        return

    # Retrieve all cloned bots from MongoDB
    bots = bots_collection.find()
    response_text = "<b>Cloned Bots List:</b>\n\n"
    for bot_entry in bots:
        response_text += f"👤 User ID: {bot_entry['user_id']}\n"
        response_text += f"🤖 Bot Token: <code>{bot_entry['bot_token']}</code>\n"
        response_text += f"🔖 Session Name: {bot_entry['clone_session_name']}\n"
        response_text += "----------------------\n"

    await message.reply(response_text, parse_mode="HTML")

bot.run()

    

@bot.on_message(filters.group & filters.command(["stop", "end"]))
async def stop_handler(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Check admin rights
    if not await is_user_admin(message):
        await message.reply("❌ You need to be an admin to use this command.")
        return

    # Determine the playback mode (defaulting to local)
    mode = playback_mode.get(chat_id, "local")

    if mode == "local":
        try:
            await call_py.leave_call(chat_id)
        except Exception as e:
            if "not in a call" in str(e).lower():
                await message.reply("❌ The bot is not currently in a voice chat.")
            else:
                await message.reply(f"❌ An error occurred while leaving the voice chat: {str(e)}\n\n support - @frozensupport1")
            return
        # Update playback records for a stop event in local mode
        record = {
            "chat_id": chat_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "event": "stop",
            "mode": mode
        }
        api_playback_records.append(record)
        playback_mode.pop(chat_id, None)
    else:
        try:
            await stop_playback(chat_id)
        except Exception as e:
            await message.reply(f"❌ An error occurred while stopping playback: {str(e)}", quote=True)
            return

    # Clear the song queue
    if chat_id in chat_containers:
        for song in chat_containers[chat_id]:
            try:
                os.remove(song.get('file_path', ''))
            except Exception as e:
                print(f"Error deleting file: {e}")
        chat_containers.pop(chat_id)

    # Cancel any playback tasks if present
    if chat_id in playback_tasks:
        playback_tasks[chat_id].cancel()
        del playback_tasks[chat_id]

    await message.reply("⏹ Stopped the music and cleared the queue.")


@bot.on_message(filters.group & filters.command("pause"))
async def pause_handler(client, message):
    chat_id = message.chat.id
    if not await is_user_admin(message):
        await message.reply("❌ You need to be an admin to use this command.")
        return
    try:
        await call_py.pause_stream(chat_id)
        await message.reply("⏸ Paused the stream.")
    except Exception as e:
        await message.reply(f"❌ Failed to pause the stream. Error: {str(e)}\n\n support - @frozensupport1 ")

@bot.on_message(filters.group & filters.command("resume"))
async def resume_handler(client, message):
    chat_id = message.chat.id
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

    status_message = await message.reply("⏩ Skipping the current song...")

    if chat_id not in chat_containers or not chat_containers[chat_id]:
        await status_message.edit("❌ No songs in the queue to skip.")
        return

    # Remove the currently playing song from the queue.
    skipped_song = chat_containers[chat_id].pop(0)
    # Determine the playback mode (default to local).
    mode = playback_mode.get(chat_id, "local")

    # Update playback records for a skip event.
    record = {
        "chat_id": chat_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "event": "skip",
        "mode": mode
    }
    api_playback_records.append(record)
    playback_mode.pop(chat_id, None)

    if mode == "local":
        try:
            await call_py.leave_call(chat_id)
        except Exception as e:
            print("Local leave_call error:", e)
        await asyncio.sleep(3)
        try:
            os.remove(skipped_song.get('file_path', ''))
        except Exception as e:
            print(f"Error deleting file: {e}")
    else:
        try:
            await stop_playback(chat_id)
        except Exception as e:
            print("API stop error:", e)
        await asyncio.sleep(3)
        try:
            if skipped_song.get('file_path'):
                os.remove(skipped_song.get('file_path', ''))
        except Exception as e:
            print(f"Error deleting file: {e}")

    # Check if there are any more songs in the queue.
    if not chat_containers.get(chat_id):
        # Try to edit the status message with a new message that includes emojis.
        try:
            await status_message.edit(
                f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue. Fetching song suggestions..."
            )
        except Exception as e:
            print(f"Error editing message: {e}")
            await status_message.delete()
            status_message = await bot.send_message(
                chat_id,
                f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue. Fetching song suggestions..."
            )
        # Use the last played song info to fetch suggestions.
        last_song = last_played_song.get(chat_id)
        if last_song and last_song.get('url'):
            print(f"Fetching suggestions using URL: {last_song.get('url')}")
            await show_suggestions(chat_id, last_song.get('url'))
        else:
            try:
                await status_message.edit(
                    f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue and no last played song available. ❌"
                )
            except Exception as e:
                await bot.send_message(
                    chat_id,
                    f"⏩ Skipped **{skipped_song['title']}**.\n\n😔 No more songs in the queue and no last played song available. ❌"
                )
    else:
        try:
            await status_message.edit(
                f"⏩ Skipped **{skipped_song['title']}**.\n\n💕 Playing the next song..."
            )
        except Exception as e:
            print(f"Error editing message: {e}")
        await skip_to_next_song(chat_id, status_message)



@bot.on_message(filters.command("reboot"))
async def reboot_handler(_, message):
    chat_id = message.chat.id

    try:
        # Remove audio files for songs in the queue for this chat.
        if chat_id in chat_containers:
            for song in chat_containers[chat_id]:
                try:
                    os.remove(song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file for chat {chat_id}: {e}")
            # Clear the queue for this chat.
            chat_containers.pop(chat_id, None)
        
        # Cancel any playback tasks for this chat.
        if chat_id in playback_tasks:
            playback_tasks[chat_id].cancel()
            del playback_tasks[chat_id]

        # Remove chat-specific cooldown and pending command entries.
        chat_last_command.pop(chat_id, None)
        chat_pending_commands.pop(chat_id, None)

        # Remove playback mode for this chat.
        playback_mode.pop(chat_id, None)

        # Clear any API playback records for this chat.
        global api_playback_records
        api_playback_records = [record for record in api_playback_records if record.get("chat_id") != chat_id]

        # Leave the voice chat for this chat.
        try:
            await call_py.leave_call(chat_id)
        except Exception as e:
            print(f"Error leaving call for chat {chat_id}: {e}")

        await message.reply("♻️ Rebooted for this chat. All data for this chat has been cleared.")
    except Exception as e:
        await message.reply(f"❌ Failed to reboot for this chat. Error: {str(e)}\n\n support - @frozensupport1")


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

import requests

API_WORKER_URL = "https://boradcasteapi.frozenbotsweb.workers.dev"
BOT_ID = "7598576464"
ADMIN_ID = 5268762773# Your bot's ID

async def register_chat_silently(chat_id):
    """Silently register chat ID with the broadcast API."""
    try:
        requests.post(
            f"{API_WORKER_URL}/register",
            json={"botId": BOT_ID, "chatId": str(chat_id)}
        )
    except Exception as e:
        print(f"Error registering chat: {e}")

@bot.on_message(filters.command(""))
async def auto_register(_, message):
    """Register the chat when any command is used."""
    chat_id = message.chat.id
    await register_chat_silently(chat_id)

@bot.on_message(filters.user(ADMIN_ID) & filters.command("broadcast"))
async def broadcast_handler(_, message):
    """Send a broadcast message to all registered chats."""
    if len(message.command) < 2:
        await message.reply("❌ Please provide a message to broadcast.")
        return

    broadcast_text = " ".join(message.command[1:])
    
    response = requests.post(
        f"{API_WORKER_URL}/broadcast",
        json={
            "botId": BOT_ID,  # Correct bot ID added here
            "token": BOT_TOKEN,
            "message": broadcast_text
        }
    )
    
    result = response.json()
    await message.reply(f"📢 Broadcast Status: {result}")


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

def ping_api(url, description):
    """Ping an API endpoint and print its HTTP status code."""
    print(f"Pinging {description}: {url}")
    try:
        response = requests.get(url, timeout=5)
        print(f"{description} responded with status code: {response.status_code}")
    except Exception as e:
        print(f"Error pinging {description}: {e}")

@bot.on_message(filters.regex(r'^Stream ended in chat id (?P<chat_id>-?\d+)$'))
async def stream_ended_handler(_, message):
    # Extract the chat ID from the message
    chat_id = int(message.matches[0]['chat_id'])
    
    # Update playback records for a natural end event
    record = {
        "chat_id": chat_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "event": "natural_end",
        "mode": playback_mode.get(chat_id, "unknown")
    }
    api_playback_records.append(record)
    playback_mode.pop(chat_id, None)
    
    if chat_id in chat_containers and chat_containers[chat_id]:
        # Remove the finished song from the queue.
        skipped_song = chat_containers[chat_id].pop(0)
        await asyncio.sleep(3)  # Delay to ensure the stream has fully ended
        
        try:
            os.remove(skipped_song.get('file_path', ''))
        except Exception as e:
            print(f"Error deleting file: {e}")
        
        if chat_containers[chat_id]:
            await bot.send_message(chat_id, "⏭ Skipping to the next song...")
            await start_playback_task(chat_id, message)
        else:
            # Queue is empty; fetch suggestions.
            last_song = last_played_song.get(chat_id)
            if last_song and last_song.get('url'):
                status_msg = await bot.send_message(chat_id, "😔 No more songs in the queue. Fetching song suggestions...")
                await show_suggestions(chat_id, last_song.get('url'), status_message=status_msg)
            else:
                await bot.send_message(
                    chat_id,
                    "❌ No more songs in the queue.\nLeaving the voice chat. 💕\n\nSupport: @frozensupport1"
                )
                await leave_voice_chat(chat_id)
    else:
        # No songs in the queue.
        last_song = last_played_song.get(chat_id)
        if last_song and last_song.get('url'):
            status_msg = await bot.send_message(chat_id, "😔 No more songs in the queue. Fetching song suggestions...")
            await show_suggestions(chat_id, last_song.get('url'), status_message=status_msg)
        else:
            await bot.send_message(chat_id, "🚪 No songs left in the queue.")


@bot.on_message(filters.command("frozen_check") & filters.chat(ASSISTANT_CHAT_ID))
async def frozen_check_command(_, message):
    await message.reply_text("frozen check successful ✨")




@bot.on_message(filters.regex(r"^#restart$") & filters.user(5268762773))
async def owner_simple_restart_handler(_, message):
    await message.reply("♻️ [WATCHDOG] restart initiated as per owner command...")
    await simple_restart()



MAIN_LOOP = None
ASSISTANT_CHAT_ID = 7386215995
BOT_CHAT_ID = 7598576464
BOT_USERNAME = "@vcmusiclubot"


# Check for Render API endpoint (set this in environment variables if needed)
RENDER_DEPLOY_URL = os.getenv("RENDER_DEPLOY_URL", "https://api.render.com/deploy/srv-cuqb40bv2p9s739h68i0?key=oegMCHfLr9I")

async def simple_restart():
    support_chat_id = -1001810811394
    log_message = "[WATCHDOG] Checking if restart is needed..."
    print(log_message)
    await bot.send_message(support_chat_id, log_message)

    if RENDER_DEPLOY_URL:
        # If Render API is available, trigger a restart via API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_DEPLOY_URL) as response:
                    if response.status == 200:
                        await bot.send_message(support_chat_id, "✅ Restart triggered via Frozen_Api")
                        return  # Exit without restarting locally
                    else:
                        await bot.send_message(support_chat_id, f"❌ Render restart failed: {response.status} {await response.text()}")
        except Exception as e:
            await bot.send_message(support_chat_id, f"⚠ Render API restart failed: {e}. Trying local restart...")

    # If Render API failed or not set, do a local restart
    try:
        await bot.stop()
        await asyncio.sleep(3)
        python_executable = sys.executable
        script_path = os.path.abspath(sys.argv[0])

        subprocess.Popen([python_executable, script_path], close_fds=True)
        os._exit(0)
    except Exception as e:
        error_message = f"❌ Local restart failed: {e}"
        print(error_message)
        await bot.send_message(support_chat_id, error_message)



async def keep_alive_loop():
    while True:
        print("[KEEP ALIVE] Bot is running...")
        await asyncio.sleep(300)

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running!")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/webhook":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            try:
                update_data = json.loads(post_data.decode("utf-8"))
                update = Update.de_json(update_data, bot)
            except Exception:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid JSON")
                return

            future = asyncio.run_coroutine_threadsafe(bot.process_new_updates([update]), MAIN_LOOP)
            def handle_future(fut):
                try:
                    fut.result()
                except Exception as e:
                    print(f"Error processing update: {e}")
                    asyncio.run(restart_bot())
            
            future.add_done_callback(handle_future)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    httpd = HTTPServer(("", port), WebhookHandler)
    print(f"HTTP server running on port {port}")
    httpd.serve_forever()

server_thread = threading.Thread(target=run_http_server, daemon=True)
server_thread.start()

if __name__ == "__main__":
    from threading import Thread
    import os
    from flask import Flask
    import asyncio

    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Bot server is running."

    def run_bot():
        try:
            import datetime

            print("Starting Frozen Music Bot...")
            call_py.start()
            bot.run()
            if not assistant.is_connected:
                assistant.run()
            print("Bot started successfully.")
            idle()
        except KeyboardInterrupt:
            print("Bot is still running. Kill the process to stop.")
        except Exception as e:
            print(f"Critical Error: {e}")
            asyncio.run(simple_restart())

    # Run the bot in a separate thread
    bot_thread = Thread(target=run_bot)
    bot_thread.start()

    # Run the Flask server on the main thread so Render can detect the open port
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))





