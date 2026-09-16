"""
Conversor de imagens em lote.

Detecta os formatos de imagem que o Pillow instalado consegue abrir na mesma
pasta deste script (com opção de examinar subpastas) e
permite:
1. Exportar em alta qualidade, mantendo a resolução original;
2. Criar miniaturas;
3. Gerar as duas versões.

As saídas são organizadas pelo formato escolhido:

    jpg/
        imagem.jpg
        mini/imagem_mini.jpg

    png/
        imagem.png
        mini/imagem_mini.png

    webp/
        imagem.webp
        mini/imagem_mini.webp

    avif/
        imagem.avif
        mini/imagem_mini.avif

Dependência recomendada:
    py -m pip install --upgrade "Pillow>=11.3.0"

O Pillow 11.3.0 ou mais recente inclui suporte a AVIF nas distribuições
oficiais para as principais plataformas, exceto algumas arquiteturas.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

# Pillow é carregado somente depois da verificação automática dos requisitos.
PIL = None
Image = None
ImageOps = None
features = None

VERSAO_MINIMA_PYTHON = (3, 10)
VERSAO_MINIMA_PILLOW = (11, 3, 0)
REQUISITO_PILLOW = "Pillow>=11.3.0"


# Extensões de entrada convencionais com leitor registrado pelo Pillow. Drivers
# apenas identificadores (BUFR, GRIB, HDF5 e MPEG) ficam deliberadamente fora.
EXTENSOES_ENTRADA = {
    ".apng": "Imagem APNG",
    ".avif": "Imagem AVIF",
    ".avifs": "Sequência AVIF",
    ".blp": "Textura BLP",
    ".bmp": "Imagem BMP",
    ".bw": "Imagem SGI",
    ".cur": "Cursor do Windows",
    ".dcx": "Imagem DCX",
    ".dds": "Textura DDS",
    ".dib": "Imagem DIB",
    ".emf": "Metarquivo EMF",
    ".fit": "Imagem FITS",
    ".fits": "Imagem FITS",
    ".flc": "Animação FLC",
    ".fli": "Animação FLI",
    ".fpx": "Imagem FlashPix",
    ".ftc": "Textura FTEX",
    ".ftu": "Textura FTEX",
    ".gbr": "Pincel GIMP",
    ".gif": "Imagem GIF",
    ".icb": "Imagem TGA",
    ".icns": "Ícone ICNS",
    ".ico": "Ícone ICO",
    ".iim": "Imagem IPTC",
    ".im": "Imagem IM",
    ".j2c": "Imagem JPEG 2000",
    ".j2k": "Imagem JPEG 2000",
    ".jfif": "Imagem JPEG",
    ".jp2": "Imagem JPEG 2000",
    ".jpc": "Imagem JPEG 2000",
    ".jpe": "Imagem JPEG",
    ".jpeg": "Imagem JPEG",
    ".jpf": "Imagem JPEG 2000",
    ".jpg": "Imagem JPG",
    ".jpx": "Imagem JPEG 2000",
    ".mic": "Imagem MIC",
    ".msp": "Imagem MSP",
    ".pbm": "Imagem PBM",
    ".pcd": "Imagem PhotoCD",
    ".pcx": "Imagem PCX",
    ".pfm": "Imagem PFM",
    ".pgm": "Imagem PGM",
    ".png": "Imagem PNG",
    ".pnm": "Imagem PNM",
    ".ppm": "Imagem PPM",
    ".psd": "Imagem Photoshop",
    ".pxr": "Imagem Pixar Raster",
    ".qoi": "Imagem QOI",
    ".ras": "Imagem Sun Raster",
    ".rgb": "Imagem SGI",
    ".rgba": "Imagem SGI",
    ".sgi": "Imagem SGI",
    ".tga": "Imagem TGA",
    ".tif": "Imagem TIFF",
    ".tiff": "Imagem TIFF",
    ".vda": "Imagem TGA",
    ".vst": "Imagem TGA",
    ".webp": "Imagem WEBP",
    ".wmf": "Metarquivo WMF",
    ".xbm": "Imagem XBM",
    ".xpm": "Imagem XPM",
}

# rótulo: (formato Pillow, extensão final, pasta de saída)
# As quatro opções originais permanecem no menu principal. As demais ficam
# no submenu "Outros". Famílias com aliases equivalentes usam uma extensão
# canônica; JP2 e J2K permanecem separados por representarem contêiner e fluxo.
FORMATOS_SAIDA = {
    "JPG": ("JPEG", ".jpg", "jpg"),
    "PNG": ("PNG", ".png", "png"),
    "WEBP": ("WEBP", ".webp", "webp"),
    "AVIF": ("AVIF", ".avif", "avif"),
    "APNG": ("PNG", ".apng", "apng"),
    "AVIFS": ("AVIF", ".avifs", "avifs"),
    "BLP": ("BLP", ".blp", "blp"),
    "BMP": ("BMP", ".bmp", "bmp"),
    "DDS": ("DDS", ".dds", "dds"),
    "DIB": ("DIB", ".dib", "dib"),
    "EPS": ("EPS", ".eps", "eps"),
    "GIF": ("GIF", ".gif", "gif"),
    "ICNS": ("ICNS", ".icns", "icns"),
    "ICO": ("ICO", ".ico", "ico"),
    "IM": ("IM", ".im", "im"),
    "J2K": ("JPEG2000", ".j2k", "j2k"),
    "JP2": ("JPEG2000", ".jp2", "jp2"),
    "MPO": ("MPO", ".mpo", "mpo"),
    "MSP": ("MSP", ".msp", "msp"),
    "PALM": ("PALM", ".palm", "palm"),
    "PBM": ("PPM", ".pbm", "pbm"),
    "PCX": ("PCX", ".pcx", "pcx"),
    "PDF": ("PDF", ".pdf", "pdf"),
    "PFM": ("PPM", ".pfm", "pfm"),
    "PGM": ("PPM", ".pgm", "pgm"),
    "PNM": ("PPM", ".pnm", "pnm"),
    "PPM": ("PPM", ".ppm", "ppm"),
    "QOI": ("QOI", ".qoi", "qoi"),
    "SGI": ("SGI", ".sgi", "sgi"),
    "TGA": ("TGA", ".tga", "tga"),
    "TIFF": ("TIFF", ".tiff", "tiff"),
    "XBM": ("XBM", ".xbm", "xbm"),
}

FORMATOS_PRINCIPAIS = ("JPG", "PNG", "WEBP", "AVIF")

# Tags EXIF usadas para corrigir orientação e dimensões após o processamento.
EXIF_ORIENTATION = 274
EXIF_IMAGE_WIDTH = 256
EXIF_IMAGE_HEIGHT = 257
EXIF_JPEG_THUMB_OFFSET = 513
EXIF_JPEG_THUMB_LENGTH = 514
EXIF_PIXEL_WIDTH = 40962
EXIF_PIXEL_HEIGHT = 40963


# ---------------------------------------------------------------------------
# Interface de terminal — somente biblioteca padrão (sem Rich)
# ---------------------------------------------------------------------------

ANSI_ATIVO = False
RESET = "\033[0m"
NEGRITO = "\033[1m"
FRACO = "\033[2m"
CIANO = "\033[96m"
VERDE = "\033[92m"
AMARELO = "\033[93m"
BRANCO_FORTE = "\033[97m"  # branco brilhante para a bola do i
VERMELHO = "\033[91m"
CINZA = "\033[90m"

LOGO_KUPIM = r"""888                        d8b
888                        Y8P
888
888  888 888  888 88888b.  888 88888b.d88b.
888 .88P 888  888 888 "88b 888 888 "888 "88b
888888K  888  888 888  888 888 888  888  888
888 "88b Y88b 888 888 d88P 888 888  888  888
888  888  "Y88888 88888P"  888 888  888  888
                  888
                  888
                  888"""

ASSINATURA_KUPIM = "kupim // image tools v0.4"
LINHA_KUPIM = "└───────────────────────────────────────────────────────────"


def habilitar_ansi() -> None:
    """Ativa sequências ANSI quando o terminal oferece suporte."""
    global ANSI_ATIVO

    if not sys.stdout.isatty():
        ANSI_ATIVO = False
        return

    if os.name != "nt":
        ANSI_ATIVO = True
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        modo = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(modo)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            ANSI_ATIVO = bool(
                kernel32.SetConsoleMode(handle, modo.value | 0x0004)
            )
        else:
            ANSI_ATIVO = False
    except Exception:
        ANSI_ATIVO = False


def estilizar(texto: str, *codigos: str) -> str:
    """Aplica estilo ANSI somente quando o terminal o suporta."""
    if not ANSI_ATIVO or not codigos:
        return texto
    return "".join(codigos) + texto + RESET


def largura_terminal() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def largura_interface() -> int:
    """Largura estável, mas adaptável, para painéis e divisores."""
    return max(42, min(72, largura_terminal() - 2))


def limpar_tela() -> None:
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def mostrar_logo() -> None:
    """Exibe o logo em ciano, com os trechos marcados e a bola do i em branco."""
    if largura_terminal() >= 62:
        if ANSI_ATIVO:
            # Intervalos brancos (início inclusivo, fim exclusivo) conforme
            # as marcações [ ] fornecidas para cada linha do logo.
            trechos_brancos = {
                0: (27, 30),  # d8b — bola do i
                1: (27, 30),  # Y8P — bola do i
                3: (21, 43),  # 888 inicial volta a ciano; restante permanece branco
                4: (25, 44),
                5: (28, 44),
                6: (29, 44),
                7: (33, 44),
            }

            for indice, linha in enumerate(LOGO_KUPIM.splitlines()):
                trecho = trechos_brancos.get(indice)
                if trecho is None:
                    sys.stdout.write(f"{CIANO}{NEGRITO}{linha}{RESET}\n")
                    continue

                inicio, fim = trecho
                antes = linha[:inicio]
                branco = linha[inicio:fim]
                depois = linha[fim:]

                sys.stdout.write(
                    f"{CIANO}{NEGRITO}{antes}{RESET}"
                    f"{BRANCO_FORTE}{NEGRITO}{branco}{RESET}"
                    f"{CIANO}{NEGRITO}{depois}{RESET}\n"
                )
        else:
            print(LOGO_KUPIM)
        print()
    print(estilizar(ASSINATURA_KUPIM, NEGRITO))
    print(estilizar(LINHA_KUPIM, CINZA))

def titulo_secao(titulo: str) -> None:
    """Desenha um painel simples semelhante à estética de CLIs modernas."""
    largura = largura_interface()
    interior = largura - 2
    texto = f" {titulo} "
    if len(texto) > interior:
        texto = texto[:interior]
    topo = "╭" + "─" * interior + "╮"
    meio = "│" + texto.center(interior) + "│"
    base = "╰" + "─" * interior + "╯"
    print()
    print(estilizar(topo, CINZA))
    print(estilizar(meio, NEGRITO))
    print(estilizar(base, CINZA))


def imprimir_ok(texto: str) -> None:
    print(f"  {estilizar('✓', VERDE, NEGRITO)} {texto}")


def imprimir_aviso(texto: str) -> None:
    print(f"  {estilizar('!', AMARELO, NEGRITO)} {texto}")


def imprimir_erro(texto: str) -> None:
    print(f"  {estilizar('✗', VERMELHO, NEGRITO)} {texto}")


def imprimir_status_sistema(nome: str, detalhe: str = "", ok: bool = True) -> None:
    marcador = estilizar("✓ OK", VERDE, NEGRITO) if ok else estilizar("✗ ERRO", VERMELHO, NEGRITO)
    print(f"  {nome:<12} {detalhe:<22} {marcador}")


def encurtar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    if limite <= 3:
        return texto[:limite]
    return texto[: limite - 3] + "..."


def _ler_tecla_navegacao() -> str | None:
    """Lê uma tecla sem exigir Enter. Suporta Windows e terminais POSIX."""
    if os.name == "nt":
        import msvcrt

        tecla = msvcrt.getwch()
        if tecla == "\x03":
            raise KeyboardInterrupt
        if tecla in {"\x00", "\xe0"}:
            especial = msvcrt.getwch()
            if especial == "H":
                return "cima"
            if especial == "P":
                return "baixo"
            return None
        if tecla in {"\r", "\n"}:
            return "enter"
        if tecla == "\x08":
            return "backspace"
        if tecla.isdigit():
            return tecla
        return None

    # Fallback POSIX usando somente a biblioteca padrão.
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        anterior = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            tecla = sys.stdin.read(1)
            if tecla == "\x03":
                raise KeyboardInterrupt
            if tecla in {"\r", "\n"}:
                return "enter"
            if tecla in {"\x08", "\x7f"}:
                return "backspace"
            if tecla.isdigit():
                return tecla
            if tecla == "\x1b":
                resto = sys.stdin.read(2)
                if resto == "[A":
                    return "cima"
                if resto == "[B":
                    return "baixo"
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, anterior)
    except Exception:
        return None


def menu_navegavel(
    titulo: str,
    opcoes: list[tuple[str, str]],
    indice_padrao: int,
    desabilitadas: set[str] | None = None,
) -> str:
    """
    Menu navegável com ↑/↓ e Enter.

    A seleção começa sobre a opção padrão. As teclas numéricas também podem
    escolher diretamente uma opção. Em terminais sem suporte interativo/ANSI,
    usa entrada digitada tradicional preservando o mesmo padrão.
    """
    desabilitadas = desabilitadas or set()

    if not 0 <= indice_padrao < len(opcoes):
        raise ValueError("Índice padrão fora da lista de opções.")
    if opcoes[indice_padrao][0] in desabilitadas:
        raise ValueError("A opção padrão não pode estar desabilitada.")
    if all(valor in desabilitadas for valor, _ in opcoes):
        raise ValueError("O menu precisa ter ao menos uma opção habilitada.")

    titulo_secao(titulo)

    # Fallback simples para terminais redirecionados ou sem ANSI.
    if not sys.stdin.isatty() or not ANSI_ATIVO:
        for indice, (valor, rotulo) in enumerate(opcoes, start=1):
            sufixo = " (padrão)" if indice - 1 == indice_padrao else ""
            if valor in desabilitadas:
                sufixo = " (indisponível)"
            print(f"  {indice}. {rotulo}{sufixo}")
        validas = {
            valor for valor, _ in opcoes if valor not in desabilitadas
        }
        padrao = opcoes[indice_padrao][0]
        while True:
            resposta = ler_linha_com_voltar("\nEscolha: ").strip().lower()
            if not resposta:
                return padrao
            if resposta in validas:
                return resposta
            print("Opção inválida. Tente novamente.")

    selecionado = indice_padrao
    buffer_numerico = ""
    multiplos_digitos = len(opcoes) >= 10

    def mover(direcao: int) -> None:
        nonlocal selecionado, buffer_numerico
        buffer_numerico = ""
        for _ in opcoes:
            selecionado = (selecionado + direcao) % len(opcoes)
            if opcoes[selecionado][0] not in desabilitadas:
                return

    def montar_linhas() -> list[str]:
        linhas: list[str] = []
        for indice, (valor, rotulo) in enumerate(opcoes):
            seta = "›" if indice == selecionado else " "
            sufixo = "  (padrão)" if indice == indice_padrao else ""
            texto = f"  {seta} {indice + 1}. {rotulo}{sufixo}"
            if valor in desabilitadas:
                texto += "  (indisponível)"
                texto = estilizar(texto, CINZA, FRACO)
            elif indice == selecionado:
                texto = estilizar(texto, CIANO, NEGRITO)
            elif indice == indice_padrao:
                texto = estilizar(texto, FRACO)
            linhas.append(texto)
        linhas.append("")
        instrucao_numeros = (
            "digite o número + Enter"
            if multiplos_digitos
            else "números = atalho"
        )
        linhas.append(
            estilizar(
                f"  ↑/↓ navegar  •  Enter confirmar  •  Backspace voltar  •  {instrucao_numeros}",
                CINZA,
            )
        )
        if multiplos_digitos:
            digitado = buffer_numerico or "_"
            linhas.append(estilizar(f"  Número: {digitado}", CINZA))
        return linhas

    def desenhar(primeira_vez: bool = False) -> int:
        linhas = montar_linhas()
        if not primeira_vez:
            sys.stdout.write(f"\033[{len(linhas)}F")
            sys.stdout.write("\033[J")
        sys.stdout.write("\n".join(linhas) + "\n")
        sys.stdout.flush()
        return len(linhas)

    desenhar(primeira_vez=True)
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            tecla = _ler_tecla_navegacao()
            if tecla == "cima":
                mover(-1)
                desenhar()
            elif tecla == "baixo":
                mover(1)
                desenhar()
            elif tecla == "backspace":
                if buffer_numerico:
                    buffer_numerico = buffer_numerico[:-1]
                    desenhar()
                    continue
                print()
                raise VoltarEtapa
            elif tecla == "enter":
                if buffer_numerico:
                    numero = int(buffer_numerico)
                    buffer_numerico = ""
                    if not 1 <= numero <= len(opcoes):
                        desenhar()
                        continue
                    valor = opcoes[numero - 1][0]
                    if valor in desabilitadas:
                        desenhar()
                        continue
                    selecionado = numero - 1
                print()
                return opcoes[selecionado][0]
            elif tecla and tecla.isdigit():
                if multiplos_digitos:
                    buffer_numerico = (buffer_numerico + tecla)[-3:]
                    desenhar()
                else:
                    numero = int(tecla)
                    if 1 <= numero <= len(opcoes):
                        valor = opcoes[numero - 1][0]
                        if valor in desabilitadas:
                            continue
                        selecionado = numero - 1
                        desenhar()
                        print()
                        return opcoes[selecionado][0]
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def ler_linha_com_voltar(
    mensagem: str,
    caracteres_permitidos: set[str] | None = None,
) -> str:
    """Lê uma linha; Backspace com o campo vazio retorna à etapa anterior."""
    if not sys.stdin.isatty():
        return input(mensagem)

    buffer: list[str] = []
    sys.stdout.write(mensagem)
    sys.stdout.flush()

    def apagar_ultimo() -> None:
        if buffer:
            buffer.pop()
            sys.stdout.write("\b \b")
            sys.stdout.flush()

    if os.name == "nt":
        import msvcrt

        while True:
            tecla = msvcrt.getwch()
            if tecla == "\x03":
                raise KeyboardInterrupt
            if tecla in {"\x00", "\xe0"}:
                msvcrt.getwch()  # descarta a segunda parte de teclas especiais
                continue
            if tecla in {"\r", "\n"}:
                print()
                return "".join(buffer)
            if tecla == "\x08":
                if buffer:
                    apagar_ultimo()
                else:
                    print()
                    raise VoltarEtapa
                continue
            if tecla.isprintable() and (
                caracteres_permitidos is None or tecla in caracteres_permitidos
            ):
                buffer.append(tecla)
                sys.stdout.write(tecla)
                sys.stdout.flush()

    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        anterior = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                tecla = sys.stdin.read(1)
                if tecla == "\x03":
                    raise KeyboardInterrupt
                if tecla in {"\r", "\n"}:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(buffer)
                if tecla in {"\x08", "\x7f"}:
                    if buffer:
                        apagar_ultimo()
                    else:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        raise VoltarEtapa
                    continue
                if tecla == "\x1b":
                    # Descarta sequências de escape mais comuns (setas etc.).
                    continue
                if tecla.isprintable() and (
                    caracteres_permitidos is None or tecla in caracteres_permitidos
                ):
                    buffer.append(tecla)
                    sys.stdout.write(tecla)
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, anterior)
    except VoltarEtapa:
        raise
    except KeyboardInterrupt:
        raise
    except Exception:
        # Fallback raro: mantém a entrada tradicional.
        return input(mensagem)


def limpar_linha_atual() -> None:
    if ANSI_ATIVO:
        sys.stdout.write("\r\033[2K")
        sys.stdout.flush()


def mostrar_progresso(atual: int, total: int, arquivo: str = "") -> None:
    """Atualiza uma barra de progresso em uma única linha."""
    if total <= 0:
        return

    proporcao = min(1.0, max(0.0, atual / total))
    largura_barra = max(12, min(30, largura_interface() - 35))
    preenchido = round(largura_barra * proporcao)
    barra = "█" * preenchido + "░" * (largura_barra - preenchido)
    percentual = round(proporcao * 100)
    nome = encurtar(arquivo, max(12, largura_interface() - largura_barra - 20))
    linha = f"  {barra} {percentual:>3}%  {atual}/{total}"
    if nome:
        linha += f"  {nome}"

    if ANSI_ATIVO:
        sys.stdout.write("\r\033[2K" + estilizar(linha, CIANO))
        sys.stdout.flush()
    else:
        print(linha)


def versao_numerica(texto: str) -> tuple[int, ...]:
    """Extrai a parte numérica de uma versão para comparação simples."""
    numeros = re.findall(r"\d+", texto)
    return tuple(int(numero) for numero in numeros[:3])


def executar_pip(argumentos: list[str]) -> None:
    """Executa o pip usando exatamente o mesmo Python que abriu o script."""
    subprocess.run(
        [sys.executable, "-m", "pip", *argumentos],
        check=True,
    )


def garantir_pip() -> bool:
    """Verifica o pip e tenta instalá-lo com ensurepip quando necessário."""
    if importlib.util.find_spec("pip") is not None:
        return True

    print("    pip não encontrado. Tentando instalar automaticamente...")
    try:
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            check=True,
        )
        importlib.invalidate_caches()
    except (OSError, subprocess.CalledProcessError) as erro:
        print(f"    [ERRO] Não foi possível instalar o pip: {erro}")
        return False

    if importlib.util.find_spec("pip") is None:
        print("    [ERRO] O pip continua indisponível após a tentativa de instalação.")
        return False

    return True


def versao_pillow_instalada() -> str | None:
    """Retorna a versão instalada do Pillow sem importá-lo no processo atual."""
    from importlib import metadata

    try:
        return metadata.version("Pillow")
    except metadata.PackageNotFoundError:
        return None


def instalar_ou_atualizar_pillow(forcar: bool = False) -> bool:
    """Instala/atualiza Pillow; opcionalmente força a reinstalação do pacote."""
    argumentos = ["install", "--upgrade"]
    if forcar:
        argumentos.append("--force-reinstall")
    argumentos.append(REQUISITO_PILLOW)

    try:
        executar_pip(argumentos)
        importlib.invalidate_caches()
        return True
    except (OSError, subprocess.CalledProcessError) as erro:
        print(f"    [ERRO] Falha ao instalar/atualizar Pillow: {erro}")
        return False


def codec_pillow_disponivel(nome: str) -> bool:
    """Testa um codec Pillow em um subprocesso limpo."""
    codigo = (
        "from PIL import Image, features; "
        "Image.init(); "
        f"nome={nome!r}; "
        "ok=False; "
        "\ntry:\n"
        "    ok=bool(features.check_module(nome))\n"
        "except (ValueError, AttributeError):\n"
        "    ext='.' + nome.lower(); fmt=nome.upper(); "
        "ok=(ext in Image.registered_extensions() and fmt in Image.SAVE)\n"
        "raise SystemExit(0 if ok else 1)"
    )
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", codigo],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return resultado.returncode == 0


def carregar_pillow() -> bool:
    """Importa Pillow somente após a preparação das dependências."""
    global PIL, Image, ImageOps, features

    try:
        import PIL as pil_modulo
        from PIL import Image as image_modulo
        from PIL import ImageOps as imageops_modulo
        from PIL import features as features_modulo
    except ImportError as erro:
        print(f"    [ERRO] Pillow não pôde ser importado: {erro}")
        return False

    PIL = pil_modulo
    Image = image_modulo
    ImageOps = imageops_modulo
    features = features_modulo
    return True


def verificar_pre_requisitos() -> bool:
    """Verifica e, quando possível, instala automaticamente os requisitos."""
    titulo_secao("VERIFICAÇÃO DO SISTEMA")

    versao_python = sys.version_info[:3]
    versao_python_texto = ".".join(str(parte) for parte in versao_python)
    minima_python_texto = ".".join(str(parte) for parte in VERSAO_MINIMA_PYTHON)

    if versao_python < VERSAO_MINIMA_PYTHON:
        imprimir_status_sistema("Python", versao_python_texto, ok=False)
        imprimir_erro(f"É necessário Python {minima_python_texto} ou superior.")
        print(
            "  O próprio arquivo .py não pode substituir o interpretador que o abriu.\n"
            "  Instale/atualize o Python e execute o conversor novamente."
        )
        return False
    imprimir_status_sistema("Python", versao_python_texto)

    if not garantir_pip():
        imprimir_status_sistema("pip", "indisponível", ok=False)
        return False
    imprimir_status_sistema("pip", "disponível")

    versao = versao_pillow_instalada()
    precisa_instalar = versao is None

    if versao is not None and versao_numerica(versao) < VERSAO_MINIMA_PILLOW:
        imprimir_aviso(f"Pillow {versao} é antigo; atualizando para {REQUISITO_PILLOW}...")
        precisa_instalar = True
    elif versao is None:
        imprimir_aviso("Pillow não encontrado; instalando automaticamente...")

    if precisa_instalar:
        if not instalar_ou_atualizar_pillow():
            imprimir_status_sistema("Pillow", "falha na instalação", ok=False)
            return False
        versao = versao_pillow_instalada()

    imprimir_status_sistema("Pillow", versao or "versão não identificada")

    avif_ok = codec_pillow_disponivel("avif")
    webp_ok = codec_pillow_disponivel("webp")

    if not avif_ok:
        imprimir_aviso("AVIF não detectado; tentando reinstalar Pillow...")
        if instalar_ou_atualizar_pillow(forcar=True):
            avif_ok = codec_pillow_disponivel("avif")
            webp_ok = codec_pillow_disponivel("webp")

    imprimir_status_sistema("AVIF", "codec", avif_ok)
    imprimir_status_sistema("WEBP", "codec", webp_ok)

    if not carregar_pillow():
        return False

    print()
    imprimir_ok("Pré-requisitos verificados. Iniciando o conversor.")
    return True


def pausar_antes_de_fechar() -> None:
    """Mantém a janela aberta até o usuário confirmar o encerramento."""
    try:
        print()
        input(estilizar("  Pressione Enter para fechar o programa...", CINZA))
    except (EOFError, KeyboardInterrupt):
        # Em terminais sem entrada interativa não existe como aguardar Enter.
        pass


class VoltarEtapa(Exception):
    """Sinaliza navegação para a etapa anterior da interface."""


class ErroFormatoIndisponivel(RuntimeError):
    """Indica que o Pillow instalado não possui o codec solicitado."""


def solicitar_opcao(
    mensagem: str,
    opcoes_validas: Iterable[str],
    padrao: str | None = None,
) -> str:
    """Solicita uma opção válida; Enter usa o padrão quando informado."""
    validas = set(opcoes_validas)

    if padrao is not None and padrao not in validas:
        raise ValueError("A opção padrão precisa estar entre as opções válidas.")

    while True:
        resposta = input(mensagem).strip().lower()

        if not resposta and padrao is not None:
            return padrao

        if resposta in validas:
            return resposta

        print("Opção inválida. Tente novamente.")


def solicitar_inteiro(
    mensagem: str,
    padrao: int,
    minimo: int,
    maximo: int,
) -> int:
    """Solicita um inteiro; Backspace com campo vazio retorna uma etapa."""
    caracteres = set("0123456789")

    while True:
        resposta = ler_linha_com_voltar(
            mensagem,
            caracteres_permitidos=caracteres,
        ).strip()

        if not resposta:
            return padrao

        try:
            valor = int(resposta)
        except ValueError:
            print("Digite um número inteiro válido.")
            continue

        if minimo <= valor <= maximo:
            return valor

        print(f"Digite um valor entre {minimo} e {maximo}.")


def suporte_modulo(nome: str) -> bool:
    """Verifica um módulo opcional do Pillow, inclusive em versões antigas."""
    try:
        return bool(features.check_module(nome))
    except (ValueError, AttributeError):
        Image.init()
        extensao = f".{nome.lower()}"
        formato = nome.upper()
        return (
            extensao in Image.registered_extensions()
            and formato in Image.SAVE
        )


def verificar_formato_disponivel(formato: str) -> None:
    """Interrompe a opção quando o codec não está disponível."""
    Image.init()

    if formato == "AVIF" and not suporte_modulo("avif"):
        raise ErroFormatoIndisponivel(
            "O Pillow instalado não possui suporte a AVIF.\n"
            "Atualize-o com:\n\n"
            '    py -m pip install --upgrade "Pillow>=11.3.0"\n\n'
            f"Versão atual do Pillow: {PIL.__version__}"
        )

    if formato == "WEBP" and not suporte_modulo("webp"):
        raise ErroFormatoIndisponivel(
            "O Pillow instalado não possui suporte a WEBP. "
            "Instale uma distribuição do Pillow com suporte a libwebp."
        )

    if formato not in Image.SAVE:
        raise ErroFormatoIndisponivel(
            f"O formato {formato} não pode ser salvo por esta instalação "
            "do Pillow."
        )


def extensoes_entrada_disponiveis() -> set[str]:
    """Retorna somente extensões com um leitor real registrado no Pillow."""
    Image.init()
    registradas = Image.registered_extensions()
    return {
        extensao
        for extensao in EXTENSOES_ENTRADA
        if extensao in registradas and registradas[extensao] in Image.OPEN
    }


def localizar_imagens(pasta: Path, recursivo: bool = False) -> list[Path]:
    """Localiza imagens compatíveis na pasta ou em toda a sua árvore."""
    extensoes = extensoes_entrada_disponiveis()
    pastas_saida = {
        dados[2].casefold() for dados in FORMATOS_SAIDA.values()
    }

    if recursivo:
        candidatas: list[Path] = []
        for raiz, diretorios, arquivos in os.walk(pasta):
            raiz_path = Path(raiz)

            # Não reimporta resultados de execuções anteriores. A exclusão
            # vale somente para pastas de saída diretamente ao lado do script.
            if raiz_path == pasta:
                diretorios[:] = [
                    nome
                    for nome in diretorios
                    if nome.casefold() not in pastas_saida
                ]

            candidatas.extend(raiz_path / nome for nome in arquivos)
    else:
        candidatas = [arquivo for arquivo in pasta.iterdir() if arquivo.is_file()]

    imagens = [
        arquivo
        for arquivo in candidatas
        if arquivo.suffix.lower() in extensoes
    ]
    return sorted(
        imagens,
        key=lambda caminho: str(caminho.relative_to(pasta)).casefold(),
    )


def preparar_para_jpeg(imagem: Image.Image) -> Image.Image:
    """Remove transparência, preenchendo as áreas transparentes com branco."""
    possui_alpha = imagem.mode in {"RGBA", "LA"} or (
        imagem.mode == "P" and "transparency" in imagem.info
    )

    if possui_alpha:
        rgba = imagem.convert("RGBA")
        fundo = Image.new("RGB", rgba.size, (255, 255, 255))
        fundo.paste(rgba, mask=rgba.getchannel("A"))
        return fundo

    return imagem.convert("RGB")


def preparar_para_avif(imagem: Image.Image) -> Image.Image:
    """Converte para um modo de 8 bits compatível com o codificador AVIF."""
    possui_alpha = imagem.mode in {"RGBA", "LA"} or (
        imagem.mode == "P" and "transparency" in imagem.info
    )

    return imagem.convert("RGBA" if possui_alpha else "RGB")


def preparar_imagem(
    imagem: Image.Image,
    formato: str,
    extensao: str,
) -> Image.Image:
    """Ajusta o modo de cor para o formato escolhido."""
    if formato in {"JPEG", "MPO", "EPS", "PDF"}:
        return preparar_para_jpeg(imagem)

    if formato == "AVIF":
        return preparar_para_avif(imagem)

    if extensao in {".pbm", ".xbm"} or formato == "MSP":
        return imagem.convert("1")

    if extensao == ".pgm":
        return imagem.convert("L")

    if extensao == ".pfm":
        return imagem.convert("L").convert("F")

    if extensao in {".ppm", ".pnm"}:
        return preparar_para_jpeg(imagem)

    if formato in {"GIF", "PALM", "BLP"}:
        rgba = imagem.convert("RGBA")
        return rgba.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)

    if formato in {"BMP", "DIB", "PCX"}:
        return preparar_para_jpeg(imagem)

    if formato in {
        "PNG",
        "WEBP",
        "QOI",
        "TGA",
        "TIFF",
        "DDS",
        "ICNS",
        "ICO",
        "JPEG2000",
        "SGI",
    }:
        if imagem.mode in {"RGBA", "LA", "RGB", "L"}:
            return imagem.copy()

        if imagem.mode == "P" and "transparency" in imagem.info:
            return imagem.convert("RGBA")

        if imagem.mode == "P":
            return imagem.convert("RGB")

        return imagem.convert("RGB")

    if imagem.mode not in {"1", "L", "P", "RGB", "RGBA"}:
        return imagem.convert("RGB")

    return imagem.copy()


def exif_corrigido(
    imagem_original: Image.Image,
    tamanho_saida: tuple[int, int],
) -> bytes | None:
    """
    Preserva o EXIF sem reaplicar a orientação antiga.

    Também atualiza tags de dimensões que já existiam e remove referências a
    miniaturas JPEG internas, que podem se tornar inválidas após a conversão.
    """
    try:
        exif = imagem_original.getexif()
    except (AttributeError, OSError, SyntaxError):
        return None

    if not exif:
        return None

    exif.pop(EXIF_ORIENTATION, None)
    exif.pop(EXIF_JPEG_THUMB_OFFSET, None)
    exif.pop(EXIF_JPEG_THUMB_LENGTH, None)

    largura, altura = tamanho_saida

    if EXIF_IMAGE_WIDTH in exif:
        exif[EXIF_IMAGE_WIDTH] = largura
    if EXIF_IMAGE_HEIGHT in exif:
        exif[EXIF_IMAGE_HEIGHT] = altura
    if EXIF_PIXEL_WIDTH in exif:
        exif[EXIF_PIXEL_WIDTH] = largura
    if EXIF_PIXEL_HEIGHT in exif:
        exif[EXIF_PIXEL_HEIGHT] = altura

    try:
        dados = exif.tobytes()
    except (OSError, TypeError, ValueError):
        return None

    return dados or None


def metadados_salvamento(
    imagem_original: Image.Image,
    formato: str,
    tamanho_saida: tuple[int, int],
    preservar_metadados: bool,
) -> dict[str, Any]:
    """Obtém metadados compatíveis com o formato de saída."""
    if not preservar_metadados:
        return {}

    metadados: dict[str, Any] = {}

    formatos_icc = {"JPEG", "PNG", "WEBP", "AVIF", "TIFF", "JPEG2000"}
    formatos_exif = {"JPEG", "PNG", "WEBP", "AVIF", "TIFF", "JPEG2000", "MPO"}

    icc_profile = imagem_original.info.get("icc_profile")
    if icc_profile and formato in formatos_icc:
        metadados["icc_profile"] = icc_profile

    exif = exif_corrigido(imagem_original, tamanho_saida)
    if exif and formato in formatos_exif:
        metadados["exif"] = exif

    # Estes codificadores aceitam DPI explicitamente.
    dpi = imagem_original.info.get("dpi")
    if dpi and formato in {"JPEG", "PNG", "TIFF", "BMP"}:
        metadados["dpi"] = dpi

    # Pillow oferece preservação direta de XMP para WEBP e AVIF.
    xmp = imagem_original.info.get("xmp")
    if xmp and formato in {"WEBP", "AVIF"}:
        metadados["xmp"] = xmp

    return metadados


def parametros_salvamento(
    formato: str,
    extensao: str,
    alta_qualidade: bool,
    metadados: dict[str, Any],
) -> dict[str, Any]:
    """Retorna parâmetros equilibrados e apropriados para cada formato."""
    parametros: dict[str, Any] = dict(metadados)

    if formato == "JPEG":
        if alta_qualidade:
            parametros.update(
                quality=95,
                subsampling=0,
                optimize=True,
                progressive=True,
            )
        else:
            parametros.update(
                quality=85,
                subsampling=1,
                optimize=True,
                progressive=True,
            )

    elif formato == "PNG":
        # PNG é sem perdas: compressão altera tamanho e velocidade, não pixels.
        parametros.update(
            optimize=True,
            compress_level=6 if alta_qualidade else 9,
        )

    elif formato == "WEBP":
        if alta_qualidade:
            parametros.update(
                lossless=True,
                quality=100,
                method=6,
                exact=True,
            )
        else:
            parametros.update(
                lossless=False,
                quality=84,
                method=6,
                exact=True,
            )

    elif formato == "AVIF":
        if alta_qualidade:
            parametros.update(
                quality=100,
                subsampling="4:4:4",
                speed=4,
            )
        else:
            parametros.update(
                quality=80,
                subsampling="4:2:0",
                speed=6,
            )

    elif formato == "MPO":
        parametros.update(
            quality=95 if alta_qualidade else 85,
            subsampling=0 if alta_qualidade else 1,
        )

    elif formato == "GIF":
        parametros.update(optimize=True)

    elif formato == "TIFF":
        parametros.update(compression="tiff_lzw")

    elif formato == "JPEG2000":
        if alta_qualidade:
            parametros.update(irreversible=False)
        else:
            parametros.update(
                irreversible=True,
                quality_mode="rates",
                quality_layers=[12],
            )

    elif formato == "ICO":
        parametros.update(bitmap_format="png")

    elif formato == "TGA" and not alta_qualidade:
        parametros.update(compression="tga_rle")

    elif formato == "SGI" and not alta_qualidade:
        parametros.update(compression="rle")

    elif formato == "PDF":
        parametros.update(
            quality=95 if alta_qualidade else 85,
            optimize=True,
        )

    # Mantém a assinatura uniforme mesmo quando uma família escolhe sua
    # variante pelo modo da imagem ou pela extensão do destino.
    _ = extensao

    return parametros


def caminho_sem_conflito(caminho: Path) -> Path:
    """Evita sobrescrever um arquivo que já existe."""
    if not caminho.exists():
        return caminho

    contador = 2

    while True:
        candidato = caminho.with_name(
            f"{caminho.stem}_{contador}{caminho.suffix}"
        )
        if not candidato.exists():
            return candidato
        contador += 1


def verificar_saida_antes_da_lixeira(caminho: Path) -> None:
    """Reabre e decodifica a saída antes de permitir remover o original."""
    with Image.open(caminho) as imagem_teste:
        imagem_teste.verify()

    with Image.open(caminho) as imagem_teste:
        imagem_teste.load()
        if imagem_teste.width <= 0 or imagem_teste.height <= 0:
            raise OSError("A saída não possui dimensões válidas.")


def enviar_para_lixeira(caminho: Path) -> tuple[bool, str]:
    """Envia um único arquivo para a Lixeira do Windows, sem exclusão direta."""
    if os.name != "nt":
        return False, "A Lixeira automática está disponível somente no Windows."

    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", wintypes.WORD),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 0x0003
        FOF_SILENT = 0x0004
        FOF_NOCONFIRMATION = 0x0010
        FOF_ALLOWUNDO = 0x0040
        FOF_NOERRORUI = 0x0400

        operacao = SHFILEOPSTRUCTW()
        operacao.wFunc = FO_DELETE
        operacao.pFrom = str(caminho.resolve()) + "\0\0"
        operacao.pTo = None
        operacao.fFlags = (
            FOF_SILENT
            | FOF_NOCONFIRMATION
            | FOF_ALLOWUNDO
            | FOF_NOERRORUI
        )

        resultado = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operacao))
        if resultado != 0:
            return False, f"O Windows retornou o código {resultado}."
        if operacao.fAnyOperationsAborted:
            return False, "A operação foi cancelada pelo Windows."
        if caminho.exists():
            return False, "O arquivo continuou no local original."
        return True, "Enviado para a Lixeira."
    except (OSError, ValueError) as erro:
        return False, str(erro)


def nomes_base_unicos(imagens: list[Path]) -> dict[Path, str]:
    """Distingue arquivos de entrada com o mesmo nome-base."""
    contagens = Counter(imagem.stem.casefold() for imagem in imagens)
    resultados: dict[Path, str] = {}

    for imagem in imagens:
        nome_base = imagem.stem
        if contagens[imagem.stem.casefold()] > 1:
            extensao_origem = imagem.suffix.lower().lstrip(".")
            nome_base = f"{nome_base}_de_{extensao_origem}"
        resultados[imagem] = nome_base

    return resultados


def abrir_imagem_estatica(
    origem: Path,
) -> tuple[Image.Image, Image.Image, int]:
    """
    Abre a imagem e retorna original, quadro corrigido e número de quadros.

    Em arquivos animados ou sequenciais, somente o primeiro quadro é usado.
    Essa decisão é informada ao usuário no relatório da conversão.
    """
    imagem_original = Image.open(origem)

    try:
        numero_quadros = int(getattr(imagem_original, "n_frames", 1))

        if numero_quadros > 1:
            imagem_original.seek(0)

        imagem_original.load()
        imagem_corrigida = ImageOps.exif_transpose(imagem_original)
        return imagem_original, imagem_corrigida, numero_quadros
    except Exception:
        imagem_original.close()
        raise


def salvar_versao(
    origem: Path,
    destino: Path,
    formato: str,
    alta_qualidade: bool,
    largura_maxima: int | None,
    altura_maxima: int | None,
    preservar_metadados: bool,
) -> int:
    """Converte uma imagem e retorna o total de quadros encontrado."""
    imagem_original: Image.Image | None = None

    try:
        imagem_original, imagem_corrigida, numero_quadros = (
            abrir_imagem_estatica(origem)
        )

        if largura_maxima is not None and altura_maxima is not None:
            imagem_processada = imagem_corrigida.copy()
            imagem_processada.thumbnail(
                (largura_maxima, altura_maxima),
                Image.Resampling.LANCZOS,
            )
        else:
            imagem_processada = imagem_corrigida.copy()

        imagem_final = preparar_imagem(
            imagem_processada,
            formato,
            destino.suffix.lower(),
        )

        metadados = metadados_salvamento(
            imagem_original=imagem_original,
            formato=formato,
            tamanho_saida=imagem_final.size,
            preservar_metadados=preservar_metadados,
        )
        parametros = parametros_salvamento(
            formato=formato,
            extensao=destino.suffix.lower(),
            alta_qualidade=alta_qualidade,
            metadados=metadados,
        )

        destino.parent.mkdir(parents=True, exist_ok=True)
        imagem_final.save(destino, format=formato, **parametros)
        return numero_quadros

    except Exception:
        # Evita deixar arquivos incompletos quando o codificador falha.
        try:
            destino.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    finally:
        if imagem_original is not None:
            imagem_original.close()


def mostrar_arquivos(imagens: list[Path], pasta_base: Path) -> None:
    """Exibe os arquivos encontrados em uma lista alinhada."""
    titulo_secao(f"IMAGENS ENCONTRADAS · {len(imagens)}")
    limite_nome = max(24, largura_interface() - 10)

    for indice, imagem in enumerate(imagens, start=1):
        try:
            nome_exibido = str(imagem.relative_to(pasta_base))
        except ValueError:
            nome_exibido = imagem.name
        nome = encurtar(nome_exibido, limite_nome)
        print(f"  {estilizar(str(indice).rjust(3), CIANO)}  {nome}")


def escolher_imagens(imagens: list[Path]) -> list[Path]:
    """Permite selecionar imagens pelos números; Backspace vazio retorna ao menu."""
    print()
    print("  Digite os números separados por vírgula  " + estilizar("ex.: 1, 3, 5", CINZA))
    print("  Pressione Enter para selecionar todas.")
    print(estilizar("  Backspace com o campo vazio volta para a etapa anterior.", CINZA))

    caracteres = set("0123456789, ")

    while True:
        resposta = ler_linha_com_voltar(
            f"\n  {estilizar('›', CIANO, NEGRITO)} Imagens: ",
            caracteres_permitidos=caracteres,
        ).strip()

        if not resposta:
            imprimir_ok(f"Todas as {len(imagens)} imagens foram selecionadas.")
            return imagens.copy()

        partes = [parte.strip() for parte in resposta.split(",")]

        if not partes or any(not parte for parte in partes):
            imprimir_aviso("Seleção inválida. Use números separados por vírgula.")
            continue

        try:
            indices = [int(parte) for parte in partes]
        except ValueError:
            imprimir_aviso("Digite somente números separados por vírgula.")
            continue

        invalidos = [indice for indice in indices if not 1 <= indice <= len(imagens)]
        if invalidos:
            imprimir_aviso(
                "Número(s) fora da lista: "
                + ", ".join(str(indice) for indice in invalidos)
            )
            continue

        selecionadas: list[Path] = []
        vistos: set[int] = set()

        for indice in indices:
            if indice not in vistos:
                selecionadas.append(imagens[indice - 1])
                vistos.add(indice)

        imprimir_ok(f"{len(selecionadas)} imagem(ns) selecionada(s).")
        for imagem in selecionadas:
            print(f"    {estilizar('→', CINZA)} {imagem.name}")

        return selecionadas


def selecionar_imagens_para_converter(pasta_script: Path) -> list[Path]:
    """Lista imagens e oferece seleção total, individual, por tipo ou recursiva."""
    analisou_subpastas = False
    imagens = localizar_imagens(pasta_script, recursivo=False)

    while True:
        if not imagens and analisou_subpastas:
            imprimir_aviso("Nenhuma imagem compatível foi encontrada.")
            return []

        if imagens:
            mostrar_arquivos(imagens, pasta_script)
        else:
            titulo_secao("IMAGENS ENCONTRADAS · 0")
            imprimir_aviso("Nenhuma imagem foi encontrada diretamente nesta pasta.")

        if len(imagens) == 1:
            titulo_secao("SELECIONAR IMAGENS")
            imprimir_ok(
                f"O arquivo {imagens[0].name} foi selecionado automaticamente."
            )
            return imagens.copy()

        opcoes: list[tuple[str, str]] = []
        desabilitadas: set[str] = set()

        opcoes.append(("1", f"Todos os {len(imagens)} arquivos"))
        opcoes.append(("2", "Escolher pelos números da lista"))
        if not imagens:
            desabilitadas.update({"1", "2"})

        contagens = Counter(imagem.suffix.lower() for imagem in imagens)
        escolhas_extensao: dict[str, str] = {}

        for extensao in sorted(contagens):
            valor = str(len(opcoes) + 1)
            descricao = EXTENSOES_ENTRADA.get(extensao, "Imagem")
            quantidade = contagens[extensao]
            rotulo = (
                f"Somente {extensao.upper()} · {descricao} · "
                f"{quantidade} arquivo(s)"
            )
            opcoes.append((valor, rotulo))
            escolhas_extensao[valor] = extensao

        valor_analisar = str(len(opcoes) + 1)
        opcoes.append((valor_analisar, "Analisar pastas e subpastas vizinhas"))
        if analisou_subpastas:
            desabilitadas.add(valor_analisar)

        if imagens:
            indice_padrao = 0
        else:
            indice_padrao = len(opcoes) - 1

        escolha = menu_navegavel(
            "SELECIONAR IMAGENS",
            opcoes,
            indice_padrao=indice_padrao,
            desabilitadas=desabilitadas,
        )

        if escolha == valor_analisar:
            titulo_secao("ANALISANDO PASTAS E SUBPASTAS")
            imagens = localizar_imagens(pasta_script, recursivo=True)
            analisou_subpastas = True
            imprimir_ok(f"Análise concluída: {len(imagens)} imagem(ns) encontrada(s).")
            continue

        if escolha == "1":
            imprimir_ok(f"Todas as {len(imagens)} imagens foram selecionadas.")
            return imagens.copy()

        if escolha == "2":
            try:
                return escolher_imagens(imagens)
            except VoltarEtapa:
                continue

        extensao = escolhas_extensao[escolha]
        selecionadas = [
            imagem for imagem in imagens if imagem.suffix.lower() == extensao
        ]
        imprimir_ok(
            f"{len(selecionadas)} imagem(ns) {extensao.upper()} selecionada(s)."
        )
        return selecionadas


def formato_saida_disponivel(nome: str) -> bool:
    """Confirma que extensão e codificador de saída estão registrados."""
    formato, extensao, _ = FORMATOS_SAIDA[nome]
    Image.init()
    registradas = Image.registered_extensions()
    return formato in Image.SAVE and registradas.get(extensao) == formato


def escolher_formato() -> tuple[str, str, str, str]:
    """Mantém os quatro formatos originais e oferece os demais em Outros."""
    opcoes_principais = [
        ("1", "JPG"),
        ("2", "PNG"),
        ("3", "WEBP"),
        ("4", "AVIF"),
        ("5", "Outros"),
    ]

    while True:
        escolha = menu_navegavel(
            "FORMATO DE SAÍDA",
            opcoes_principais,
            indice_padrao=2,
        )

        if escolha == "5":
            nomes = list(FORMATOS_PRINCIPAIS) + sorted(
                nome
                for nome in FORMATOS_SAIDA
                if nome not in FORMATOS_PRINCIPAIS
            )
            opcoes_outros = [
                (str(indice), nome)
                for indice, nome in enumerate(nomes, start=1)
            ]
            desabilitadas = {
                str(indice)
                for indice, nome in enumerate(nomes, start=1)
                if not formato_saida_disponivel(nome)
            }
            try:
                escolha_outros = menu_navegavel(
                    "OUTROS FORMATOS DE SAÍDA",
                    opcoes_outros,
                    indice_padrao=2,
                    desabilitadas=desabilitadas,
                )
            except VoltarEtapa:
                continue
            nome = nomes[int(escolha_outros) - 1]
        else:
            nome = FORMATOS_PRINCIPAIS[int(escolha) - 1]

        formato, extensao, pasta_formato = FORMATOS_SAIDA[nome]

        try:
            verificar_formato_disponivel(formato)
        except ErroFormatoIndisponivel as erro:
            imprimir_erro(f"Formato indisponível: {erro}")
            imprimir_aviso("Escolha outro formato ou atualize o Pillow.")
            continue

        return nome, formato, extensao, pasta_formato


def configurar_processamento(
    imagens: list[Path],
) -> tuple[str, str, str, str, str, int, int, bool, bool, bool]:
    """Configura a conversão em etapas navegáveis com retorno por Backspace."""
    etapa = "processamento"
    largura = 400
    altura = 400
    nome_formato = "WEBP"
    formato, extensao, pasta_formato = FORMATOS_SAIDA[nome_formato]
    modo = "1"
    preservar_metadados = False
    destino_separado = True
    remover_originais = False

    while True:
        if etapa == "processamento":
            try:
                escolha_processamento = menu_navegavel(
                    "CONFIGURAÇÃO DO PROCESSAMENTO",
                    [
                        (
                            "1",
                            "Executar processamento padrão "
                            "(WEBP, alta qualidade, sem metadados, pasta separada)",
                        ),
                        ("2", "Personalizar processamento"),
                    ],
                    indice_padrao=0,
                )
            except VoltarEtapa:
                raise

            if escolha_processamento == "1":
                nome_formato = "WEBP"
                formato, extensao, pasta_formato = FORMATOS_SAIDA[nome_formato]
                verificar_formato_disponivel(formato)
                return (
                    nome_formato,
                    formato,
                    extensao,
                    pasta_formato,
                    "1",
                    400,
                    400,
                    False,
                    True,
                    False,
                )

            etapa = "formato"
            continue

        if etapa == "formato":
            try:
                nome_formato, formato, extensao, pasta_formato = escolher_formato()
            except VoltarEtapa:
                etapa = "processamento"
                continue
            etapa = "modo"
            continue

        if etapa == "modo":
            try:
                modo = menu_navegavel(
                    "TIPO DE CONVERSÃO",
                    [
                        ("1", "Alta qualidade, mantendo a resolução original"),
                        ("2", "Miniatura"),
                        ("3", "Ambas as versões"),
                    ],
                    indice_padrao=0,
                )
            except VoltarEtapa:
                etapa = "formato"
                continue

            etapa = "largura" if modo in {"2", "3"} else "metadados"
            continue

        if etapa == "largura":
            titulo_secao("DIMENSÕES DA MINIATURA")
            print(
                "  A proporção original será preservada e a imagem "
                "não será ampliada.\n"
            )
            print(estilizar("  Backspace com o campo vazio volta para a etapa anterior.\n", CINZA))
            try:
                largura = solicitar_inteiro(
                    "  Largura máxima em pixels [400]: ",
                    padrao=400,
                    minimo=16,
                    maximo=20000,
                )
            except VoltarEtapa:
                etapa = "modo"
                continue
            etapa = "altura"
            continue

        if etapa == "altura":
            try:
                altura = solicitar_inteiro(
                    "  Altura máxima em pixels [400]: ",
                    padrao=400,
                    minimo=16,
                    maximo=20000,
                )
            except VoltarEtapa:
                etapa = "largura"
                continue
            etapa = "metadados"
            continue

        if etapa == "metadados":
            try:
                escolha_metadados = menu_navegavel(
                    "METADADOS",
                    [
                        ("1", "Preservar EXIF, perfil de cor e dados compatíveis"),
                        ("2", "Remover metadados da saída"),
                    ],
                    indice_padrao=1,
                )
            except VoltarEtapa:
                etapa = "altura" if modo in {"2", "3"} else "modo"
                continue
            preservar_metadados = escolha_metadados == "1"
            etapa = "destino"
            continue

        if etapa == "destino":
            try:
                escolha_destino = menu_navegavel(
                    "EXPORTAR OS ARQUIVOS PARA",
                    [
                        ("1", "Pasta separada"),
                        ("2", "Na mesma pasta que o arquivo original"),
                    ],
                    indice_padrao=0,
                )
            except VoltarEtapa:
                etapa = "metadados"
                continue
            destino_separado = escolha_destino == "1"
            etapa = "originais"
            continue

        if etapa == "originais":
            try:
                escolha_originais = menu_navegavel(
                    "ARQUIVOS ORIGINAIS APÓS A CONVERSÃO",
                    [
                        ("1", "Não enviar para a Lixeira"),
                        ("2", "Enviar para a Lixeira"),
                    ],
                    indice_padrao=0,
                )
            except VoltarEtapa:
                etapa = "destino"
                continue
            remover_originais = escolha_originais == "2"
            if remover_originais:
                etapa = "confirmar_lixeira"
                continue

            return (
                nome_formato,
                formato,
                extensao,
                pasta_formato,
                modo,
                largura,
                altura,
                preservar_metadados,
                destino_separado,
                False,
            )

        if etapa == "confirmar_lixeira":
            try:
                confirmacao_lixeira = menu_navegavel(
                    "CONFIRMAR ENVIO PARA A LIXEIRA",
                    [
                        (
                            "1",
                            f"Confirmar: até {len(imagens)} arquivo(s) original(is)",
                        ),
                        ("2", "Cancelar e preservar todos os originais"),
                    ],
                    indice_padrao=1,
                )
            except VoltarEtapa:
                etapa = "originais"
                continue

            remover_originais = confirmacao_lixeira == "1"
            return (
                nome_formato,
                formato,
                extensao,
                pasta_formato,
                modo,
                largura,
                altura,
                preservar_metadados,
                destino_separado,
                remover_originais,
            )


def main() -> None:
    pasta_script = Path(__file__).resolve().parent

    titulo_secao("CONVERSOR DE IMAGENS")
    print(f"  Pillow   {PIL.__version__}")
    print(f"  Pasta    {pasta_script}")

    while True:
        try:
            imagens = selecionar_imagens_para_converter(pasta_script)
        except VoltarEtapa:
            # Não há etapa anterior à seleção de imagens. Apenas redesenha.
            continue

        if not imagens:
            return

        try:
            (
                nome_formato,
                formato,
                extensao,
                pasta_formato,
                modo,
                largura,
                altura,
                preservar_metadados,
                destino_separado,
                remover_originais,
            ) = configurar_processamento(imagens)
        except VoltarEtapa:
            # Backspace na primeira tela de configuração retorna à seleção.
            continue

        break

    pasta_saida = pasta_script / pasta_formato
    pasta_miniaturas = pasta_saida / "mini"

    if destino_separado:
        if modo in {"1", "3"}:
            pasta_saida.mkdir(parents=True, exist_ok=True)
        if modo in {"2", "3"}:
            pasta_miniaturas.mkdir(parents=True, exist_ok=True)

    bases = nomes_base_unicos(imagens)

    arquivos_gerados = 0
    saidas_com_erro = 0
    imagens_completas = 0
    imagens_parciais = 0
    imagens_sem_saida = 0
    imagens_sequenciais = 0
    originais_na_lixeira = 0
    originais_preservados = 0
    erros_lixeira = 0

    nomes_modo = {
        "1": "Alta qualidade",
        "2": "Miniatura",
        "3": "Alta qualidade + miniatura",
    }
    nome_metadados = "Preservados" if preservar_metadados else "Removidos"
    nome_destino = (
        f"Pasta separada ({pasta_formato})"
        if destino_separado
        else "Mesma pasta do arquivo original"
    )
    nome_originais = "Enviar para a Lixeira" if remover_originais else "Preservar"

    titulo_secao("CONVERSÃO")
    print(f"  Formato      {estilizar(nome_formato, NEGRITO)}")
    print(f"  Modo         {nomes_modo[modo]}")
    print(f"  Metadados    {nome_metadados}")
    print(f"  Destino      {nome_destino}")
    print(f"  Originais    {nome_originais}")
    print(f"  Imagens      {len(imagens)}")
    print()

    for indice, origem in enumerate(imagens, start=1):
        mostrar_progresso(indice - 1, len(imagens), origem.name)

        nome_base = bases[origem]
        sucessos_imagem = 0
        erros_imagem = 0
        sequencial_detectada = False
        saidas_imagem: list[str] = []
        caminhos_gerados_imagem: list[Path] = []

        if destino_separado:
            base_saida = pasta_saida
            base_miniatura = pasta_miniaturas
            nome_base = bases[origem]
        else:
            base_saida = origem.parent
            base_miniatura = origem.parent
            nome_base = origem.stem

        if modo in {"1", "3"}:
            destino_original = caminho_sem_conflito(
                base_saida / f"{nome_base}{extensao}"
            )

            try:
                quadros = salvar_versao(
                    origem=origem,
                    destino=destino_original,
                    formato=formato,
                    alta_qualidade=True,
                    largura_maxima=None,
                    altura_maxima=None,
                    preservar_metadados=preservar_metadados,
                )
                sequencial_detectada = sequencial_detectada or quadros > 1
                sucessos_imagem += 1
                arquivos_gerados += 1
                caminhos_gerados_imagem.append(destino_original)
                saidas_imagem.append(str(destino_original.relative_to(pasta_script)))
            except Exception as erro:
                erros_imagem += 1
                saidas_com_erro += 1
                saidas_imagem.append(
                    f"ERRO alta qualidade — {type(erro).__name__}: {erro}"
                )

        if modo in {"2", "3"}:
            destino_miniatura = caminho_sem_conflito(
                base_miniatura / f"{nome_base}_mini{extensao}"
            )

            try:
                quadros = salvar_versao(
                    origem=origem,
                    destino=destino_miniatura,
                    formato=formato,
                    alta_qualidade=False,
                    largura_maxima=largura,
                    altura_maxima=altura,
                    preservar_metadados=preservar_metadados,
                )
                sequencial_detectada = sequencial_detectada or quadros > 1
                sucessos_imagem += 1
                arquivos_gerados += 1
                caminhos_gerados_imagem.append(destino_miniatura)
                saidas_imagem.append(str(destino_miniatura.relative_to(pasta_script)))
            except Exception as erro:
                erros_imagem += 1
                saidas_com_erro += 1
                saidas_imagem.append(
                    f"ERRO miniatura — {type(erro).__name__}: {erro}"
                )

        limpar_linha_atual()

        if sucessos_imagem and not erros_imagem:
            imagens_completas += 1
            print(f"  {estilizar('✓', VERDE, NEGRITO)} {origem.name}")
        elif sucessos_imagem and erros_imagem:
            imagens_parciais += 1
            print(f"  {estilizar('!', AMARELO, NEGRITO)} {origem.name} — concluída parcialmente")
        else:
            imagens_sem_saida += 1
            print(f"  {estilizar('✗', VERMELHO, NEGRITO)} {origem.name} — falha")

        for saida in saidas_imagem:
            if saida.startswith("ERRO"):
                print(f"      {estilizar('└', VERMELHO)} {saida}")
            else:
                print(f"      {estilizar('└', CINZA)} {saida}")

        if sequencial_detectada:
            imagens_sequenciais += 1
            imprimir_aviso(
                f"{origem.name} possui vários quadros; somente o primeiro foi exportado."
            )

        saidas_esperadas = 2 if modo == "3" else 1
        if remover_originais:
            if sequencial_detectada:
                originais_preservados += 1
                imprimir_aviso(
                    "Original preservado porque possui vários quadros e somente "
                    "o primeiro foi exportado."
                )
            elif sucessos_imagem == saidas_esperadas and erros_imagem == 0:
                try:
                    for caminho_gerado in caminhos_gerados_imagem:
                        verificar_saida_antes_da_lixeira(caminho_gerado)
                    enviado, detalhe = enviar_para_lixeira(origem)
                except Exception as erro:
                    enviado = False
                    detalhe = f"Saída não validada: {type(erro).__name__}: {erro}"

                if enviado:
                    originais_na_lixeira += 1
                    print(
                        f"      {estilizar('└', CINZA)} "
                        "Original enviado para a Lixeira"
                    )
                else:
                    originais_preservados += 1
                    erros_lixeira += 1
                    imprimir_aviso(
                        f"Original preservado; falha ao enviar para a Lixeira: {detalhe}"
                    )
            else:
                originais_preservados += 1
                imprimir_aviso(
                    "Original preservado porque a conversão não foi concluída integralmente."
                )

    mostrar_progresso(len(imagens), len(imagens), "Concluído")
    if ANSI_ATIVO:
        print()

    titulo_secao("CONVERSÃO CONCLUÍDA")
    print(f"  {'Imagens selecionadas':<31} {len(imagens):>5}")
    print(f"  {'Concluídas integralmente':<31} {imagens_completas:>5}")
    print(f"  {'Concluídas parcialmente':<31} {imagens_parciais:>5}")
    print(f"  {'Sem saída':<31} {imagens_sem_saida:>5}")
    print(f"  {'Arquivos gerados':<31} {arquivos_gerados:>5}")
    print(f"  {'Saídas com erro':<31} {saidas_com_erro:>5}")

    if imagens_sequenciais:
        print(f"  {'Sequenciais/animadas':<31} {imagens_sequenciais:>5}")
    if remover_originais:
        print(f"  {'Originais na Lixeira':<31} {originais_na_lixeira:>5}")
        print(f"  {'Originais preservados':<31} {originais_preservados:>5}")
        print(f"  {'Falhas ao usar a Lixeira':<31} {erros_lixeira:>5}")

    print()
    print(f"  Formato      {nome_formato}")
    print(f"  Modo         {nomes_modo[modo]}")
    print(f"  Metadados    {nome_metadados}")
    print(f"  Destino      {nome_destino}")
    print(f"  Originais    {nome_originais}")
    if destino_separado:
        print(f"  {estilizar('→', CIANO, NEGRITO)} {pasta_saida}")
    else:
        print(
            f"  {estilizar('→', CIANO, NEGRITO)} "
            "Saídas criadas ao lado de cada arquivo original"
        )
    print()

    if saidas_com_erro == 0:
        imprimir_ok("Conversão concluída com sucesso.")
    else:
        imprimir_aviso("Conversão concluída com uma ou mais saídas com erro.")


if __name__ == "__main__":
    habilitar_ansi()
    limpar_tela()
    mostrar_logo()

    try:
        if verificar_pre_requisitos():
            main()
    except KeyboardInterrupt:
        print("\n")
        imprimir_aviso("Operação cancelada pelo usuário.")
    except Exception as erro:
        titulo_secao("ERRO INESPERADO")
        imprimir_erro(f"{type(erro).__name__}: {erro}")
        print(
            "\n  O programa foi interrompido, mas esta janela permanecerá aberta "
            "até sua confirmação."
        )
    finally:
        pausar_antes_de_fechar()
