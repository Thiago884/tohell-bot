import discord
from discord.ext import commands, tasks
from discord import app_commands, HTTPException
import os
import asyncio
from flask import Flask
from threading import Thread
from collections import defaultdict
import traceback
from datetime import datetime
from bot_commands import setup_bot_commands
from database import init_db, load_db_data, connect_db

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
    if bot.is_ready():
        return "Bot is online and ready", 200
    else:
        return "Bot is connecting", 503

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

async def test_db_connection():
    """Testa a conexão com o banco de dados"""
    try:
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST', '192.185.214.113'),
            user=os.getenv('DB_USER', 'thia5326_tohell'),
            password=os.getenv('DB_PASSWORD', 'Thi@goba1102@@'),
            database=os.getenv('DB_NAME', 'thia5326_tohell_bot'),
            connect_timeout=5
        )
        if conn.is_connected():
            print("✅ Conexão com o banco de dados estabelecida com sucesso!")
            conn.close()  # Fechar a conexão após o teste
            return True
        else:
            print("❌ Falha ao conectar ao banco de dados")
            return False
    except mysql.connector.Error as e:
        print(f"❌ Falha ao conectar ao banco de dados: {e}")
        traceback.print_exc()
        return False

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
        traceback.print_exc()
    
    # Inicialização do banco de dados
    print("\nInicializando banco de dados...")
    try:
        db_initialized = await init_db()
        if db_initialized:
            loaded = await load_db_data(boss_timers, user_stats, user_notifications)
            if loaded:
                print("✅ Banco de dados pronto!")
            else:
                print("⚠ Dados não puderam ser carregados - usando dados em memória")
        else:
            print("⚠ Tabelas não puderam ser inicializadas - usando dados em memória")
    except Exception as e:
        print(f"❌ Erro ao inicializar banco de dados: {e}")
        traceback.print_exc()
        print("⚠ O bot funcionará com dados em memória apenas")
    
    # Configura comandos e tasks
    print("\nConfigurando comandos...")
    await setup_bot_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID)
    
    print("\n✅ Bot totalmente inicializado e pronto para uso!")

@bot.event
async def on_disconnect():
    """Fecha o pool de conexões ao desconectar"""
    await close_pool()
    print("⚠ Bot desconectado - pool de conexões fechado")

@bot.tree.command(name="teste", description="Verifica se o bot está respondendo")
async def teste(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Bot funcionando corretamente!", ephemeral=True)

@bot.command()
async def ping(ctx):
    await ctx.send(f'🏓 Pong! Latência: {round(bot.latency * 1000)}ms')

def keep_alive():
    """Inicia o servidor Flask em thread separada"""
    t = Thread(target=run_flask, daemon=True)
    t.start()

if __name__ == "__main__":
    keep_alive()
    
    # Testar conexão com o banco antes de iniciar o bot
    print("\n🔍 Testando conexão com o banco de dados...")
    loop = asyncio.get_event_loop()
    db_ok = loop.run_until_complete(test_db_connection())
    
    if not db_ok:
        print("\n❌ ATENÇÃO: Não foi possível conectar ao banco de dados!")
        print("O bot funcionará com dados em memória apenas")
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("\n❌ ERRO: Token não encontrado!")
        print("Verifique se você configurou a variável de ambiente 'DISCORD_TOKEN'")
        exit(1)
    
    print("\n🔑 Token encontrado, iniciando bot...")
    try:
        bot.run(token)
    except discord.LoginError:
        print("\n❌ Falha no login: Token inválido!")
    except Exception as e:
        print(f"\n❌ Erro inesperado: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        print("\n🛑 Bot encerrado")