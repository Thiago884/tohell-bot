# views.py
import discord
from discord.ui import Button, View
from datetime import datetime, timedelta
import pytz
from shared_functions import get_boss_by_abbreviation, format_time_remaining, parse_time_input, validate_time
from database import save_timer, save_user_stats, clear_timer, add_user_notification, remove_user_notification

brazil_tz = pytz.timezone('America/Sao_Paulo')

class BossControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Anotar Horário", style=discord.ButtonStyle.green, custom_id="boss_control:anotar", emoji="📝")
    async def boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                modal = AnotarBossModal()
                await interaction.response.send_modal(modal)
            else:
                await interaction.followup.send("Por favor, tente novamente.", ephemeral=True)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de anotar: {str(e)}")
            traceback.print_exc()
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Ocorreu um erro ao abrir o formulário.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Ocorreu um erro ao abrir o formulário.",
                        ephemeral=True
                    )
            except Exception as e:
                print(f"Erro ao enviar mensagem de erro: {e}")
    
    @discord.ui.button(label="Limpar Boss", style=discord.ButtonStyle.red, custom_id="boss_control:limpar", emoji="❌")
    async def clear_boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                modal = LimparBossModal()
                await interaction.response.send_modal(modal)
            else:
                await interaction.followup.send("Por favor, tente novamente.", ephemeral=True)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de limpar: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
            except:
                pass
    
    @discord.ui.button(label="Próximos", style=discord.ButtonStyle.blurple, custom_id="boss_control:proximos", emoji="⏳")
    async def next_bosses_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            embed = await create_next_bosses_embed()
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de próximos bosses: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao buscar os próximos bosses.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Ranking", style=discord.ButtonStyle.blurple, custom_id="boss_control:ranking", emoji="🏆")
    async def ranking_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            embed = await create_ranking_embed()
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de ranking: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao gerar o ranking.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Notificações", style=discord.ButtonStyle.gray, custom_id="boss_control:notificacoes", emoji="🔔")
    async def notifications_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                modal = NotificationModal()
                await interaction.response.send_modal(modal)
            else:
                await interaction.followup.send("Por favor, tente novamente.", ephemeral=True)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de notificações: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
            except:
                pass
    
    @discord.ui.button(label="Histórico", style=discord.ButtonStyle.gray, custom_id="boss_control:historico", emoji="📜")
    async def history_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            embed = await create_history_embed()
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de histórico: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao buscar o histórico.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Não Anotados", style=discord.ButtonStyle.red, custom_id="boss_control:nao_anotados", emoji="❌")
    async def unrecorded_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            embed = await create_unrecorded_embed()
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de não anotados: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao buscar os bosses não anotados.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Backup", style=discord.ButtonStyle.gray, custom_id="boss_control:backup", emoji="💾")
    async def backup_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            else:
                await interaction.followup.send("Processando backup...", ephemeral=True)
            
            if not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ Apenas administradores podem usar esta função.", ephemeral=True)
                return
            
            view = discord.ui.View(timeout=60)
            
            backup_button = discord.ui.Button(label="Criar Backup", style=discord.ButtonStyle.green)
            restore_button = discord.ui.Button(label="Restaurar Backup", style=discord.ButtonStyle.red)
            
            async def backup_callback(interaction: discord.Interaction):
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                backup_file = create_backup()
                if backup_file:
                    try:
                        with open(backup_file, 'rb') as f:
                            await interaction.followup.send(
                                f"✅ Backup criado com sucesso!",
                                file=discord.File(f, filename=backup_file),
                                ephemeral=True
                            )
                    except Exception as e:
                        await interaction.followup.send(
                            f"✅ Backup criado, mas erro ao enviar arquivo: {e}",
                            ephemeral=True
                        )
                else:
                    await interaction.followup.send(
                        "❌ Falha ao criar backup!",
                        ephemeral=True
                    )
            
            async def restore_callback(interaction: discord.Interaction):
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                
                backup_files = [f for f in os.listdir() if f.startswith('backup_') and f.endswith('.json')]
                if not backup_files:
                    await interaction.followup.send("Nenhum arquivo de backup encontrado.", ephemeral=True)
                    return
                
                select_view = discord.ui.View(timeout=120)
                select = discord.ui.Select(
                    placeholder="Selecione um backup para restaurar",
                    options=[discord.SelectOption(label=f) for f in backup_files]
                )
                
                async def restore_selected(interaction: discord.Interaction):
                    if not interaction.response.is_done():
                        await interaction.response.defer(ephemeral=True)
                    backup_file = select.values[0]
                    
                    if restore_backup(backup_file):
                        load_db_data(boss_timers, user_stats, user_notifications)
                        
                        await interaction.followup.send(
                            f"✅ Backup **{backup_file}** restaurado com sucesso!",
                            ephemeral=True
                        )
                        
                        await update_table(interaction.channel)
                    else:
                        await interaction.followup.send(
                            f"❌ Falha ao restaurar backup **{backup_file}**!",
                            ephemeral=True
                        )
                
                select.callback = restore_selected
                select_view.add_item(select)
                
                await interaction.followup.send(
                    "Selecione o backup para restaurar:",
                    view=select_view,
                    ephemeral=True
                )
            
            backup_button.callback = backup_callback
            restore_button.callback = restore_callback
            view.add_item(backup_button)
            view.add_item(restore_button)
            
            await interaction.followup.send(
                "Selecione uma opção de backup:",
                view=view,
                ephemeral=True
            )
        except Exception as e:
            print(f"ERRO DETALHADO no botão de backup: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
            except:
                pass