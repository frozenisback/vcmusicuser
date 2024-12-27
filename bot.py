from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import MediaStream
import aiohttp
import asyncio
from pyrogram.types import Message
import isodate
import os

# Your session string
STRING_SESSION = "BQHDLbkAwrcnh8Oe0R28KeHE2Bn2n3tMwKurNM8wBLOlD3q80-ayHd6Q4fgKNTdZg02QmdgNEW8WVH89PhUk5_WPJGC5l8NN5kWFBZSRZQtk9R74TR5sEVOktsw6ziw4KwlqWm1VGnibwk9A6b9PyCjuqCXOu0pvZypDcYOjBaLMU15ZB0Zph3x2mzn3VuV4VxDp51Hzwmc1VnfQ3MTCaOMQGfceoBNbD8JuGQFwrelUKbebQWpWDER59rsxLGR4CREs7xVc45raqPBVEsvE002Je1UgS4E_tMScr3Wdw8EWZYJai4fAUS49JL0Wd-Dl2rDacEF9lNhBosklWT_cc7EgYiJ5IgAAAAG4QLY7AA"

app = Client("music_bot", session_string=STRING_SESSION)

# Initialize PyTgCalls
call_py = PyTgCalls(app)

# Containers for song queues per chat/group
chat_containers = {}

# API endpoint for searching YouTube links
API_URL = "https://small-bush-de65.tenopno.workers.dev/search?title="

# Utility function to convert ISO 8601 duration to HH:MM:SS
def iso8601_to_human_readable(iso_duration):
    duration = isodate.parse_duration(iso_duration)
    total_seconds = int(duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"

# Function to fetch YouTube link using the API
async def fetch_youtube_link(query):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}{query}") as response:
            if response.status == 200:
                data = await response.json()
                return data.get("link"), data.get("title"), data.get("duration")
            else:
                raise Exception(f"API returned status code {response.status}")

# Command to handle /start
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply(
        "👋 **Welcome to the Music Bot!**\n\n"
        "🎵 Use `/play <song name>` to search and play music in your voice chat.\n"
        "⏹ Use `/stop` to stop the music.\n"
        "⏸ Use `/pause` to pause the music.\n"
        "▶️ Use `/resume` to resume the music.\n\n"
        "Happy listening! 🎧"
    )

# Command to play audio
@app.on_message(filters.regex(r'^/play(?: (?P<query>.+))?$'))
async def play_handler(client, message):
    chat_id = message.chat.id
    query = message.matches[0]['query']  # Extract query from the command

    if not query:
        await message.reply("❓ Please provide a song name to play.\nExample: `/play Shape of You`")
        return

    await_message = await message.reply("🔍 Searching for the song...")

    try:
        # Fetch YouTube link from the API
        video_url, video_title, video_duration = await fetch_youtube_link(query)

        if not video_url:
            await await_message.edit("❌ Could not find the song. Please try another query.")
            return

        # Convert ISO 8601 duration to human-readable format
        readable_duration = iso8601_to_human_readable(video_duration)

        # Forward URL to the bot
        forwarded_message = await app.send_message("@YoutubeAudioDownloadBot", video_url)

        # Wait for the bot to respond with the audio file
        bot_response = None
        for _ in range(10):  # Retry for up to 10 iterations
            async for response in app.get_chat_history("@YoutubeAudioDownloadBot", limit=10):
                if response.audio:  # Check if the message contains an audio file
                    bot_response = response
                    break
            if bot_response:
                break
            await asyncio.sleep(2)

        if not bot_response:
            await await_message.edit("❌ Failed to retrieve the audio file.")
            await forwarded_message.delete()
            return

        # Download the audio file locally
        audio_file_path = await bot_response.download()

        # Clean up forwarded messages immediately
        await asyncio.gather(
            forwarded_message.delete(),
            bot_response.delete(),
        )

        # Initialize a queue container for the chat if it doesn't exist
        if chat_id not in chat_containers:
            chat_containers[chat_id] = []

        # Add the song to the chat-specific queue
        chat_containers[chat_id].append({
            "url": video_url,
            "title": video_title,
            "duration": readable_duration,
            "duration_seconds": isodate.parse_duration(video_duration).total_seconds(),
            "file_path": audio_file_path,
            "requester": message.from_user.mention if message.from_user else "Unknown"
        })

        # If the queue has only one song, start playing immediately
        if len(chat_containers[chat_id]) == 1:
            await skip_to_next_song(chat_id)
        else:
            await await_message.edit(
                f"✅ Added to queue:\n"
                f"**Title:** {video_title}\n\n"
                f"**Duration:** {readable_duration}\n\n"
                f"**Requested by:** {message.from_user.mention if message.from_user else 'Unknown'}",
                disable_web_page_preview=True
            )

    except Exception as e:
        await await_message.edit(f"❌ Failed to play the song. Error: {str(e)}")

# Function to skip to the next song in the queue
async def skip_to_next_song(chat_id):
    while chat_id in chat_containers and chat_containers[chat_id]:
        try:
            song_info = chat_containers[chat_id][0]  # Get the first song in the queue
            file_path = song_info['file_path']

            # Play the next song in the voice chat
            await call_py.play(
                chat_id,
                MediaStream(
                    file_path,
                )
            )

            # Notify the group about the next song
            await app.send_message(
                chat_id,
                f"🎵 **Now Playing**\n"
                f"**Title:** {song_info['title']}\n\n"
                f"**Duration:** {song_info['duration']}\n\n"
                f"**Requested by:** {song_info['requester']}",
                disable_web_page_preview=True
            )

            # Wait for the song to finish
            await asyncio.sleep(song_info['duration_seconds'])

            # End playback and skip first, then delete the file
            chat_containers[chat_id].pop(0)
            await call_py.leave_call(chat_id)
            await asyncio.sleep(3)
            os.remove(file_path)
        except Exception as e:
            print(f"Error while playing or skipping songs: {e}")

    # If the queue is empty, leave the voice chat
    if chat_id in chat_containers and not chat_containers[chat_id]:
        await call_py.leave_call(chat_id)

# Command to stop the bot from playing
@app.on_message(filters.command("stop"))
async def stop_handler(client, message):
    chat_id = message.chat.id
    if chat_id in chat_containers:
        for song in chat_containers[chat_id]:
            try:
                os.remove(song['file_path'])
            except Exception as e:
                print(f"Error deleting file: {e}")
        chat_containers.pop(chat_id)  # Clear the chat-specific queue
    await call_py.leave_call(chat_id)
    await message.reply("⏹ Stopped the music and cleared the queue.")

# Command to pause the stream
@app.on_message(filters.command("pause"))
async def pause_handler(client, message):
    await call_py.pause_stream(message.chat.id)
    await message.reply("⏸ Paused the stream.")

# Command to resume the stream
@app.on_message(filters.command("resume"))
async def resume_handler(client, message):
    await call_py.resume_stream(message.chat.id)
    await message.reply("▶️ Resumed the stream.")

# Command to skip the current song
@app.on_message(filters.command("skip"))
async def skip_handler(client, message):
    chat_id = message.chat.id

    if chat_id not in chat_containers or not chat_containers[chat_id]:
        await message.reply("❌ No songs in the queue to skip.")
        return

    # Remove the current song from the chat-specific queue
    skipped_song = chat_containers[chat_id].pop(0)

    # End playback and skip first, then delete the file
    await call_py.leave_call(chat_id)
    await asyncio.sleep(3)
    try:
        os.remove(skipped_song['file_path'])
    except Exception as e:
        print(f"Error deleting file: {e}")

    if not chat_containers[chat_id]:  # If no songs left in the queue
        await message.reply(f"⏩ Skipped **{skipped_song['title']}**.\n\n🎵 No more songs in the queue.")
    else:
        # Play the next song in the queue
        await message.reply(f"⏩ Skipped **{skipped_song['title']}**.\n\n🎵 Playing the next song...")
        await skip_to_next_song(chat_id)

@app.on_message(
    filters.command(["join"], "/")
)
async def join(client: Client, message: Message):
    tex = message.command[1] if len(message.command) > 1 else message.chat.id
    g = await message.reply_text("`Processing...`")
    try:
        await client.join_chat(tex)
        await g.edit(f"**Successfully Joined Chat ID** `{tex}`")
    except Exception as ex:
        await g.edit(f"**ERROR:** \n\n{str(ex)}")


# Start PyTgCalls and the Pyrogram Client
call_py.start()
print("Bot is running. Use /play to search and stream music.")
idle()

