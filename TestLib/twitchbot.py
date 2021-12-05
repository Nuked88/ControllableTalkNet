import os
from twitchio.ext import commands
from dotenv import load_dotenv

load_dotenv()




from twitchio.ext import commands


class Bot(commands.Bot):

    def __init__(self):
        # Initialise our Bot with our access token, prefix and a list of channels to join on boot...
        super().__init__(token=os.environ['TMI_TOKEN'],
                            client_id=os.environ['CLIENT_ID'],
                            nick=os.environ['BOT_NICK'],
                            prefix="!",
                            initial_channels=[os.environ['CHANNEL']])

    async def event_ready(self):
        # We are logged in and ready to chat and use commands...
        print(f'Logged in as | {self.nick}')


    async def event_message(self, message):
        # This is where we handle all of our commands...
        if message.content.startswith('@aki '):
            await message.channel.send('Hello!')
            print(message.content)
            print(message.author.name)
        #await self.handle_commands(message)


    @commands.command(name='aki', aliases=['t'])
    async def hello_command(ctx, *, message,mm):
        print(mm)
        await ctx.send(message)

bot = Bot()
bot.run()
