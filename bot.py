from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream
import yt_dlp
import asyncio
from pytgcalls import filters as fl
from pytgcalls.types import Update
from pytgcalls.types import GroupCallParticipant
from pytgcalls.types import ChatUpdate
from pyrogram.types import Message

# Your session string
STRING_SESSION = "BQHDLbkAwrcnh8Oe0R28KeHE2Bn2n3tMwKurNM8wBLOlD3q80-ayHd6Q4fgKNTdZg02QmdgNEW8WVH89PhUk5_WPJGC5l8NN5kWFBZSRZQtk9R74TR5sEVOktsw6ziw4KwlqWm1VGnibwk9A6b9PyCjuqCXOu0pvZypDcYOjBaLMU15ZB0Zph3x2mzn3VuV4VxDp51Hzwmc1VnfQ3MTCaOMQGfceoBNbD8JuGQFwrelUKbebQWpWDER59rsxLGR4CREs7xVc45raqPBVEsvE002Je1UgS4E_tMScr3Wdw8EWZYJai4fAUS49JL0Wd-Dl2rDacEF9lNhBosklWT_cc7EgYiJ5IgAAAAG4QLY7AA"

app = Client("music_bot", session_string=STRING_SESSION)

# Initialize PyTgCalls
call_py = PyTgCalls(app)

# Queue for songs
queue = {}

# Path to the cookies file
COOKIES_FILE = "cookies.txt"

# Function to search for a video on YouTube using yt-dlp
async def search_youtube(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',
        'cookiefile': COOKIES_FILE,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(query, download=False)
        return results['entries'][0]

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
        await message.reply("❓ Please provide a song name or YouTube URL to play.\nExample: `/play Shape of You`")
        return

    await_message = await message.reply("🔍 Searching for the song...")

    try:
        # Search YouTube
        video_result = await search_youtube(query)
        video_url = video_result['webpage_url']
        video_title = video_result['title']
        video_duration = video_result['duration']  # Duration in seconds
        formatted_duration = f"{video_duration // 60}m {video_duration % 60}s"

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
            return

        # Download the audio file locally
        audio_file_path = await bot_response.download()

        # Add the song to the queue
        if chat_id not in queue:
            queue[chat_id] = []
        queue[chat_id].append({
            "url": video_url,
            "title": video_title,
            "file_path": audio_file_path,
            "requester": message.from_user.mention if message.from_user else "Unknown"
        })

        # If the queue has only one song, start playing immediately
        if len(queue[chat_id]) == 1:
            await play_song(chat_id, await_message)

        else:
            await await_message.edit(
                f"✅ Added to queue:\n"
                f"**Title:** {video_title}\n"
                f"**Duration:** {formatted_duration}\n"
                f"**Requested by:** {message.from_user.mention if message.from_user else 'Unknown'}",
                disable_web_page_preview=True
            )

        # Clean up forwarded messages
        await asyncio.gather(
            forwarded_message.delete(),
            bot_response.delete(),
        )
    except Exception as e:
        await await_message.edit(f"❌ Failed to play the song. Error: {str(e)}")

# Function to play the song
async def play_song(chat_id, await_message):
    try:
        song_info = queue[chat_id][0]  # Get the first song in the queue
        file_path = song_info['file_path']

        # Play the song in the voice chat
        await call_py.play(
            chat_id,
            MediaStream(
                file_path,
            )
        )

        await await_message.edit(
            f"🎵 **Now Playing**\n"
            f"**Title:** {song_info['title']}\n"
            f"**Requested by:** {song_info['requester']}",
            disable_web_page_preview=True
        )
    except Exception as e:
        await await_message.edit(f"❌ Error playing the song: {str(e)}")

# Command to stop the bot from playing
@app.on_message(filters.command("stop"))
async def stop_handler(client, message):
    chat_id = message.chat.id
    if chat_id in queue:
        queue.pop(chat_id)  # Clear the queue
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
    
    if chat_id not in queue or not queue[chat_id]:
        await message.reply("❌ No songs in the queue to skip.")
        return

    # Remove the current song from the queue
    skipped_song = queue[chat_id].pop(0)

    if not queue[chat_id]:  # If no songs left in the queue
        await call_py.leave_call(chat_id)  # Leave the voice chat
        await message.reply(f"⏩ Skipped **{skipped_song['title']}**.\n🎵 No more songs in the queue.")
    else:
        # Play the next song in the queue
        await message.reply(f"⏩ Skipped **{skipped_song['title']}**.\n🎵 Playing the next song...")
        await play_song(chat_id, message)

@app.on_message(filters.command("ping"))
async def ping_handler(client, message):
    pings = call_py.ping
    await message.reply(f"🏓 Pong - {pings}")

@app.on_message(filters.command("cache"))
async def cache_handler(client, message):
    cached_peers = call_py.cache_peer
    await message.reply(f"🔍 Cached Peers:\n{cached_peers}")



# Start PyTgCalls and the Pyrogram Client
call_py.start()
print("Bot is running. Use /play to search and stream music.")
idle()

