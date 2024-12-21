from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream
import yt_dlp
import asyncio

# Your session string
STRING_SESSION = "BQHDLbkAHmvy_8YL3jhi8yMQciHrELqqQR7tGwcww1TgICIpOVKdFE53nfI4l3RNwciZydLZ_zZlukn_OKnomoPo3NmHAwBcBCPgSvTGEc_SQElYpqQVZQRWH3ZngoeHI5td1MP_IKnkcsxW7-GW1kO0zic2NcoeiTBbAWqjp-UoSw8y7WlsRSFvERNlxN6_N7aevH0Y6gjSnCRpYMXUUO1Cghx015zuo7rN9m0YW_YhJApLCE11QYV_IzHcKF1N9SoG3xFQdZ2pup15ntW6HFNtEoenxRjvcbCyG9YB8Wpcx5jlb67pFFl2NypdQQbJ6v59Hgku62VOFEFKoNNaHmYLUHsFoAAAAAG4QLY7AA"

# Initialize Pyrogram Client with StringSession
app = Client("test", session_string=STRING_SESSION)

# Initialize PyTgCalls
call_py = PyTgCalls(app)

# Function to search for a video on YouTube using yt-dlp
async def search_youtube(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(query, download=False)
        return results['entries'][0]  # Return the first search result

# Command to search and play audio
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
            await await_message.edit("❌ Failed to retrieve the audio file from the api")
            return

        # Download the audio file locally
        audio_file_path = await bot_response.download()

        # Play the audio file in the voice chat
        await call_py.play(
            message.chat.id,
            MediaStream(
                audio_file_path,
                AudioQuality.HIGH
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
        await await_message.edit(f"❌ Failed to play the song. Error: {str(e)}")

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

