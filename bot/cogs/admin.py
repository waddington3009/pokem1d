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
        # Todos os comandos deste cog exigem servidor.
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # ------------------------------------------------------------------
    @commands.command(name="config", aliases=["settings", "configuracao"])
    @commands.has_guild_permissions(manage_guild=True)
    async def config_cmd(self, ctx: commands.Context) -> None:
        """Mostra a configuração atual do servidor."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            prefix = guild.prefix or settings.default_prefix
            redirect = f"<#{guild.redirect_channel_id}>" if guild.redirect_channel_id else "—"
            game_ch = f"<#{guild.game_channel_id}>" if guild.game_channel_id else "— (qualquer canal)"
            blacklist = ", ".join(f"<#{c}>" for c in guild.blacklist) or "—"
            enabled = "✅ Ativados" if guild.spawns_enabled else "🚫 Desativados"
            lang = guild.language

        embed = embeds.info_text("", title=f"⚙️ Configuração — {ctx.guild.name}")
        embed.add_field(name="Prefixo", value=f"`{prefix}`", inline=True)
        embed.add_field(name="Idioma", value=lang, inline=True)
        embed.add_field(name="Spawns", value=enabled, inline=True)
        embed.add_field(name="Canal de comandos", value=game_ch, inline=False)
        embed.add_field(name="Canal de redirecionamento", value=redirect, inline=False)
        embed.add_field(name="Canais bloqueados", value=blacklist, inline=False)
        embed.set_footer(text=f"Use {prefix}help Administração para ver os comandos.")
        await ctx.send(embed=embed)

    @commands.command(name="setprefix", aliases=["prefix"])
    @commands.has_guild_permissions(manage_guild=True)
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
    @commands.has_guild_permissions(manage_guild=True)
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
    @commands.has_guild_permissions(manage_guild=True)
    async def unredirect(self, ctx: commands.Context) -> None:
        """Remove o redirecionamento — spawns voltam a ocorrer em qualquer canal."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.redirect_channel_id = None
        await ctx.send(embed=embeds.ok_embed(
            "Redirecionamento removido", "Os pokémon podem aparecer em qualquer canal liberado."
        ))

    @commands.command(name="setchannel", aliases=["canal", "gamechannel", "travarcanal"])
    @commands.has_guild_permissions(manage_guild=True)
    async def setchannel(self, ctx: commands.Context,
                         canal: discord.TextChannel | None = None) -> None:
        """Trava os comandos do bot (e os spawns) em um único canal."""
        canal = canal or ctx.channel
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.game_channel_id = canal.id
            guild.redirect_channel_id = canal.id  # spawns também só aqui
        self.bot.set_game_channel_cache(ctx.guild.id, canal.id)
        await ctx.send(embed=embeds.ok_embed(
            "Canal de jogo definido",
            f"🎮 Agora os comandos e os spawns só funcionam em {canal.mention}.\n"
            f"Para liberar de novo, use `{ctx.prefix}unsetchannel`.",
        ))

    @commands.command(name="unsetchannel", aliases=["destravarcanal", "freechannel"])
    @commands.has_guild_permissions(manage_guild=True)
    async def unsetchannel(self, ctx: commands.Context) -> None:
        """Remove a trava de canal — comandos voltam a funcionar em qualquer canal."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.game_channel_id = None
        self.bot.set_game_channel_cache(ctx.guild.id, None)
        await ctx.send(embed=embeds.ok_embed(
            "Trava removida",
            "Os comandos voltaram a funcionar em qualquer canal. "
            "(O redirecionamento de spawns continua como estava — use `unredirect` se quiser soltar.)",
        ))

    @commands.command(name="togglespawns")
    @commands.has_guild_permissions(manage_guild=True)
    async def togglespawns(self, ctx: commands.Context) -> None:
        """Ativa/desativa os spawns no servidor."""
        async with session_scope() as session:
            guild = await get_or_create_guild(session, ctx.guild.id)
            guild.spawns_enabled = not guild.spawns_enabled
            estado = guild.spawns_enabled
        msg = "ativados ✅" if estado else "desativados 🚫"
        await ctx.send(embed=embeds.ok_embed("Spawns", f"Spawns {msg}."))

    @commands.command(name="blacklist")
    @commands.has_guild_permissions(manage_guild=True)
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
    @commands.has_guild_permissions(manage_guild=True)
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
