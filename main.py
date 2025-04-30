import discord
from discord.ext import commands
import os
import asyncio
from flask import Flask
from threading import Thread
from bot_commands import setup_bot_commands
from database import init_db, load_db_data

# Configurações do Flask para keep-alive
app = Flask('')

@app.route('/')
def home():
    return "Bot está rodando!"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    if bot.is_ready():
        return "Bot is online", 200
    else:
        return "Bot is connecting", 503

def run():
    app.run(host='0.0.0.0', port=8080, threaded=True)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Variáveis globais (serão preenchidas durante a execução)
boss_timers = {}
user_stats = {}
user_notifications = {}
table_message = None
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # ← Alterar este valor

async def run_bot():
    while True:
        try:
            print("Iniciando o bot...")
            await bot.start(token)
        except HTTPException as e:
            if e.status == 429:
                retry_after = e.response.headers.get('Retry-After', 30)
                print(f"Rate limit atingido. Tentando novamente em {retry_after} segundos...")
                await asyncio.sleep(float(retry_after))
            else:
                print(f"Erro HTTP {e.status}: {e.text}")
                await asyncio.sleep(30)
        except Exception as e:
            print(f"Erro inesperado: {e}")
            await asyncio.sleep(30)
        else:
            break

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user.name}')
    print(f'Canal de notificação configurado para ID: {NOTIFICATION_CHANNEL_ID}')
    await bot.change_presence(activity=discord.Game(name="!bosshelp para ajuda"))
    
    # Inicializa o banco de dados e carrega os dados
    init_db()
    load_db_data()
    
    # Configura os comandos e tasks
    await setup_bot_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID)
    
    # Inicia as tasks periódicas
    from bot_commands import check_boss_respawns, live_table_updater, periodic_table_update, daily_backup
    check_boss_respawns.start()
    live_table_updater.start()
    periodic_table_update.start()
    daily_backup.start()

# Iniciar o bot
if __name__ == "__main__":
    keep_alive()
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("ERRO: Token não encontrado! Verifique as Secrets do Render.")
    else:
        print("Token encontrado, iniciando bot...")
        asyncio.run(run_bot())