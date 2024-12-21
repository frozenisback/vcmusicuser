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

# Initialize Pyrogram Client with StringSession
app = Client("test", session_string=STRING_SESSION)

# Initialize PyTgCalls
call_py = PyTgCalls(app)

# Path to the cookies file
COOKIES_FILE = "cookies.txt"  # Ensure this file exists and contains valid cookies

# Function to search for a video on YouTube using yt-dlp
async def search_youtube(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',
        'cookiefile': COOKIES_FILE,  # Include cookies file for authenticated requests
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(query, download=False)
        return results['entries'][0]  # Return the first search result

# Command to handle /start
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply(
        "\U0001F44B **Welcome to the user Music Bot!**\n\n"
        "\U0001F3B5 Use /play [song name] to search and play music in your voice chat.\n"
        "\U0001F6D1 Use /stop to stop the music and leave the voice chat.\n\n"
        "Happy listening! \U0001F3A7"
    )

# Automatically send the start message for direct messages
@app.on_message(filters.private)
async def auto_start_handler(client, message):
    # Check if the sender is a bot
    if message.from_user.is_bot:
        return  # Ignore messages from bots
    
    await start_handler(client, message)


# Command to search and play audio
@app.on_message(filters.regex(r'^/play(?: (?P<query>.+))?$'))  # Regex for /play with or without a query
async def play_handler(client, message):
    query = message.matches[0]['query']  # Extract query from the command, if present

    if not query:
        # If no query is provided, send usage instructions
        await message.reply(
            "🎶 **How to use /play**\n\n"
            "To play a song in the voice chat, use the command like this:\n"
            "`/play <song name or YouTube URL>`\n\n"
            "Example:\n"
            "`/play Shape of You`\n"
            "or\n"
            "`/play https://youtu.be/JGwWNGJdvx8`"
        )
        return

    # Send "await" message
    await_message = await message.reply("🔍 Searching for the song...")

    try:
        # Perform YouTube search
        video_result = await search_youtube(query)
        video_url = video_result['webpage_url']
        video_title = video_result['title']
        video_duration = video_result['duration']  # Duration in seconds

        # Format duration into Mm Ss
        formatted_duration = f"{video_duration // 60}m {video_duration % 60}s"

        # Forward URL to the bot
        forwarded_message = await app.send_message("@YoutubeAudioDownloadBot", video_url)

        # Wait for the bot to respond with the audio file
        bot_response = None
        for _ in range(10):  # Retry for up to 10 iterations (adjust as needed)
            async for response in app.get_chat_history("@YoutubeAudioDownloadBot", limit=10):
                if response.audio:  # Check if the message contains an audio file
                    bot_response = response
                    break
            if bot_response:
                break
            await asyncio.sleep(2)  # Wait 2 seconds before checking again

        if not bot_response:
            await await_message.edit("❌ Failed to retrieve the audio file from the API.")
            return

        # Download the audio file locally
        audio_file_path = await bot_response.download()

        # Play the audio file in the voice chat using cookies
        await call_py.play(
            message.chat.id,
            MediaStream(
                audio_file_path,
                video_flags=MediaStream.Flags.IGNORE,
            )
        )

        # Edit message with the title, duration, and requester details
        await await_message.edit(
            f"\U0001F3B6 **Started Playing**\n"
            f"**Title:** [{video_title}]({video_url})\n"
            f"**Duration:** {formatted_duration}\n"
            f"**Requested by:** {message.from_user.mention}",
            disable_web_page_preview=True
        )

        # Clean up chat messages
        await asyncio.gather(
            forwarded_message.delete(),
            bot_response.delete(),
        )
    except Exception as e:
        await await_message.edit(f"\u274C Failed to play the song. Error: {str(e)}")

# Command to stop the bot from playing
@app.on_message(filters.command("stop"))
async def stop_handler(client, message):
    await call_py.leave_call(message.chat.id)
    await message.reply("\U0001F6D1 Stopped the music and left the voice chat.")

# Command to view cache
@app.on_message(filters.command("cache"))
async def cache_handler(client, message):
    cached_peers = call_py.cache_peer
    await message.reply(f"🔍 Cached Peers:\n{cached_peers}")

# Command to view ping
@app.on_message(filters.command("ping"))
async def ping_handler(client, message):
    pings = call_py.ping
    await message.reply(f"🏓 Pong - {pings}")

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
    
# Start PyTgCalls and the Pyrogram Client
call_py.start()

print("Bot is running. Use the command /play <song name> to search and stream music.")

# Keep the bot running
idle()

