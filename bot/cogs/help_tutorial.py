"""Ajuda bonita (p!help) e tutorial interativo (p!tutorial)."""
from __future__ import annotations

from types import SimpleNamespace

import discord
from discord.ext import commands

from config import settings
from bot.data.pokemon_data import POKEDEX
from bot.utils import embeds
from bot.utils.battle_scene import render_battle_scene
from bot.utils.explore_scene import render_explore_scene
from bot.utils.images import render_grid

# Categoria (nome do cog) -> emoji + ordem de exibição
CATEGORIES: list[tuple[str, str]] = [
    ("Geral", "ℹ️"),
    ("Exploração", "🌿"),
    ("Captura", "🎯"),
    ("Spawn", "🌟"),
    ("Coleção", "📦"),
    ("Batalha", "⚔️"),
    ("Liga", "🏆"),
    ("Evolução", "🧬"),
    ("Economia", "💰"),
    ("Itens", "🎒"),
    ("Trocas", "🔄"),
    ("Progressão", "📈"),
    ("Administração", "🛠️"),
]
_EMOJI = dict(CATEGORIES)
_HIDDEN_COGS = {"Dono"}


def _visible_commands(cog: commands.Cog) -> list[commands.Command]:
    return sorted((c for c in cog.get_commands() if not c.hidden), key=lambda c: c.name)


def _can_see(name: str, is_admin: bool) -> bool:
    if name in _HIDDEN_COGS:
        return False
    if name == "Administração" and not is_admin:
        return False
    return True


# ==========================================================================
#  HELP
# ==========================================================================
def build_overview(bot: commands.Bot, prefix: str, is_admin: bool) -> discord.Embed:
    emb = discord.Embed(
        title="📖 Central de Ajuda — PokeM1D",
        description=(
            f"Bem-vindo, treinador! O jogo é todo pelo **`/menu`** (privado, só você vê). 🎮\n\n"
            f"🎓 É novo? Comece por **`/tutorial`** — um guia visual passo a passo.\n"
            f"🚀 Pra começar: **`/start`** te dá um inicial e itens.\n\n"
            f"As categorias abaixo são uma **referência** dos comandos (admins usam por prefixo). 👇"
        ),
        color=settings.color_default,
    )
    linhas = []
    for name, emoji in CATEGORIES:
        cog = bot.get_cog(name)
        if cog is None or not _can_see(name, is_admin):
            continue
        cmds = _visible_commands(cog)
        if not cmds:
            continue
        linhas.append(f"{emoji} **{name}** — {len(cmds)} comandos")
    emb.add_field(name="Categorias", value="\n".join(linhas) or "—", inline=False)
    emb.set_thumbnail(url=settings.sprite_animated(25))  # Pikachu
    emb.set_footer(text=f"{prefix}help <categoria>  •  {prefix}tutorial para aprender jogando")
    return emb


def build_category(bot: commands.Bot, prefix: str, name: str) -> discord.Embed:
    cog = bot.get_cog(name)
    emoji = _EMOJI.get(name, "📁")
    emb = discord.Embed(
        title=f"{emoji} {name}",
        color=settings.color_info,
    )
    if cog is None:
        emb.description = "Categoria não encontrada."
        return emb
    linhas = []
    for c in _visible_commands(cog):
        doc = (c.short_doc or "").strip() or "—"
        alias = f"  ·  *{', '.join(c.aliases[:3])}*" if c.aliases else ""
        linhas.append(f"**`{prefix}{c.name}`**{alias}\n┗ {doc}")
    emb.description = "\n\n".join(linhas) or "Sem comandos visíveis."
    emb.set_footer(text=f"Use {prefix}help <comando> para mais detalhes  •  🏠 volta ao início")
    return emb


def build_command(prefix: str, cmd: commands.Command) -> discord.Embed:
    emb = discord.Embed(
        title=f"🔎 {prefix}{cmd.qualified_name}",
        description=(cmd.help or cmd.short_doc or "Sem descrição."),
        color=settings.color_default,
    )
    sig = cmd.signature.strip()
    emb.add_field(name="Como usar", value=f"`{prefix}{cmd.qualified_name} {sig}`".strip(), inline=False)
    if cmd.aliases:
        emb.add_field(name="Atalhos", value=", ".join(f"`{a}`" for a in cmd.aliases), inline=False)
    return emb


class HelpView(discord.ui.View):
    def __init__(self, ctx, is_admin: bool):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.prefix = ctx.prefix
        self.is_admin = is_admin
        self.message: discord.Message | None = None
        # popula o menu de categorias
        options = []
        for name, emoji in CATEGORIES:
            cog = ctx.bot.get_cog(name)
            if cog is None or not _can_see(name, is_admin) or not _visible_commands(cog):
                continue
            options.append(discord.SelectOption(label=name, emoji=emoji,
                                                description=f"Ver comandos de {name}"))
        self.select.options = options or [discord.SelectOption(label="Geral")]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Abra a sua própria ajuda com `help`. 😉", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="📂 Escolha uma categoria...", row=0)
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        emb = build_category(self.ctx.bot, self.prefix, select.values[0])
        await interaction.response.edit_message(embed=emb, view=self)

    @discord.ui.button(label="Início", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        emb = build_overview(self.ctx.bot, self.prefix, self.is_admin)
        await interaction.response.edit_message(embed=emb, view=self)

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ==========================================================================
#  TUTORIAL
# ==========================================================================
def _stub(sp, level: int, frac: float):
    """BattleMon falso só para desenhar a cena do tutorial."""
    return SimpleNamespace(species=sp, name=sp.name, level=level, shiny=False,
                           hp=int(300 * frac), max_hp=300, alive=frac > 0,
                           hp_fraction=(lambda f=frac: f))


async def _img_explore(name: str, shiny: bool = False):
    sp = POKEDEX.by_name(name)
    return await render_explore_scene("pokemon", sp, shiny) if sp else None


async def _img_coins():
    return await render_explore_scene("coins")


async def _img_battle():
    a, b = POKEDEX.by_name("Charizard"), POKEDEX.by_name("Blastoise")
    if not a or not b:
        return None
    p1, p2 = _stub(a, 36, 0.72), _stub(b, 34, 0.4)
    return await render_battle_scene(p1, p2, [p1], [p2])


async def _img_grid(pairs):
    entries = []
    for n, sub in pairs:
        sp = POKEDEX.by_name(n)
        if sp:
            entries.append((sp.id, False, sp.name, sub))
    return await render_grid(entries, cols=3) if entries else None


# cada passo: título, cor, descrição e gerador de imagem.
# Tudo gira em torno do /menu (privado). Sem comandos de prefixo.
STEPS = [
    {
        "title": "🎓 Bem-vindo ao PokeM1D!",
        "color": 0xE91E63,
        "desc": (
            "Sua jornada começa aqui! Você vai **explorar, capturar, batalhar e evoluir** pokémon.\n\n"
            "✨ **Tudo se joga pelo `/menu`** — um painel **privado** (só você vê), sem encher o chat.\n\n"
            "▶️ Use os botões abaixo para avançar.\n"
            "💡 Comece digitando **`/start`** para ganhar seu inicial + itens grátis!"
        ),
        "img": lambda: _img_explore("Pikachu"),
    },
    {
        "title": "🌿 Passo 1 — Explorar",
        "color": 0x57F287,
        "desc": (
            "Abra o **`/menu`** e clique em **🌿 Explorar** para procurar pokémon selvagens.\n\n"
            "A cada exploração você pode encontrar:\n"
            "🐾 **Um pokémon** — escolha **Capturar**, **Batalhar** ou **Ignorar**\n"
            "💰 **Um tesouro** — PokéCoins grátis\n"
            "🍃 **Nada** — tente de novo em instantes\n\n"
            "Quanto mais raro o pokémon, mais forte e cobiçado! ✨"
        ),
        "img": lambda: _img_explore("Eevee"),
    },
    {
        "title": "🎯 Passo 2 — Capturar",
        "color": 0x3BA55D,
        "desc": (
            "Ao encontrar um selvagem, clique em **🎯 Capturar** e escolha a **pokébola**:\n\n"
            "⚪ **Poké Ball** — chance base\n"
            "🔵 **Great Ball** — +15%\n"
            "🟡 **Ultra Ball** — +30%\n"
            "🟣 **Master Ball** — captura garantida (rara!)\n\n"
            "Pokémon raros são mais difíceis — guarde as bolas boas pra eles! 💎\n"
            "Compre mais na **🛒 Loja** do `/menu`."
        ),
        "img": lambda: _img_explore("Snorlax"),
    },
    {
        "title": "⚔️ Passo 3 — Batalhar",
        "color": 0xED4245,
        "desc": (
            "No **`/menu`**, clique em **⚔️ Duelar** para batalhar contra um selvagem — **só você vê**!\n\n"
            "⚡ As batalhas têm **tipos** (água vence fogo…), **golpes** e **troca de pokémon**.\n"
            "🏅 Vencer dá **XP e PokéCoins**.\n"
            "🔁 No fim aparece **VITÓRIA/DERROTA** e o botão **Duelar de novo** — emende quantas quiser!\n\n"
            "*(Para PvP contra um amigo, o staff te explica.)*"
        ),
        "img": _img_battle,
    },
    {
        "title": "📦 Passo 4 — Coleção & Time",
        "color": 0x5865F2,
        "desc": (
            "Tudo no **`/menu`**:\n\n"
            "📦 **Coleção** — veja seus pokémon e clique em um para **⭐ Tornar líder, "
            "❤️ Favoritar, 🧬 Evoluir ou 🔁 Soltar**.\n"
            "🎒 **Time** — **➕ Adicionar / ➖ Remover** e definir o **líder** (ele batalha "
            "primeiro e define o nível dos encontros).\n\n"
            "Seu time cresce conquistando insígnias na Liga! 🏆"
        ),
        "img": lambda: _img_grid([
            ("Charizard", "#1 Nv36"), ("Pikachu", "#2 Nv18"), ("Gengar", "#3 Nv30"),
            ("Lucario", "#4 Nv40"), ("Gyarados", "#5 Nv33"), ("Snorlax", "#6 Nv28"),
        ]),
    },
    {
        "title": "🏆 Passo 5 — A Liga Pokémon",
        "color": 0xE67E22,
        "desc": (
            "O grande desafio! No **`/menu` → 🏆 Liga** você vê os 8 **Ginásios**, a "
            "**Elite dos 4**, o **Campeão** e os **covis lendários**.\n\n"
            "🎖️ Cada vitória dá uma **insígnia** + moedas + itens.\n"
            "📈 Insígnias **aumentam o tamanho do seu time**.\n"
            "💠 No fim te espera a **Câmara dos Míticos** (6 míticos Nv100)!"
        ),
        "img": lambda: _img_explore("Onix"),
    },
    {
        "title": "💰 Passo 6 — Economia & Mercado",
        "color": 0xF1C40F,
        "desc": (
            "Junte PokéCoins e gaste com sabedoria, tudo no **`/menu`**:\n\n"
            "🎁 **Missões** — pegue a **recompensa diária** (mantenha o streak!)\n"
            "🛒 **Loja** — compre bolas, pedras e doces com um clique\n"
            "🏪 **Market** — **compre** pokémon de outros treinadores ou **anuncie** os seus\n"
            "👤 **Perfil** — veja seu nível, moedas e estatísticas"
        ),
        "img": _img_coins,
    },
    {
        "title": "🧬 Passo 7 — Evolução",
        "color": 0x9B59B6,
        "desc": (
            "Deixe seus pokémon mais fortes! Na **Coleção** do `/menu`, abra um pokémon e clique em **🧬 Evoluir**.\n\n"
            "⬆️ **Por nível** — batalhe, suba de nível e evolua\n"
            "🔀 **Evolução dupla** — pokémon como Eevee e Slowpoke deixam **você escolher** a forma!\n"
            "💎 **Por pedra / 🍬 Rare Candy** — compre na 🛒 Loja e use na própria Coleção"
        ),
        "img": lambda: _img_grid([("Charmander", "Nv1"), ("Charmeleon", "Nv16"), ("Charizard", "Nv36")]),
    },
    {
        "title": "✅ Pronto, treinador!",
        "color": 0x2ECC71,
        "desc": (
            "Você já sabe o essencial! É tudo por **um comando**:\n\n"
            "## 🎮 `/menu`\n"
            "Lá dentro: 🌿 Explorar · ⚔️ Duelar · 📦 Coleção · 🎒 Time · 🛒 Loja · "
            "🏪 Market · 🏆 Liga · 📋 Missões · 👤 Perfil.\n\n"
            "Tudo **privado** (só você vê) — o chat fica limpo. 🧹\n\n"
            "Ainda não começou? Digite **`/start`** e boa sorte! 🎉"
        ),
        "img": lambda: _img_explore("Mew"),
    },
]


class TutorialView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.prefix = ctx.prefix
        self.i = 0
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        self.prev.disabled = self.i == 0
        self.next.disabled = self.i == len(STEPS) - 1
        self.counter.label = f"{self.i + 1}/{len(STEPS)}"

    async def _build(self) -> tuple[discord.Embed, discord.File | None]:
        step = STEPS[self.i]
        emb = discord.Embed(
            title=step["title"],
            description=step["desc"].format(p=self.prefix),
            color=step["color"],
        )
        emb.set_footer(text=f"Tutorial • passo {self.i + 1} de {len(STEPS)}  •  /help = lista completa")
        file = None
        factory = step.get("img")
        if factory is not None:
            try:
                buf = await factory()
            except Exception:  # noqa: BLE001
                buf = None
            if buf is not None:
                file = discord.File(buf, filename="tut.png")
                emb.set_image(url="attachment://tut.png")
        return emb, file

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Abra o seu próprio tutorial com `tutorial`. 😉", ephemeral=True)
            return False
        return True

    async def start(self, ephemeral: bool = False) -> None:
        emb, file = await self._build()
        kwargs = {"embed": emb, "view": self, "ephemeral": ephemeral}
        if file:
            kwargs["file"] = file
        self.message = await self.ctx.send(**kwargs)

    async def _show(self, interaction: discord.Interaction) -> None:
        self._sync()
        emb, file = await self._build()
        await interaction.response.edit_message(
            embed=emb, view=self, attachments=([file] if file else []))

    @discord.ui.button(label="Voltar", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.i = max(0, self.i - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.gray, disabled=True)
    async def counter(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        pass

    @discord.ui.button(label="Avançar", emoji="▶️", style=discord.ButtonStyle.success)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.i = min(len(STEPS) - 1, self.i + 1)
        await self._show(interaction)

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ==========================================================================
class HelpTutorial(commands.Cog, name="Ajuda"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="help", aliases=["ajuda", "comandos", "commands"])
    async def help_cmd(self, ctx: commands.Context, *, alvo: str | None = None) -> None:
        """Mostra a ajuda interativa com todas as categorias e comandos."""
        eph = ctx.interaction is not None
        is_admin = ctx.guild is not None and ctx.author.guild_permissions.manage_guild

        # help <comando> -> detalhe
        if alvo:
            cmd = self.bot.get_command(alvo.lower())
            if cmd is not None and not cmd.hidden:
                await ctx.send(embed=build_command(ctx.prefix, cmd), ephemeral=eph)
                return
            # help <categoria> -> abre naquela categoria
            match = next((n for n, _ in CATEGORIES if n.lower() == alvo.lower()), None)
            if match and _can_see(match, is_admin):
                await ctx.send(embed=build_category(self.bot, ctx.prefix, match), ephemeral=eph)
                return
            await ctx.send(embed=embeds.err_embed(
                f"Não achei `{alvo}`. Veja a lista com `/help`."), ephemeral=eph)
            return

        view = HelpView(ctx, is_admin)
        view.message = await ctx.send(
            embed=build_overview(self.bot, ctx.prefix, is_admin), view=view, ephemeral=eph)

    @commands.hybrid_command(name="tutorial", aliases=["guia", "tuto", "comojoga"])
    async def tutorial_cmd(self, ctx: commands.Context) -> None:
        """Guia visual interativo: aprenda as mecânicas passo a passo."""
        await TutorialView(ctx).start(ephemeral=ctx.interaction is not None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpTutorial(bot))
