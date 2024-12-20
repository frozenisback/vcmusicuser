from pyrogram import Client, filters
from pytgcalls import idle, PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream
import yt_dlp
import asyncio
from time import time

# Your session string
STRING_SESSION = "BQHDLbkAE835_DiKOWitYvWY7kQ2FrDScRWQHwW4ztkLt4M14vZGI2eq6VR5tw_pHnXkaBeRpjQGTN_Vb4B_55t5h-p3fdprVJMrsBowHoHFm5JgBRNUsPsRAGoB4Peq7ZJc9we7TW_PWa0laJc4JtQnG4cBtuGekdDBo3fMAhH5nlR1cflKxFLmbaEw6m-BJWjc9xhsg-LbiyXTbH02ibK-iiDjNYTv4L3jasPZW-_3mbZhWVuI8CboBpYeI64YU_cTG3sX_LsAacMoGjurhz2mhHH7ZE8BuwsBxEBaBDTQFcH18-wG8DfPw-ozeU0XPJC8VkdFDeAX3hOL6QSK2Cpds0g0ZgAAAAHUQvNiAA"

# Initialize Pyrogram Client with StringSession
app = Client("test", session_string=STRING_SESSION)

# Initialize PyTgCalls
call_py = PyTgCalls(app)

# Function to search for a video on YouTube using yt-dlp
async def search_youtube(query):
    ydl_opts = {
        'format': 'worstaudio/worst',  # Download the lowest quality audio and video
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',  # Search and return the first result
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(query, download=False)
        return results['entries'][0]  # Return the first search result

# Command to search and play music
@app.on_message(filters.regex(r'^/play (?P<query>.+)'))  # Responds to any chat
async def play_handler(client, message):
    query = message.matches[0]['query']  # Extract query from the command

    # Send "await" message
    await_message = await message.reply("🔎 Searching for the song...")

    try:
        # Perform YouTube search
        video_result = await search_youtube(query)  # Await the coroutine properly
        video_url = video_result['webpage_url']
        video_title = video_result['title']

        # Play the video
        await call_py.play(
            message.chat.id,
            MediaStream(
                video_url,  # Set audio quality # Set video quality
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
@app.on_message(filters.regex(r'^/ping'))
async def ping_handler(client, message):
    start_time = time()  # Get the current time before sending the message
    response = await message.reply("🏓 Pong!")  # Send a reply to the user
    end_time = time()  # Get the time after the reply is sent
    latency = round((end_time - start_time) * 1000)  # Calculate the round-trip latency in ms
    await response.edit(f"🏓 Bot latency is {latency}ms")  # Edit the response with the latency


# Command to stop the bot from playing
@app.on_message(filters.regex(r'^/stop'))
async def stop_handler(client, message):
    await call_py.leave_call(message.chat.id)  # Stop the current call
    await message.reply("🛑 Stopped the music and left the voice chat.")

# Start PyTgCalls and the Pyrogram Client
call_py.start()

print("Bot is running. Use the command /play <song name> to search and stream music.")

# Keep the bot running
idle()
