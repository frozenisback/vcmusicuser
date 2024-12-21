from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream
import yt_dlp
import asyncio
import logging

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Your session string
STRING_SESSION = "BQHDLbkATTZi0QsIFyqEzgBd6ozQFbLXwfB0geUsx2EKEOnoU8m6-RnMgaRyQAZZaFbIwfkJ9p9Bgc5h2cqFt3d7BP5nB8dUC5AYozOE4vTtp16HburpQtZ0DVxpE6Nk0fw2UMPUuq1R0zVHjtF8KPcjms0xM1zxdhJkP1UuLDNuCA_y9ectk0jX-IRlj2KnypLHFT9KacpLot-fGYC8ZHSM-bDn25XhDA9r8Cn8fymmQAwxsJjs4rrpPETVZ_e5T29iPtyVamdeUY0BC9X6qL5xCp7kUYQJEcfW1XTvB9n_qZqhq5tzPikB-XoOhhYufPQfqCsR9R2QyaplODWyKHjwPJcxbAAAAAG4QLY7AA"

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

# Command to search and play audio
@app.on_message(filters.regex(r'^/play (?P<query>.+)'))
async def play_handler(client, message):
    query = message.matches[0]['query']  # Extract query from the command
    await_message = await message.reply("🔎 Searching for the song...")

    try:
        # Perform YouTube search
        video_result = await search_youtube(query)
        video_url = video_result['webpage_url']
        video_title = video_result['title']

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
            await await_message.edit("❌ Failed to retrieve the audio file from the bot.")
            return

        # Download the audio file locally
        audio_file_path = await bot_response.download()

        # Play the audio file in the voice chat using cookies
        await call_py.play(
            message.chat.id,
            MediaStream(
                audio_file_path,
                AudioQuality.HIGH,
                ytdlp_parameters=f"--cookies {COOKIES_FILE}"  # Pass cookies to yt-dlp
            )
        )

        # Edit message with the title of the audio being played
        await await_message.edit(
            f"🎶 Now Playing: [{video_title}]({video_url})",
            disable_web_page_preview=True
        )

        # Clean up chat messages
        await asyncio.gather(
            forwarded_message.delete(),
            bot_response.delete(),
            await_message.delete()
        )
    except Exception as e:
        logging.error(f"Error in play_handler: {e}")
        await await_message.edit(f"❌ Failed to play the song. Error: {str(e)}")

# Command to stop the bot from playing
@app.on_message(filters.command("stop"))
async def stop_handler(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        await message.reply("🛑 Stopped the music and left the voice chat.")
    except Exception as e:
        logging.error(f"Error in stop_handler: {e}")
        await message.reply(f"❌ Failed to stop the music. Error: {str(e)}")

# Start the bot with a restart loop
while True:
    try:
        call_py.start()
        logging.info("Bot is running. Use the command /play <song name> to search and stream music.")
        idle()
    except Exception as e:
        logging.error(f"Bot crashed with error: {e}. Restarting...")
        asyncio.sleep(5)  # Wait before restarting
