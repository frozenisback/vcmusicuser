from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream
import yt_dlp
import asyncio
from time import time

# Your session string
STRING_SESSION = "BQHDLbkAJatUS2ycH470F_fvXMeaF4O-ILmXUx43JZXFsAJmHI3Ej1HVazx_RhmoAHJMw01-b2JTw5GhzBcBrHSPvg2yoR20TkN0_3VkkxHqQ6Dguldlv5BDfE_TFk4fAUmaUi327GjP7ntMDa0GObKAXv-sjv7CJDFcjpF1nPi9o_FlOpiQQkjw6auHgD8hjwtWfHkeAU5sHHd1LSTUW4DgoisPqRFsE21JAtgCr_Ea_RTEAumD0zaqA5sqzAl78YU_8SNLxH39B4zWQNplNRNNwZJV5uaxiBtOLm-j60Yw37xBqfRN2I9DAHeW5HtVUc5Ytrt_88Z6Fh485jSylqIxUD67DwAAAAG4QLY7AA"

# Initialize Pyrogram Client with StringSession
app = Client("test", session_string=STRING_SESSION)

# Initialize PyTgCalls
call_py = PyTgCalls(app)

# Path to the cookies file
COOKIES_FILE = "cookies.txt"  # Ensure this file exists and contains valid cookies

# Function to search for a video on YouTube using yt-dlp
async def search_youtube(query):
    ydl_opts = {
        'format': 'worstaudio/worst',  # Download the lowest quality audio and video
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',  # Search and return the first result
        'cookiefile': COOKIES_FILE,  # Use the cookie file for authenticated requests
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(query, download=False)
        return results['entries'][0]  # Return the first search result

# Command to search and play music
@app.on_message(filters.regex(r'^/play (?P<query>.+)'))  # Responds to /play command with arguments
async def play_handler(client, message):
    query = message.matches[0]['query']  # Extract query from the command

    # Send "await" message
    await_message = await message.reply("🔎 Searching for the song...")

    try:
        # Perform YouTube search
        video_result = await search_youtube(query)
        video_url = video_result['webpage_url']
        video_title = video_result['title']

        # Play the video with cookies
        await call_py.play(
            message.chat.id,
            MediaStream(
                video_url,
                AudioQuality.HIGH,
                ytdlp_parameters=f"--cookies {COOKIES_FILE}",  # Pass cookies to yt-dlp
            ),
        )

        # Edit message with the title of the video being played
        await await_message.edit(
            f"🎶 Started playing: [{video_title}]({video_url})",
            disable_web_page_preview=True
        )
    except Exception as e:
        await await_message.edit(f"❌ Failed to play the song. Error: {str(e)}")

# Command to ping the bot
@app.on_message(filters.command("ping"))
async def ping_handler(client, message):
    start_time = time()
    response = await message.reply("🏓 Pong!")
    end_time = time()
    latency = round((end_time - start_time) * 1000)
    await response.edit(f"🏓 Bot latency is {latency}ms")

# Command to stop the bot from playing
@app.on_message(filters.command("stop"))
async def stop_handler(client, message):
    await call_py.leave_call(message.chat.id)
    await message.reply("🛑 Stopped the music and left the voice chat.")

# Start PyTgCalls and the Pyrogram Client
call_py.start()

print("Bot is running. Use the command /play <song name> to search and stream music.")

# Keep the bot running
idle()

