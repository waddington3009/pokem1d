"""Configuração por servidor: prefixo, canal de spawn, blacklist, idioma."""
from __future__ import annotations

import discord
from discord.ext import commands

from config import settings
from bot.database.db import get_or_create_guild, session_scope
from bot.utils import embeds


class Admin(commands.Cog, name="Administração"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        # Comandos de admin: precisam de servidor E (dono do bot OU 'Gerenciar Servidor').
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if await self.bot.is_owner(ctx.author):
            return True
        if ctx.author.guild_permissions.manage_guild:
            return True
        raise commands.MissingPermissions(["manage_guild"])

    # ------------------------------------------------------------------
    @commands.command(name="config", aliases=["settings", "configuracao"])
    async def config_cmd(self, ctx: commands.Context) -> None:
        """Mostra a configuração atual do servidor."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            prefix = guild.prefix or settings.default_prefix
            redirect = f"<#{guild.redirect_channel_id}>" if guild.redirect_channel_id else "—"
            channels = self.bot._merge_channels(guild)
            game_ch = ", ".join(f"<#{c}>" for c in channels) if channels else "— (qualquer canal)"
            blacklist = ", ".join(f"<#{c}>" for c in guild.blacklist) or "—"
            enabled = "✅ Ativados" if guild.spawns_enabled else "🚫 Desativados"
            lang = guild.language
            warn = f"<#{guild.warning_channel_id}>" if guild.warning_channel_id else "—"

        embed = embeds.info_text("", title=f"⚙️ Configuração — {ctx.guild.name}")
        embed.add_field(name="Prefixo", value=f"`{prefix}`", inline=True)
        embed.add_field(name="Idioma", value=lang, inline=True)
        embed.add_field(name="Spawns", value=enabled, inline=True)
        embed.add_field(name="Canais de jogo", value=game_ch, inline=False)
        embed.add_field(name="Canal de redirecionamento", value=redirect, inline=False)
        embed.add_field(name="Canal de anúncios (raros)", value=warn, inline=False)
        embed.add_field(name="Canais bloqueados", value=blacklist, inline=False)
        embed.set_footer(text=f"Use {prefix}help Administração para ver os comandos.")
        await ctx.send(embed=embed)

    @commands.command(name="setprefix", aliases=["prefix"])
    async def setprefix(self, ctx: commands.Context, novo_prefixo: str) -> None:
        """Define o prefixo de comandos do servidor."""
        if len(novo_prefixo) > 5:
            await ctx.send(embed=embeds.err_embed("O prefixo deve ter no máximo 5 caracteres."))
            return
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.prefix = novo_prefixo
        self.bot.prefix_cache[ctx.guild.id] = novo_prefixo
        await ctx.send(embed=embeds.ok_embed(
            "Prefixo atualizado", f"Agora use `{novo_prefixo}` antes dos comandos."
        ))

    @commands.command(name="redirect", aliases=["setspawn"])
    async def redirect(self, ctx: commands.Context,
                       canal: discord.TextChannel | None = None) -> None:
        """Concentra todos os spawns em um canal específico."""
        canal = canal or ctx.channel
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.redirect_channel_id = canal.id
        await ctx.send(embed=embeds.ok_embed(
            "Redirecionamento ativado", f"Os pokémon agora aparecerão apenas em {canal.mention}."
        ))

    @commands.command(name="unredirect")
    async def unredirect(self, ctx: commands.Context) -> None:
        """Remove o redirecionamento — spawns voltam a ocorrer em qualquer canal."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.redirect_channel_id = None
        await ctx.send(embed=embeds.ok_embed(
            "Redirecionamento removido", "Os pokémon podem aparecer em qualquer canal liberado."
        ))

    @commands.command(name="setchannel", aliases=["addchannel", "canal", "gamechannel"])
    async def setchannel(self, ctx: commands.Context,
                         canal: discord.TextChannel | None = None) -> None:
        """Adiciona um canal onde o bot opera (comandos + spawns). Pode ter vários."""
        canal = canal or ctx.channel
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            channels = self.bot._merge_channels(guild)
            if canal.id in channels:
                await ctx.send(embed=embeds.err_embed(f"{canal.mention} já é um canal de jogo."))
                return
            channels.append(canal.id)
            guild.game_channels = channels
            guild.game_channel_id = None       # migra o campo legado para a lista
            guild.redirect_channel_id = None    # spawns agora seguem a lista de canais
        self.bot.set_game_channels_cache(ctx.guild.id, channels)
        lista = ", ".join(f"<#{c}>" for c in channels)
        await ctx.send(embed=embeds.ok_embed(
            "Canal adicionado! 🎮",
            f"O bot agora opera em **{len(channels)}** canal(is): {lista}\n"
            f"Para remover um, use `{ctx.prefix}unsetchannel #canal`.",
        ))

    @commands.command(name="unsetchannel", aliases=["delchannel", "destravarcanal"])
    async def unsetchannel(self, ctx: commands.Context,
                           canal: discord.TextChannel | None = None) -> None:
        """Remove um canal de jogo. Sem #canal = libera o bot em qualquer canal."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            channels = self.bot._merge_channels(guild)
            if canal is None:
                channels = []
                msg = "Trava removida — o bot opera em **qualquer** canal de novo."
            else:
                if canal.id not in channels:
                    await ctx.send(embed=embeds.err_embed(f"{canal.mention} não é um canal de jogo."))
                    return
                channels = [c for c in channels if c != canal.id]
                if channels:
                    lista = ", ".join(f"<#{c}>" for c in channels)
                    msg = f"{canal.mention} removido. Canais ativos: {lista}"
                else:
                    msg = f"{canal.mention} removido. Sem canais definidos → o bot opera em **qualquer** canal."
            guild.game_channels = channels
            guild.game_channel_id = None
        self.bot.set_game_channels_cache(ctx.guild.id, channels)
        await ctx.send(embed=embeds.ok_embed("Canais de jogo atualizados", msg))

    @commands.command(name="setwarningchannel", aliases=["setwarning", "setanuncio", "canalanuncio"])
    async def setwarningchannel(self, ctx: commands.Context,
                                canal: discord.TextChannel | None = None) -> None:
        """Define o canal onde o bot anuncia capturas raras (Super-Raro+) e shinies."""
        canal = canal or ctx.channel
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.warning_channel_id = canal.id
        await ctx.send(embed=embeds.ok_embed(
            "Canal de anúncios definido! 📢",
            f"Capturas **Super-Raras, Lendárias, Míticas** e **shinies** serão anunciadas em {canal.mention}.\n"
            f"Assim a galera vê as conquistas mesmo com o jogo no `/menu` (privado).",
        ))

    @commands.command(name="unsetwarningchannel", aliases=["unsetwarning", "removeranuncio"])
    async def unsetwarningchannel(self, ctx: commands.Context) -> None:
        """Desativa os anúncios de capturas raras."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.warning_channel_id = None
        await ctx.send(embed=embeds.ok_embed("Anúncios desativados", "As capturas raras não serão mais anunciadas."))

    @commands.command(name="togglespawns")
    async def togglespawns(self, ctx: commands.Context) -> None:
        """Ativa/desativa os spawns no servidor."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.spawns_enabled = not guild.spawns_enabled
            estado = guild.spawns_enabled
        msg = "ativados ✅" if estado else "desativados 🚫"
        await ctx.send(embed=embeds.ok_embed("Spawns", f"Spawns {msg}."))

    @commands.command(name="blacklist")
    async def blacklist(self, ctx: commands.Context, acao: str = "list",
                        canal: discord.TextChannel | None = None) -> None:
        """Bloqueia/desbloqueia canais para spawn. Uso: blacklist <add|remove|list> [#canal]."""
        acao = acao.lower()
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            bl = list(guild.blacklist or [])
            if acao == "add":
                canal = canal or ctx.channel
                if canal.id not in bl:
                    bl.append(canal.id)
                guild.blacklist = bl
                await ctx.send(embed=embeds.ok_embed("Canal bloqueado", f"{canal.mention} não terá spawns."))
            elif acao in ("remove", "rem", "del"):
                canal = canal or ctx.channel
                bl = [c for c in bl if c != canal.id]
                guild.blacklist = bl
                await ctx.send(embed=embeds.ok_embed("Canal liberado", f"{canal.mention} voltou a ter spawns."))
            else:  # list
                listed = ", ".join(f"<#{c}>" for c in bl) or "—"
                await ctx.send(embed=embeds.info_text(listed, title="🚫 Canais bloqueados"))

    @commands.command(name="setlanguage", aliases=["idioma", "lang"])
    async def setlanguage(self, ctx: commands.Context, idioma: str) -> None:
        """Define o idioma do servidor (pt | en)."""
        idioma = idioma.lower()
        if idioma not in ("pt", "en"):
            await ctx.send(embed=embeds.err_embed("Idiomas suportados: `pt`, `en`."))
            return
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.language = idioma
        await ctx.send(embed=embeds.ok_embed("Idioma", f"Idioma definido para `{idioma}`."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
