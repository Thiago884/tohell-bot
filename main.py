# main.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, HTTPException
import os
import asyncio
from flask import Flask, send_from_directory
from threading import Thread
from collections import defaultdict
import traceback
from datetime import datetime, timedelta
import pytz
import random  # Import random for backoff jitter
from boss_commands import setup_boss_commands
from drops import setup_drops_command
from database import init_db, load_db_data
import logging
from slash_commands import setup_slash_commands

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações - Substitua com seus valores
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # ID do canal de notificações
GUILD_ID = 1152651838651371520  # ID do servidor para sync rápido (opcional, None para global)

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

# Estruturas de dados
BOSSES = [
    "Super Red Dragon", "Hell Maine", "Illusion of Kundun",
    "Death Beam Knight", "Genocider", "Phoenix of Darkness",
    "Hydra", "Rei Kundun"
]

# Inicializa apenas com estrutura básica, as salas serão carregadas do banco
boss_timers = {boss: {} for boss in BOSSES}

user_stats = defaultdict(lambda: {
    'count': 0,
    'last_recorded': None,
    'username': 'Unknown'
})

user_notifications = defaultdict(list)
table_message = None

async def load_all_salas():
    """Carrega todas as salas do banco de dados"""
    from database import get_all_salas_from_db
    salas = await get_all_salas_from_db()
    
    if not salas:
        # Se não houver salas no banco, usa as padrão
        salas = [1, 2, 3, 4, 5, 6, 7, 8]
    
    for boss in BOSSES:
        # Para cada boss, criar estrutura ordenada
        boss_timers[boss] = {}
        for sala in sorted(salas):  # Ordenar salas
            boss_timers[boss][sala] = {
                'death_time': None,
                'respawn_time': None,
                'closed_time': None,
                'recorded_by': None,
                'opened_notified': False
            }

@bot.event
async def on_connect():
    logger.info("✅ Conectado ao Discord")

@bot.event
async def on_disconnect():
    logger.warning("⚠ Desconectado do Discord")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Erro no evento {event}: {args} {kwargs}", exc_info=True)

@bot.event
async def on_ready():
    """Evento disparado quando o bot está pronto"""
    logger.info("\n" + "="*50)
    logger.info(f'✅ Bot conectado como: {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'🕒 Hora do servidor: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}')
    logger.info("="*50 + "\n")
    
    # Verifica o canal de notificação
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        logger.info(f'📢 Canal de notificações: #{channel.name} (ID: {channel.id})')
        
        global table_message
        table_message = None
        try:
            from boss_commands import update_table
            table_message = await update_table(
                bot, channel, boss_timers, 
                user_stats, user_notifications, 
                table_message, NOTIFICATION_CHANNEL_ID
            )
            logger.info("✅ Tabela enviada com sucesso no canal!")
        except Exception as e:
            logger.error(f"❌ Erro ao enviar tabela inicial: {e}")
            traceback.print_exc()
    else:
        logger.error(f'⚠ ATENÇÃO: Canal de notificação (ID: {NOTIFICATION_CHANNEL_ID}) não encontrado!')
    
    await bot.change_presence(activity=discord.Game(name="Use /bosshelp"))

    # Sincronização de comandos - MODIFICADO
    try:
        # Primeiro sincroniza globalmente
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)} comandos slash sincronizados globalmente")

        # Depois sincroniza no servidor específico (se GUILD_ID estiver definido)
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced_guild = await bot.tree.sync(guild=guild)
            logger.info(f"✅ {len(synced_guild)} comandos sincronizados no servidor")
    except Exception as e:
        logger.error(f"❌ Erro ao sincronizar comandos: {e}")
        traceback.print_exc()

    # Inicialização do banco de dados
    logger.info("\nInicializando banco de dados...")
    try:
        await init_db()
        await load_db_data(boss_timers, user_stats, user_notifications)
        
        # CARREGUE TODAS AS SALAS DO BANCO
        await load_all_salas()
        
        logger.info("✅ Dados carregados com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}")
        traceback.print_exc()
    
    # Configura comandos
    logger.info("\nConfigurando comandos...")
    try:
        boss_funcs = await setup_boss_commands(
            bot, boss_timers, user_stats, 
            user_notifications, table_message, NOTIFICATION_CHANNEL_ID
        )
        
        await setup_slash_commands(
            bot, boss_timers, user_stats, user_notifications,
            table_message, NOTIFICATION_CHANNEL_ID, *boss_funcs
        )
        
        await setup_drops_command(bot)
        logger.info("✅ Comandos configurados com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao configurar comandos: {e}")
        traceback.print_exc()
    
    logger.info("\n✅ Bot totalmente inicializado e pronto para uso!")

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Sincroniza comandos slash"""
    if not ctx.message.content.strip() == '!sync':
        return  # Ignora se não for exatamente !sync
    
    try:
        synced = await bot.tree.sync()
        msg = f"✅ {len(synced)} comandos sincronizados globalmente"
        
        if ctx.guild:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced_guild = await bot.tree.sync(guild=ctx.guild)
            msg += f"\n✅ {len(synced_guild)} comandos sincronizados neste servidor"
        
        await ctx.send(msg)
    except Exception as e:
        await ctx.send(f"❌ Erro ao sincronizar comandos: {e}")
        traceback.print_exc()

def keep_alive():
    """Inicia o servidor Flask"""
    t = Thread(target=run_flask, daemon=True)
    t.start()

async def shutdown_sequence():
    """Executa o desligamento limpo"""
    logger.info("\n🛑 Iniciando sequência de desligamento...")
    
    # Cancela tasks específicas do bot
    if hasattr(bot, 'boss_commands_shutdown'):
        await bot.boss_commands_shutdown()
    
    # Cancela outras tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info("✅ Sequência de desligamento concluída")

async def main():
    keep_alive()
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("\n❌ ERRO: Token não encontrado!")
        return
    
    logger.info("\n🔑 Iniciando bot...")
    
    max_attempts = 5
    base_delay = 5
    
    try:
        for attempt in range(max_attempts):
            try:
                await bot.start(token)
                # Se o bot.start() retornar, significa uma desconexão graciosa
                logger.info("Bot desconectado graciosamente.")
                break
                    
            except discord.HTTPException as e:
                if e.status == 429 and attempt < max_attempts - 1:
                    wait_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Rate limit atingido na inicialização. "
                        f"Tentando novamente em {wait_time:.2f} segundos... (Tentativa {attempt + 1}/{max_attempts})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Erro HTTP na conexão: {e}. Desistindo.")
                    raise
        else:
            logger.error("❌ Número máximo de tentativas de conexão atingido. Não foi possível conectar ao Discord.")

    except KeyboardInterrupt:
        logger.info("\n🛑 Desligamento solicitado pelo usuário")
    except discord.LoginFailure:
        logger.error("❌ Falha no login: Token inválido ou privilégios de 'Intents' não habilitados.")
    except discord.HTTPException:
        logger.error("Falha na conexão com o Discord após múltiplas tentativas.")
    except Exception as e:
        logger.error(f"\n❌ Erro fatal: {type(e).__name__}: {e}", exc_info=True)
    finally:
        await shutdown_sequence()
        if not bot.is_closed():
            await bot.close()
        logger.info("✅ Bot desligado corretamente")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Execução interrompida pelo usuário")
    except Exception as e:
        logger.error(f"\n❌ Erro fatal: {e}", exc_info=True)