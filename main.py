import discord
from discord.ext import commands, tasks
from discord import app_commands, HTTPException
import os
import asyncio
from flask import Flask, send_from_directory
from threading import Thread
from collections import defaultdict
import traceback
from datetime import datetime
from boss_commands import setup_boss_commands
from utility_commands import setup_utility_commands
from drops import setup_drops_command
from database import init_db, load_db_data
from shared_functions import get_next_bosses
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Configuração do Flask (keep-alive)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Timers de Boss - Online"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    return "Bot is online and ready" if bot.is_ready() else "Bot is connecting", 200

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Configuração do Bot Discord
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

# Variáveis Globais
BOSSES = [
    "Super Red Dragon",
    "Hell Maine",
    "Illusion of Kundun",
    "Death Beam Knight",
    "Genocider",
    "Phoenix of Darkness",
    "Hydra",
    "Rei Kundun"
]

SALAS = [1, 2, 3, 4, 5, 6, 7, 8]

# Estruturas de dados
boss_timers = {boss: {sala: {
    'death_time': None,
    'respawn_time': None,
    'closed_time': None,
    'recorded_by': None,
    'opened_notified': False
} for sala in SALAS} for boss in BOSSES}

user_stats = defaultdict(lambda: {
    'count': 0,
    'last_recorded': None,
    'username': 'Unknown'
})

user_notifications = defaultdict(list)
table_message = None
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # Substitua pelo seu canal

@bot.event
async def on_ready():
    """Evento disparado quando o bot está pronto"""
    print("\n" + "="*50)
    print(f'✅ Bot conectado como: {bot.user.name} (ID: {bot.user.id})')
    print(f'🕒 Hora do servidor: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}')
    print("="*50 + "\n")
    
    # Verifica o canal de notificação
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        print(f'📢 Canal de notificações: #{channel.name} (ID: {channel.id})')
    else:
        print(f'⚠ ATENÇÃO: Canal de notificação (ID: {NOTIFICATION_CHANNEL_ID}) não encontrado!')
    
    await bot.change_presence(activity=discord.Game(name="Digite !bosshelp"))
    
    # Sincroniza comandos slash
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos slash sincronizados")
    except Exception as e:
        print(f"❌ Erro ao sincronizar comandos slash: {e}")
    
    # Inicialização do banco de dados
    print("\nInicializando banco de dados...")
    try:
        await init_db()
        await load_db_data(boss_timers, user_stats, user_notifications)
        print("✅ Dados carregados com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao inicializar banco de dados: {e}")
        traceback.print_exc()
    
    # Configura comandos
    print("\nConfigurando comandos...")
    try:
        boss_funcs = await setup_boss_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID)
        await setup_utility_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID, *boss_funcs)
        await setup_drops_command(bot)
        print("✅ Comandos configurados com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao configurar comandos: {e}")
        traceback.print_exc()
    
    print("\n✅ Bot totalmente inicializado e pronto para uso!")

@bot.tree.command(name="teste", description="Verifica se o bot está respondendo")
async def teste(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Bot funcionando corretamente!", ephemeral=True)

@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latência: {latency}ms",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

def keep_alive():
    """Inicia o servidor Flask em thread separada"""
    t = Thread(target=run_flask, daemon=True)
    t.start()

async def main():
    keep_alive()
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("\n❌ ERRO: Token não encontrado!")
        return
    
    print("\n🔑 Iniciando bot...")
    try:
        async with bot:
            await bot.start(token)
    except Exception as e:
        print(f"\n❌ Erro: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        print("\n🛑 Finalizando bot...")
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("✅ Bot desligado")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Execução interrompida")