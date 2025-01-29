from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import MediaStream
import aiohttp
import asyncio
from pyrogram.types import Message
import isodate
import os
import re
import time
import psutil
from datetime import timedelta
import uuid
import tempfile

# Bot and Assistant session strings 
API_ID = 29385418  # Replace with your actual API ID
API_HASH = "5737577bcb32ea1aac1ac394b96c4b10"  # Replace with your actual API Hash
BOT_TOKEN = "7598576464:AAEH2ftzzjK38uIsufcUnKwgKAhlRiSJoNA"  # Replace with your bot token
ASSISTANT_SESSION = "BQHAYsoAb3ae0jLs1ZCipc8iNCwh7-I-e6bbxJhaJeJH0uRjp_zPgLecdoKkWzK0sQQ7oJQNKCOXNhoQ6mTxSStvVFZrMyzMtZBhnA8i9U89NVvuJ8HL6GIGnKuiqKpLjTc6vzpyaik5AygMQ9pQ6-rIL9WPQTlLDZg4XnUNHkRpZcOuTjvGjvJFkWLqXg-eonQfJ5Aexopgdv_7gAPCGTD0Mw3JTyxUAYVKs4Y9WcAYHjSQ0bfydO7cuOHbqbNUeKp5vi526nZzuFdd1kEgYTxgaQHBhZ_ZoS1yxLVpc-oAizBiCU_bV4cGO3l-4SCZilPJ0Tmbu1cNR9GS1jH4DOH4-3VPaAAAAAG4QLY7AA"  # Replace with your assistant session string

# Initialize the bot and assistant clients
bot = Client("music_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)
assistant = Client("assistant_account", session_string=ASSISTANT_SESSION)
call_py = PyTgCalls(assistant)

# API Endpoints
API_URL = "https://small-bush-de65.tenopno.workers.dev/search?title="
DOWNLOAD_API_URL = "https://frozen-youtube-api-search-link-ksog.onrender.com/download?url="

# Containers for song queues per chat/group
chat_containers = {}
bot_start_time = time.time()

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
                    return data.get("link"), data.get("title"), data.get("duration")
                else:
                    raise Exception(f"API returned status code {response.status}")
    except Exception as e:
        raise Exception(f"Failed to fetch YouTube link: {str(e)}")

@bot.on_message(filters.command("start"))
async def start_handler(_, message):
    await message.reply("👋 **Welcome to the Music Bot!**\n\n🎵 Use `/play <song name>` to search and play music in your voice chat.\n⏹ Use `/stop` to stop the music.\n⏸ Use `/pause` to pause the music.\n▶️ Use `/resume` to resume the music.\n\nHappy listening! 🎧")

@bot.on_message(filters.regex(r'^/play(?: (?P<query>.+))?$'))
async def play_handler(_, message):
    chat_id = message.chat.id
    try:
        query = message.matches[0]['query']  # Extract query from the command

        if not query:
            await message.reply("❓ Please provide a song name to play.\nExample: /play Shape of You")
            return

        processing_message = await message.reply("🔍 Searching for the song...")

        # Fetch YouTube link from the API
        video_url, video_title, video_duration = await fetch_youtube_link(query)

        if not video_url:
            await processing_message.edit("❌ Could not find the song. Please try another query.")
            return

        # Convert ISO 8601 duration to human-readable format
        readable_duration = iso8601_to_human_readable(video_duration)

        # Add the song to the chat-specific queue
        if chat_id not in chat_containers:
            chat_containers[chat_id] = []

        chat_containers[chat_id].append({
            "url": video_url,
            "title": video_title,
            "duration": readable_duration,
            "duration_seconds": isodate.parse_duration(video_duration).total_seconds(),
            "requester": message.from_user.first_name if message.from_user else "Unknown",
        })

        queue_number = len(chat_containers[chat_id]) - 1  # Correct the queue number to start from 0

        # If the queue has only one song, start playing immediately
        if queue_number == 0:
            await skip_to_next_song(chat_id, processing_message)
        else:
            await processing_message.edit(
                f"🎵 Added to queue:\n\n"
                f"**Title:** {video_title}\n"
                f"**Duration:** {readable_duration}\n"
                f"**Requested by:** {message.from_user.first_name if message.from_user else 'Unknown'}\n"
                f"**Queue number:** {queue_number}\n\n"
                f"If the assistant is not in the voice chat, please use /clear.",
                disable_web_page_preview=True
            )

    except Exception as e:
        await message.reply(f"❌ Failed to play the song. Error: {str(e)}")

async def skip_to_next_song(chat_id, message):
    try:
        while chat_id in chat_containers and chat_containers[chat_id]:
            song_info = chat_containers[chat_id][0]  # Get the first song in the queue

            video_url = song_info.get('url')
            if not video_url:
                print(f"Invalid video URL for song: {song_info}")
                chat_containers[chat_id].pop(0)
                continue

            try:
                await message.edit(
                    f"🔎 Processing song \n**{song_info['title']}**..."
                )

                # Send the video URL to the new API for download
                media_path = await download_audio(video_url)

                # Play the media using pytgcalls
                await call_py.play(
                    chat_id,
                    MediaStream(
                        media_path,
                        video_flags=MediaStream.Flags.IGNORE,
                    ),
                )

                # Notify the group about the currently playing song
                await message.edit(
                    f"🎵 **Now Playing**\n\n"
                    f"**Title:** {song_info['title']}\n\n"
                    f"**Duration:** {song_info['duration']}\n\n"
                    f"**Requested by:** {song_info['requester']}",
                    disable_web_page_preview=True,
                )

                # Wait for the song to finish
                await asyncio.sleep(song_info['duration_seconds'] + 10)  
            except Exception as playback_error:
                print(f"Error during playback: {playback_error}")
                await message.edit(
                    f"❌ Playback error for **{song_info['title']}**. Skipping to the next song...",
                )

            finally:
                # Clean up: remove the song from the queue
                chat_containers[chat_id].pop(0)

        # Leave the voice chat if the queue is empty
        if chat_id in chat_containers and not chat_containers[chat_id]:
            try:
                await call_py.leave_group_call(chat_id)
                await message.reply("✅ Queue finished. Leaving the voice chat.")
            except Exception as leave_error:
                print(f"Error leaving call: {leave_error}")

    except Exception as e:
        print(f"Unexpected error in skip_to_next_song: {str(e)}")

async def download_audio(url):
    """Downloads the audio from a given URL and returns the file path."""
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        file_name = temp_file.name
        download_url = f"{DOWNLOAD_API_URL}{url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as response:
                if response.status == 200:
                    with open(file_name, 'wb') as f:
                        f.write(await response.read())
                    return file_name
                else:
                    raise Exception(f"Failed to download audio. HTTP status: {response.status}")
    except Exception as e:
        raise Exception(f"Error downloading audio: {e}")

@bot.on_message(filters.command(["stop", "end"]))
async def stop_handler(client, message):
    chat_id = message.chat.id

    try:
        # Leave the voice chat (handles cases where the bot is not in VC)
        await call_py.leave_call(chat_id)
    except Exception as e:
        # Handle cases where the bot is not in the voice chat
        if "not in a call" in str(e).lower():
            await message.reply("❌ The bot is not currently in a voice chat.")
        else:
            await message.reply(f"❌ An error occurred while leaving the voice chat: {str(e)}")
        return

    # Clear the chat-specific queue
    if chat_id in chat_containers:
        for song in chat_containers[chat_id]:
            try:
                os.remove(song.get('file_path', ''))
            except Exception as e:
                print(f"Error deleting file: {e}")
        chat_containers.pop(chat_id)

    await message.reply("⏹ Stopped the music and cleared the queue.")

@bot.on_message(filters.command("pause"))
async def pause_handler(_, message):
    try:
        await call_py.pause_stream(message.chat.id)
        await message.reply("⏸ Paused the stream.")
    except Exception as e:
        await message.reply(f"❌ Failed to pause the stream. Error: {str(e)}")

@bot.on_message(filters.command("resume"))
async def resume_handler(_, message):
    try:
        await call_py.resume_stream(message.chat.id)
        await message.reply("▶️ Resumed the stream.")
    except Exception as e:
        await message.reply(f"❌ Failed to resume the stream. Error: {str(e)}")

@bot.on_message(filters.command("skip"))
async def skip_handler(client, message):
    chat_id = message.chat.id
    await_message = await message.reply("⏩ Skipping the current song...")

    try:
        if chat_id not in chat_containers or not chat_containers[chat_id]:
            await await_message.edit("❌ No songs in the queue to skip.")
            return

        # Remove the current song from the chat-specific queue
        skipped_song = chat_containers[chat_id].pop(0)

        # End playback and skip first, then delete the file
        await call_py.leave_call(chat_id)
        await asyncio.sleep(3)
        try:
            os.remove(skipped_song.get('file_path', ''))
        except Exception as e:
            print(f"Error deleting file: {e}")

        if not chat_containers[chat_id]:  # If no songs left in the queue
            await await_message.edit(f"⏩ Skipped **{skipped_song['title']}**.\n\n🎵 No more songs in the queue.")
        else:
            # Play the next song in the queue
            await await_message.edit(f"⏩ Skipped **{skipped_song['title']}**.\n\n🎵 Playing the next song...")
            await skip_to_next_song(chat_id, await_message)

    except Exception as e:
        await await_message.edit(f"❌ Failed to skip the song. Error: {str(e)}")


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
            await call_py.leave_group_call(chat_id)

            # Remove stored audio files for each song in the queue
            for song in chat_containers[chat_id]:
                try:
                    os.remove(song.get('file_path', ''))
                except Exception as e:
                    print(f"Error deleting file: {e}")

            # Clear the queue for this chat
            chat_containers.pop(chat_id, None)

            await message.reply("♻️ Rebooted for this chat and queue is cleared.")
        else:
            await message.reply("❌ No active queue to clear in this chat.")
    except Exception as e:
        await message.reply(f"❌ Failed to reboot. Error: {str(e)}")

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
        await message.reply(f"❌ Failed to execute the command. Error: {str(e)}")

@bot.on_message(filters.command("clear"))
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

if __name__ == "__main__":
    try:
        call_py.start()
        bot.start()
        if not assistant.is_connected:
            assistant.start()
        idle()
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        bot.stop()
        assistant.stop()
        call_py.stop()
