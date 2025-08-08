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
import signal
import aiohttp
import random
import logging
from boss_commands import setup_boss_commands
from drops import setup_drops_command
from database import init_db, load_db_data
from slash_commands import setup_slash_commands

# Configuração avançada de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Mais detalhes nos logs

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
    return "Bot is online and ready" if hasattr(bot, 'is_ready') and bot.is_ready() else "Bot is connecting", 200

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Configuração do Bot Discord com tratamento melhorado de sessão HTTP
intents = discord.Intents.all()

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_closed = False
        self._tasks_started = False
        self.start_time = datetime.now()

    async def setup_hook(self):
        """Configuração inicial do bot com tratamento de sessão HTTP"""
        logger.info("Configurando hook inicial...")

        # O discord.py cria uma sessão HTTP padrão. Para usar uma sessão customizada,
        # primeiro guardamos uma referência à sessão antiga.
        old_session = self.http._HTTPClient__session

        # Em seguida, criamos nossa nova sessão e a atribuímos ao cliente HTTP do bot.
        timeout = aiohttp.ClientTimeout(total=60)
        self.http._HTTPClient__session = aiohttp.ClientSession(timeout=timeout)
        logger.debug("Sessão HTTP personalizada criada e atribuída.")

        # Finalmente, fechamos a sessão antiga para evitar vazamentos de recursos.
        if old_session:
            await old_session.close()
            logger.debug("Sessão HTTP padrão fechada com sucesso.")

        logger.info("Hook inicial configurado com sucesso.")

    async def close(self):
        """Fechamento limpo do bot"""
        if self._is_closed:
            return

        logger.info("Iniciando fechamento limpo do bot...")
        self._is_closed = True

        # A chamada a super().close() já cuida do fechamento da sessão HTTP
        # que foi atribuída em setup_hook.
        logger.debug("Chamando close() da classe pai para finalizar a conexão...")
        await super().close()
        logger.info("Bot fechado corretamente.")

    async def on_error(self, event, *args, **kwargs):
        logger.error(f'Erro no evento {event}:', exc_info=True)

bot = MyBot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

# Inicialização dos bosses
BOSSES = [
    "Super Red Dragon", "Hell Maine", "Illusion of Kundun",
    "Death Beam Knight", "Genocider", "Phoenix of Darkness",
    "Hydra", "Rei Kundun", "Erohim"
]

# Modificar a estrutura inicial dos bosses
boss_timers = {}
special_bosses_with_20 = ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim"]

for boss in BOSSES:
    # Erohim só tem sala 20
    if boss == "Erohim":
        boss_timers[boss] = {
            20: {
                'death_time': None,
                'respawn_time': None,
                'closed_time': None,
                'recorded_by': None,
                'opened_notified': False
            }
        }
    else:
        # Inicializa com salas 1-8 para todos os bosses
        boss_timers[boss] = {
            sala: {
                'death_time': None,
                'respawn_time': None,
                'closed_time': None,
                'recorded_by': None,
                'opened_notified': False
            }
            for sala in range(1, 9)  # Salas 1-8 para todos os bosses normais
        }

        # Adiciona sala 20 apenas para bosses especiais
        if boss in special_bosses_with_20:
            boss_timers[boss][20] = {
                'death_time': None,
                'respawn_time': None,
                'closed_time': None,
                'recorded_by': None,
                'opened_notified': False
            }

    # Log detalhado para verificar as salas de cada boss
    logger.debug(f"Boss '{boss}' carregado com salas: {list(boss_timers[boss].keys())}")

user_stats = defaultdict(lambda: {
    'count': 0,
    'last_recorded': None,
    'username': 'Unknown'
})

user_notifications = defaultdict(list)
table_message = None

async def sync_commands(bot, force=False):
    """Sincroniza comandos slash com tratamento de comandos já registrados"""
    try:
        logger.info("Iniciando sincronização de comandos...")

        # Sincronizar comandos globais
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)} comandos slash sincronizados globalmente")

        # Sincronizar comandos de guild específica se configurado
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced_guild = await bot.tree.sync(guild=guild)
            logger.info(f"✅ {len(synced_guild)} comandos sincronizados no servidor")

    except Exception as e:
        logger.error(f"❌ Erro ao sincronizar comandos: {e}", exc_info=True)
        # Tentar novamente em 5 segundos
        await asyncio.sleep(5)
        await sync_commands(bot, force=True)

@bot.event
async def on_ready():
    """Evento disparado quando o bot está pronto"""
    logger.info("\n" + "="*50)
    logger.info(f'✅ Bot conectado como: {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'🕒 Hora do servidor: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}')
    logger.info(f'⏱ Tempo de inicialização: {(datetime.now() - bot.start_time).total_seconds():.2f} segundos')
    logger.info("="*50 + "\n")

    # Adiciona um delay inicial para evitar rate limits
    await asyncio.sleep(5)

    # Sincronização de comandos slash - limpa comandos existentes primeiro
    logger.info("Limpando comandos existentes...")
    bot.tree.clear_commands(guild=None)
    if GUILD_ID:
        bot.tree.clear_commands(guild=discord.Object(id=GUILD_ID))

    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)} comandos slash sincronizados globalmente")

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced_guild = await bot.tree.sync(guild=guild)
            logger.info(f"✅ {len(synced_guild)} comandos sincronizados no servidor")
    except Exception as e:
        logger.error(f"❌ Erro ao sincronizar comandos: {e}", exc_info=True)

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
            logger.error(f"❌ Erro ao enviar tabela inicial: {e}", exc_info=True)
    else:
        logger.error(f'⚠ ATENÇÃO: Canal de notificação (ID: {NOTIFICATION_CHANNEL_ID}) não encontrado!')

    await bot.change_presence(activity=discord.Game(name="Use /bosshelp"))

    # Inicialização do banco de dados
    logger.info("\nInicializando banco de dados...")
    try:
        await init_db()
        await load_db_data(boss_timers, user_stats, user_notifications)
        logger.info("✅ Dados carregados com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}", exc_info=True)

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
        logger.error(f"❌ Erro ao configurar comandos: {e}", exc_info=True)

    logger.info("\n✅ Bot totalmente inicializado e pronto para uso!")
    logger.info(f"⏱ Tempo total de inicialização: {(datetime.now() - bot.start_time).total_seconds():.2f} segundos")

@bot.event
async def on_command_error(ctx, error):
    """Evento disparado quando ocorre um erro em um comando"""
    if isinstance(error, commands.NotOwner):
        await ctx.send("❌ Apenas o dono do bot pode usar este comando!")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignora erros de comando não encontrado
    else:
        logger.error(f"Erro no comando {ctx.command}: {error}", exc_info=True)
        await ctx.send(f"❌ Ocorreu um erro ao executar o comando: {error}")

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Sincroniza comandos slash"""
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
        logger.info("Cancelando tasks de boss commands...")
        await bot.boss_commands_shutdown()

    # Cancela outras tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    logger.info(f"Cancelando {len(tasks)} tasks pendentes...")
    for task in tasks:
        task.cancel()

    # Espera as tasks serem canceladas
    logger.info("Aguardando tasks serem canceladas...")
    await asyncio.gather(*tasks, return_exceptions=True)

    # Fecha a sessão do bot
    if not bot.is_closed():
        logger.info("Fechando conexão do bot...")
        await bot.close()

    logger.info("✅ Sequência de desligamento concluída")

async def run_bot():
    """Função principal para executar o bot com retry backoff"""
    global bot

    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("\n❌ ERRO: Token não encontrado na variável de ambiente DISCORD_TOKEN!")
        return

    logger.info("\n🔑 Iniciando bot...")

    max_retries = 3
    base_delay = 5.0

    for attempt in range(max_retries):
        try:
            logger.info(f"\nTentativa {attempt + 1}/{max_retries} de conexão...")

            # Fechar o bot se já estiver em execução
            if not bot.is_closed():
                logger.debug("Fechando instância anterior do bot...")
                await bot.close()

            # Criar nova instância do bot para garantir limpeza
            bot = MyBot(
                command_prefix='!',
                intents=intents,
                help_command=None
            )

            logger.debug("Iniciando conexão com o Discord...")
            await bot.start(token)
            break  # Se chegou aqui, a conexão foi bem-sucedida

        except Exception as e:
            logger.error(f"❌ Erro na tentativa {attempt + 1}: {str(e)}", exc_info=True)
            if attempt == max_retries - 1:
                logger.error("❌ Falha ao conectar após várias tentativas")
                await shutdown_sequence()
                return

            wait_time = min(base_delay * (2 ** attempt), 30)  # Max 30 segundos
            logger.info(f"⏱ Esperando {wait_time:.2f} segundos antes da próxima tentativa...")
            await asyncio.sleep(wait_time)

async def shutdown_signal_handler():
    """Manipulador para sinais de desligamento"""
    logger.info("\n🛑 Recebido sinal de desligamento, iniciando sequência...")
    await shutdown_sequence()

async def main():
    """Ponto de entrada principal"""
    keep_alive()

    # Adicionar delay inicial maior para garantir que o ambiente de hospedagem se estabilize
    initial_delay = random.uniform(30, 60)  # 30-60 segundos de delay inicial
    logger.info(f"⏱ Aguardando {initial_delay:.2f} segundos antes de iniciar...")
    await asyncio.sleep(initial_delay)

    try:
        # Configurar manipulador de sinal
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown_signal_handler()))

        await run_bot()
    except Exception as e:
        logger.error(f"❌ Erro fatal na função main: {e}", exc_info=True)
    finally:
        # Garantir que o bot seja fechado corretamente
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Execução interrompida pelo usuário")
    except Exception as e:
        logger.error(f"\n❌ Erro fatal no nível superior: {e}", exc_info=True)